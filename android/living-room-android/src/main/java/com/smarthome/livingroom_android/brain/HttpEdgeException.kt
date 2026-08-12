package com.smarthome.livingroom_android.brain

/** HTTP / brain edge protocol error. Code 401 → clear local edgeId and re-register. */
class HttpEdgeException(
    val httpCode: Int,
    message: String,
) : Exception(message)
