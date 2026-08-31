from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any

from mac_edge.brain_client import BrainError, format_intent_summary
from mac_edge.multi_brain import MultiBrainClient, remember_intent_origin
from mac_edge.config import Config
from mac_edge.delivery import run_pending_deliveries
from mac_edge.executor import (
    DEADLINE_SLEEP_MIN_SEC,
    earliest_local_deadline_ms,
    fail_empty_plan_intent,
    handle_intent as executor_handle,
    prefetch_upcoming_speaks,
    sleep_sec_until_deadline,
)
from mac_edge.intranet_ping_monitor import IntranetPingMonitor
from mac_edge.local_ledger import LocalLedger, bind as bind_ledger
from mac_edge.scheduler import IntentScheduler
from mac_edge.services import voice_stream_enabled
from mac_edge.state import clear_edge_id, load_edge_id, save_edge_id, ensure_runtime_id
from mac_edge.timing_beats import set_beat_listener
from mac_edge.voice_supervisor import VoiceSupervisor
from mac_edge.plugins.video_live_ingest import VideoLiveIngestServer
from mac_edge.plugins.xiaodu_speaker import XiaoduTtsHttpServer, bind_server

try:
    import importlib.util
    from pathlib import Path

    # Load the shared server/mdns_service.py by file path so we don't add
    # server/ to sys.path (which would shadow the mac `tests` namespace package).
    _MDNS_PATH = Path(__file__).resolve().parents[3] / "server" / "mdns_service.py"
    _spec = importlib.util.spec_from_file_location("home_agent_mdns_service", _MDNS_PATH)
    mdns_service = importlib.util.module_from_spec(_spec)
    if _spec is not None and _spec.loader is not None:
        _spec.loader.exec_module(mdns_service)
except Exception:
    mdns_service = None

log = logging.getLogger("mac_edge.agent")

# While Brain is down: warn at most once per this interval (no stack traces).
_BRAIN_WARN_EVERY_SEC = 60.0
# Cap backoff so we still recover reasonably fast after Brain returns.
_MAX_BACKOFF_SEC = 120.0
# Idle "no intents" chatter — once per minute is enough.
_EMPTY_INTENTS_LOG_EVERY_SEC = 60.0
# Heartbeat must not hang the channel forever; keep it snappier than pull/execute.
_HEARTBEAT_HTTP_TIMEOUT_SEC = 8.0


