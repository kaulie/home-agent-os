package com.smarthome.livingroom.a11y

import android.icu.text.Transliterator

/**
 * Chinese → Latin for NetEase TV search (首字母 / 全拼).
 * Uses ICU Transliterator (API 24+), no third-party pinyin lib.
 */
object ChinesePinyin {
    private val toLatin: Transliterator by lazy {
        Transliterator.getInstance(
            "Han-Latin; NFD; [:Nonspacing Mark:] Remove; NFC; Any-Lower",
        )
    }

    /** e.g. 十年 → shinian */
    fun fullLetters(text: String): String {
        val out = StringBuilder()
        for (ch in text) {
            when {
                ch.isWhitespace() || ch in IGNORE -> Unit
                ch.code < 128 -> if (ch.isLetterOrDigit()) out.append(ch.lowercaseChar())
                else -> out.append(toLatin.transliterate(ch.toString()).filter { it.isLetter() })
            }
        }
        return out.toString()
    }

    /** e.g. 十年 → sn ；陈奕迅 → cyx */
    fun initials(text: String): String {
        val out = StringBuilder()
        for (ch in text) {
            when {
                ch.isWhitespace() || ch in IGNORE -> Unit
                ch.code < 128 -> if (ch.isLetterOrDigit()) out.append(ch.lowercaseChar())
                else -> {
                    val py = toLatin.transliterate(ch.toString()).filter { it.isLetter() }
                    if (py.isNotEmpty()) out.append(py.first())
                }
            }
        }
        return out.toString()
    }

    private const val IGNORE = "·.-_/|'\"“”《》【】（）()[]{}，。、！？:：;；,@#￥%…"
}
