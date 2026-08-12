package com.smarthome.livingroom.control

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothA2dp
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import com.smarthome.livingroom.debug.DebugLogStore
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Connects a bonded Bluetooth speaker (A2DP) — e.g. Marshall WILLEN on Chromecast TV.
 */
class BluetoothSpeakerConnector(
    private val context: Context,
) {
    data class ConnectResult(
        val success: Boolean,
        val message: String,
        val deviceName: String? = null,
        val deviceAddress: String? = null,
    )

    fun hasConnectPermission(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.BLUETOOTH_CONNECT,
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }

    @SuppressLint("MissingPermission")
    fun connectBondedSpeaker(
        nameHint: String = DEFAULT_NAME,
        addressHint: String = DEFAULT_ADDRESS,
    ): ConnectResult {
        if (!hasConnectPermission()) {
            return ConnectResult(false, "缺少 BLUETOOTH_CONNECT 权限，请在弹窗中允许")
        }

        val adapter = BluetoothAdapter.getDefaultAdapter()
            ?: return ConnectResult(false, "本机无蓝牙适配器")

        if (!adapter.isEnabled) {
            return ConnectResult(false, "蓝牙未开启，请先在系统设置中打开")
        }

        val device = resolveBondedDevice(adapter, nameHint, addressHint)
            ?: return ConnectResult(
                false,
                "未找到已配对设备「$nameHint」($addressHint)，请先在 TV 设置里配对",
            )

        DebugLogStore.append(
            "[蓝牙] 尝试连接 A2DP: ${device.name ?: nameHint} (${device.address})",
        )

        return connectA2dp(adapter, device)
    }

    @SuppressLint("MissingPermission")
    private fun resolveBondedDevice(
        adapter: BluetoothAdapter,
        nameHint: String,
        addressHint: String,
    ): BluetoothDevice? {
        val bonded = adapter.bondedDevices ?: emptySet()
        bonded.firstOrNull { it.address.equals(addressHint, ignoreCase = true) }?.let {
            return it
        }
        val hint = nameHint.trim()
        if (hint.isNotEmpty()) {
            bonded.firstOrNull { dev ->
                dev.name?.contains(hint, ignoreCase = true) == true
            }?.let { return it }
        }
        return null
    }

    @SuppressLint("MissingPermission")
    private fun connectA2dp(adapter: BluetoothAdapter, device: BluetoothDevice): ConnectResult {
        val latch = CountDownLatch(1)
        var outcome: ConnectResult? = null
        var proxyRef: BluetoothProfile? = null

        val listener = object : BluetoothProfile.ServiceListener {
            override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                proxyRef = proxy
                try {
                    if (profile != BluetoothProfile.A2DP) {
                        outcome = ConnectResult(false, "A2DP 服务不可用")
                        return
                    }
                    val a2dp = proxy as BluetoothA2dp
                    val before = a2dp.getConnectionState(device)
                    if (before == BluetoothProfile.STATE_CONNECTED) {
                        outcome = ConnectResult(
                            true,
                            "A2DP 已连接",
                            device.name,
                            device.address,
                        )
                        DebugLogStore.append("[蓝牙] 已是连接状态")
                        return
                    }

                    val invoked = invokeConnect(a2dp, device)
                    DebugLogStore.append("[蓝牙] connect() 调用=${if (invoked) "已发出" else "失败"}")

                    var after = a2dp.getConnectionState(device)
                    val deadline = System.currentTimeMillis() + CONNECT_WAIT_MS
                    while (System.currentTimeMillis() < deadline) {
                        after = a2dp.getConnectionState(device)
                        if (after == BluetoothProfile.STATE_CONNECTED) break
                        if (after == BluetoothProfile.STATE_DISCONNECTED && !invoked) break
                        Thread.sleep(400)
                    }

                    outcome = when (after) {
                        BluetoothProfile.STATE_CONNECTED -> ConnectResult(
                            true,
                            "A2DP 连接成功",
                            device.name,
                            device.address,
                        )
                        BluetoothProfile.STATE_CONNECTING -> ConnectResult(
                            false,
                            "仍在连接中，请确认 WILLEN 已开机且在范围内",
                            device.name,
                            device.address,
                        )
                        else -> ConnectResult(
                            false,
                            "连接失败 (state=$after)，请在 TV 蓝牙设置中手动点 WILLEN",
                            device.name,
                            device.address,
                        )
                    }
                    DebugLogStore.append("[蓝牙] 结果: ${outcome?.message}")
                } catch (t: Throwable) {
                    outcome = ConnectResult(false, "连接异常: ${t.message}", device.name, device.address)
                    DebugLogStore.append("[蓝牙] 异常: ${t.message}")
                } finally {
                    latch.countDown()
                }
            }

            override fun onServiceDisconnected(profile: Int) {
            }
        }

        if (!adapter.getProfileProxy(context, listener, BluetoothProfile.A2DP)) {
            return ConnectResult(false, "无法获取 A2DP 服务")
        }

        if (!latch.await(PROXY_WAIT_SEC, TimeUnit.SECONDS)) {
            proxyRef?.let { adapter.closeProfileProxy(BluetoothProfile.A2DP, it) }
            return ConnectResult(false, "连接超时（${PROXY_WAIT_SEC}s）")
        }
        proxyRef?.let { adapter.closeProfileProxy(BluetoothProfile.A2DP, it) }
        return outcome ?: ConnectResult(false, "未知错误")
    }

    private fun invokeConnect(a2dp: BluetoothA2dp, device: BluetoothDevice): Boolean {
        try {
            val method = BluetoothA2dp::class.java.getMethod("connect", BluetoothDevice::class.java)
            return method.invoke(a2dp, device) as? Boolean ?: false
        } catch (_: Throwable) {
        }
        try {
            val method = BluetoothDevice::class.java.getMethod("connect")
            val code = method.invoke(device) as? Int
            return code == 0
        } catch (_: Throwable) {
        }
        return false
    }

    companion object {
        const val DEFAULT_NAME = "WILLEN"
        const val DEFAULT_ADDRESS = "68:59:32:EB:C3:DC"
        private const val CONNECT_WAIT_MS = 8_000L
        private const val PROXY_WAIT_SEC = 15L
    }
}
