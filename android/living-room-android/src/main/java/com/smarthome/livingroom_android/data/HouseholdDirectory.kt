package com.smarthome.livingroom_android.data

import org.json.JSONArray
import org.json.JSONObject

data class HouseholdPerson(
    val name: String,
    val number: String,
    val aliases: List<String> = emptyList(),
)

/** Local directory of people this Console is allowed to call. Plugin only looks up by this-step `name`. */
object HouseholdDirectory {
    fun parse(raw: String): List<HouseholdPerson> {
        if (raw.isBlank()) return emptyList()
        return runCatching {
            val arr = JSONArray(raw)
            (0 until arr.length()).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                val name = o.optString("name").trim()
                val number = o.optString("number").trim()
                if (name.isEmpty() || number.isEmpty()) return@mapNotNull null
                val aliases = o.optJSONArray("aliases")?.let { a ->
                    (0 until a.length()).mapNotNull { j -> a.optString(j).trim().takeIf { it.isNotEmpty() } }
                }.orEmpty()
                HouseholdPerson(name, number, aliases)
            }
        }.getOrDefault(emptyList())
    }

    fun encode(people: List<HouseholdPerson>): String {
        val arr = JSONArray()
        for (p in people) {
            arr.put(
                JSONObject()
                    .put("name", p.name)
                    .put("number", p.number)
                    .put("aliases", JSONArray(p.aliases)),
            )
        }
        return arr.toString()
    }

    fun resolve(people: List<HouseholdPerson>, rawName: String): HouseholdPerson? {
        val q = normalize(rawName)
        if (q.isEmpty()) return null
        people.firstOrNull { normalize(it.name) == q }?.let { return it }
        people.firstOrNull { it.aliases.any { a -> normalize(a) == q } }?.let { return it }
        people.firstOrNull { q.contains(normalize(it.name)) && normalize(it.name).length >= 2 }?.let { return it }
        people.firstOrNull { it.aliases.any { a -> q.contains(normalize(a)) && normalize(a).length >= 2 } }?.let { return it }
        return null
    }

    private fun normalize(raw: String): String =
        raw.trim()
            .replace(Regex("[\\s　]+"), "")
            .removePrefix("给")
            .removePrefix("打给")
            .removeSuffix("打电话")
            .removeSuffix("电话")
            .removeSuffix("手机")
            .lowercase()
}
