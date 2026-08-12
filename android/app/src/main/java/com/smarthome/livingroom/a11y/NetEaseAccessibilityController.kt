package com.smarthome.livingroom.a11y

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import com.smarthome.livingroom.debug.DebugLogStore

/**
 * Drives NetEase Cloud Music TV via Accessibility:
 * launch → open 搜索 tab → type 首字母/全拼 (TV has no real EditText) → click result.
 */
class NetEaseAccessibilityController(
    private val context: Context,
) {
    /** GitV 等设备上 `input keyevent` 常 exit=255；探测失败后全程改用手势/无障碍点击。 */
    private var shellKeysUsable = true

    fun playBySearch(song: String, artist: String?): Boolean {
        shellKeysUsable = true
        val service = LivingRoomAccessibilityService.instance
            ?: throw IllegalStateException("无障碍未开启：请先在系统设置里打开「客厅中控」无障碍服务")

        val query = buildSearchQuery(song, artist)
        require(query.isNotBlank()) { "song is required" }

        val pkg = resolveNetEasePackage()
            ?: throw IllegalStateException("未安装网易云（com.netease.cloudmusic.tv / com.netease.cloudmusic）")

        val deadline = SystemClock.uptimeMillis() + A11Y_BUDGET_MS
        DebugLogStore.append(
            "[网易云/无障碍] 总时限 ${A11Y_BUDGET_MS / 1000}s，超时即失败",
        )

        service.setAutomationTarget(pkg)
        try {
            return playBySearchInner(service, pkg, query, song, artist, deadline)
        } finally {
            service.setAutomationTarget(null)
        }
    }

    private fun playBySearchInner(
        service: LivingRoomAccessibilityService,
        pkg: String,
        query: String,
        song: String,
        artist: String?,
        deadline: Long,
    ): Boolean {
        step("1/7 启动应用", "包名=$pkg 查询「$query」")
        launchPackage(pkg)
        val foreground = waitForWindow(
            service,
            pkg,
            timeoutMs = minOf(12_000L, remainingMs(deadline)),
            relaunchOnStall = true,
        )
        if (!foreground) {
            dumpAndFail(service, "步骤1失败：等待 $pkg 前台超时（当前窗口可能不是网易云）")
        }
        stepOk("1/7 启动应用", "已进入前台")
        sleepWithinBudget(deadline, 800)

        ensureBudget(deadline, "启动后")
        // 再次确认前台是网易云，避免误在中控自己的界面上操作
        val pkgNow = LivingRoomAccessibilityService.instance?.root()?.packageName?.toString()
        if (pkgNow != pkg) {
            stepWarn("1/7 启动应用", "前台仍是 $pkgNow，再次拉起网易云")
            launchPackage(pkg)
            if (!waitForWindow(service, pkg, timeoutMs = minOf(5_000L, remainingMs(deadline)))) {
                dumpAndFail(service, "步骤1失败：无法把前台切到网易云（当前 $pkgNow）")
            }
        }
        step("2/7 关闭浮层", "最多 1 轮")
        cancelExitDialogIfPresent(service)
        val dismissed = dismissOverlays(service, rounds = 1)
        stepOk("2/7 关闭浮层", if (dismissed > 0) "关闭了 $dismissed 次" else "未发现可关浮层")
        sleepWithinBudget(deadline, 400)

        ensureBudget(deadline, "关浮层后")
        step("2.5/7 回到最外层", "标记：顶栏出现【推荐】或【发现】")
        if (!ensureOuterHomeShell(service, deadline)) {
            stepWarn("2.5/7 回到最外层", "仍未见推荐/发现，继续尝试（受总时限约束）")
        } else {
            stepOk("2.5/7 回到最外层", "已在主层（推荐/发现可见）")
        }

        ensureBudget(deadline, "打开搜索前")
        step("3/7 打开搜索", "拼音提示文案；总时限内完成")
        if (!ensureSearchPage(service, deadline)) {
            dumpAndFail(
                service,
                "步骤3失败：${A11Y_BUDGET_MS / 1000}s 内未进入搜索页",
            )
        }
        stepOk("3/7 打开搜索", "已定位到拼音搜索提示")

        ensureBudget(deadline, "输入前")
        step("4/7 输入关键词", "首字母/全拼")
        if (!typeQuery(service, song.trim(), artist?.trim(), deadline)) {
            dumpAndFail(service, "步骤4失败：拼音注入后仍未出现含「${song.trim()}」的结果")
        }
        stepOk("4/7 输入关键词", "已注入拼音并等到结果线索")

        ensureBudget(deadline, "点结果前")
        step("5/7 确认搜索", "跳过")
        stepOk("5/7 确认搜索", "跳过")

        step("6/7 点击结果", "匹配歌名「$song」${artist?.let { " / 歌手「$it」" } ?: ""}")
        val resultClick = clickResult(service, song, artist)
        if (!resultClick) {
            dumpAndFail(service, "步骤6失败：结果列表里没有可点击且含「$song」的节点")
        }
        stepOk("6/7 点击结果", "已点击匹配项")
        sleepWithinBudget(deadline, 800)

        ensureBudget(deadline, "点播放前")
        step("7/7 点击播放", "只点真正的播放键，避开「最近播放」")
        when (val play = clickSongPlayControl(service)) {
            PlayClickResult.CLICKED -> {
                stepOk("7/7 点击播放", "已点击播放控件")
                DebugLogStore.append("[网易云/无障碍] 全部步骤成功")
                return true
            }
            PlayClickResult.SKIPPED_NO_SAFE_BUTTON -> {
                // 点结果后 TV 常已开播；没有安全的「播放」键就不要乱点
                stepWarn("7/7 点击播放", "未找到安全播放键（已避开最近播放等），视为点结果后已开播")
                DebugLogStore.append("[网易云/无障碍] 步骤完成（弱成功：点结果后未再点播放）")
                return true
            }
            PlayClickResult.FAILED -> {
                dumpAndFail(service, "步骤7失败：播放控件点不动")
            }
        }
    }

    private enum class PlayClickResult { CLICKED, SKIPPED_NO_SAFE_BUTTON, FAILED }

    /**
     * 切勿点「最近播放」——会进我的/历史页。
     * 优先精确文案：播放 / 立即播放 / 开始播放；其次「播放全部」。
     */
    private fun clickSongPlayControl(service: LivingRoomAccessibilityService): PlayClickResult {
        val preferredExact = listOf("播放", "立即播放", "开始播放", "Play", "play")
        val secondaryExact = listOf("播放全部", "Play all", "PLAY")
        val denySubstrings = listOf(
            "最近播放", "播放列表", "播放历史", "播放次数", "万次", "播放量",
            "正在播放", "私人漫游", "播客",
        )

        fun isDenied(label: String): Boolean =
            denySubstrings.any { label.contains(it) }

        fun tryExact(labels: List<String>): Boolean {
            for (key in labels) {
                val nodes = service.findNodes { node ->
                    val t = node.text?.toString()?.trim().orEmpty()
                    val d = node.contentDescription?.toString()?.trim().orEmpty()
                    t.equals(key, ignoreCase = true) || d.equals(key, ignoreCase = true)
                }.filter { node ->
                    val label = "${node.text} ${node.contentDescription}"
                    !isDenied(label)
                }
                if (nodes.isEmpty()) {
                    DebugLogStore.append("[网易云/无障碍] 播放精确「$key」无安全候选")
                    continue
                }
                DebugLogStore.append(
                    "[网易云/无障碍] 播放精确「$key」候选 ${nodes.size}: " +
                        nodes.take(3).joinToString(" | ") { describe(it) },
                )
                for (node in nodes) {
                    val how = service.clickNodeDetailed(node)
                    if (how != null) {
                        DebugLogStore.append(
                            "[网易云/无障碍] 播放点中「${describe(node)}」via $how",
                        )
                        return true
                    }
                }
            }
            return false
        }

        if (tryExact(preferredExact)) return PlayClickResult.CLICKED
        if (tryExact(secondaryExact)) return PlayClickResult.CLICKED

        // 最后才允许 contains「播放」，但仍排除最近播放等
        val loose = service.findNodes { node ->
            val t = node.text?.toString()?.trim().orEmpty()
            val d = node.contentDescription?.toString()?.trim().orEmpty()
            val blob = "$t $d"
            if (isDenied(blob)) return@findNodes false
            t == "播放" || d == "播放" ||
                t.equals("Play", true) ||
                t.startsWith("播放") && t.length <= 4
        }
        if (loose.isEmpty()) {
            DebugLogStore.append("[网易云/无障碍] 无安全播放按钮可点")
            return PlayClickResult.SKIPPED_NO_SAFE_BUTTON
        }
        DebugLogStore.append(
            "[网易云/无障碍] 播放宽松候选 ${loose.size}: " +
                loose.take(3).joinToString(" | ") { describe(it) },
        )
        for (node in loose) {
            val how = service.clickNodeDetailed(node)
            if (how != null) {
                DebugLogStore.append("[网易云/无障碍] 播放点中「${describe(node)}」via $how")
                return PlayClickResult.CLICKED
            }
        }
        return PlayClickResult.FAILED
    }

    private fun remainingMs(deadline: Long): Long =
        (deadline - SystemClock.uptimeMillis()).coerceAtLeast(0)

    private fun ensureBudget(deadline: Long, where: String) {
        if (SystemClock.uptimeMillis() >= deadline) {
            throw IllegalStateException(
                "无障碍超时(${A11Y_BUDGET_MS / 1000}s)：$where",
            )
        }
    }

    private fun sleepWithinBudget(deadline: Long, ms: Long) {
        val wait = minOf(ms, remainingMs(deadline))
        if (wait > 0) SystemClock.sleep(wait)
    }

    private fun buildSearchQuery(song: String, artist: String?): String {
        val s = song.trim()
        val a = artist?.trim().orEmpty()
        if (a.isEmpty()) return s
        if (s.contains(a)) return s
        return "$s $a"
    }

    private fun countTextMatches(
        service: LivingRoomAccessibilityService,
        texts: List<String>,
    ): Int {
        var n = 0
        for (key in texts) {
            n += service.findNodes { node ->
                val t = node.text?.toString().orEmpty()
                val d = node.contentDescription?.toString().orEmpty()
                t.equals(key, true) || t.contains(key) || d.contains(key, true)
            }.size
        }
        return n
    }

    fun dumpUi() {
        val service = LivingRoomAccessibilityService.instance
            ?: throw IllegalStateException("无障碍未开启")
        val tree = service.dumpVisibleTree()
        DebugLogStore.append("—— 界面节点 ——\n$tree")
    }

    private fun step(name: String, detail: String) {
        DebugLogStore.append("[网易云/无障碍] ▶ $name · $detail")
    }

    private fun stepOk(name: String, detail: String) {
        DebugLogStore.append("[网易云/无障碍] ✔ $name · $detail")
    }

    private fun stepWarn(name: String, detail: String) {
        DebugLogStore.append("[网易云/无障碍] ⚠ $name · $detail")
    }

    /**
     * Enter search page: click top-tab 「搜索」, then wait for the TV hint
     * 「请输入歌曲的首字母或者全拼」.
     */
    private fun ensureSearchPage(
        service: LivingRoomAccessibilityService,
        deadline: Long,
    ): Boolean {
        cancelExitDialogIfPresent(service)
        if (looksLikeSearchPage(service)) {
            DebugLogStore.append("[网易云/无障碍] 已在搜索页（命中拼音提示文案）")
            focusSearchHint(service)
            return true
        }

        var attempt = 0
        while (remainingMs(deadline) > 500) {
            ensureBudget(deadline, "打开搜索循环")
            attempt++
            cancelExitDialogIfPresent(service)
            if (looksLikeSearchPage(service)) {
                focusSearchHint(service)
                return true
            }

            DebugLogStore.append(
                "[网易云/无障碍] 打开搜索 第 ${attempt} 次（剩余 ${remainingMs(deadline) / 1000}s）",
            )
            if (!clickSearchEntry(service, deadline)) {
                if (remainingMs(deadline) < 800) break
                dismissOverlays(service, rounds = 1)
                sleepWithinBudget(deadline, 400)
                cancelExitDialogIfPresent(service)
                if (!clickSearchEntry(service, deadline)) {
                    stepWarn("3/7 打开搜索", "第 ${attempt} 次未点到搜索入口")
                }
            }

            if (waitUntilSearchPage(service, timeoutMs = minOf(3_000L, remainingMs(deadline)))) {
                focusSearchHint(service)
                return true
            }

            stepWarn("3/7 打开搜索", "未见拼音提示，若未超时则重试")
            cancelExitDialogIfPresent(service)
            sleepWithinBudget(deadline, 300)
        }
        return looksLikeSearchPage(service).also {
            if (it) focusSearchHint(service)
        }
    }

    private fun isExitDialogShowing(service: LivingRoomAccessibilityService): Boolean =
        service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            t.contains("确认退出") || t.contains("退出网易云")
        }.isNotEmpty()

    /** TV 搜索页锚点：提示文案 / 字母键盘 / 热搜 */
    private fun looksLikeSearchPage(service: LivingRoomAccessibilityService): Boolean {
        if (findSearchHintNodes(service).isNotEmpty()) return true
        if (editableCount(service) > 0) return true
        // 选中「搜索」后可能先进入落地页，再 DPAD_DOWN 才出现输入提示
        val softMarkers = listOf("热门搜索", "热搜", "搜索历史", "猜你想搜", "历史记录")
        for (m in softMarkers) {
            if (service.findNodes { it.text?.toString()?.contains(m) == true }.isNotEmpty()) {
                return true
            }
        }
        val letters = service.findNodes { node ->
            val t = node.text?.toString()?.trim().orEmpty()
            t.length == 1 && t[0].isLetter()
        }
        return letters.size >= 8
    }

    private fun findSearchHintNodes(
        service: LivingRoomAccessibilityService,
    ): List<AccessibilityNodeInfo> {
        val markers = listOf(
            "请输入歌曲的首字母或者全拼",
            "请输入歌曲的首字母或全拼",
            "首字母或者全拼",
            "首字母或全拼",
            "输入歌曲",
            "输入歌名",
        )
        return service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            val d = node.contentDescription?.toString().orEmpty()
            markers.any { m -> t.contains(m) || d.contains(m) }
        }
    }

    /** 点一下提示附近，尽量把输入焦点落到搜索区。 */
    private fun focusSearchHint(service: LivingRoomAccessibilityService) {
        val hint = findSearchHintNodes(service).firstOrNull() ?: return
        val how = service.clickNodeDetailed(hint)
        DebugLogStore.append(
            "[网易云/无障碍] 定位提示「${describe(hint)}」" +
                if (how != null) " 并点击 via $how" else "（节点不可点，仅作页面确认）",
        )
        SystemClock.sleep(400)
    }

    private fun waitUntilSearchPage(
        service: LivingRoomAccessibilityService,
        timeoutMs: Long,
    ): Boolean {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        var lastLog = 0L
        while (SystemClock.uptimeMillis() < deadline) {
            cancelExitDialogIfPresent(service)
            if (looksLikeSearchPage(service)) {
                DebugLogStore.append("[网易云/无障碍] 已识别搜索页（拼音提示文案）")
                return true
            }
            val now = SystemClock.uptimeMillis()
            if (now - lastLog > 2_000) {
                DebugLogStore.append("[网易云/无障碍] 等待「请输入歌曲的首字母或者全拼」…")
                lastLog = now
            }
            SystemClock.sleep(350)
        }
        return false
    }

    /** If 「确认退出网易云音乐?」 is up, tap 取消 — never 确认. */
    private fun cancelExitDialogIfPresent(service: LivingRoomAccessibilityService): Boolean {
        val exitHints = service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            t.contains("确认退出") || t.contains("退出网易云")
        }
        if (exitHints.isEmpty()) return false

        DebugLogStore.append("[网易云/无障碍] 检测到退出确认框，点击「取消」")
        val cancelNodes = service.findNodes { node ->
            val t = node.text?.toString()?.trim().orEmpty()
            t == "取消" || t.equals("Cancel", ignoreCase = true)
        }
        for (node in cancelNodes) {
            val how = service.clickNodeDetailed(node)
            if (how != null) {
                DebugLogStore.append("[网易云/无障碍] 已取消退出 via $how")
                SystemClock.sleep(600)
                return true
            }
        }
        DebugLogStore.append("[网易云/无障碍] 退出框存在但「取消」点不到")
        return false
    }

    private fun editableCount(service: LivingRoomAccessibilityService): Int =
        service.findNodes {
            it.isEditable || it.className?.contains("EditText") == true
        }.size

    private val outerHomeTabNames = listOf("推荐", "发现", "精选", "首页")
    private val outerHomeContentMarkers = listOf("歌单推荐", "每日推荐", "私人漫游", "私人雷达")

    /** 最外层主页：顶栏 Tab 或典型首页内容（部分版本顶栏只有「精选」）。 */
    private fun isOnOuterHomeShell(service: LivingRoomAccessibilityService): Boolean {
        if (outerHomeTabNames.any { findTopTabExact(service, it) != null }) return true
        val hits = outerHomeContentMarkers.count { marker ->
            service.findNodes { it.text?.toString()?.contains(marker) == true }.isNotEmpty()
        }
        return hits >= 2
    }

    /**
     * 顶栏右滑后「推荐/发现」可能滚出屏幕，但「搜索」已可见——此时不应 BACK。
     */
    private fun isHomeTabBarContext(service: LivingRoomAccessibilityService): Boolean =
        isOnOuterHomeShell(service) ||
            collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()

    private fun findTopTabExact(
        service: LivingRoomAccessibilityService,
        name: String,
    ): AccessibilityNodeInfo? {
        val band = context.resources.displayMetrics.heightPixels * 0.32f
        return service.findNodes { node ->
            if (!service.isNodeOnScreen(node)) return@findNodes false
            if (service.nodeBounds(node).top.toFloat() !in 0f..band) return@findNodes false
            val t = node.text?.toString()?.trim().orEmpty()
            val d = node.contentDescription?.toString()?.trim().orEmpty()
            t == name || d == name
        }.firstOrNull()
    }

    /**
     * 子页面没有主 Tab 时，先退到最外层再找「搜索」。
     * 退回后必须等待页面稳定；若弹出「确认退出」说明已在根，点取消并停止再退。
     */
    private fun ensureOuterHomeShell(
        service: LivingRoomAccessibilityService,
        deadline: Long,
    ): Boolean {
        cancelExitDialogIfPresent(service)
        if (looksLikeSearchPage(service)) return true
        if (isOnOuterHomeShell(service)) {
            val which = outerHomeTabNames.firstOrNull { findTopTabExact(service, it) != null }
            DebugLogStore.append("[网易云/无障碍] 已在最外层（可见「$which」）")
            return true
        }

        DebugLogStore.append("[网易云/无障碍] 未见到「推荐/发现」，判断在子页面，开始逐层退出")
        repeat(6) { i ->
            if (remainingMs(deadline) < 1_500) {
                DebugLogStore.append("[网易云/无障碍] 退层中止：剩余时间不足")
                return isOnOuterHomeShell(service)
            }
            if (looksLikeSearchPage(service) || isOnOuterHomeShell(service)) {
                DebugLogStore.append("[网易云/无障碍] 已回到最外层（第 ${i + 1} 次检查）")
                return true
            }
            DebugLogStore.append("[网易云/无障碍] 退出子页 ${i + 1}/6 …")
            val atRoot = popBackOneLevel(service, deadline)
            if (isOnOuterHomeShell(service)) {
                DebugLogStore.append("[网易云/无障碍] 退回后已见到推荐/发现")
                return true
            }
            if (atRoot) {
                DebugLogStore.append(
                    "[网易云/无障碍] 再退会退出 App（已取消退出框），停止 BACK",
                )
                return isOnOuterHomeShell(service)
            }
        }
        return isOnOuterHomeShell(service)
    }

    /**
     * @return true 表示已经触达根（弹出退出确认并已点取消），不应再 BACK。
     */
    private fun popBackOneLevel(
        service: LivingRoomAccessibilityService,
        deadline: Long = SystemClock.uptimeMillis() + 5_000,
    ): Boolean {
        DebugLogStore.append("[网易云/无障碍] 发送返回键，等待页面响应…")
        service.performGlobalAction(
            android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK,
        )
        sleepWithinBudget(deadline, 800)
        if (cancelExitDialogIfPresent(service)) {
            sleepWithinBudget(deadline, 400)
            return true
        }
        sleepWithinBudget(deadline, 400)
        cancelExitDialogIfPresent(service)
        DebugLogStore.append("[网易云/无障碍] 退层完成，页面已停顿")
        return false
    }

    /**
     * Dismiss common NetEase TV home overlays: ads, VIP, login tips, "知道了", close (X), etc.
     * Does NOT send BACK here — BACK is only used in ensureOuterHomeShell / reveal fallback.
     */
    private fun dismissOverlays(service: LivingRoomAccessibilityService, rounds: Int): Int {
        cancelExitDialogIfPresent(service)
        val dismissLabels = listOf(
            "关闭", "关掉", "跳过", "我知道了", "知道了", "以后再说", "暂不",
            "同意并继续", "同意", "允许", "稍后", "不了", "忽略",
            "Close", "Skip", "Got it", "Not now", "OK",
            // 取消放最后：退出框用 cancelExitDialog；其它弹窗的取消也可关
            "取消", "Cancel",
        )
        var count = 0
        repeat(rounds) {
            var dismissed = false

            // Prefer canceling exit dialog if present this round.
            if (cancelExitDialogIfPresent(service)) {
                count++
                dismissed = true
            }

            if (!dismissed) {
                for (label in dismissLabels) {
                    val nodes = service.findNodes { node ->
                        val t = node.text?.toString()?.trim().orEmpty()
                        val d = node.contentDescription?.toString()?.trim().orEmpty()
                        // Avoid clicking 「确认」 on exit dialog via loose contains.
                        if (t.contains("确认退出") || t.contains("退出网易云")) return@findNodes false
                        t.equals(label, ignoreCase = true) ||
                            d.equals(label, ignoreCase = true) ||
                            (label.length >= 2 && (t.contains(label) || d.contains(label, ignoreCase = true)))
                    }
                    for (node in nodes) {
                        val how = service.clickNodeDetailed(node)
                        if (how != null) {
                            DebugLogStore.append(
                                "[网易云/无障碍] 关闭浮层「${describe(node)}」via $how",
                            )
                            dismissed = true
                            count++
                            SystemClock.sleep(400)
                            break
                        }
                    }
                    if (dismissed) break
                }
            }

            if (!dismissed) {
                val closeNodes = service.findNodes { node ->
                    val d = node.contentDescription?.toString()?.lowercase().orEmpty()
                    val id = node.viewIdResourceName?.lowercase().orEmpty()
                    d == "close" || d == "关闭" || d.contains("close") ||
                        id.contains("close") || id.contains("dismiss") || id.endsWith("_close")
                }
                for (node in closeNodes) {
                    val how = service.clickNodeDetailed(node)
                    if (how != null) {
                        DebugLogStore.append("[网易云/无障碍] 关闭按钮「${describe(node)}」via $how")
                        dismissed = true
                        count++
                        SystemClock.sleep(400)
                        break
                    }
                }
            }

            if (!dismissed) {
                return count
            }
        }
        return count
    }

    /**
     * Find and activate top-tab「搜索」.
     * 右滑容易越过搜索落到「我的」：滑的时候逐步确认，点之前反复核对焦点，别抢点。
     */
    private fun clickSearchEntry(
        service: LivingRoomAccessibilityService,
        deadline: Long,
    ): Boolean {
        if (looksLikeSearchPage(service)) return true
        if (!isHomeTabBarContext(service)) {
            DebugLogStore.append("[网易云/无障碍] 找搜索前先确保最外层")
            ensureOuterHomeShell(service, deadline)
        }
        escapeMyTabIfNeeded(service)

        var pass = 0
        while (remainingMs(deadline) > 800) {
            ensureBudget(deadline, "寻找搜索 Tab")
            pass++
            DebugLogStore.append("[网易云/无障碍] 找搜索 pass=$pass 剩余 ${remainingMs(deadline)/1000}s")
            escapeMyTabIfNeeded(service)
            if (!isHomeTabBarContext(service)) {
                DebugLogStore.append("[网易云/无障碍] 仍不在主层且无搜索，先退层")
                ensureOuterHomeShell(service, deadline)
            }
            val visible = collectSearchEntryCandidates(service, onlyOnScreen = true)
            if (visible.isNotEmpty()) {
                DebugLogStore.append(
                    "[网易云/无障碍] 可见搜索入口 ${visible.size} 个(第${pass + 1}轮): " +
                        visible.take(4).joinToString(" | ") {
                            "${describe(it.first)}(s=${it.second})"
                        },
                )
                for ((node, score) in visible.take(1)) {
                    if (!isExactSearchTab(node)) {
                        DebugLogStore.append(
                            "[网易云/无障碍] 跳过非搜索 Tab「${describe(node)}」",
                        )
                        continue
                    }
                    // GitV 上 input tap / 手势经常无效；搜索已是 [CF] 时应优先遥控器逻辑：OK / 离焦再回来。
                    val st = readTopTabState(service)
                    DebugLogStore.append(
                        "[网易云/无障碍] 顶栏已看见「搜索」，准备激活 " +
                            "score=$score 高亮=${st.focused} 下划线=${st.selected}" +
                            if (st.underlineStuckOnMy) "（下划线停我的=正常）" else "",
                    )
                    bringNetEaseToFrontIfNeeded(
                        service,
                        resolveNetEasePackage().orEmpty(),
                    )
                    sleepWithinBudget(deadline, 200)
                    if (!waitForWindow(
                            service,
                            resolveNetEasePackage().orEmpty(),
                            minOf(1_500L, remainingMs(deadline)),
                        )
                    ) {
                        DebugLogStore.append("[网易云/无障碍] ⚠ 置顶后仍不是网易云前台，继续尝试")
                    }
                    if (tryActivateSearchTab(service, node, deadline)) {
                        return true
                    }
                }
            } else {
                val offscreen = collectSearchEntryCandidates(service, onlyOnScreen = false)
                DebugLogStore.append(
                    "[网易云/无障碍] 顶栏未见「搜索」(第${pass + 1}轮)；" +
                        "树内匹配=${offscreen.size}，缓慢右移露出…",
                )
            }

            revealTopTabsToTheRight(service, pass, deadline)
        }
        if (remainingMs(deadline) > 200) {
            DebugLogStore.append("[网易云/无障碍] 搜索入口兜底：固定坐标 + 手势")
            if (emergencyActivateSearchTab(service, deadline)) return true
        }
        return looksLikeSearchPage(service)
    }

    private fun bringNetEaseToFrontIfNeeded(
        service: LivingRoomAccessibilityService,
        pkg: String,
    ) {
        if (service.root()?.packageName?.toString() == pkg) return
        bringNetEaseToFront()
    }

    /** 顶栏搜索贴边/过窄，或时间耗尽前的最后尝试。 */
    private fun emergencyActivateSearchTab(
        service: LivingRoomAccessibilityService,
        deadline: Long,
    ): Boolean {
        centerSearchTabIfClipped(service, service.findNodes { n ->
            val t = n.text?.toString()?.trim().orEmpty()
            val d = n.contentDescription?.toString()?.trim().orEmpty()
            t == "搜索" || d == "搜索"
        }.firstOrNull(), deadline)
        if (tapSearchTabArea(service, anchor = service.findNodes { n ->
            val d = n.contentDescription?.toString()?.trim().orEmpty()
            n.isClickable && d == "搜索"
        }.firstOrNull())) {
            sleepWithinBudget(deadline, 900)
            if (waitUntilSearchPage(service, timeoutMs = minOf(2_000L, remainingMs(deadline)))) {
                DebugLogStore.append("[网易云/无障碍] 搜索入口激活成功 style=TAP_AREA")
                return true
            }
        }
        val fs = service.findNodes { n ->
            val d = n.contentDescription?.toString()?.trim().orEmpty()
            n.isFocused && d == "搜索"
        }.firstOrNull()
        if (fs != null && service.activateNodeOnce(fs, "GESTURE_LONG")) {
            sleepWithinBudget(deadline, 900)
            return waitUntilSearchPage(service, timeoutMs = minOf(2_000L, remainingMs(deadline)))
        }
        return false
    }

    private fun centerSearchTabIfClipped(
        service: LivingRoomAccessibilityService,
        node: AccessibilityNodeInfo?,
        deadline: Long,
    ) {
        val target = node ?: return
        val bounds = service.nodeBounds(target)
        val content = service.rootContentBounds()
        val nearRight = bounds.right >= content.right - 16
        if (bounds.width() >= 48 && !nearRight) return
        DebugLogStore.append(
            "[网易云/无障碍] 搜索 Tab 贴内容区右缘(w=${bounds.width()} " +
                "right=${bounds.right} contentRight=${content.right})，顶栏左滑居中",
        )
        service.swipeTopBarScrollTabsLeft()
        sleepWithinBudget(deadline, 500)
    }

    private fun tapSearchTabArea(
        service: LivingRoomAccessibilityService,
        anchor: AccessibilityNodeInfo? = null,
    ): Boolean {
        val target = anchor
            ?: findSearchClickableTab(service)
            ?: service.findNodes { n ->
                val t = n.text?.toString()?.trim().orEmpty()
                val d = n.contentDescription?.toString()?.trim().orEmpty()
                (t == "搜索" || d == "搜索") && (n.isFocused || n.isClickable)
            }.firstOrNull()
        if (target != null) {
            val b = service.nodeBounds(target)
            if (!b.isEmpty) {
                val x = b.exactCenterX()
                val y = b.exactCenterY()
                DebugLogStore.append(
                    "[网易云/无障碍] 节点坐标点搜索 (${x.toInt()},${y.toInt()}) " +
                        "bounds=${b.toShortString()}",
                )
                return service.tapAt(x, y, 200)
            }
        }
        val content = service.rootContentBounds()
        val x = content.right - content.width() * 0.05f
        val y = content.top + content.height() * 0.075f
        DebugLogStore.append(
            "[网易云/无障碍] 内容区坐标点搜索 (${x.toInt()},${y.toInt()}) " +
                "content=${content.toShortString()} display=${context.resources.displayMetrics.widthPixels}px",
        )
        return service.tapAt(x, y, 200)
    }

    /** 部分 TV 选中搜索 Tab 后，输入区出现在内容区中部。 */
    private fun tapSearchContentArea(service: LivingRoomAccessibilityService): Boolean {
        val content = service.rootContentBounds()
        val x = content.exactCenterX().toFloat()
        val y = content.top + content.height() * 0.22f
        DebugLogStore.append("[网易云/无障碍] 点内容区搜索框 (${x.toInt()},${y.toInt()})")
        return service.tapAt(x, y, 200)
    }

    private fun isExactSearchTab(node: AccessibilityNodeInfo): Boolean {
        val t = node.text?.toString()?.trim().orEmpty()
        val d = node.contentDescription?.toString()?.trim().orEmpty()
        return t == "搜索" || t.equals("Search", ignoreCase = true) ||
            d == "搜索" || d.equals("Search", ignoreCase = true)
    }

    /**
     * 激活顶栏「搜索」Tab。
     * GitV 上 shell keyevent 常失效：一旦 exit≠0 即改用手势/无障碍点击，不再 DPAD 对齐。
     */
    private fun tryActivateSearchTab(
        service: LivingRoomAccessibilityService,
        node: AccessibilityNodeInfo,
        deadline: Long,
    ): Boolean {
        val gestureFirstStyles = listOf(
            "GESTURE",
            "GESTURE_LONG",
            "SHELL_TAP",
            "SELECT_CLICK",
        )
        val clickStyles = listOf(
            "GESTURE",
            "SELECT_CLICK",
            "ACTION_CLICK",
            "SHELL_TAP",
        )

        centerSearchTabIfClipped(service, node, deadline)

        fun collectClickTargets(): List<AccessibilityNodeInfo> {
            val seen = LinkedHashSet<Int>()
            val out = mutableListOf<AccessibilityNodeInfo>()
            fun add(n: AccessibilityNodeInfo?) {
                if (n == null) return
                if (seen.add(System.identityHashCode(n))) out.add(n)
            }
            add(findSearchClickableTab(service))
            add(clickableAncestorOrSelf(service, node))
            if (node.isClickable) add(node)
            return out.sortedByDescending {
                var s = service.nodeBounds(it).width()
                if (it.isClickable) s += 200
                if (it.isFocused) s += 100
                s
            }
        }

        fun succeeded(style: String, tryDown: Boolean): Boolean {
            sleepWithinBudget(deadline, 450)
            if (tryDown && shellKeysUsable) {
                injectKeyEvent(20, "DPAD_DOWN")
                sleepWithinBudget(deadline, 300)
            }
            val ok = waitUntilSearchPage(
                service,
                timeoutMs = minOf(1_200L, remainingMs(deadline)),
            )
            if (ok) {
                DebugLogStore.append("[网易云/无障碍] 搜索入口激活成功 style=$style")
            } else {
                DebugLogStore.append("[网易云/无障碍] ⚠ style=$style 未见搜索页特征")
            }
            return ok
        }

        fun attemptActivate(
            target: AccessibilityNodeInfo,
            style: String,
            tryDown: Boolean,
        ): Boolean {
            val bounds = service.nodeBounds(target)
            DebugLogStore.append(
                "[网易云/无障碍] 点「搜索」 style=$style target=${describe(target)}" +
                    " bounds=${bounds.toShortString()} clickable=${target.isClickable}",
            )
            service.focusNodeChain(target)
            sleepWithinBudget(deadline, 150)
            val dispatched = service.activateNodeOnce(target, style)
            DebugLogStore.append("[网易云/无障碍] style=$style dispatch=$dispatched")
            if (!succeeded(style, tryDown)) {
                return false
            }
            return true
        }

        val targets = collectClickTargets()
        var st = readTopTabState(service)
        val styles = if (shellKeysUsable) clickStyles else gestureFirstStyles
        val content = service.rootContentBounds()
        DebugLogStore.append(
            "[网易云/无障碍] 激活候选 ${targets.size} 个 高亮=${st.focused} 下划线=${st.selected} " +
                "content=${content.toShortString()}" +
                if (!shellKeysUsable) " keyevent=已禁用" else "",
        )

        if (shellKeysUsable) {
            injectKeyEvent(84, "KEYCODE_SEARCH")
            if (waitUntilSearchPage(service, timeoutMs = minOf(1_500L, remainingMs(deadline)))) {
                DebugLogStore.append("[网易云/无障碍] 搜索入口激活成功 style=KEYCODE_SEARCH")
                return true
            }
        }

        for (target in targets) {
            for (style in styles) {
                if (remainingMs(deadline) < 400) break
                if (attemptActivate(target, style, tryDown = false)) return true
            }
        }

        val tapAnchor = targets.firstOrNull() ?: node
        if (tapSearchTabArea(service, tapAnchor) && succeeded("TAP_NODE", false)) {
            return true
        }

        if (st.focusedIsSearch || readTopTabState(service).focusedIsSearch) {
            DebugLogStore.append("[网易云/无障碍] 搜索 Tab 已高亮，点内容区激活输入")
            tapSearchContentArea(service)
            if (succeeded("TAP_CONTENT", false)) return true
        }

        if (shellKeysUsable && !st.focusedIsSearch) {
            DebugLogStore.append("[网易云/无障碍] 手势未进搜索页，尝试 DPAD 对齐")
            injectKeyEvent(21, "DPAD_LEFT")
            sleepWithinBudget(deadline, 350)
            injectKeyEvent(22, "DPAD_RIGHT")
            sleepWithinBudget(deadline, 350)
            service.focusNodeChain(node)
            sleepWithinBudget(deadline, 200)
            st = readTopTabState(service)
            if (st.focusedIsSearch && shellKeysUsable) {
                service.activateNodeOnce(node, "ACTION_CLICK")
                injectKeyEvent(23, "DPAD_CENTER")
                if (succeeded("OK_BURST", tryDown = true)) return true
            }
        }
        return false
    }

    private fun findSearchClickableTab(
        service: LivingRoomAccessibilityService,
    ): AccessibilityNodeInfo? {
        val band = context.resources.displayMetrics.heightPixels * 0.32f
        return service.findNodes { n ->
            if (!service.isNodeOnScreen(n)) return@findNodes false
            if (service.nodeBounds(n).top.toFloat() !in 0f..band) return@findNodes false
            val t = n.text?.toString()?.trim().orEmpty()
            val d = n.contentDescription?.toString()?.trim().orEmpty()
            n.isClickable && (t == "搜索" || d == "搜索")
        }.maxByOrNull { n ->
            var s = 0
            if (n.isFocused) s += 30
            if (n.isSelected) s += 15
            s
        }
    }

    private fun injectKeyEvent(code: Int, label: String): Boolean {
        if (!shellKeysUsable) return false
        return try {
            val exit = Runtime.getRuntime()
                .exec(arrayOf("input", "keyevent", code.toString()))
                .waitFor()
            if (exit != 0) {
                shellKeysUsable = false
                DebugLogStore.append(
                    "[网易云/无障碍] $label($code) exit=$exit，keyevent 已禁用，改用手势/无障碍点击",
                )
            }
            exit == 0
        } catch (t: Throwable) {
            shellKeysUsable = false
            DebugLogStore.append("[网易云/无障碍] $label 不可用: ${t.message}")
            false
        }
    }

    private fun clickableAncestorOrSelf(
        service: LivingRoomAccessibilityService,
        node: AccessibilityNodeInfo,
    ): AccessibilityNodeInfo {
        val base = service.nodeBounds(node)
        var cur: AccessibilityNodeInfo? = node
        var best = node
        var depth = 0
        while (cur != null && depth < 3) {
            val r = service.nodeBounds(cur)
            // 父节点过宽（整条 Tab 栏）就不要用，否则点空
            val tooWide = base.width() > 0 && r.width() > base.width() * 2.2
            if (cur.isClickable && !tooWide) {
                return cur
            }
            if (!tooWide && r.width() >= service.nodeBounds(best).width() && !r.isEmpty) {
                best = cur
            }
            cur = cur.parent
            depth++
        }
        return best
    }

    private fun isBlacklistedTabLabel(label: String): Boolean {
        if (label.isBlank()) return false
        val blacklist = listOf(
            "我的", "账号", "个人", "设置", "会员中心", "Mine", "Profile", "Account", "Settings",
        )
        return blacklist.any { label.contains(it, ignoreCase = true) }
    }

    private data class TopTabState(
        val focused: String,
        val selected: String,
    ) {
        fun looksLikeSearch(label: String): Boolean =
            label.contains("搜索") || label.contains("Search", ignoreCase = true)

        val selectedIsSearch: Boolean get() = looksLikeSearch(selected)
        val focusedIsSearch: Boolean get() = looksLikeSearch(focused)
        /** 下划线常永久停在「我的」，不能当失败条件。 */
        val underlineStuckOnMy: Boolean
            get() = selected.contains("我的") || selected.contains("Mine", ignoreCase = true)
        val focusedIsMy: Boolean
            get() = focused.contains("我的") || focused.contains("Mine", ignoreCase = true)
    }

    private fun readTopTabState(service: LivingRoomAccessibilityService): TopTabState {
        val band = context.resources.displayMetrics.heightPixels * 0.32f
        fun pick(predicate: (AccessibilityNodeInfo) -> Boolean): String {
            val nodes = service.findNodes { node ->
                if (!service.isNodeOnScreen(node)) return@findNodes false
                if (service.nodeBounds(node).top.toFloat() !in 0f..band) return@findNodes false
                val t = node.text?.toString()?.trim().orEmpty()
                val d = node.contentDescription?.toString()?.trim().orEmpty()
                if (t.isEmpty() && d.isEmpty()) return@findNodes false
                predicate(node)
            }
            return nodes.firstOrNull()?.let { describe(it) } ?: "(无)"
        }
        return TopTabState(
            focused = pick { it.isFocused },
            selected = pick { it.isSelected },
        )
    }

    private fun focusedTopTabLabel(service: LivingRoomAccessibilityService): String {
        val st = readTopTabState(service)
        return "选中=${st.selected}/高亮=${st.focused}"
    }

    private fun nudgeFocusAwayFromMyTab(service: LivingRoomAccessibilityService) {
        repeat(4) {
            val st = readTopTabState(service)
            // 只看高亮；下划线停在我的不算要拨
            if (!st.focusedIsMy) return
            DebugLogStore.append("[网易云/无障碍] 高亮在「我的」→ DPAD_LEFT")
            injectDpadLeft(times = 1)
            SystemClock.sleep(550)
        }
    }

    private fun isOnMyPage(service: LivingRoomAccessibilityService): Boolean {
        // 不能只看 selected/下划线——它可能永远停在「我的」
        val st = readTopTabState(service)
        if (st.focusedIsMy && !st.focusedIsSearch) {
            val markers = listOf("我的音乐", "本地音乐", "已购")
            if (markers.any { m ->
                    service.findNodes { it.text?.toString()?.contains(m) == true }.isNotEmpty()
                }
            ) {
                return true
            }
        }
        val markers = listOf("我的音乐", "本地音乐")
        val hasMyContent = markers.any { m ->
            service.findNodes { it.text?.toString()?.contains(m) == true }.isNotEmpty()
        }
        return hasMyContent &&
            collectSearchEntryCandidates(service, onlyOnScreen = true).isEmpty() &&
            !isOnOuterHomeShell(service)
    }

    /** 若误进「我的」内容页，点回推荐/发现。 */
    private fun escapeMyTabIfNeeded(service: LivingRoomAccessibilityService) {
        if (!isOnMyPage(service)) return
        val st0 = readTopTabState(service)
        DebugLogStore.append(
            "[网易云/无障碍] 检测到「我的」内容页（高亮=${st0.focused} 下划线=${st0.selected}），点回主 Tab",
        )
        nudgeFocusAwayFromMyTab(service)
        val band = context.resources.displayMetrics.heightPixels * 0.28f
        val safe = listOf("推荐", "发现", "首页", "音乐", "播客", "漫游")
        for (name in safe) {
            val nodes = service.findNodes { node ->
                if (!service.isNodeOnScreen(node)) return@findNodes false
                if (service.nodeBounds(node).top.toFloat() !in 0f..band) return@findNodes false
                val t = node.text?.toString()?.trim().orEmpty()
                t == name
            }
            val n = nodes.firstOrNull() ?: continue
            service.focusNodeChain(n)
            SystemClock.sleep(500)
            if (service.activateNodeOnce(n, "GESTURE")) {
                DebugLogStore.append("[网易云/无障碍] 已点回「$name」")
                SystemClock.sleep(1_000)
                return
            }
        }
    }

    private fun collectSearchEntryCandidates(
        service: LivingRoomAccessibilityService,
        onlyOnScreen: Boolean,
    ): List<Pair<AccessibilityNodeInfo, Int>> {
        val keywords = listOf("搜索", "Search")
        val scored = ArrayList<Pair<AccessibilityNodeInfo, Int>>()
        val band = context.resources.displayMetrics.heightPixels * 0.28f
        for (key in keywords) {
            val nodes = service.findNodes { node ->
                val t = node.text?.toString()?.trim().orEmpty()
                val d = node.contentDescription?.toString()?.trim().orEmpty()
                if (isBlacklistedTabLabel(t) || isBlacklistedTabLabel(d)) return@findNodes false
                if (t.contains("确认退出") || t.contains("退出")) return@findNodes false
                if (t.length > 4 && t != key) return@findNodes false
                if (onlyOnScreen && !service.isNodeOnScreen(node)) return@findNodes false
                t.equals(key, ignoreCase = true) || d.equals(key, ignoreCase = true)
            }
            for (node in nodes) {
                val t = node.text?.toString()?.trim().orEmpty()
                val top = service.nodeBounds(node).top.toFloat()
                var score = 0
                if (t.equals(key, ignoreCase = true)) score += 25
                if (node.isClickable) score += 40
                if (!node.isClickable) score -= 15
                if (node.isSelected) score += 4
                // 已 focused 的搜索 Tab 优先（日志里的 [CF]）
                if (node.isFocused) score += 40
                if (service.isNodeOnScreen(node)) score += 10
                val w = service.nodeBounds(node).width()
                if (w < 40) score -= 30
                if (w >= 80) score += 12
                if (top in 0f..band) score += 15 else score -= 20
                scored += node to score
            }
        }
        return scored.sortedByDescending { it.second }
    }

    /**
     * 缓慢露出右侧 Tab。看到「搜索」就停；焦点到「我的」立刻左拨。
     * 若滑到头仍无「搜索」且不在最外层（无推荐/发现）→ 退一层并等待，再继续。
     */
    private fun revealTopTabsToTheRight(
        service: LivingRoomAccessibilityService,
        pass: Int,
        deadline: Long,
    ) {
        if (remainingMs(deadline) < 600) return
        if (collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()) {
            DebugLogStore.append("[网易云/无障碍] 「搜索」已可见，不再右滑")
            return
        }

        if (!isHomeTabBarContext(service)) {
            DebugLogStore.append(
                "[网易云/无障碍] 当前无「推荐/发现」且未见搜索，右滑前先退到最外层",
            )
            ensureOuterHomeShell(service, deadline)
            SystemClock.sleep(1_200)
            if (collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()) return
        }

        val scrolled = service.scrollTopBarForward()
        if (scrolled > 0) {
            DebugLogStore.append("[网易云/无障碍] 顶栏 SCROLL_FORWARD ×$scrolled，停顿确认")
            SystemClock.sleep(800)
            if (collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()) return
        }

        val swiped = service.swipeTopBarToRevealRight(distanceRatio = 0.28f + pass * 0.06f)
        DebugLogStore.append(
            if (swiped) "[网易云/无障碍] 顶栏小幅左滑（第${pass + 1}次）"
            else "[网易云/无障碍] 顶栏左滑失败",
        )
        SystemClock.sleep(900)
        if (collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()) {
            DebugLogStore.append("[网易云/无障碍] 滑后已看见「搜索」，停止右移")
            return
        }

        if (!shellKeysUsable) {
            DebugLogStore.append("[网易云/无障碍] keyevent 不可用，跳过 DPAD_RIGHT 扫 Tab")
            return
        }

        DebugLogStore.append("[网易云/无障碍] 逐步 DPAD_RIGHT 寻找「搜索」")
        var stuckCount = 0
        var hitEnd = false
        for (step in 0 until 5) {
            val before = readTopTabState(service)
            injectDpadRight(times = 1)
            SystemClock.sleep(650)
            val after = readTopTabState(service)
            DebugLogStore.append(
                "[网易云/无障碍] DPAD_RIGHT ${step + 1}/5: " +
                    "高亮 ${before.focused}→${after.focused} / 下划线 ${before.selected}→${after.selected}",
            )
            if (before.focused == after.focused) {
                stuckCount++
            } else {
                stuckCount = 0
            }
            // 只有高亮到了「我的」才算滑过头；下划线停在我的是正常现象
            if (after.focusedIsMy) {
                DebugLogStore.append("[网易云/无障碍] 高亮到了「我的」，左拨一格回到搜索附近")
                injectDpadLeft(times = 1)
                SystemClock.sleep(650)
                hitEnd = true
                break
            }
            if (after.focusedIsSearch ||
                collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()
            ) {
                DebugLogStore.append("[网易云/无障碍] 高亮已对准/看见「搜索」，停止右移")
                SystemClock.sleep(500)
                return
            }
            if (stuckCount >= 2) {
                DebugLogStore.append("[网易云/无障碍] 高亮连续不动，可能已到尽头")
                hitEnd = true
                break
            }
        }

        if (collectSearchEntryCandidates(service, onlyOnScreen = true).isNotEmpty()) return

        // 滑到头仍无搜索：多半在子页面的局部 Tab，退一层再找
        if (hitEnd || !isHomeTabBarContext(service)) {
            DebugLogStore.append(
                "[网易云/无障碍] 右滑尽头仍无「搜索」" +
                    "（主层=${isHomeTabBarContext(service)}），退一层后等待再滑",
            )
            val atRoot = popBackOneLevel(service, deadline)
            if (atRoot) {
                DebugLogStore.append("[网易云/无障碍] 已在根层，不再 BACK，下一轮继续找搜索")
            } else {
                DebugLogStore.append("[网易云/无障碍] 已退层并等待，下一轮从当前页继续右滑")
            }
            // 额外停顿，避免刚退层就滑
            SystemClock.sleep(1_200)
        }
    }

    private fun injectDpadLeft(times: Int): Boolean {
        repeat(times) {
            if (!injectKeyEvent(21, "DPAD_LEFT")) return false
            SystemClock.sleep(200)
        }
        return shellKeysUsable
    }

    private fun injectDpadRight(times: Int): Boolean {
        repeat(times) {
            if (!injectKeyEvent(22, "DPAD_RIGHT")) return false
            SystemClock.sleep(200)
        }
        return shellKeysUsable
    }

    /**
     * NetEase TV: fake search box — type 首字母 or 全拼 via key injection / on-screen letters.
     * Phone builds may still have a real EditText (SET_TEXT tried first).
     */
    private fun typeQuery(
        service: LivingRoomAccessibilityService,
        song: String,
        artist: String?,
        deadline: Long,
    ): Boolean {
        val songKey = song.trim()
        if (songKey.isEmpty()) return false
        ensureBudget(deadline, "输入关键词")

        // 先清空残留输入，避免 sn 追加到旧内容后面
        DebugLogStore.append("[网易云/无障碍] 输入前先点「清空」")
        clearTvSearchInput(service)
        sleepWithinBudget(deadline, 400)

        // Real EditText path (mobile / rare TV builds)
        val edits = service.findNodes { it.isEditable || it.className?.contains("EditText") == true }
        if (edits.isNotEmpty()) {
            val query = buildSearchQuery(songKey, artist)
            DebugLogStore.append("[网易云/无障碍] 发现真实输入框，SET_TEXT「$query」")
            val target = edits.first()
            target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            SystemClock.sleep(200)
            service.setText(target, "") // 再清一次
            SystemClock.sleep(150)
            if (service.setText(target, query)) {
                waitForSongInTree(service, songKey, timeoutMs = minOf(4_000L, remainingMs(deadline)))
                return true
            }
            DebugLogStore.append("[网易云/无障碍] SET_TEXT 失败，改走拼音注入")
        } else {
            DebugLogStore.append("[网易云/无障碍] 无 EditText（符合 TV 假搜索框），改用拼音/首字母")
            focusSearchHint(service)
        }

        val songInitials = ChinesePinyin.initials(songKey)
        val songFull = ChinesePinyin.fullLetters(songKey)
        val artistInitials = artist?.let { ChinesePinyin.initials(it) }.orEmpty()
        val candidates = linkedSetOf<String>().apply {
            if (songInitials.isNotEmpty()) add(songInitials)
            if (artistInitials.isNotEmpty() && songInitials.isNotEmpty()) {
                add(songInitials + artistInitials)
            }
            if (songFull.isNotEmpty() && songFull != songInitials) add(songFull)
        }

        if (candidates.isEmpty()) {
            DebugLogStore.append("[网易云/无障碍] 无法生成拼音（歌名可能已是无法转换的字符）")
            return false
        }

        DebugLogStore.append(
            "[网易云/无障碍] 拼音候选: ${candidates.joinToString(" → ")}",
        )

        for ((index, py) in candidates.withIndex()) {
            if (remainingMs(deadline) < 800) {
                DebugLogStore.append("[网易云/无障碍] 拼音注入中止：超时")
                break
            }
            if (index > 0) {
                clearTvSearchInput(service)
                sleepWithinBudget(deadline, 300)
            }
            DebugLogStore.append("[网易云/无障碍] 尝试注入「$py」")
            val injected = injectPinyin(service, py)
            if (!injected) {
                stepWarn("4/7 输入关键词", "注入「$py」失败，试下一个")
                continue
            }
            if (waitForSongInTree(service, songKey, timeoutMs = minOf(4_000L, remainingMs(deadline)))) {
                DebugLogStore.append("[网易云/无障碍] 拼音「$py」已打出结果线索")
                return true
            }
            stepWarn("4/7 输入关键词", "注入「$py」后未见「$songKey」，试下一个")
        }
        return false
    }

    private fun injectPinyin(service: LivingRoomAccessibilityService, py: String): Boolean {
        val ascii = py.lowercase().filter { it.isLetterOrDigit() }
        if (ascii.isEmpty()) return false

        // 1) 屏上字母键（TV 常见）
        if (tapOnScreenLetters(service, ascii)) {
            DebugLogStore.append("[网易云/无障碍] 已点屏上字母「$ascii」")
            return true
        }

        // 2) shell input text
        if (shellInputText(ascii)) {
            DebugLogStore.append("[网易云/无障碍] input text「$ascii」成功")
            return true
        }

        // 3) 逐键 keyevent
        if (shellInputKeyLetters(ascii)) {
            DebugLogStore.append("[网易云/无障碍] keyevent 逐字「$ascii」成功")
            return true
        }
        return false
    }

    private fun tapOnScreenLetters(
        service: LivingRoomAccessibilityService,
        ascii: String,
    ): Boolean {
        var tapped = 0
        for (ch in ascii) {
            val upper = ch.uppercaseChar().toString()
            val lower = ch.lowercaseChar().toString()
            val nodes = service.findNodes { node ->
                val t = node.text?.toString()?.trim().orEmpty()
                val d = node.contentDescription?.toString()?.trim().orEmpty()
                t.equals(upper, ignoreCase = true) ||
                    t.equals(lower, ignoreCase = true) ||
                    d.equals(upper, ignoreCase = true) ||
                    d.equals(lower, ignoreCase = true)
            }.filter { node ->
                val t = node.text?.toString()?.trim().orEmpty()
                t.length <= 2 && service.isNodeOnScreen(node)
            }
            val target = nodes.firstOrNull() ?: return false
            if (service.clickNodeDetailed(target) == null) return false
            tapped++
            SystemClock.sleep(120)
        }
        return tapped == ascii.length
    }

    private fun shellInputText(ascii: String): Boolean =
        try {
            val p = Runtime.getRuntime().exec(arrayOf("input", "text", ascii))
            p.waitFor() == 0
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/无障碍] input text 不可用: ${t.message}")
            false
        }

    private fun shellInputKeyLetters(ascii: String): Boolean =
        try {
            for (ch in ascii.lowercase()) {
                val code = when (ch) {
                    in 'a'..'z' -> 29 + (ch - 'a') // KEYCODE_A
                    in '0'..'9' -> 7 + (ch - '0') // KEYCODE_0
                    else -> continue
                }
                Runtime.getRuntime().exec(arrayOf("input", "keyevent", code.toString())).waitFor()
                SystemClock.sleep(90)
            }
            true
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/无障碍] keyevent 不可用: ${t.message}")
            false
        }

    /** 优先点界面上的「清空」；点不到再 DEL 兜底。 */
    private fun clearTvSearchInput(service: LivingRoomAccessibilityService) {
        val labels = listOf("清空", "清除", "Clear", "clear")
        for (key in labels) {
            val nodes = service.findNodes { node ->
                val t = node.text?.toString()?.trim().orEmpty()
                val d = node.contentDescription?.toString()?.trim().orEmpty()
                t.equals(key, ignoreCase = true) ||
                    d.equals(key, ignoreCase = true) ||
                    t == key ||
                    d.contains(key)
            }
            for (node in nodes) {
                val how = service.clickNodeDetailed(node)
                if (how != null) {
                    DebugLogStore.append(
                        "[网易云/无障碍] 已点「${describe(node)}」清空残留输入 via $how",
                    )
                    SystemClock.sleep(450)
                    return
                }
            }
        }
        DebugLogStore.append("[网易云/无障碍] 未找到「清空」按钮，改用 DEL×12 清残留")
        repeat(12) {
            try {
                Runtime.getRuntime().exec(arrayOf("input", "keyevent", "67")).waitFor() // DEL
            } catch (_: Throwable) {
                return
            }
            SystemClock.sleep(35)
        }
    }

    private fun waitForSongInTree(
        service: LivingRoomAccessibilityService,
        songKey: String,
        timeoutMs: Long,
    ): Boolean {
        if (songKey.isEmpty()) {
            SystemClock.sleep(2_500)
            return false
        }
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            cancelExitDialogIfPresent(service)
            val hit = service.findNodes { node ->
                val blob = "${node.text} ${node.contentDescription}"
                blob.contains(songKey)
            }
            if (hit.isNotEmpty()) {
                DebugLogStore.append(
                    "[网易云/无障碍] 结果树已出现「$songKey」（${hit.size} 个节点）",
                )
                return true
            }
            SystemClock.sleep(400)
        }
        DebugLogStore.append("[网易云/无障碍] 等待结果「$songKey」超时")
        return false
    }

    private fun clickResult(
        service: LivingRoomAccessibilityService,
        song: String,
        artist: String?,
    ): Boolean {
        val songKey = song.trim()
        val artistKey = artist?.trim().orEmpty()

        val ranked = service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            val d = node.contentDescription?.toString().orEmpty()
            val blob = "$t $d"
            blob.contains(songKey)
        }.sortedByDescending { node ->
            val blob = "${node.text} ${node.contentDescription}"
            var score = 0
            if (blob.contains(songKey)) score += 10
            if (artistKey.isNotEmpty() && blob.contains(artistKey)) score += 8
            if (node.isClickable) score += 3
            score
        }

        if (ranked.isEmpty()) {
            DebugLogStore.append("[网易云/无障碍] 结果候选=0（界面文字不含「$songKey」）")
            return false
        }

        val preview = ranked.take(5).joinToString(" | ") { describe(it) }
        DebugLogStore.append(
            "[网易云/无障碍] 结果候选 ${ranked.size} 个，前5: $preview",
        )

        for ((index, node) in ranked.withIndex()) {
            val how = service.clickNodeDetailed(node)
            if (how != null) {
                DebugLogStore.append(
                    "[网易云/无障碍] 点中第 ${index + 1} 候选「${describe(node)}」via $how",
                )
                return true
            }
            DebugLogStore.append(
                "[网易云/无障碍] 第 ${index + 1} 候选点击失败「${describe(node)}」",
            )
        }
        DebugLogStore.append("[网易云/无障碍] 所有含歌名候选均点击失败")
        return false
    }

    private fun clickByTexts(
        service: LivingRoomAccessibilityService,
        texts: List<String>,
        purpose: String,
    ): Boolean {
        for (key in texts) {
            val nodes = service.findNodes { node ->
                val t = node.text?.toString().orEmpty()
                val d = node.contentDescription?.toString().orEmpty()
                t.equals(key, true) || t.contains(key) || d.contains(key, true)
            }
            if (nodes.isEmpty()) {
                DebugLogStore.append("[网易云/无障碍] $purpose 关键词「$key」无匹配")
                continue
            }
            DebugLogStore.append(
                "[网易云/无障碍] $purpose 关键词「$key」候选 ${nodes.size}: " +
                    nodes.take(3).joinToString(" | ") { describe(it) },
            )
            for (node in nodes) {
                val how = service.clickNodeDetailed(node)
                if (how != null) {
                    DebugLogStore.append(
                        "[网易云/无障碍] $purpose 点中「${describe(node)}」via $how",
                    )
                    return true
                }
            }
            DebugLogStore.append("[网易云/无障碍] $purpose 「$key」候选全部点不动")
        }
        return false
    }

    private fun describe(node: AccessibilityNodeInfo): String {
        val text = node.text?.toString()?.trim().orEmpty()
        val desc = node.contentDescription?.toString()?.trim().orEmpty()
        val id = node.viewIdResourceName?.substringAfterLast('/').orEmpty()
        val cls = node.className?.toString()?.substringAfterLast('.').orEmpty()
        val label = when {
            text.isNotEmpty() -> text
            desc.isNotEmpty() -> desc
            id.isNotEmpty() -> "#$id"
            else -> cls.ifEmpty { "?" }
        }
        val flags = buildString {
            if (node.isClickable) append('C')
            if (node.isEditable) append('E')
            if (node.isFocused) append('F')
            if (node.isSelected) append('S')
        }
        return if (flags.isEmpty()) label.take(40) else "${label.take(36)}[$flags]"
    }

    private fun waitForWindow(
        service: LivingRoomAccessibilityService,
        pkg: String,
        timeoutMs: Long,
        relaunchOnStall: Boolean = false,
    ): Boolean {
        if (pkg.isEmpty()) return false
        val root0 = service.root()
        val pkg0 = root0?.packageName?.toString().orEmpty()
        if (pkg0 == pkg) {
            DebugLogStore.append(
                "[网易云/无障碍] 前台窗口已是目标 pkg=$pkg0 children=${root0?.childCount}",
            )
            return true
        }
        if (timeoutMs <= 0) {
            DebugLogStore.append(
                "[网易云/无障碍] 等待前台跳过（无剩余时间），${service.windowPackageSummary()}（需要 $pkg）",
            )
            return false
        }
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        var lastRelaunch = 0L
        var lastLog = 0L
        while (SystemClock.uptimeMillis() < deadline) {
            val root = service.root()
            val rootPkg = root?.packageName?.toString().orEmpty()
            if (root != null && rootPkg == pkg) {
                DebugLogStore.append(
                    "[网易云/无障碍] 前台窗口已是目标 pkg=$rootPkg children=${root.childCount}",
                )
                return true
            }
            val now = SystemClock.uptimeMillis()
            if (relaunchOnStall && root == null && now - lastRelaunch > 2_500) {
                DebugLogStore.append(
                    "[网易云/无障碍] 无窗口树，再次拉起 $pkg · ${service.windowPackageSummary()}",
                )
                launchPackage(pkg)
                lastRelaunch = now
            } else if (now - lastLog > 2_000) {
                DebugLogStore.append(
                    "[网易云/无障碍] 等待 $pkg … ${service.windowPackageSummary()}",
                )
                lastLog = now
            }
            SystemClock.sleep(300)
        }
        DebugLogStore.append(
            "[网易云/无障碍] 等待前台超时，${service.windowPackageSummary()}（需要 $pkg）",
        )
        return false
    }

    private fun dumpAndFail(service: LivingRoomAccessibilityService, message: String): Nothing {
        DebugLogStore.append("[网易云/无障碍] ✖ $message")
        DebugLogStore.append("—— 失败时界面 ——\n${service.dumpVisibleTree()}")
        throw IllegalStateException(message)
    }

    private fun resolveNetEasePackage(): String? {
        val candidates = listOf("com.netease.cloudmusic", "com.netease.cloudmusic.tv")
        for (pkg in candidates) {
            if (isInstalled(pkg)) return pkg
        }
        return try {
            @Suppress("DEPRECATION")
            context.packageManager.getInstalledApplications(0)
                .map { it.packageName }
                .firstOrNull {
                    val n = it.lowercase()
                    n.contains("cloudmusic") || (n.contains("netease") && n.contains("music"))
                }
        } catch (_: Throwable) {
            null
        }
    }

    private fun isInstalled(packageName: String): Boolean =
        try {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }

    private fun bringNetEaseToFront() {
        val pkg = resolveNetEasePackage() ?: return
        try {
            val launch = context.packageManager.getLaunchIntentForPackage(pkg) ?: return
            launch.addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP,
            )
            context.startActivity(launch)
            DebugLogStore.append("[网易云/无障碍] 已置顶前台 $pkg（不重置页面）")
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/无障碍] 置顶前台失败: ${t.message}")
        }
    }

    private fun launchPackage(packageName: String) {
        val launch = context.packageManager.getLaunchIntentForPackage(packageName)
            ?: throw IllegalStateException("无法启动 $packageName")
        launch.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or
                Intent.FLAG_ACTIVITY_SINGLE_TOP,
        )
        context.startActivity(launch)
        DebugLogStore.append("[网易云/无障碍] 已拉起 $packageName")
        Log.i(TAG, "launched $packageName")
    }

    companion object {
        private const val TAG = "NetEaseA11y"

        /** 整段无障碍最长耗时，超时即失败 */
        private const val A11Y_BUDGET_MS = 45_000L

        fun openAccessibilitySettings(context: Context) {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        }
    }
}
