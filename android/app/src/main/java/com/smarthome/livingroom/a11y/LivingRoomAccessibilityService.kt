package com.smarthome.livingroom.a11y

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.smarthome.livingroom.debug.DebugLogStore

/**
 * Accessibility bridge used to drive NetEase Cloud Music TV UI.
 * Must be enabled manually in system Accessibility settings.
 */
class LivingRoomAccessibilityService : AccessibilityService() {

    /** 自动化目标包：root() 会优先从 interactive windows 里找该包（切换 App 时 active 常为 null）。 */
    @Volatile
    private var automationTargetPackage: String? = null

    fun setAutomationTarget(packageName: String?) {
        automationTargetPackage = packageName
    }

    fun activeWindowPackage(): String? =
        rootInActiveWindow?.packageName?.toString()

    fun windowPackageSummary(): String {
        val active = activeWindowPackage() ?: "null"
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return "active=$active"
        val pkgs = try {
            windows?.mapNotNull { it.root?.packageName?.toString() }?.distinct().orEmpty()
        } catch (_: Throwable) {
            emptyList()
        }
        return if (pkgs.isEmpty()) {
            "active=$active windows=0"
        } else {
            "active=$active windows=${pkgs.size} pkgs=${pkgs.joinToString()}"
        }
    }

    fun root(): AccessibilityNodeInfo? {
        val target = automationTargetPackage
        val active = rootInActiveWindow
        if (target.isNullOrEmpty()) return active
        if (active != null && active.packageName?.toString() == target) return active
        findRootInWindows(target)?.let { return it }
        return active
    }

