# Endpoint Contract

Status: Design Convention (Phase A)  
Source: `/Users/gaolei/devspace/home-agent-docs/endpoint_proto.txt`  
Aligns with: [`participant-model.md`](participant-model.md), [`asset-contract.md`](asset-contract.md)  
Cast wire: [`chromecast-cast-protocol.md`](chromecast-cast-protocol.md)

## 1. Core

**Device ≠ Endpoint.** Device is physical; Endpoint is what Runtime can invoke and observe.

A Device may expose one or more Endpoints. Planner / Brain asks “which Endpoint can `present`?”, never “how do I drive Chromecast?”.

```text
Physical Device
  ├── Endpoint A (type, capabilities, state, events, availability)
  └── Endpoint B …
```

## 2. Endpoint identity

Stable IDs, independent of transport / session:

| Field | Meaning |
|-------|---------|
| `endpoint_id` | Stable logical id (e.g. `living_room_tv`, `iphone.display`) |
| `device_id` | Physical / participant bearer when known |
| `type` | Functional type: `display`, `camera`, `speaker`, `light`, … |

`endpoint_id` must not change when IP, Cast session, or Web Receiver restarts. Connection loss → `availability=offline`, not a new Endpoint.

## 3. Endpoint type (not vendor)

Prefer functional types: `display`, `camera`, `speaker`, `microphone`, `vehicle`, `climate`, `light`, `media`, `input`, `storage`, `sensor`.

Examples: Chromecast → `display`; Kindle → `display`; iPhone screen → `display`.

## 4. Capability on Endpoint

Endpoints expose standard capabilities, not vendor APIs.

For display: semantic **`present`** (content_types: image / text / video / …).  
Current wire still uses Runtime caps `display.photo` / `display.slideshow` on Edge; migrate toward `present` without teaching Planner vendor names.

Capability contract (minimum): `name`, `description`, `input_schema`, `output_schema`, `preconditions`, `verification`, `timeout`.

## 5. State & availability

- **reported_state** — observation, not absolute truth  
- **desired_state** / **execution_state** — when useful  
- **availability**: `online` | `offline` | `degraded` | `unknown`  

Device online ≠ Endpoint ready (e.g. Cast device up, Receiver not ready).

## 6. Command ≠ completion

```text
request → accepted → executing → completed | waiting | feedback_required | cancelled
```

Cast message accepted ≠ TV has displayed content. Completion comes from Endpoint **events** (or explicit verification).

## 7. Events

Endpoints emit events for Runtime continuation / verification, e.g.:

- `receiver.ready`
- `presentation.started` / `presentation.completed` / `presentation.error` / `presentation.cleared`
- `endpoint.online` / `endpoint.offline`

## 8. Asset decoupling

Endpoints receive `asset_id` / AssetRef (see [`asset-contract.md`](asset-contract.md)). Temporary access URLs are transport for V1 Cast; permanent URLs are not identity.

## 9. Registry queries

Runtime / Brain should support:

- by `endpoint_id`
- by `type` + capability + `availability`
- by `location` / metadata

Planner must not branch on `if device == chromecast`.

## 10. Layering (who owns what)

| Layer | Owns |
|-------|------|
| Brain | Plan, PresentationSpec *what*, select Endpoint by type/capability |
| Runtime | Registry, invoke, hydrate, wait for events, step status |
| Endpoint Adapter | Vendor transport (Cast / HTTP / …) |
| Receiver HTML (Cast) | Render only; owned/deployed outside this repo — see Cast protocol |

Endpoint does **not** schedule, retry globally, or call other Endpoints. Cross-device flows are Runtime orchestration.

## 11. Dual delivery (phase 1)

- **Pull**: Intent Source / Kindle read `intent_detail.presentation` (Brain-assembled).  
- **Push**: Chromecast via Cast Presentation Command (see Cast protocol).  

Both consume the same PresentationSpec shape over time (`presentation_id`, content, options).

Default **Response Target** follows Input–Output symmetry ([`presentation-io-symmetry.md`](presentation-io-symmetry.md)): return to the Input Source unless Intent / user / context / policy names another Endpoint. Execution Target (where a capability ran) is not the Response Target.

## 12. Out of scope here

Tesla vehicle/climate examples, building Receiver HTML in-repo, deleting `display.photo` wire names in one shot.
