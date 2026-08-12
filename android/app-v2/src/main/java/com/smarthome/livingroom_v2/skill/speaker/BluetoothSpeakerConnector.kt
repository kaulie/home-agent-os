package com.smarthome.livingroom_v2.skill.speaker

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothA2dp
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * A2DP connect/disconnect for a bonded Marshall (WILLEN) speaker.
 * Rewritten for v2 — does not import v1 packages.
 */
class BluetoothSpeakerConnector(
    private val context: Context,
) {
    data class Result(
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
    ): Result = runA2dpAction(nameHint, addressHint, connect = true)

    @SuppressLint("MissingPermission")
    fun disconnectBondedSpeaker(
        nameHint: String = DEFAULT_NAME,
        addressHint: String = DEFAULT_ADDRESS,
    ): Result = runA2dpAction(nameHint, addressHint, connect = false)

    @SuppressLint("MissingPermission")
    private fun runA2dpAction(
        nameHint: String,
        addressHint: String,
        connect: Boolean,
    ): Result {
        if (!hasConnectPermission()) {
            return Result(false, "缺少 BLUETOOTH_CONNECT 权限，请在弹窗中允许")
        }
        val adapter = BluetoothAdapter.getDefaultAdapter()
            ?: return Result(false, "本机无蓝牙适配器")
        if (!adapter.isEnabled) {
            return Result(false, "蓝牙未开启，请先在系统设置中打开")
        }
        val device = resolveBondedDevice(adapter, nameHint, addressHint)
            ?: return Result(
                false,
                "未找到已配对设备「$nameHint」($addressHint)，请先在 TV 设置里配对",
            )

        Log.i(TAG, "${if (connect) "connect" else "disconnect"} A2DP ${device.name} ${device.address}")
        return invokeA2dp(adapter, device, connect)
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
    private fun invokeA2dp(
        adapter: BluetoothAdapter,
        device: BluetoothDevice,
        connect: Boolean,
    ): Result {
        val latch = CountDownLatch(1)
        var outcome: Result? = null
        var proxyRef: BluetoothProfile? = null

        val listener = object : BluetoothProfile.ServiceListener {
            override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                proxyRef = proxy
                try {
                    if (profile != BluetoothProfile.A2DP) {
                        outcome = Result(false, "A2DP 服务不可用")
                        return
                    }
                    val a2dp = proxy as BluetoothA2dp
                    val before = a2dp.getConnectionState(device)
                    if (connect && before == BluetoothProfile.STATE_CONNECTED) {
                        outcome = Result(true, "A2DP 已连接", device.name, device.address)
                        return
                    }
                    if (!connect && before == BluetoothProfile.STATE_DISCONNECTED) {
                        outcome = Result(true, "A2DP 已断开", device.name, device.address)
                        return
                    }

                    val invoked = if (connect) {
                        invokeHidden(a2dp, device, "connect")
                    } else {
                        invokeHidden(a2dp, device, "disconnect")
                    }
                    Log.i(TAG, "${if (connect) "connect" else "disconnect"} invoked=$invoked")

                    val target = if (connect) {
                        BluetoothProfile.STATE_CONNECTED
                    } else {
                        BluetoothProfile.STATE_DISCONNECTED
                    }
                    var after = a2dp.getConnectionState(device)
                    val deadline = System.currentTimeMillis() + WAIT_MS
                    while (System.currentTimeMillis() < deadline) {
                        after = a2dp.getConnectionState(device)
                        if (after == target) break
                        Thread.sleep(400)
                    }

                    outcome = when {
                        after == target -> Result(
                            true,
                            if (connect) "A2DP 连接成功" else "A2DP 断开成功",
                            device.name,
                            device.address,
                        )
                        connect && after == BluetoothProfile.STATE_CONNECTING -> Result(
                            false,
                            "仍在连接中，请确认 WILLEN 已开机且在范围内",
                            device.name,
                            device.address,
                        )
                        else -> Result(
                            false,
                            "${if (connect) "连接" else "断开"}失败 (state=$after)",
                            device.name,
                            device.address,
                        )
                    }
                } catch (t: Throwable) {
                    outcome = Result(false, "蓝牙异常: ${t.message}", device.name, device.address)
                } finally {
                    latch.countDown()
                }
            }

            override fun onServiceDisconnected(profile: Int) = Unit
        }

        if (!adapter.getProfileProxy(context, listener, BluetoothProfile.A2DP)) {
            return Result(false, "无法获取 A2DP 服务")
        }
        if (!latch.await(PROXY_WAIT_SEC, TimeUnit.SECONDS)) {
            proxyRef?.let { adapter.closeProfileProxy(BluetoothProfile.A2DP, it) }
            return Result(false, "操作超时（${PROXY_WAIT_SEC}s）")
        }
        proxyRef?.let { adapter.closeProfileProxy(BluetoothProfile.A2DP, it) }
        return outcome ?: Result(false, "未知错误")
    }

    private fun invokeHidden(a2dp: BluetoothA2dp, device: BluetoothDevice, methodName: String): Boolean {
        try {
            val method = BluetoothA2dp::class.java.getMethod(methodName, BluetoothDevice::class.java)
            return method.invoke(a2dp, device) as? Boolean ?: false
        } catch (_: Throwable) {
        }
        return false
    }

    companion object {
        const val DEFAULT_NAME = "WILLEN"
        const val DEFAULT_ADDRESS = "68:59:32:EB:C3:DC"
        private const val TAG = "BtSpeakerConnector"
        private const val WAIT_MS = 8_000L
        private const val PROXY_WAIT_SEC = 15L
    }
}
