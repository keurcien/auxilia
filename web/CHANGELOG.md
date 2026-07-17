# Changelog

## [0.5.19](https://github.com/keurcien/auxilia/compare/web-v0.5.18...web-v0.5.19) (2026-07-17)


### Bug Fixes

* **agents:** seed MCP tool map on connect so explicit save persists all servers ([#222](https://github.com/keurcien/auxilia/issues/222)) ([aeaf515](https://github.com/keurcien/auxilia/commit/aeaf51544f36159b10a68e7bc842d2299b6f2d5e))

## [0.5.18](https://github.com/keurcien/auxilia/compare/web-v0.5.17...web-v0.5.18) (2026-07-13)


### Features

* **agents:** explicit save with read/edit agent page ([#215](https://github.com/keurcien/auxilia/issues/215)) ([375e259](https://github.com/keurcien/auxilia/commit/375e25939668661aea8e3f69e11bafc050d68444))


### Bug Fixes

* **agents:** fail background runs fast on unauthorized MCP OAuth ([#208](https://github.com/keurcien/auxilia/issues/208)) ([e2e8a6a](https://github.com/keurcien/auxilia/commit/e2e8a6a223f31f3dd5d8b01d3536b5b2287b11d5))
* proper dark mode styling for code blocks ([#212](https://github.com/keurcien/auxilia/issues/212)) ([c213d77](https://github.com/keurcien/auxilia/commit/c213d77eb927851f330e45da20f2c202fa3853de))

## [0.5.17](https://github.com/keurcien/auxilia/compare/web-v0.5.16...web-v0.5.17) (2026-07-11)


### Features

* **model:** add muse from meta ([#211](https://github.com/keurcien/auxilia/issues/211)) ([0771ba6](https://github.com/keurcien/auxilia/commit/0771ba6edc055420ef45e29f4e47fdb13d5a50bc))


### Bug Fixes

* **triggers:** show running state in trigger run history ([#209](https://github.com/keurcien/auxilia/issues/209)) ([83c114f](https://github.com/keurcien/auxilia/commit/83c114fed296d26311018fd98ae70f101ce011fc))

## [0.5.16](https://github.com/keurcien/auxilia/compare/web-v0.5.15...web-v0.5.16) (2026-07-08)


### Features

* **model-providers:** add GLM 5.2 via OpenRouter with selectable rea… ([#197](https://github.com/keurcien/auxilia/issues/197)) ([6ec9138](https://github.com/keurcien/auxilia/commit/6ec9138598f00eb9ccb3cbf589f5f5382ae670f9))

## [0.5.15](https://github.com/keurcien/auxilia/compare/web-v0.5.14...web-v0.5.15) (2026-07-07)


### Features

* **runs:** move run records to Postgres + thread last-run status ([#194](https://github.com/keurcien/auxilia/issues/194)) ([fae7fd0](https://github.com/keurcien/auxilia/commit/fae7fd0696be338b4a83a41f3004360dcc7da56f))
* **runs:** react to run status changes in sidebar and run history ([#196](https://github.com/keurcien/auxilia/issues/196)) ([023a2e9](https://github.com/keurcien/auxilia/commit/023a2e92f77cae6bc0a13ddc843ffca94fe2d09f))

## [0.5.14](https://github.com/keurcien/auxilia/compare/web-v0.5.13...web-v0.5.14) (2026-07-07)


### Features

* **triggers:** add "Run now" action to trigger card menu ([#189](https://github.com/keurcien/auxilia/issues/189)) ([076e102](https://github.com/keurcien/auxilia/commit/076e102e62665ce7b06e0571a7a1f8fc7afbdb18))
* **triggers:** add border to trigger thread icon in sidebar ([#187](https://github.com/keurcien/auxilia/issues/187)) ([f829420](https://github.com/keurcien/auxilia/commit/f829420e6c721de7a6f005f8f9ba0ca0eb4319b1))
* **triggers:** link trigger name in chat header to trigger detail ([#188](https://github.com/keurcien/auxilia/issues/188)) ([b57c683](https://github.com/keurcien/auxilia/commit/b57c6838fadaa6b8a223a6b28a552cd9105b4998))
* **triggers:** redesign schedule time field with chevron picker ([#186](https://github.com/keurcien/auxilia/issues/186)) ([9f87279](https://github.com/keurcien/auxilia/commit/9f87279310eaf1f1c6e164158a7fd39604f69245))

## [0.5.13](https://github.com/keurcien/auxilia/compare/web-v0.5.12...web-v0.5.13) (2026-07-06)


### Code Refactoring

* **triggers:** remove Draft badge from new trigger header ([#184](https://github.com/keurcien/auxilia/issues/184)) ([fd88991](https://github.com/keurcien/auxilia/commit/fd889913414fbc4def3fb49a677cc02557f5cf54))

## [0.5.12](https://github.com/keurcien/auxilia/compare/web-v0.5.11...web-v0.5.12) (2026-07-06)


### Features

* **triggers:** scheduled agent runs ([#182](https://github.com/keurcien/auxilia/issues/182)) ([d987da9](https://github.com/keurcien/auxilia/commit/d987da917f48fa9c8f63809de5903f261d3eca12))

## [0.5.11](https://github.com/keurcien/auxilia/compare/web-v0.5.10...web-v0.5.11) (2026-07-06)


### Features

* **agents:** display agent owner on card and dialog ([#181](https://github.com/keurcien/auxilia/issues/181)) ([b2222cd](https://github.com/keurcien/auxilia/commit/b2222cdc075ec2c2f3ee6de7455c76ac04c4370f))

## [0.5.10](https://github.com/keurcien/auxilia/compare/web-v0.5.9...web-v0.5.10) (2026-07-02)


### Features

* organize agents list with tags ([#176](https://github.com/keurcien/auxilia/issues/176)) ([648e6ea](https://github.com/keurcien/auxilia/commit/648e6ea4fb4ee19fd4ac89db3df71bfcfa7a77c6))


### Bug Fixes

* address Cubic review comments from [#176](https://github.com/keurcien/auxilia/issues/176) ([#178](https://github.com/keurcien/auxilia/issues/178)) ([efc35d6](https://github.com/keurcien/auxilia/commit/efc35d69eea28ac3a1f8dca0650010b6bcd06500))

## [0.5.9](https://github.com/keurcien/auxilia/compare/web-v0.5.8...web-v0.5.9) (2026-06-30)


### Features

* teams for agent access ([#173](https://github.com/keurcien/auxilia/issues/173)) ([30552b7](https://github.com/keurcien/auxilia/commit/30552b79e49e170c88d2418bc9a1b77fe2b75b17))
* **web:** show subagent avatars in agent card footer ([#171](https://github.com/keurcien/auxilia/issues/171)) ([8e50338](https://github.com/keurcien/auxilia/commit/8e503380e9c1a91c2cdc827047cdb1f093636b00))

## [0.5.8](https://github.com/keurcien/auxilia/compare/web-v0.5.7...web-v0.5.8) (2026-06-29)


### Bug Fixes

* **slack:** de-duplicate HITL tool header; keep quote bar on multi-line args ([#165](https://github.com/keurcien/auxilia/issues/165)) ([b1500bf](https://github.com/keurcien/auxilia/commit/b1500bf870842ca8ef31c3b271cf94605a235d50))

## [0.5.7](https://github.com/keurcien/auxilia/compare/web-v0.5.6...web-v0.5.7) (2026-06-29)


### Features

* **threads:** rename threads from the sidebar ([#156](https://github.com/keurcien/auxilia/issues/156)) ([9f60eef](https://github.com/keurcien/auxilia/commit/9f60eef660d6faf67ce98d734d01b6171e50f5ea))

## [0.5.6](https://github.com/keurcien/auxilia/compare/web-v0.5.5...web-v0.5.6) (2026-06-28)


### Features

* **web:** durable run wiring — run-id capture, server Stop, reattach ([#153](https://github.com/keurcien/auxilia/issues/153)) ([4a1cf3a](https://github.com/keurcien/auxilia/commit/4a1cf3ac7173b7c563c2593436998c4567fae6dd))

## [0.5.5](https://github.com/keurcien/auxilia/compare/web-v0.5.4...web-v0.5.5) (2026-06-26)


### Bug Fixes

* **web:** surface real tool error text; refactor(agents): collapse agent construction ([#144](https://github.com/keurcien/auxilia/issues/144)) ([e7fdc8e](https://github.com/keurcien/auxilia/commit/e7fdc8e0b82fcb0d52cf8b3c62bd02b4c5e0084e))

## [0.5.4](https://github.com/keurcien/auxilia/compare/web-v0.5.3...web-v0.5.4) (2026-06-22)


### Features

* **agents:** improve agents list navigation and tabs ([#133](https://github.com/keurcien/auxilia/issues/133)) ([05e9ed3](https://github.com/keurcien/auxilia/commit/05e9ed30d37a3138e716ce1f8ffca48cefde4b44))

## [0.5.3](https://github.com/keurcien/auxilia/compare/web-v0.5.2...web-v0.5.3) (2026-06-22)


### Features

* **agents:** add Archived tab with restore and permanent delete ([#130](https://github.com/keurcien/auxilia/issues/130)) ([f6bed78](https://github.com/keurcien/auxilia/commit/f6bed781c46120fa90cdabff86a51c485598aecf))

## [0.5.2](https://github.com/keurcien/auxilia/compare/web-v0.5.1...web-v0.5.2) (2026-06-20)


### Bug Fixes

* **mcp:** render Metabase interactive visualize_query MCP App ([#128](https://github.com/keurcien/auxilia/issues/128)) ([2bbc28c](https://github.com/keurcien/auxilia/commit/2bbc28c8ac9febaf291f7d35e52227df49347ed2))

## [0.5.1](https://github.com/keurcien/auxilia/compare/web-v0.5.0...web-v0.5.1) (2026-06-18)


### Features

* add search bar to Add Subagent dialog ([#111](https://github.com/keurcien/auxilia/issues/111)) ([5e7b60e](https://github.com/keurcien/auxilia/commit/5e7b60e5d306ce7fb0a70be755605a101206f775))

## [0.5.0](https://github.com/keurcien/auxilia/compare/web-v0.4.0...web-v0.5.0) (2026-06-15)


### Features

* **web:** Studio shell redesign — floating sidebar, page specs & smooth collapse ([#119](https://github.com/keurcien/auxilia/issues/119)) ([301c3ff](https://github.com/keurcien/auxilia/commit/301c3ffdaa0681c6b20f19634c47ec71a667eb88))

## [0.4.0](https://github.com/keurcien/auxilia/compare/web-v0.3.0...web-v0.4.0) (2026-06-12)


### Features

* add color field to agents with pastel palette ([6b977ee](https://github.com/keurcien/auxilia/commit/6b977ee03410419c5853af8786dbcefdfcf1c31c))
* add subagent bindings with Deep Agents integration ([#63](https://github.com/keurcien/auxilia/issues/63)) ([c01eeea](https://github.com/keurcien/auxilia/commit/c01eeeac5bab6d59ec43d4ac26a14a59a8ad693c))
* agent thread history page + thread source ([#94](https://github.com/keurcien/auxilia/issues/94)) ([e9faa17](https://github.com/keurcien/auxilia/commit/e9faa17ab8da4104b661bf976e7b97144bdfbb82))
* allow archive agents ([#61](https://github.com/keurcien/auxilia/issues/61)) ([d6a04dc](https://github.com/keurcien/auxilia/commit/d6a04dc8dd8a4bd39ea988426d8bc8161423e8c7))
* dark light theme rework ([#9](https://github.com/keurcien/auxilia/issues/9)) ([b7fecd9](https://github.com/keurcien/auxilia/commit/b7fecd9c0627dc397e57eaf4430c004175cdcf2f))
* dynamic default model selection  ([#1](https://github.com/keurcien/auxilia/issues/1)) ([75941a8](https://github.com/keurcien/auxilia/commit/75941a8c9e072c617ba12bd1442206f786e5ac60))
* enforce auth on agent routes and update related tests ([#92](https://github.com/keurcien/auxilia/issues/92)) ([65f3658](https://github.com/keurcien/auxilia/commit/65f3658fc70856247fb6adfc387ca30cb1c9886c))
* handle mcp servers with UI widgets (mcp-apps)  ([#19](https://github.com/keurcien/auxilia/issues/19)) ([bd97146](https://github.com/keurcien/auxilia/commit/bd97146d0c88d2eebf5fe4e88bb6df2876db2ea9))
* per-agent sandbox with code execution UI ([#68](https://github.com/keurcien/auxilia/issues/68)) ([ed007a5](https://github.com/keurcien/auxilia/commit/ed007a56e0281184330265875413ae74c9267ac9))
* save status indicator in agent creation ([#4](https://github.com/keurcien/auxilia/issues/4)) ([91e6a77](https://github.com/keurcien/auxilia/commit/91e6a7778ce12736ed829f1e88f78d8b2eb96992))


### Bug Fixes

* conflicting tailwind imports ([13c8f66](https://github.com/keurcien/auxilia/commit/13c8f66636b3e03dda812f684744f6eed9d9b5f1))
* pass structuredContent from artifact to AppRenderer for MCP app widgets ([e7374a6](https://github.com/keurcien/auxilia/commit/e7374a6e31359539cbf64a19917e7685fe94c3d4))
* portal agent dialog to body to fix positioning inside animated cards ([1233943](https://github.com/keurcien/auxilia/commit/123394342129dcbc3139b11f682fba60d0e870bf))
* remove client setup for DCR official MCP servers ([92aa1d2](https://github.com/keurcien/auxilia/commit/92aa1d28e494e199ff9435e8e33b4576add9ba36))
* scope HITL decisions to hanging tool calls only ([#93](https://github.com/keurcien/auxilia/issues/93)) ([5675fec](https://github.com/keurcien/auxilia/commit/5675fececc2b3fd8f0aece8b591b5f9a365d9fae))
* update pending invites UI without needing refresh ([#38](https://github.com/keurcien/auxilia/issues/38)) ([1a2bf7b](https://github.com/keurcien/auxilia/commit/1a2bf7b4c7add6d0f8370b72c01b4ee03dbcc692))
