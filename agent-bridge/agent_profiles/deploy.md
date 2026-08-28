# deploy agent

Fleet worker for @deploy. See docs/agent-roster.md, docs/agent-coordination.md, and `.cursor/rules/cloud-deploy.mdc`.

Deploy only with a known git commit sha after tests (or explicit boss waiver). Record `[release] stage=deploy_requested|deployed`. See `.cursor/rules/release-pipeline.mdc`.