    private fun findRootInWindows(packageName: String): AccessibilityNodeInfo? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) return null
        return try {
            windows?.firstNotNullOfOrNull { window ->
                val r = window.root ?: return@firstNotNullOfOrNull null
                if (r.packageName?.toString() == packageName) r else null
            }
        } catch (t: Throwable) {
            Log.w(TAG, "getWindows failed", t)
            null
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        DebugLogStore.append("无障碍服务已连接")
        Log.i(TAG, "service connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() {
        DebugLogStore.append("无障碍服务被中断")
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        DebugLogStore.append("无障碍服务已断开")
        super.onDestroy()
    }

    fun dumpVisibleTree(maxNodes: Int = 80): String {
        val root = root() ?: return "(no root)"
        val lines = ArrayList<String>()
        fun walk(node: AccessibilityNodeInfo?, depth: Int) {
            if (node == null || lines.size >= maxNodes) return
            val text = node.text?.toString()?.trim().orEmpty()
            val desc = node.contentDescription?.toString()?.trim().orEmpty()
            val id = node.viewIdResourceName?.substringAfterLast('/') ?: ""
            val flags = buildString {
                if (node.isClickable) append('C')
                if (node.isEditable) append('E')
                if (node.isFocused) append('F')
                if (node.isSelected) append('S')
            }
            if (text.isNotEmpty() || desc.isNotEmpty() || id.isNotEmpty() || flags.isNotEmpty()) {
                lines += "${"  ".repeat(depth)}[$flags] id=$id text=$text desc=$desc"
            }
            for (i in 0 until node.childCount) {
                walk(node.getChild(i), depth + 1)
            }
        }
        walk(root, 0)
        return lines.joinToString("\n")
    }

    fun findNodes(predicate: (AccessibilityNodeInfo) -> Boolean): List<AccessibilityNodeInfo> {
        val root = root() ?: return emptyList()
        val out = ArrayList<AccessibilityNodeInfo>()
        fun walk(node: AccessibilityNodeInfo?) {
            if (node == null) return
            if (predicate(node)) out += AccessibilityNodeInfo.obtain(node)
            for (i in 0 until node.childCount) {
                walk(node.getChild(i))
            }
        }
        walk(root)
        return out
    }

    fun clickNode(node: AccessibilityNodeInfo): Boolean = clickNodeDetailed(node) != null

    /**
     * @return how the click was performed, or null if all strategies failed.
     */
    fun clickNodeDetailed(node: AccessibilityNodeInfo): String? {
        var cur: AccessibilityNodeInfo? = node
        var depth = 0
        while (cur != null) {
            if (cur.isClickable) {
                if (cur.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    return if (depth == 0) "ACTION_CLICK" else "ACTION_CLICK(parent+$depth)"
                }
            }
            cur = cur.parent
            depth++
        }
        return if (clickByGesture(node)) "GESTURE" else null
    }

    /**
     * TV Leanback tabs often report ACTION_CLICK success without navigating.
     * Try one activation style at a time; caller verifies UI after each.
     */
    fun activateNodeOnce(node: AccessibilityNodeInfo, style: String): Boolean {
        val rect = nodeBounds(node)
        return when (style) {
            "SHELL_TAP" -> {
                if (rect.isEmpty) false
                else shellTap(rect.centerX(), rect.centerY())
            }
            "SHELL_TAP_RIGHT" -> {
                // 白胶囊右侧放大镜图标区域
                if (rect.isEmpty) false
                else shellTap(rect.left + (rect.width() * 0.78f).toInt(), rect.centerY())
            }
            "SHELL_TAP_DOUBLE" -> {
                if (rect.isEmpty) false
                else {
                    val x = rect.centerX()
                    val y = rect.centerY()
                    shellTap(x, y)
                    SystemClock.sleep(120)
                    shellTap(x, y)
                }
            }
            "GESTURE" -> clickByGesture(node, durationMs = 160)
            "GESTURE_LONG" -> clickByGesture(node, durationMs = 280)
            "GESTURE_OFFSET" -> {
                if (rect.isEmpty) false
                else tapAt(rect.left + rect.width() * 0.72f, rect.exactCenterY(), 180)
            }
            "GESTURE_SWIPE_CLICK" -> {
                // 极短位移，部分 TV 对零长度 tap 不响应
                if (rect.isEmpty) false
                else swipeClick(rect.exactCenterX(), rect.exactCenterY())
            }
            "FOCUS_OK" -> {
                focusNodeChain(node)
                SystemClock.sleep(200)
                shellKeyEvent(23) // DPAD_CENTER
            }
            "ACTION_CLICK" -> {
                var cur: AccessibilityNodeInfo? = node
                while (cur != null) {
                    if (cur.isClickable && cur.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                        return true
                    }
                    cur = cur.parent
                }
                false
            }
            "SELECT_CLICK" -> {
                var cur: AccessibilityNodeInfo? = node
                while (cur != null) {
                    cur.performAction(AccessibilityNodeInfo.ACTION_SELECT)
                    if (cur.isClickable) {
                        return cur.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    }
                    cur = cur.parent
                }
                false
            }
            else -> false
        }
    }

    fun focusNodeChain(node: AccessibilityNodeInfo) {
        var cur: AccessibilityNodeInfo? = node
        while (cur != null) {
            cur.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            if (cur.isClickable) break
            cur = cur.parent
        }
    }

    fun shellTap(x: Int, y: Int): Boolean =
        try {
            Runtime.getRuntime()
                .exec(arrayOf("input", "tap", x.toString(), y.toString()))
                .waitFor() == 0
        } catch (_: Throwable) {
            false
        }

    private fun shellKeyEvent(code: Int): Boolean =
        try {
            Runtime.getRuntime().exec(arrayOf("input", "keyevent", code.toString())).waitFor() == 0
        } catch (_: Throwable) {
            false
        }

    fun tapAt(x: Float, y: Float, durationMs: Long = 80): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceAtLeast(50))
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return dispatchGesture(gesture, null, null)
    }

    private fun swipeClick(x: Float, y: Float): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val path = Path().apply {
            moveTo(x, y)
            lineTo(x + 3f, y + 2f)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, 120)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return dispatchGesture(gesture, null, null)
    }

    fun setText(node: AccessibilityNodeInfo, value: String): Boolean {
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value)
        }
        if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) return true
        // Fallback: clipboard-less paste is unavailable; try selecting and setting again.
        return false
    }

    fun rootContentBounds(): Rect {
        val root = root()
        if (root == null) {
            val dm = resources.displayMetrics
            return Rect(0, 0, dm.widthPixels, dm.heightPixels)
        }
        val r = nodeBounds(root)
        if (r.isEmpty) {
            val dm = resources.displayMetrics
            return Rect(0, 0, dm.widthPixels, dm.heightPixels)
        }
        return r
    }

    /** Swipe within the active window content (TV 常有黑边，勿用 displayMetrics 全屏坐标). */
    fun swipeInContent(fromXRatio: Float, toXRatio: Float, yRatio: Float = 0.08f): Boolean {
        val c = rootContentBounds()
        val y = c.top + c.height() * yRatio
        val fromX = c.left + c.width() * fromXRatio
        val toX = c.left + c.width() * toXRatio
        return swipe(fromX, y, toX, y, durationMs = 380)
    }

    fun nodeBounds(node: AccessibilityNodeInfo): Rect {
        val rect = Rect()
        node.getBoundsInScreen(rect)
        return rect
    }

    fun isNodeOnScreen(node: AccessibilityNodeInfo): Boolean {
        if (!node.isVisibleToUser) return false
        val rect = nodeBounds(node)
        if (rect.isEmpty || rect.width() < 2 || rect.height() < 2) return false
        val dm = resources.displayMetrics
        return rect.right > 8 &&
            rect.left < dm.widthPixels - 8 &&
            rect.bottom > 8 &&
            rect.top < dm.heightPixels - 8
    }

    /**
     * Swipe on screen. Coordinates in pixels.
     * Finger left (fromX > toX) reveals content on the right — for top tabs that hide 「搜索」.
     */
    fun swipe(
        fromX: Float,
        fromY: Float,
        toX: Float,
        toY: Float,
        durationMs: Long = 320,
    ): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val path = Path().apply {
            moveTo(fromX, fromY)
            lineTo(toX, toY)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceAtLeast(80))
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return dispatchGesture(gesture, null, null)
    }

    /** Horizontal swipe on the top tab strip: scroll tabs left (center a right-edge tab like 搜索). */
    fun swipeTopBarScrollTabsLeft(distanceRatio: Float = 0.38f): Boolean {
        val to = (0.25f + distanceRatio).coerceAtMost(0.78f)
        return swipeInContent(fromXRatio = 0.25f, toXRatio = to)
    }

    /** Horizontal swipe on the top tab strip: reveal tabs further to the right. */
    fun swipeTopBarToRevealRight(distanceRatio: Float = 0.55f): Boolean {
        val c = rootContentBounds()
        val yRatio = 0.10f
        val fromXRatio = 0.82f
        val toXRatio = (fromXRatio - distanceRatio).coerceAtLeast(0.12f)
        val y = c.top + c.height() * yRatio
        val fromX = c.left + c.width() * fromXRatio
        val toX = c.left + c.width() * toXRatio
        return swipe(fromX, y, toX, y, durationMs = 380)
    }

    /** Try ACTION_SCROLL_FORWARD on scrollable nodes near the top of the screen. */
    fun scrollTopBarForward(): Int {
        val dm = resources.displayMetrics
        val topBand = dm.heightPixels * 0.35f
        var scrolled = 0
        val scrollables = findNodes { node ->
            if (!node.isScrollable) return@findNodes false
            val r = nodeBounds(node)
            r.top < topBand && r.width() > dm.widthPixels * 0.2
        }
        for (node in scrollables) {
            if (node.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)) {
                scrolled++
            }
        }
        return scrolled
    }

    private fun clickByGesture(node: AccessibilityNodeInfo, durationMs: Long = 80): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        val rect = nodeBounds(node)
        if (rect.isEmpty) return false
        return tapAt(rect.exactCenterX(), rect.exactCenterY(), durationMs)
    }

    companion object {
        private const val TAG = "LivingRoomA11y"
        @Volatile
        var instance: LivingRoomAccessibilityService? = null
            private set

        fun isConnected(): Boolean = instance != null
    }
}
