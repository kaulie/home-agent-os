package com.smarthome.livingroom_android.command

/** Local beat index for interval/cron steps (scheduler-owned, not Brain-computed). */
object TimingBeats {
    private val lock = Any()
    // (intentId, stepNum) -> beatIndex
    private val beats = mutableMapOf<Pair<String, Int>, Int>()

    private fun beatKey(intentId: String, stepNum: Int): Pair<String, Int> =
        intentId.trim() to stepNum

    fun getBeat(intentId: String, stepNum: Int): Int = synchronized(lock) {
        beats[beatKey(intentId, stepNum)] ?: 0
    }

    fun setBeat(intentId: String, stepNum: Int, beat: Int) = synchronized(lock) {
        beats[beatKey(intentId, stepNum)] = maxOf(0, beat)
    }

    fun advanceBeat(intentId: String, stepNum: Int): Int = synchronized(lock) {
        val k = beatKey(intentId, stepNum)
        val nxt = (beats[k] ?: 0) + 1
        beats[k] = nxt
        nxt
    }

    fun clearIntent(intentId: String) = synchronized(lock) {
        val iid = intentId.trim()
        beats.keys.filter { it.first == iid }.forEach { beats.remove(it) }
    }
}
