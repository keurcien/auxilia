# Changelog

## [0.4.15](https://github.com/keurcien/auxilia/compare/backend-v0.4.14...backend-v0.4.15) (2026-07-06)


### Features

* **triggers:** scheduled agent runs ([#182](https://github.com/keurcien/auxilia/issues/182)) ([d987da9](https://github.com/keurcien/auxilia/commit/d987da917f48fa9c8f63809de5903f261d3eca12))

## [0.4.14](https://github.com/keurcien/auxilia/compare/backend-v0.4.13...backend-v0.4.14) (2026-07-06)


### Features

* **agents:** display agent owner on card and dialog ([#181](https://github.com/keurcien/auxilia/issues/181)) ([b2222cd](https://github.com/keurcien/auxilia/commit/b2222cdc075ec2c2f3ee6de7455c76ac04c4370f))


### Bug Fixes

* **agents:** validate structured output instead of returning empty results ([#179](https://github.com/keurcien/auxilia/issues/179)) ([ea59e38](https://github.com/keurcien/auxilia/commit/ea59e386b20ac9bc9cf27b8894584ebd56a2a21a))

## [0.4.13](https://github.com/keurcien/auxilia/compare/backend-v0.4.12...backend-v0.4.13) (2026-07-02)


### Features

* **model-providers:** disable Claude Opus models ([#174](https://github.com/keurcien/auxilia/issues/174)) ([f2afc5b](https://github.com/keurcien/auxilia/commit/f2afc5bdadbe9196e2f86765a22685741beefde1))
* organize agents list with tags ([#176](https://github.com/keurcien/auxilia/issues/176)) ([648e6ea](https://github.com/keurcien/auxilia/commit/648e6ea4fb4ee19fd4ac89db3df71bfcfa7a77c6))


### Bug Fixes

* address Cubic review comments from [#176](https://github.com/keurcien/auxilia/issues/176) ([#178](https://github.com/keurcien/auxilia/issues/178)) ([efc35d6](https://github.com/keurcien/auxilia/commit/efc35d69eea28ac3a1f8dca0650010b6bcd06500))
* **runs:** lower Redis run retention default from 24h to 1h ([#177](https://github.com/keurcien/auxilia/issues/177)) ([0171b50](https://github.com/keurcien/auxilia/commit/0171b50f0a931e61e41cbd884a2eed2d5f935e6e))

## [0.4.12](https://github.com/keurcien/auxilia/compare/backend-v0.4.11...backend-v0.4.12) (2026-06-30)


### Features

* teams for agent access ([#173](https://github.com/keurcien/auxilia/issues/173)) ([30552b7](https://github.com/keurcien/auxilia/commit/30552b79e49e170c88d2418bc9a1b77fe2b75b17))

## [0.4.11](https://github.com/keurcien/auxilia/compare/backend-v0.4.10...backend-v0.4.11) (2026-06-29)


### Bug Fixes

* **slack:** de-duplicate HITL tool header; keep quote bar on multi-line args ([#165](https://github.com/keurcien/auxilia/issues/165)) ([b1500bf](https://github.com/keurcien/auxilia/commit/b1500bf870842ca8ef31c3b271cf94605a235d50))

## [0.4.10](https://github.com/keurcien/auxilia/compare/backend-v0.4.9...backend-v0.4.10) (2026-06-29)


### Bug Fixes

* **slack:** durable-delivery follow-ups (tool output, errors, HITL header) ([#163](https://github.com/keurcien/auxilia/issues/163)) ([4e8b6fd](https://github.com/keurcien/auxilia/commit/4e8b6fdc004537e71adbc5680db1af33fe516728))

## [0.4.9](https://github.com/keurcien/auxilia/compare/backend-v0.4.8...backend-v0.4.9) (2026-06-29)


### Features

* **slack:** run Slack agent turns through the durable runtime ([#161](https://github.com/keurcien/auxilia/issues/161)) ([de4e017](https://github.com/keurcien/auxilia/commit/de4e01745ad538e826c39a95a1516804ed9f9167))

## [0.4.8](https://github.com/keurcien/auxilia/compare/backend-v0.4.7...backend-v0.4.8) (2026-06-29)


### Features

* **mcp:** hardcode Gmail OAuth scopes instead of PRM discovery ([#160](https://github.com/keurcien/auxilia/issues/160)) ([a4c719b](https://github.com/keurcien/auxilia/commit/a4c719b460dca8881fd1ef453b74384894707844))
* **threads:** rename threads from the sidebar ([#156](https://github.com/keurcien/auxilia/issues/156)) ([9f60eef](https://github.com/keurcien/auxilia/commit/9f60eef660d6faf67ce98d734d01b6171e50f5ea))


### Bug Fixes

* **threads:** restrict rename endpoint to title only ([#158](https://github.com/keurcien/auxilia/issues/158)) ([9183619](https://github.com/keurcien/auxilia/commit/9183619167f371962997f04b349cdd8f8ed03a8f))

## [0.4.7](https://github.com/keurcien/auxilia/compare/backend-v0.4.6...backend-v0.4.7) (2026-06-28)


### Features

* **agents:** durable Redis-backed agent runtime ([#153](https://github.com/keurcien/auxilia/issues/153)) ([72e6686](https://github.com/keurcien/auxilia/commit/72e668685d02c9746bc67fa60d4697f8289b4c91))

## [0.4.6](https://github.com/keurcien/auxilia/compare/backend-v0.4.5...backend-v0.4.6) (2026-06-26)


### Bug Fixes

* **web:** surface real tool error text; refactor(agents): collapse agent construction ([#144](https://github.com/keurcien/auxilia/issues/144)) ([e7fdc8e](https://github.com/keurcien/auxilia/commit/e7fdc8e0b82fcb0d52cf8b3c62bd02b4c5e0084e))

## [0.4.5](https://github.com/keurcien/auxilia/compare/backend-v0.4.4...backend-v0.4.5) (2026-06-25)


### Features

* **mcp:** discover OAuth scopes via PRM, drop tool-call 401 probe ([#135](https://github.com/keurcien/auxilia/issues/135)) ([a986e5f](https://github.com/keurcien/auxilia/commit/a986e5fbf3599b3008b4863d3e44ea5d9e8c13ff))


### Bug Fixes

* **mcp:** persist OAuth tokens after authorization-code grant ([#141](https://github.com/keurcien/auxilia/issues/141)) ([65c8029](https://github.com/keurcien/auxilia/commit/65c8029b1d640b4ac6e38eb0603f77bd2c468e9e))


### Code Refactoring

* **mcp:** tighten WebOAuthClientProvider toward the SDK ([#139](https://github.com/keurcien/auxilia/issues/139)) ([0d8a037](https://github.com/keurcien/auxilia/commit/0d8a037b69b86dc1f9b34b1584949e3787a6d6ce))

## [0.4.4](https://github.com/keurcien/auxilia/compare/backend-v0.4.3...backend-v0.4.4) (2026-06-22)


### Bug Fixes

* lint ([bbd9ab3](https://github.com/keurcien/auxilia/commit/bbd9ab3f69199c336e29ce0997ac5a385c8e8188))

## [0.4.3](https://github.com/keurcien/auxilia/compare/backend-v0.4.2...backend-v0.4.3) (2026-06-22)


### Features

* **agents:** add Archived tab with restore and permanent delete ([#130](https://github.com/keurcien/auxilia/issues/130)) ([f6bed78](https://github.com/keurcien/auxilia/commit/f6bed781c46120fa90cdabff86a51c485598aecf))


### Bug Fixes

* lint ([#132](https://github.com/keurcien/auxilia/issues/132)) ([9b5d502](https://github.com/keurcien/auxilia/commit/9b5d5026224659d2a4707659235286428f7daa72))

## [0.4.2](https://github.com/keurcien/auxilia/compare/backend-v0.4.1...backend-v0.4.2) (2026-06-20)


### Bug Fixes

* **mcp:** render Metabase interactive visualize_query MCP App ([#128](https://github.com/keurcien/auxilia/issues/128)) ([2bbc28c](https://github.com/keurcien/auxilia/commit/2bbc28c8ac9febaf291f7d35e52227df49347ed2))

## [0.4.1](https://github.com/keurcien/auxilia/compare/backend-v0.4.0...backend-v0.4.1) (2026-06-18)


### Code Refactoring

* **agents:** drop custom MCP tool-error wrapping for native handling ([#122](https://github.com/keurcien/auxilia/issues/122)) ([fc52af4](https://github.com/keurcien/auxilia/commit/fc52af4feca37f8ad8fd50d5d5c74b4a60bb3cc9))

## [0.4.0](https://github.com/keurcien/auxilia/compare/backend-v0.3.0...backend-v0.4.0) (2026-06-12)


### Features

* add color field to agents with pastel palette ([6b977ee](https://github.com/keurcien/auxilia/commit/6b977ee03410419c5853af8786dbcefdfcf1c31c))
* add subagent bindings with Deep Agents integration ([#63](https://github.com/keurcien/auxilia/issues/63)) ([c01eeea](https://github.com/keurcien/auxilia/commit/c01eeeac5bab6d59ec43d4ac26a14a59a8ad693c))
* agent thread history page + thread source ([#94](https://github.com/keurcien/auxilia/issues/94)) ([e9faa17](https://github.com/keurcien/auxilia/commit/e9faa17ab8da4104b661bf976e7b97144bdfbb82))
* allow archive agents ([#61](https://github.com/keurcien/auxilia/issues/61)) ([d6a04dc](https://github.com/keurcien/auxilia/commit/d6a04dc8dd8a4bd39ea988426d8bc8161423e8c7))
* dynamic default model selection  ([#1](https://github.com/keurcien/auxilia/issues/1)) ([75941a8](https://github.com/keurcien/auxilia/commit/75941a8c9e072c617ba12bd1442206f786e5ac60))
* enforce auth on agent routes and update related tests ([#92](https://github.com/keurcien/auxilia/issues/92)) ([65f3658](https://github.com/keurcien/auxilia/commit/65f3658fc70856247fb6adfc387ca30cb1c9886c))
* per-agent sandbox with code execution UI ([#68](https://github.com/keurcien/auxilia/issues/68)) ([ed007a5](https://github.com/keurcien/auxilia/commit/ed007a56e0281184330265875413ae74c9267ac9))


### Bug Fixes

* defer sandbox imports to avoid crash when opensandbox is not installed ([ef986b4](https://github.com/keurcien/auxilia/commit/ef986b4d24b46b95c290389126bc5275b31700ac))
* preserve subagents when parent agent has code execution ([#95](https://github.com/keurcien/auxilia/issues/95)) ([ed9ef3b](https://github.com/keurcien/auxilia/commit/ed9ef3b07b18c4747f8b3d49bede0e747c130f1d))
* remove client setup for DCR official MCP servers ([92aa1d2](https://github.com/keurcien/auxilia/commit/92aa1d28e494e199ff9435e8e33b4576add9ba36))
* scope HITL decisions to hanging tool calls only ([#93](https://github.com/keurcien/auxilia/issues/93)) ([5675fec](https://github.com/keurcien/auxilia/commit/5675fececc2b3fd8f0aece8b591b5f9a365d9fae))
* surface GraphRecursionError as a resumable AI message ([#97](https://github.com/keurcien/auxilia/issues/97)) ([00fcbe9](https://github.com/keurcien/auxilia/commit/00fcbe96a7ab0b1455f0a7e98ffd5eb5fa5d5299))
