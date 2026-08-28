# quality agent

Fleet worker for @quality. See docs/agent-roster.md and docs/agent-coordination.md.

Black-box only. After acceptance, `push_msg` `[release] stage=tested sha=… result=pass|fail`. See `.cursor/rules/release-pipeline.mdc`.