class EdgeAgent:
    """Two Brain channels + highest-priority step execution.

    Channels (separate threads, separate httpx clients):
      1) heartbeat — keep-alive only; never blocks step timing
      2) control   — pull intents / refresh detail / deadline sleep → enqueue
      3) executor  — run steps (notify.speak etc.); highest work priority

    Status RUNNING posts use a small background pool (see brain_client).
    """

    def __init__(self, config: Config):
        self.config = config
        self._stop = False
        self._edge_id_lock = threading.Lock()
        self._edge_id: str | None = load_edge_id(config.edge_id_path)
        # P0: ensure a stable Runtime Identity exists (client-supplied, persisted).
        # Smooth migration: reuse cached edge_id if present.
        self._runtime_id = ensure_runtime_id(
            config.runtime_id_path, edge_id_path=config.edge_id_path
        )
        self._brain_down = False
        self._brain_fail_streak = 0
        self._last_brain_warn_mono = 0.0
        self._suppressed_brain_errors = 0
        self._last_empty_intents_mono = 0.0
        self._intranet_ping = IntranetPingMonitor(config.intranet_ping)

        self._ledger = LocalLedger(config.data_dir / "local_ledger.json")
        bind_ledger(self._ledger)
        set_beat_listener(self._ledger.note_beat)

        self._work_lock = threading.Lock()
        self._pending_intents: dict[str, dict[str, Any]] = {}
        self._executing_ids: set[str] = set()
        self._work_wake = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        # Schedule hops (parsed → scheduled → dispatched) on the control
        # thread so a long query.content cannot leave the next intent stuck
        # at intent_parsed.
        self._scheduler = IntentScheduler()
        # Voice may POST /voice/wake only after Brain knows this id (heartbeat OK).
        # Cached edge_id from another Brain would 401 until re-register.
        self._heartbeat_ok_edge_id: str | None = None
        self._voice = VoiceSupervisor(
            mac_root=config.data_dir.parent,
            edge_id_path=config.edge_id_path,
            brain_url=config.brain_base_url,
            client_hint=config.identity.client_hint,
            enabled=voice_stream_enabled(),
            get_edge_id=self._get_voice_edge_id,
        )
        self._video_ingest = VideoLiveIngestServer.from_env(config.data_dir)
        self._xiaodu_tts = XiaoduTtsHttpServer.from_env(config.data_dir)
        self._mdns: Any = None

    def request_stop(self, *_args: Any) -> None:
        log.info("stop requested")
        self._stop = True
        self._work_wake.set()
        self._intranet_ping.stop()
        self._voice.stop()
        if self._video_ingest is not None:
            self._video_ingest.stop()
        if self._xiaodu_tts is not None:
            self._xiaodu_tts.stop()
            bind_server(None)
        if self._mdns is not None:
            self._mdns.close()
            self._mdns = None

    def _start_mdns_publish(self) -> None:
        """Publish this Mac as gateway + runtime via mDNS (multi-identity)."""
        if mdns_service is None:
            log.info("mdns publish skipped (mdns_service not importable)")
            return
        try:
            pub = mdns_service.MdnsPublisher()
            edge_id = (self._get_edge_id() or "mac").strip()
            http_port = int(os.environ.get("MAC_EDGE_VIDEO_INGEST_HTTP_PORT") or 8790)
            txt = {
                "edge_id": edge_id,
                "voice_port": os.environ.get("MAC_EDGE_VOICE_INGEST_PORT") or "8792",
                "video_port": str(http_port),
                "img_port": "8080",
                "tts_port": "8000",
                "lan_ip": mdns_service.lan_ipv4(),
            }
            pub.publish(
                name=f"Home Agent Gateway {edge_id}",
                type_=mdns_service.GATEWAY_TYPE,
                port=http_port,
                txt=txt,
                hostname="gateway.local",
            )
            pub.publish(
                name=f"Home Agent Runtime {edge_id}",
                type_=mdns_service.RUNTIME_TYPE,
                port=http_port,
                txt={"edge_id": edge_id},
                hostname=f"runtime-{edge_id}.local",
            )
            self._mdns = pub
            log.info("mdns published gateway+runtime edge_id=%s txt=%s", edge_id, txt)
        except Exception:
            log.warning("mdns publish failed; continuing without it", exc_info=True)

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        log.info(
            "Mac Edge starting brain=%s brains=%s domains=%s hint=%s interval=%ss data=%s "
            "cached_edge_id=%s runtime_id=%s cast_display=%s intranet_ping=%s/%s "
            "channels=heartbeat|control|executor deadline_sleep=cap10s/half-remaining",
            self.config.brain_base_url,
            ",".join(self.config.brain_base_urls),
            ",".join(f"{k}={v}" for k, v in self.config.brain_urls_by_domain.items()) or "-",
            self.config.identity.client_hint,
            self.config.interval_sec,
            self.config.data_dir,
            self._get_edge_id() or "(none)",
            self._runtime_id,
            self.config.cast_display_url,
            "on" if self.config.intranet_ping.enabled else "off",
            self.config.intranet_ping.mode,
        )
        self._intranet_ping.start()
        self._voice.start()
        if self._video_ingest is not None:
            try:
                self._video_ingest.start()
            except OSError:
                log.exception("video live ingest failed to bind; continuing without it")
                self._video_ingest = None
        if self._xiaodu_tts is not None:
            try:
                self._xiaodu_tts.start()
                bind_server(self._xiaodu_tts)
            except OSError:
                log.exception("xiaodu TTS HTTP failed to bind; continuing without it")
                self._xiaodu_tts = None
                bind_server(None)
        self._start_mdns_publish()
        self._ensure_channel_threads()

        try:
            # Control channel: pull + deadline wake. Never does heartbeat here.
            with MultiBrainClient(list(self.config.brain_base_urls), config=self.config) as brain:
                while not self._stop:
                    self._ensure_channel_threads()
                    tick_started = time.monotonic()
                    sleep_for = max(DEADLINE_SLEEP_MIN_SEC, float(self.config.interval_sec))
                    next_deadline: int | None = None
                    try:
                        next_deadline = self._control_tick(brain)
                        if self._brain_down:
                            log.info(
                                "brain reachable again (after %s failed control tick(s))",
                                self._brain_fail_streak,
                            )
                        self._brain_down = False
                        self._brain_fail_streak = 0
                        self._suppressed_brain_errors = 0
                        elapsed = time.monotonic() - tick_started
                        if next_deadline is not None:
                            sleep_for = sleep_sec_until_deadline(
                                next_deadline,
                                default_interval_sec=self.config.interval_sec,
                            )
                        else:
                            sleep_for = max(
                                DEADLINE_SLEEP_MIN_SEC,
                                self.config.interval_sec - elapsed,
                            )
                    except BrainError as e:
                        if e.is_unauthorized:
                            log.warning("unauthorized during control — clearing edge_id")
                            self._clear_edge_id()
                            sleep_for = max(
                                DEADLINE_SLEEP_MIN_SEC, float(self.config.interval_sec)
                            )
                        else:
                            self._note_brain_problem(e)
                            eid = self._get_edge_id()
                            next_deadline = (
                                self._dispatch_ledger(eid, brain=None) if eid else None
                            )
                            if next_deadline is not None:
                                # Keep executing the local plan; do not 120s-backoff.
                                sleep_for = sleep_sec_until_deadline(
                                    next_deadline,
                                    default_interval_sec=self.config.interval_sec,
                                )
                            else:
                                sleep_for = self._backoff_seconds()
                    except Exception:
                        log.exception("control tick failed")
                        elapsed = time.monotonic() - tick_started
                        sleep_for = max(
                            DEADLINE_SLEEP_MIN_SEC, self.config.interval_sec - elapsed
                        )
                    self._interruptible_sleep(sleep_for)
        finally:
            self._stop = True
            self._work_wake.set()
            for t in (self._worker_thread, self._heartbeat_thread):
                if t and t.is_alive():
                    t.join(timeout=5.0)
            self._intranet_ping.stop()
            set_beat_listener(None)
            bind_ledger(None)

        log.info("Mac Edge stopped edge_id=%s", self._get_edge_id() or "(none)")

    def _ensure_channel_threads(self) -> None:
        """Restart heartbeat/executor if an uncaught exception killed the thread."""
        for attr, target, name in (
            ("_heartbeat_thread", self._heartbeat_loop, "mac-edge-heartbeat"),
            ("_worker_thread", self._executor_loop, "mac-edge-executor"),
        ):
            t = getattr(self, attr, None)
            if t is not None and t.is_alive():
                continue
            if t is not None:
                log.warning("%s died — restarting", name)
            started = threading.Thread(target=target, name=name, daemon=True)
            setattr(self, attr, started)
            started.start()

    # --- identity ---

    def _get_edge_id(self) -> str | None:
        with self._edge_id_lock:
            return self._edge_id

    def _get_voice_edge_id(self) -> str | None:
        """Identity Brain has accepted via heartbeat — not a cached file id."""
        with self._edge_id_lock:
            return self._heartbeat_ok_edge_id

    def _set_edge_id(self, edge_id: str) -> None:
        with self._edge_id_lock:
            self._edge_id = edge_id

    def _set_heartbeat_ok(self, edge_id: str | None) -> None:
        with self._edge_id_lock:
            self._heartbeat_ok_edge_id = (edge_id or "").strip() or None

    def _clear_edge_id(self) -> None:
        clear_edge_id(self.config.edge_id_path)
        with self._edge_id_lock:
            self._edge_id = None
            self._heartbeat_ok_edge_id = None

    def _apply_music_linkage_hint(self, result) -> None:
        try:
            from mac_edge.music_linkage import apply_brain_hint

            raw = getattr(result, "raw", None) or {}
            hint = raw.get("music_linkage") if isinstance(raw, dict) else None
            if apply_brain_hint(hint if isinstance(hint, dict) else None):
                log.info("music linkage hint applied: %s", hint)
        except Exception:
            log.exception("music linkage hint failed")

    # --- channel 1: heartbeat ---

    def _heartbeat_loop(self) -> None:
        """Dedicated keep-alive channel — isolated from pull/execute timing."""
        timeout = min(float(self.config.http_timeout_sec), _HEARTBEAT_HTTP_TIMEOUT_SEC)
        try:
            with MultiBrainClient(
                list(self.config.brain_base_urls), config=self.config, timeout_sec=timeout
            ) as brain:
                while not self._stop:
                    try:
                        started = time.monotonic()
                        eid = self._get_edge_id()
                        if eid:
                            try:
                                result = brain.heartbeat(eid)
                                self._set_heartbeat_ok(eid)
                                self._apply_music_linkage_hint(result)
                            except BrainError as e:
                                if e.is_unauthorized:
                                    log.warning(
                                        "heartbeat 401 — clearing edge_id (control will re-register)"
                                    )
                                    self._clear_edge_id()
                                else:
                                    self._note_brain_problem(e)
                                    self._set_heartbeat_ok(None)
                            except Exception:
                                log.exception("heartbeat failed")
                        elapsed = time.monotonic() - started
                        sleep_for = max(
                            DEADLINE_SLEEP_MIN_SEC,
                            float(self.config.interval_sec) - elapsed,
                        )
                        self._interruptible_sleep(sleep_for)
                    except Exception:
                        log.exception("heartbeat loop iteration failed — continue")
                        self._interruptible_sleep(float(self.config.interval_sec))
        finally:
            pass  # MultiBrainClient closes its own clients on __exit__

    # --- channel 2: control (pull / enqueue / deadlines) ---

    def _control_tick(self, brain) -> int | None:
        """Pull new intents from Brain, flush local state, enqueue from ledger."""
        if not self._get_edge_id():
            self._register(brain)
            if not self._get_edge_id():
                return None

        eid = self._get_edge_id()
        assert eid
        # Peek (not pop): step 2 on Mac must re-see the intent after iPhone finishes step 1.
        peeked = brain.pull_intents(eid, consume=False) or []
        to_ingest: list[dict[str, Any]] = []
        for intent in peeked:
            if not isinstance(intent, dict):
                continue
            iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
            origin = str(intent.get("_brain_origin") or "").strip()
            if iid and origin:
                remember_intent_origin(iid, origin)
            # Fresh plan only for intents the ledger has not accepted yet.
            if iid and self._ledger.get(iid) is None:
                detail = brain.fetch_intent_detail(iid)
                if isinstance(detail, dict) and detail:
                    intent = _merge_intent_detail(intent, detail)
            if fail_empty_plan_intent(intent, edge_id=eid, brain=brain):
                continue
            to_ingest.append(intent)
            if iid:
                log.info("  %s", format_intent_summary(intent))

        added = self._ledger.ingest_peek(to_ingest, eid)
        if peeked:
            log.info(
                "intents: peeked %d added=%d (edge_id=%s) — enqueue from ledger",
                len(peeked),
                added,
                eid,
            )
        flushed = self._ledger.flush_to_brain(brain, eid)
        if flushed:
            log.info("intents: flushed %d ledger record(s) to Brain", flushed)
        self._scheduler.reconcile_peeked_terminal(peeked, edge_id=eid, brain=brain)
        delivered = run_pending_deliveries(peeked, edge_id=eid, brain=brain)
        if delivered:
            log.info("delivery: handled %d pending row(s) (edge_id=%s)", delivered, eid)
        return self._dispatch_ledger(eid, brain)

    def _dispatch_ledger(
        self,
        edge_id: str | None,
        brain: BrainClient | None = None,
    ) -> int | None:
        """Enqueue locally owned work. Brain emptiness does not drop these."""
        eid = (edge_id or "").strip()
        if not eid:
            return None
        intents = self._ledger.snapshot_open(eid)
        if not intents:
            self._log_empty_intents()
            return None
        log.info(
            "intents: local ledger %d open (edge_id=%s) — enqueue executor",
            len(intents),
            eid,
        )
        for intent in intents:
            if not isinstance(intent, dict):
                continue
            iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
            try:
                self._scheduler.handle(intent, edge_id=eid, brain=brain)
            except Exception:
                log.exception("scheduler failed id=%s", iid or "?")
            if iid:
                self._enqueue_intent(iid, intent)
        prefetch_upcoming_speaks(intents, eid)
        return earliest_local_deadline_ms(intents, eid)

    def _enqueue_intent(self, intent_id: str, intent: dict[str, Any]) -> None:
        iid = str(intent_id or "").strip()
        if not iid:
            return
        if self._ledger is not None:
            fresh = self._ledger.get(iid)
            if fresh is None:
                return
            intent = fresh
        with self._work_lock:
            self._pending_intents[iid] = intent
        self._work_wake.set()

    # --- channel 3: executor (highest work priority) ---

    def _executor_loop(self) -> None:
        """Step execution channel — TTS/actions only block this thread."""
        with MultiBrainClient(list(self.config.brain_base_urls), config=self.config) as brain:
            while not self._stop:
                self._work_wake.wait(timeout=1.0)
                self._work_wake.clear()
                if self._stop:
                    break
                batch = self._take_pending()
                if not batch:
                    continue
                eid = (self._get_edge_id() or "").strip()
                if not eid:
                    continue
                for iid, intent in batch:
                    if self._stop:
                        break
                    with self._work_lock:
                        self._executing_ids.add(iid)
                    try:
                        try:
                            self._scheduler.handle(intent, edge_id=eid, brain=brain)
                        except Exception:
                            log.exception("scheduler failed id=%s", iid)
                        try:
                            # Highest priority work: capability run (incl. notify.speak).
                            executor_handle(
                                intent,
                                edge_id=eid,
                                config=self.config,
                                brain=brain,
                            )
                        except Exception:
                            log.exception("executor failed id=%s", iid)
                    finally:
                        with self._work_lock:
                            self._executing_ids.discard(iid)
                            if iid in self._pending_intents:
                                if self._ledger is not None and self._ledger.get(iid) is None:
                                    del self._pending_intents[iid]
                                else:
                                    self._work_wake.set()

    def _take_pending(self) -> list[tuple[str, dict[str, Any]]]:
        with self._work_lock:
            ready: list[tuple[str, dict[str, Any]]] = []
            keep: dict[str, dict[str, Any]] = {}
            for iid, intent in self._pending_intents.items():
                if iid in self._executing_ids:
                    if self._ledger is not None:
                        fresh = self._ledger.get(iid)
                        if fresh is None:
                            continue
                        keep[iid] = fresh
                    else:
                        keep[iid] = intent
                    continue
                if self._ledger is not None:
                    fresh = self._ledger.get(iid)
                    if fresh is None:
                        continue
                    ready.append((iid, fresh))
                else:
                    ready.append((iid, intent))
            self._pending_intents = keep
        return ready

    def _register(self, brain: BrainClient) -> None:
        result = brain.register()
        self._set_edge_id(result.edge_id)
        save_edge_id(self.config.edge_id_path, result.edge_id)
        try:
            brain.heartbeat(result.edge_id)
            self._set_heartbeat_ok(result.edge_id)
        except BrainError as e:
            if e.is_unauthorized:
                log.warning("heartbeat after register 401 — clearing edge_id")
                self._clear_edge_id()
            else:
                self._note_brain_problem(e)

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
        log.info("intents: empty (edge_id=%s)", self._get_edge_id())

    def _interruptible_sleep(self, seconds: float) -> None:
        end = time.monotonic() + max(0.0, float(seconds))
        while not self._stop:
            remain = end - time.monotonic()
            if remain <= 0:
                return
            time.sleep(min(DEADLINE_SLEEP_MIN_SEC, remain))


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
        "context",
        "outputs",
        "step_outputs",
        "step_log",
    ):
        if key not in detail or detail[key] is None:
            continue
        # Production intent_detail often omits step_outputs; keep peek's bag.
        if key == "step_outputs" and not detail[key]:
            continue
        merged[key] = detail[key]
    if detail.get("id") is not None:
        merged["id"] = detail["id"]
    elif detail.get("intent_id") is not None:
        merged["id"] = detail["intent_id"]
    return merged
