"""voicewakeup.echo is independent of notify.speak."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from mac_edge.plugins.voicewakeup_echo import DEFAULT_ECHO, echo_from_params


class VoiceWakeupEchoTests(unittest.TestCase):
    def test_default_phrase_when_text_missing(self) -> None:
        with patch("mac_edge.plugins.voicewakeup_echo.echo", return_value=DEFAULT_ECHO) as fn:
            msg, outputs = echo_from_params({})
        fn.assert_called_once_with(None)
        self.assertEqual(outputs["echo_text"], DEFAULT_ECHO)
        self.assertIn("voicewakeup.echo", msg)

    def test_uses_resolved_text(self) -> None:
        with patch("mac_edge.plugins.voicewakeup_echo.echo", return_value="又咋了") as fn:
            _msg, outputs = echo_from_params({"text": "又咋了"})
        fn.assert_called_once_with("又咋了")
        self.assertEqual(outputs["echo_text"], "又咋了")

    def test_say_uses_chinese_voice(self) -> None:
        from mac_edge.plugins import voicewakeup_echo as mod

        completed = type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        with (
            patch.object(mod, "_pick_zh_say_voice", return_value="Tingting"),
            patch.object(mod.shutil, "which", return_value=mod.SAY_BIN),
            patch("mac_edge.plugins.voicewakeup_echo.subprocess.run", return_value=completed) as run,
        ):
            mod.echo("又咋了")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:3], [mod.SAY_BIN, "-v", "Tingting"])
        self.assertEqual(cmd[-1], "又咋了")

    def test_echo_does_not_mute_mic(self) -> None:
        from mac_edge.plugins import voicewakeup_echo as mod

        completed = type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        with (
            patch.object(mod, "_pick_zh_say_voice", return_value="Tingting"),
            patch.object(mod.shutil, "which", return_value=mod.SAY_BIN),
            patch("mac_edge.plugins.voicewakeup_echo.subprocess.run", return_value=completed),
            patch("mac_edge.tts_playback.playback_session") as session,
        ):
            mod.echo("又咋了")
        session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
