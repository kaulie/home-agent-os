from __future__ import annotations

import logging
import signal
import time
from typing import Any

from mac_edge.brain_client import BrainClient, BrainError, format_intent_summary
from mac_edge.config import Config
from mac_edge.executor import handle_intent as executor_handle
from mac_edge.intranet_ping_monitor import IntranetPingMonitor
from mac_edge.scheduler import IntentScheduler
from mac_edge.state import clear_edge_id, load_edge_id, save_edge_id

log = logging.getLogger("mac_edge.agent")

# While Brain is down: warn at most once per this interval (no stack traces).
_BRAIN_WARN_EVERY_SEC = 60.0
# Cap backoff so we still recover reasonably fast after Brain returns.
_MAX_BACKOFF_SEC = 120.0
# Idle "no intents" chatter — once per minute is enough.
_EMPTY_INTENTS_LOG_EVERY_SEC = 60.0


class EdgeAgent:
    """Background loop: register → heartbeat → pull → scheduler → executor."""

    def __init__(self, config: Config):
        self.config = config
        self._stop = False
        self._edge_id: str | None = load_edge_id(config.edge_id_path)
        self._scheduler = IntentScheduler()
        self._brain_down = False
        self._brain_fail_streak = 0
        self._last_brain_warn_mono = 0.0
        self._suppressed_brain_errors = 0
        self._last_empty_intents_mono = 0.0
        self._intranet_ping = IntranetPingMonitor(config.intranet_ping)

    def request_stop(self, *_args: Any) -> None:
        log.info("stop requested")
        self._stop = True
        self._intranet_ping.stop()

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        log.info(
            "Mac Edge starting brain=%s hint=%s interval=%ss data=%s "
            "cached_edge_id=%s cast_display=%s intranet_ping=%s/%s",
            self.config.brain_base_url,
            self.config.identity.client_hint,
            self.config.interval_sec,
            self.config.data_dir,
            self._edge_id or "(none)",
            self.config.cast_display_url,
            "on" if self.config.intranet_ping.enabled else "off",
            self.config.intranet_ping.mode,
        )
        self._intranet_ping.start()

        try:
            with BrainClient(self.config) as brain:
                while not self._stop:
                    tick_started = time.monotonic()
                    sleep_for = max(0.5, float(self.config.interval_sec))
                    try:
                        self._tick(brain)
                        if self._brain_down:
                            log.info(
                                "brain reachable again (after %s failed tick(s))",
                                self._brain_fail_streak,
                            )
                        self._brain_down = False
                        self._brain_fail_streak = 0
                        self._suppressed_brain_errors = 0
                        elapsed = time.monotonic() - tick_started
                        sleep_for = max(0.5, self.config.interval_sec - elapsed)
                    except BrainError as e:
                        if e.is_unauthorized:
                            log.warning("unauthorized during tick — clearing edge_id")
                            clear_edge_id(self.config.edge_id_path)
                            self._edge_id = None
                            sleep_for = max(0.5, float(self.config.interval_sec))
                        else:
                            self._note_brain_problem(e)
                            sleep_for = self._backoff_seconds()
                    except Exception:
                        log.exception("tick failed")
                        elapsed = time.monotonic() - tick_started
                        sleep_for = max(0.5, self.config.interval_sec - elapsed)
                    self._interruptible_sleep(sleep_for)
        finally:
            self._intranet_ping.stop()

        log.info("Mac Edge stopped edge_id=%s", self._edge_id or "(none)")

    def _tick(self, brain: BrainClient) -> None:
        if not self._edge_id:
            self._register(brain)
            if not self._edge_id:
                return

        try:
            brain.heartbeat(self._edge_id)
        except BrainError as e:
            if e.is_unauthorized:
                log.warning("heartbeat 401 — clearing edge_id and re-registering")
                clear_edge_id(self.config.edge_id_path)
                self._edge_id = None
                self._register(brain)
                if self._edge_id:
                    brain.heartbeat(self._edge_id)
                return
            raise

        assert self._edge_id
        # Peek (not pop): step 2 on Mac must re-see the intent after iPhone finishes step 1.
        intents = brain.pull_intents(self._edge_id, consume=False)
        if not intents:
            self._log_empty_intents()
            return
        log.info(
            "intents: peeked %d (edge_id=%s) — scheduler then executor",
            len(intents),
            self._edge_id,
        )
        for intent in intents:
            iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
            # Refresh plan/outputs so predecessor step status and photo_url are current.
            if iid:
                detail = brain.fetch_intent_detail(iid)
                if isinstance(detail, dict) and detail:
                    intent = _merge_intent_detail(intent, detail)
            log.info("  %s", format_intent_summary(intent))
            try:
                self._scheduler.handle(
                    intent,
                    edge_id=self._edge_id,
                    brain=brain,
                )
            except Exception:
                log.exception("scheduler failed id=%s", intent.get("id"))
            try:
                executor_handle(
                    intent,
                    edge_id=self._edge_id,
                    config=self.config,
                    brain=brain,
                )
            except Exception:
                log.exception("executor failed id=%s", intent.get("id"))

    def _register(self, brain: BrainClient) -> None:
        result = brain.register()
        self._edge_id = result.edge_id
        save_edge_id(self.config.edge_id_path, result.edge_id)

    def _note_brain_problem(self, err: BaseException) -> None:
        """Throttle Brain-down warnings: one line / minute, never full traceback."""
        self._brain_fail_streak += 1
        self._brain_down = True
        now = time.monotonic()
        if now - self._last_brain_warn_mono >= _BRAIN_WARN_EVERY_SEC:
            extra = ""
            if self._suppressed_brain_errors:
                extra = f" (suppressed {self._suppressed_brain_errors} similar)"
            log.warning(
                "brain unreachable — backing off streak=%s err=%s%s",
                self._brain_fail_streak,
                err,
                extra,
            )
            self._last_brain_warn_mono = now
            self._suppressed_brain_errors = 0
        else:
            self._suppressed_brain_errors += 1

    def _backoff_seconds(self) -> float:
        # 3, 6, 12, 24, 48, 96, cap 120 — still probes while Brain is down.
        exp = min(self._brain_fail_streak, 6)
        return float(min(_MAX_BACKOFF_SEC, self.config.interval_sec * (2**exp)))

    def _log_empty_intents(self) -> None:
        now = time.monotonic()
        if now - self._last_empty_intents_mono < _EMPTY_INTENTS_LOG_EVERY_SEC:
            return
        self._last_empty_intents_mono = now
        log.info("intents: empty (edge_id=%s)", self._edge_id)

    def _interruptible_sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end:
            time.sleep(min(0.5, end - time.monotonic()))


def _merge_intent_detail(
    intent: dict[str, Any], detail: dict[str, Any]
) -> dict[str, Any]:
    """Overlay detail fields onto pull snapshot (plan status / outputs)."""
    merged = dict(intent)
    for key in (
        "status",
        "intent_status",
        "execution_plan",
        "ctx_param",
        "scheduler_node",
        "step_log",
    ):
        if key in detail and detail[key] is not None:
            merged[key] = detail[key]
    if detail.get("id") is not None:
        merged["id"] = detail["id"]
    elif detail.get("intent_id") is not None:
        merged["id"] = detail["intent_id"]
    return merged
