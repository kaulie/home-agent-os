# P0 Dual-Brain / Capability Availability / Exposure Policy — Black-box Report

> Status: **PASS 4/4** (verified 2026-08-25 against a fresh Brain on `BRAIN_ORIGIN=lan`).
> Suite: [`run_p0_dual_brain.py`](./run_p0_dual_brain.py) · Results: [`p0_dual_brain_results.json`](./p0_dual_brain_results.json)

This suite covers the **P0 contract** from `docs/architecture/dual-brain-runtime.md` and
`docs/architecture/capability-availability.md`. It is contract-level (register / heartbeat /
capabilities / admin) and does **not** exercise the LLM planning pipeline (that stays in
[`run_suite.py`](./run_suite.py)).

`capability_timeline` is **deferred** to the analysis engine (P0 logs heartbeats instead of
keeping a `heartbeat_history` table), so no timeline test is included here.

## How to run

```bash
# 1. Start a Brain on a temp DB (LAN domain) with the LLM worker off.
cd server
BRAIN_DB_PATH=/tmp/brain_p0_bb.sqlite3 .venv/bin/python db.py init
BRAIN_DB_PATH=/tmp/brain_p0_bb.sqlite3 BRAIN_ORIGIN=lan BRAIN_SKIP_LLM_WORKER=1 \
  .venv/bin/python -c "
import logging; logging.basicConfig(level=logging.WARNING)
import home_brain as hb
from werkzeug.serving import make_server
make_server('127.0.0.1', 19531, hb.app, threaded=True).serve_forever()
" &

# 2. Run the suite against it.
BRAIN=http://127.0.0.1:19531 ../server/.venv/bin/python tests/blackbox/run_p0_dual_brain.py
```

## Cases

| ID | Name | What it asserts | Result |
|----|------|-----------------|--------|
| D  | `dual_registration` | A client-supplied `runtime_id` is authoritative: the Brain returns it verbatim and does **not** rebind to a conflicting `client_hint`. Re-registering the same `runtime_id` with a different hint still returns the same id. | ✅ |
| A  | `capability_availability` | A heartbeat snapshot with per-capability `available=false` removes that cap from the schedulable map (`/api/v1/capabilities`), while `available=true` caps remain. DECLARED-but-unavailable is a valid state. | ✅ |
| X  | `exposure_policy` | Per-domain exposure filters schedulable caps: a cap available+declared but **not** in the `lan` exposure list is excluded. Admin `GET`/`PUT` `/api/v1/admin/nodes/<id>/exposure-policy` works; after restricting `lan` to `["camera.capture"]`, `terminal.execute` is excluded while `camera.capture` stays. | ✅ |
| D2 | `dual_registration_idempotent` | Registering the same `runtime_id` multiple times creates exactly one participant (idempotent upsert, no duplicates). | ✅ |

## Notes / scope

- **Single-Brain dual-registration contract.** Full dual-Brain across *two* Brain processes
  (one LAN, one Cloud) is verified end-to-end on the Mac client (`mac/src/mac_edge/multi_brain.py`
  broadcasts register/heartbeat to all `MAC_EDGE_BRAIN_URLS` and routes status posts to the
  origin Brain). The black-box suite here runs against one Brain; the dual-URL behavior is
  covered by the Mac `BrainClient`/`MultiBrainClient` integration and the contract tests above.
- **No `heartbeat_history` table.** Per the P0 decision, heartbeat timelines are written
  to the `brain_db` structured log (`heartbeat_timeline participant_id=… capabilities_snapshot=…`),
  not persisted in a table. A future analysis engine will consume these logs.
- **Brain never probes devices.** Availability comes from the Runtime's `IsAvailable()`
  probe in the heartbeat snapshot. The Brain only consumes the reported `available` flag
  (two-phase check: scheduling-time snapshot + execution-time `IsAvailable()`).
- **Mobile compile verification** (Android Kotlin / iOS Swift) requires the native
  toolchains (Gradle/Xcode), which are not available in this environment. The source
  changes follow the same contract (client-supplied `runtime_id`, `exposure_policy`,
  per-cap `available`) and were reviewed for consistency; native build verification is
  pending `@quality` / CI.
