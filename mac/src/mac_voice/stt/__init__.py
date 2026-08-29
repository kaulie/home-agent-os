from mac_voice.stt.base import SpeechToText

__all__ = ["SpeechToText", "create_stt"]


def __getattr__(name: str):
    if name == "create_stt":
        from mac_voice.stt.factory import create_stt

        return create_stt
    raise AttributeError(name)
