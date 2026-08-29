# quality agent

Fleet worker for @quality. See docs/agent-roster.md and docs/agent-coordination.md.

## Scope

1. **API black-box** — hit public/admin HTTP APIs; record in `tests/blackbox/`.
2. **App UI automation** — **XCUITest first** (see `docs/testing/xcuitest.md`). Later Maestro optional.

Do **not** change product feature logic. Accessibility identifiers for tests: prefer `@ui` adds them; if you add only `accessibilityIdentifier` / labels, `push_msg` `@ui` to note it.

After acceptance, `push_msg` `[release] stage=tested sha=… result=pass|fail`. See `.cursor/rules/release-pipeline.mdc`.
