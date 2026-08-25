package com.smarthome.livingroom_android.skill

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.core.content.ContextCompat
import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.data.HouseholdDirectory
import com.smarthome.livingroom_android.data.HouseholdPerson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Call a named person from this-step params only.
 * Required: `name`. Optional: `number` (skips directory lookup).
 */
class PhoneCallSkill(
    private val people: () -> List<HouseholdPerson>,
) : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.1.0",
        displayName = "本机电话",
        group = "phone",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.PHONE_CALL,
                kind = "action",
                role = "电话拨打器",
                plannerRecognize = "按家里通讯录的姓名打电话（打给李秀平、给妈妈打电话）。不发短信、不开灯",
                typicalTriggers = listOf("打电话", "打给", "拨打", "打个电话", "给妈妈打电话", "打给爸爸", "呼叫高磊"),
                doNotDispatch = listOf("发短信", "开灯", "拍照", "知识问答"),
                inputSchema = mapOf(
                    "name" to SchemaField(
                        type = "string",
                        required = true,
                        description = "要呼叫的人，须能在本机家庭目录匹配（如妈妈、爸爸）",
                    ),
                    "number" to SchemaField(
                        type = "string",
                        required = false,
                        description = "若本步已带号码则直接拨，不再查目录",
                    ),
                ),
                outputSchema = mapOf(
                    "status" to SchemaField(
                        type = "string",
                        required = true,
                        description = "dialing",
                    ),
                    "called_name" to SchemaField(
                        type = "string",
                        required = true,
                        description = "实际呼叫的人",
                    ),
                ),
            ),
        ),
    )

    override suspend fun isAvailable(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult {
        val name = param(params, "name")
        val number = digits(param(params, "number"))
        if (name.isEmpty() && number.isEmpty()) {
            return SkillResult.error("phone.call 需要 name（要呼叫的人）")
        }
        if (number.isEmpty() && HouseholdDirectory.resolve(people(), name) == null) {
            return SkillResult.error("找不到「$name」。请在设置里把这个人加到可呼叫目录。")
        }
        return SkillResult.ok("available")
    }

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.Main) {
        val name = param(params, "name")
        val direct = digits(param(params, "number"))
        val person: HouseholdPerson? = if (direct.isNotEmpty()) {
            HouseholdPerson(name.ifBlank { direct }, direct)
        } else {
            HouseholdDirectory.resolve(people(), name)
        }
        if (person == null) {
            return@withContext SkillResult.error(
                if (name.isEmpty()) "phone.call 需要 name（要呼叫的人）"
                else "找不到「$name」。请在设置里把这个人加到可呼叫目录。",
            )
        }
        val tel = digits(person.number)
        if (tel.isEmpty()) {
            return@withContext SkillResult.error("「${person.name}」没有有效电话号码")
        }
        val canCall = ContextCompat.checkSelfPermission(ctx.appContext, Manifest.permission.CALL_PHONE) ==
            PackageManager.PERMISSION_GRANTED
        val intent = Intent(if (canCall) Intent.ACTION_CALL else Intent.ACTION_DIAL).apply {
            data = Uri.parse("tel:$tel")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        try {
            ctx.appContext.startActivity(intent)
        } catch (t: Throwable) {
            return@withContext SkillResult.error("无法拨号：${t.message}")
        }
        SkillResult.ok(
            message = "正在呼叫${person.name}",
            outputs = mapOf(
                "status" to "dialing",
                "called_name" to person.name,
            ),
        )
    }

    companion object {
        const val SKILL_ID = "android.phone"

        private fun param(params: Map<String, Any?>, key: String): String =
            params[key]?.toString()?.trim().orEmpty()

        private fun digits(raw: String): String =
            raw.filter { it.isDigit() || it == '+' }
    }
}
