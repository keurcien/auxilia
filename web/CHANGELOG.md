# Changelog

## [0.11.5](https://github.com/jr-k/auxilia/compare/web-v0.11.4...web-v0.11.5) (2026-10-04)


### Bug Fixes

* **workspaces:** survive deleting the last workspace ([58aa9b6](https://github.com/jr-k/auxilia/commit/58aa9b62665152a4d3de8d1b7137308a0bc3fd1a))

## [0.11.4](https://github.com/jr-k/auxilia/compare/web-v0.11.3...web-v0.11.4) (2026-10-04)


### Bug Fixes

* **onboarding:** skip model loading immediately ([0499dbf](https://github.com/jr-k/auxilia/commit/0499dbf72c501bd21481eaf55ab18aa6480ba259))

## [0.11.3](https://github.com/jr-k/auxilia/compare/web-v0.11.2...web-v0.11.3) (2026-10-04)


### Bug Fixes

* **workspaces:** preserve owner creation access ([288f5cc](https://github.com/jr-k/auxilia/commit/288f5cc11b965e3f8d7cb3dc9eb977618e8c98c6))

## [0.11.2](https://github.com/jr-k/auxilia/compare/web-v0.11.1...web-v0.11.2) (2026-10-04)


### Bug Fixes

* **workspaces:** allow recovery after deleting all workspaces ([9ba2949](https://github.com/jr-k/auxilia/commit/9ba2949cce2409241cd76a4dc8bd40014cfbf209))

## [0.11.1](https://github.com/jr-k/auxilia/compare/web-v0.11.0...web-v0.11.1) (2026-10-04)


### Bug Fixes

* **workspaces:** recover after deleting active workspace ([6f7641e](https://github.com/jr-k/auxilia/commit/6f7641e5bb5913ba68a1356541e3beef1e6ac18a))

## [0.11.0](https://github.com/jr-k/auxilia/compare/web-v0.10.3...web-v0.11.0) (2026-10-04)


### ⚠ BREAKING CHANGES

* **skills:** the `create_sandbox` / `connect_sandbox` tools are gone; sandboxes are opened by the runtime, never by the model.
* **threads:** `GET /threads/{id}` no longer returns `values`, `interrupted`, `interrupt_value` or `interrupt_id`; hydrate from `GET /threads/{id}/state`. Non-app MCP tools no longer carry `structured_content` in their ToolMessage artifact.
* **agents:** sandbox agents lose ~4KB of deepagents prompt fragments and the long `task` description, `write_file` now overwrites existing files, and a recursive sandbox-scoped `delete` tool is exposed. Existing threads see a one-time system prompt change.
* **agents:** POST /threads/{id}/runs/stream and GET /threads/{id}/runs/{run_id}/stream are removed (use the protocol endpoints /threads/{id}/commands + /threads/{id}/stream/events); the `messages` field of GET /threads/{id} (AI SDK UIMessage shape) is removed.
* **sandbox:** agents.has_code_interpreter and the SANDBOX_* / OPEN_SANDBOX_* / CLOUD_RUN_SANDBOX_* env vars are removed. The migration converts an env-configured deployment into a registry row and rebinds flagged agents automatically when the env vars are still present at upgrade time.

### Features

* add color field to agents with pastel palette ([6b977ee](https://github.com/jr-k/auxilia/commit/6b977ee03410419c5853af8786dbcefdfcf1c31c))
* add hierarchical resource groups and model onboarding ([73c6141](https://github.com/jr-k/auxilia/commit/73c6141fcaba39e9362cf8692c4e5875166c341a))
* add search bar to Add Subagent dialog ([#111](https://github.com/jr-k/auxilia/issues/111)) ([5e7b60e](https://github.com/jr-k/auxilia/commit/5e7b60e5d306ce7fb0a70be755605a101206f775))
* add subagent bindings with Deep Agents integration ([#63](https://github.com/jr-k/auxilia/issues/63)) ([c01eeea](https://github.com/jr-k/auxilia/commit/c01eeeac5bab6d59ec43d4ac26a14a59a8ad693c))
* add workspace administration and customization ([dffbfea](https://github.com/jr-k/auxilia/commit/dffbfeaabca0b2cef662254f1be5a7afdcd0922b))
* agent thread history page + thread source ([#94](https://github.com/jr-k/auxilia/issues/94)) ([e9faa17](https://github.com/jr-k/auxilia/commit/e9faa17ab8da4104b661bf976e7b97144bdfbb82))
* **agents:** add Archived tab with restore and permanent delete ([#130](https://github.com/jr-k/auxilia/issues/130)) ([f6bed78](https://github.com/jr-k/auxilia/commit/f6bed781c46120fa90cdabff86a51c485598aecf))
* **agents:** checkpoint-keyed HITL approvals via interrupt ids ([#307](https://github.com/jr-k/auxilia/issues/307)) ([4982321](https://github.com/jr-k/auxilia/commit/4982321c242e15af9030a6f7db0613a57d9e64f1))
* **agents:** display agent owner on card and dialog ([#181](https://github.com/jr-k/auxilia/issues/181)) ([b2222cd](https://github.com/jr-k/auxilia/commit/b2222cdc075ec2c2f3ee6de7455c76ac04c4370f))
* **agents:** explicit save with read/edit agent page ([#215](https://github.com/jr-k/auxilia/issues/215)) ([375e259](https://github.com/jr-k/auxilia/commit/375e25939668661aea8e3f69e11bafc050d68444))
* **agents:** full tool descriptions dialog for MCP server panels ([#353](https://github.com/jr-k/auxilia/issues/353)) ([1e51374](https://github.com/jr-k/auxilia/commit/1e513747e4e17c8d7e2fb11790d102cfd92cc20a))
* **agents:** improve agents list navigation and tabs ([#133](https://github.com/jr-k/auxilia/issues/133)) ([05e9ed3](https://github.com/jr-k/auxilia/commit/05e9ed30d37a3138e716ce1f8ffca48cefde4b44))
* **agents:** persistent run errors, recovery middleware, and langchain 1.3 ([#292](https://github.com/jr-k/auxilia/issues/292)) ([2e8766e](https://github.com/jr-k/auxilia/commit/2e8766e66d1ba2c0672a915518d69dd9282e1c12))
* **agents:** subagent tool approvals (HITL) surface and resume like the parent's ([#317](https://github.com/jr-k/auxilia/issues/317)) ([ddc00fc](https://github.com/jr-k/auxilia/commit/ddc00fccce6ede374f8dbb26209795b6370444d8))
* **agents:** upgrade to deepagents 0.7 with lean harness prompts ([#319](https://github.com/jr-k/auxilia/issues/319)) ([4522df3](https://github.com/jr-k/auxilia/commit/4522df37fd489bf5b7f1e6170fe305f369bae1fb))
* **agents:** worker-native Agent Streaming Protocol, legacy SSE removed ([#313](https://github.com/jr-k/auxilia/issues/313)) ([a05cf12](https://github.com/jr-k/auxilia/commit/a05cf127b9a1ee45efbf4d47d9d15d17bf648c54))
* allow archive agents ([#61](https://github.com/jr-k/auxilia/issues/61)) ([d6a04dc](https://github.com/jr-k/auxilia/commit/d6a04dc8dd8a4bd39ea988426d8bc8161423e8c7))
* **chat:** render the conversation from @langchain/react views, reasoning on the chain rail ([#315](https://github.com/jr-k/auxilia/issues/315)) ([766d123](https://github.com/jr-k/auxilia/commit/766d123f4f6da73efd06dac5241feeaa8f009389))
* **chat:** subagent conversation in a tinted task band ([#316](https://github.com/jr-k/auxilia/issues/316)) ([accf730](https://github.com/jr-k/auxilia/commit/accf7301a1afb9fe0cf2146edc729dc89622442b))
* dynamic default model selection  ([#1](https://github.com/jr-k/auxilia/issues/1)) ([75941a8](https://github.com/jr-k/auxilia/commit/75941a8c9e072c617ba12bd1442206f786e5ac60))
* enforce auth on agent routes and update related tests ([#92](https://github.com/jr-k/auxilia/issues/92)) ([65f3658](https://github.com/jr-k/auxilia/commit/65f3658fc70856247fb6adfc387ca30cb1c9886c))
* **mcp:** connection testing, credential management, R2 icon CDN, and new official servers ([#224](https://github.com/jr-k/auxilia/issues/224)) ([c7e48e8](https://github.com/jr-k/auxilia/commit/c7e48e8254263858b3a9654c17b61f5e9b2ebb2f))
* **mcp:** migrate to MCP SDK v2, FastMCP client and langchain.mcp ([#328](https://github.com/jr-k/auxilia/issues/328)) ([4bbe6b3](https://github.com/jr-k/auxilia/commit/4bbe6b38054e6b7d5299447e2c6321ad9349bda1))
* merge workspace administration ([882335c](https://github.com/jr-k/auxilia/commit/882335cc9e8077ad59aea8841cd08e097c200f90))
* **model-providers:** add GLM 5.2 via OpenRouter with selectable rea… ([#197](https://github.com/jr-k/auxilia/issues/197)) ([6ec9138](https://github.com/jr-k/auxilia/commit/6ec9138598f00eb9ccb3cbf589f5f5382ae670f9))
* **model:** add muse from meta ([#211](https://github.com/jr-k/auxilia/issues/211)) ([0771ba6](https://github.com/jr-k/auxilia/commit/0771ba6edc055420ef45e29f4e47fdb13d5a50bc))
* **models:** user-configurable reasoning effort per model ([#294](https://github.com/jr-k/auxilia/issues/294)) ([66d21ad](https://github.com/jr-k/auxilia/commit/66d21ada355c5dbe414205b29d2f88d59cf6dc13))
* **models:** workspace default model ([#238](https://github.com/jr-k/auxilia/issues/238)) ([c15ad05](https://github.com/jr-k/auxilia/commit/c15ad05e361f2165c458956d050f1c5e54f25626))
* **models:** workspace model management with external whitelist ([#231](https://github.com/jr-k/auxilia/issues/231)) ([83be434](https://github.com/jr-k/auxilia/commit/83be434069d43438e1e5a5c0db22021567fd9d48))
* organize agents list with tags ([#176](https://github.com/jr-k/auxilia/issues/176)) ([648e6ea](https://github.com/jr-k/auxilia/commit/648e6ea4fb4ee19fd4ac89db3df71bfcfa7a77c6))
* per-agent sandbox with code execution UI ([#68](https://github.com/jr-k/auxilia/issues/68)) ([ed007a5](https://github.com/jr-k/auxilia/commit/ed007a56e0281184330265875413ae74c9267ac9))
* Petrol Mono redesign — app pages, docs, and MCP connection management ([#246](https://github.com/jr-k/auxilia/issues/246)) ([1014a4b](https://github.com/jr-k/auxilia/commit/1014a4b0ef978be517165c511b8e481e35d8b992))
* **profile:** add navigation and response preferences ([d73fe8f](https://github.com/jr-k/auxilia/commit/d73fe8f292835a5d75d6f7f3736dd154ea7d386f))
* **runs:** move run records to Postgres + thread last-run status ([#194](https://github.com/jr-k/auxilia/issues/194)) ([fae7fd0](https://github.com/jr-k/auxilia/commit/fae7fd0696be338b4a83a41f3004360dcc7da56f))
* **runs:** react to run status changes in sidebar and run history ([#196](https://github.com/jr-k/auxilia/issues/196)) ([023a2e9](https://github.com/jr-k/auxilia/commit/023a2e92f77cae6bc0a13ddc843ffca94fe2d09f))
* **sandbox:** workspace sandbox registry with per-agent bindings ([#284](https://github.com/jr-k/auxilia/issues/284)) ([61fb930](https://github.com/jr-k/auxilia/commit/61fb930791b00c92f227735bf79230ad436fb678))
* **skills:** skill library sourced from git repositories, one skill set per agent graph ([#321](https://github.com/jr-k/auxilia/issues/321)) ([7a76e69](https://github.com/jr-k/auxilia/commit/7a76e692c4a258afdd3aa17a4be297274a32fc1e))
* teams for agent access ([#173](https://github.com/jr-k/auxilia/issues/173)) ([30552b7](https://github.com/jr-k/auxilia/commit/30552b79e49e170c88d2418bc9a1b77fe2b75b17))
* **threads:** bound tool results in snapshots, cap MCP artifacts, load outputs on demand ([#322](https://github.com/jr-k/auxilia/issues/322)) ([206c243](https://github.com/jr-k/auxilia/commit/206c243c3281ccc5fe8dce089d78cb53a22a5871))
* **threads:** rename threads from the sidebar ([#156](https://github.com/jr-k/auxilia/issues/156)) ([9f60eef](https://github.com/jr-k/auxilia/commit/9f60eef660d6faf67ce98d734d01b6171e50f5ea))
* **triggers:** add "Run now" action to trigger card menu ([#189](https://github.com/jr-k/auxilia/issues/189)) ([076e102](https://github.com/jr-k/auxilia/commit/076e102e62665ce7b06e0571a7a1f8fc7afbdb18))
* **triggers:** add border to trigger thread icon in sidebar ([#187](https://github.com/jr-k/auxilia/issues/187)) ([f829420](https://github.com/jr-k/auxilia/commit/f829420e6c721de7a6f005f8f9ba0ca0eb4319b1))
* **triggers:** link trigger name in chat header to trigger detail ([#188](https://github.com/jr-k/auxilia/issues/188)) ([b57c683](https://github.com/jr-k/auxilia/commit/b57c6838fadaa6b8a223a6b28a552cd9105b4998))
* **triggers:** pick a day of month for monthly schedules ([#346](https://github.com/jr-k/auxilia/issues/346)) ([db16902](https://github.com/jr-k/auxilia/commit/db1690251e5de8e548aab4a4d9aa0fdcd9a0109d))
* **triggers:** redesign schedule time field with chevron picker ([#186](https://github.com/jr-k/auxilia/issues/186)) ([9f87279](https://github.com/jr-k/auxilia/commit/9f87279310eaf1f1c6e164158a7fd39604f69245))
* **triggers:** scheduled agent runs ([#182](https://github.com/jr-k/auxilia/issues/182)) ([d987da9](https://github.com/jr-k/auxilia/commit/d987da917f48fa9c8f63809de5903f261d3eca12))
* **users:** store SSO profile pictures and show avatars in users table ([#278](https://github.com/jr-k/auxilia/issues/278)) ([8a8cfdd](https://github.com/jr-k/auxilia/commit/8a8cfdd32c7be119f694b13e1c0bf71feed91c4a))
* **web:** durable run wiring — run-id capture, server Stop, reattach ([#153](https://github.com/jr-k/auxilia/issues/153)) ([4a1cf3a](https://github.com/jr-k/auxilia/commit/4a1cf3ac7173b7c563c2593436998c4567fae6dd))
* **web:** gate attachments per model with drag & drop hints ([#290](https://github.com/jr-k/auxilia/issues/290)) ([863db4a](https://github.com/jr-k/auxilia/commit/863db4a57767ec54292bd2fabd6cb1d3f3e76ba5))
* **web:** link subagent rows and chat header to the agent editor ([#360](https://github.com/jr-k/auxilia/issues/360)) ([7b5555e](https://github.com/jr-k/auxilia/commit/7b5555e4c2c6e84a41a593a1b4d4f53f381d951a))
* **web:** migrate chat streaming to @langchain/react + Agent Streaming Protocol ([#312](https://github.com/jr-k/auxilia/issues/312)) ([590eeb8](https://github.com/jr-k/auxilia/commit/590eeb8a6677295d54ad0e1b562939f0ddd06d83))
* **web:** Petrol Mono dialogs, menus, and composer ([#257](https://github.com/jr-k/auxilia/issues/257)) ([7b48896](https://github.com/jr-k/auxilia/commit/7b48896cc9d88a3dbaa012641e0d771eab5d8104))
* **web:** rebuild setup page on the shared Petrol Mono auth shell ([#281](https://github.com/jr-k/auxilia/issues/281)) ([78a62a4](https://github.com/jr-k/auxilia/commit/78a62a4cfb6359fa7ee063f76b1439d640c468a2))
* **web:** scripted product demo video with Petrol Mono overlays ([#288](https://github.com/jr-k/auxilia/issues/288)) ([6104d38](https://github.com/jr-k/auxilia/commit/6104d3821220d84d7ab919db98d4fcea82b21671))
* **web:** show subagent avatars in agent card footer ([#171](https://github.com/jr-k/auxilia/issues/171)) ([8e50338](https://github.com/jr-k/auxilia/commit/8e503380e9c1a91c2cdc827047cdb1f093636b00))
* **web:** Studio shell redesign — floating sidebar, page specs & smooth collapse ([#119](https://github.com/jr-k/auxilia/issues/119)) ([301c3ff](https://github.com/jr-k/auxilia/commit/301c3ffdaa0681c6b20f19634c47ec71a667eb88))
* **workspaces:** add multi-tenant isolation and administration ([3b9a629](https://github.com/jr-k/auxilia/commit/3b9a6299bc2687be2de97b7758d69d4bbdbd4184))


### Bug Fixes

* address Cubic review comments from [#176](https://github.com/jr-k/auxilia/issues/176) ([#178](https://github.com/jr-k/auxilia/issues/178)) ([efc35d6](https://github.com/jr-k/auxilia/commit/efc35d69eea28ac3a1f8dca0650010b6bcd06500))
* address PR review findings ([f8cc1e8](https://github.com/jr-k/auxilia/commit/f8cc1e85014f07b2894077b03c7d2386ab1126ae))
* **agents:** fail background runs fast on unauthorized MCP OAuth ([#208](https://github.com/jr-k/auxilia/issues/208)) ([e2e8a6a](https://github.com/jr-k/auxilia/commit/e2e8a6a223f31f3dd5d8b01d3536b5b2287b11d5))
* **agents:** persist MCP tool maps the editor UI already shows ([#262](https://github.com/jr-k/auxilia/issues/262)) ([6b75edd](https://github.com/jr-k/auxilia/commit/6b75edddf164bda210066a08ed5f8c0e8578c22d))
* **agents:** seed MCP tool map on connect so explicit save persists all servers ([#222](https://github.com/jr-k/auxilia/issues/222)) ([aeaf515](https://github.com/jr-k/auxilia/commit/aeaf51544f36159b10a68e7bc842d2299b6f2d5e))
* **backend:** Phase 3 — permission gate, MCP auth dispatch, explicit OAuth ([#304](https://github.com/jr-k/auxilia/issues/304)) ([d246094](https://github.com/jr-k/auxilia/commit/d2460947d4d94bd9e80ee3c5ff3c4d7139e03e5a))
* **chat:** harden prompt queue interactions ([1c3b36e](https://github.com/jr-k/auxilia/commit/1c3b36ea6dadce631ceff7aa2ef8e2a71957d3a5))
* conflicting tailwind imports ([13c8f66](https://github.com/jr-k/auxilia/commit/13c8f66636b3e03dda812f684744f6eed9d9b5f1))
* **mcp:** render Metabase interactive visualize_query MCP App ([#128](https://github.com/jr-k/auxilia/issues/128)) ([2bbc28c](https://github.com/jr-k/auxilia/commit/2bbc28c8ac9febaf291f7d35e52227df49347ed2))
* **oom:** Only load when needed ([#243](https://github.com/jr-k/auxilia/issues/243)) ([867b2a3](https://github.com/jr-k/auxilia/commit/867b2a35e7f7e979b161036ec5646c8f5a84de9b))
* pass structuredContent from artifact to AppRenderer for MCP app widgets ([e7374a6](https://github.com/jr-k/auxilia/commit/e7374a6e31359539cbf64a19917e7685fe94c3d4))
* portal agent dialog to body to fix positioning inside animated cards ([1233943](https://github.com/jr-k/auxilia/commit/123394342129dcbc3139b11f682fba60d0e870bf))
* proper dark mode styling for code blocks ([#212](https://github.com/jr-k/auxilia/issues/212)) ([c213d77](https://github.com/jr-k/auxilia/commit/c213d77eb927851f330e45da20f2c202fa3853de))
* remove client setup for DCR official MCP servers ([92aa1d2](https://github.com/jr-k/auxilia/commit/92aa1d28e494e199ff9435e8e33b4576add9ba36))
* render user profile pictures everywhere a person is shown ([#295](https://github.com/jr-k/auxilia/issues/295)) ([7bc3b72](https://github.com/jr-k/auxilia/commit/7bc3b72fa6864868eca5df544882ac73725750ea))
* resolve static analysis findings ([38023e4](https://github.com/jr-k/auxilia/commit/38023e44c3107a1ceacf325bf6a88e905a01269a))
* scope HITL decisions to hanging tool calls only ([#93](https://github.com/jr-k/auxilia/issues/93)) ([5675fec](https://github.com/jr-k/auxilia/commit/5675fececc2b3fd8f0aece8b591b5f9a365d9fae))
* **security:** avoid dynamic object injection sinks ([f87ebd3](https://github.com/jr-k/auxilia/commit/f87ebd309a11cfbac1f4c744ccd34734e8dca43a))
* **skills:** keep warnings out of the sync confirmation dialog ([#351](https://github.com/jr-k/auxilia/issues/351)) ([e0429b0](https://github.com/jr-k/auxilia/commit/e0429b088d81efe9726ee3a376098a346271a905))
* **slack:** de-duplicate HITL tool header; keep quote bar on multi-line args ([#165](https://github.com/jr-k/auxilia/issues/165)) ([b1500bf](https://github.com/jr-k/auxilia/commit/b1500bf870842ca8ef31c3b271cf94605a235d50))
* **triggers:** show running state in trigger run history ([#209](https://github.com/jr-k/auxilia/issues/209)) ([83c114f](https://github.com/jr-k/auxilia/commit/83c114fed296d26311018fd98ae70f101ce011fc))
* update pending invites UI without needing refresh ([#38](https://github.com/jr-k/auxilia/issues/38)) ([1a2bf7b](https://github.com/jr-k/auxilia/commit/1a2bf7b4c7add6d0f8370b72c01b4ee03dbcc692))
* **web:** cap agent table inline avatars at 3 ([#276](https://github.com/jr-k/auxilia/issues/276)) ([a7fc7e4](https://github.com/jr-k/auxilia/commit/a7fc7e4307182b19bd4f01c3dbf4237a56991748))
* **web:** display DeepSeek reasoning content in chat ([#280](https://github.com/jr-k/auxilia/issues/280)) ([16f0fe8](https://github.com/jr-k/auxilia/commit/16f0fe8f719b3194ddd7d42952f1c469d0953cc2))
* **web:** don't throw when the client aborts before the backend answers ([#365](https://github.com/jr-k/auxilia/issues/365)) ([5506be4](https://github.com/jr-k/auxilia/commit/5506be474883fab14829f84b35a87a74897649ec))
* **web:** forward client aborts through the backend proxy ([#363](https://github.com/jr-k/auxilia/issues/363)) ([9fa6642](https://github.com/jr-k/auxilia/commit/9fa664276ab8930e6ccb0f06d05938cd50f58433))
* **web:** resolve npm audit vulnerabilities via lockfile bumps ([#274](https://github.com/jr-k/auxilia/issues/274)) ([ebf59e6](https://github.com/jr-k/auxilia/commit/ebf59e6df9b29d2fdce4d1e435496c85394fb70b))
* **web:** strip stale encoding headers in the backend proxy ([#270](https://github.com/jr-k/auxilia/issues/270)) ([aa2f50b](https://github.com/jr-k/auxilia/commit/aa2f50bdf798679c822eb8c0fb389d7c69010394))
* **web:** surface real tool error text; refactor(agents): collapse agent construction ([#144](https://github.com/jr-k/auxilia/issues/144)) ([e7fdc8e](https://github.com/jr-k/auxilia/commit/e7fdc8e0b82fcb0d52cf8b3c62bd02b4c5e0084e))
* **workspaces:** restore CI after tenant isolation ([04bd9e3](https://github.com/jr-k/auxilia/commit/04bd9e3570b4f54b07c1f52fdbcc8ca8455ac161))


### Performance Improvements

* **agents:** drop instructions and tool maps from the list response ([#267](https://github.com/jr-k/auxilia/issues/267)) ([69be828](https://github.com/jr-k/auxilia/commit/69be828b5a0e8c2e9ff5aec69744eb9403cb0102))
* **web:** cut streaming memory churn — memoized conversation body, SDK throttle, values trim ([#310](https://github.com/jr-k/auxilia/issues/310)) ([720e1ac](https://github.com/jr-k/auxilia/commit/720e1ac70ac94f01d26a9f6b4fa90e2915e08e4b))
* **web:** cut the /agents page request storm ([#265](https://github.com/jr-k/auxilia/issues/265)) ([ca54ad2](https://github.com/jr-k/auxilia/commit/ca54ad21707476b5a98e52fa1c7bf3e3e3263b93))


### Code Refactoring

* enforce CONVENTIONS.md naming across backend + frontend ([#100](https://github.com/jr-k/auxilia/issues/100)) ([f3af7c2](https://github.com/jr-k/auxilia/commit/f3af7c2159aa8fc83e47bc34e41f1a3367c9f00f))
* **mcp:** serve the official server catalog from the CDN ([#258](https://github.com/jr-k/auxilia/issues/258)) ([61a4b5c](https://github.com/jr-k/auxilia/commit/61a4b5cb7387a759d0521f142d355a05155a5ae6))
* rename binding association tables and simplify naming ([#67](https://github.com/jr-k/auxilia/issues/67)) ([dfab494](https://github.com/jr-k/auxilia/commit/dfab49435fd9fb8490263762224ba9b3875d2bac))
* **triggers:** remove Draft badge from new trigger header ([#184](https://github.com/jr-k/auxilia/issues/184)) ([fd88991](https://github.com/jr-k/auxilia/commit/fd889913414fbc4def3fb49a677cc02557f5cf54))
* **web:** resource modules, API import boundary and useThreadSession ([#325](https://github.com/jr-k/auxilia/issues/325)) ([62f6f1c](https://github.com/jr-k/auxilia/commit/62f6f1c45c49361af4cb53d5f779d3442cd7f5fa))

## [0.10.3](https://github.com/keurcien/auxilia/compare/web-v0.10.2...web-v0.10.3) (2026-09-25)


### Bug Fixes

* **web:** don't throw when the client aborts before the backend answers ([#365](https://github.com/keurcien/auxilia/issues/365)) ([5506be4](https://github.com/keurcien/auxilia/commit/5506be474883fab14829f84b35a87a74897649ec))
* **web:** forward client aborts through the backend proxy ([#363](https://github.com/keurcien/auxilia/issues/363)) ([9fa6642](https://github.com/keurcien/auxilia/commit/9fa664276ab8930e6ccb0f06d05938cd50f58433))

## [0.10.2](https://github.com/keurcien/auxilia/compare/web-v0.10.1...web-v0.10.2) (2026-09-23)


### Features

* **web:** link subagent rows and chat header to the agent editor ([#360](https://github.com/keurcien/auxilia/issues/360)) ([7b5555e](https://github.com/keurcien/auxilia/commit/7b5555e4c2c6e84a41a593a1b4d4f53f381d951a))

## [0.10.1](https://github.com/keurcien/auxilia/compare/web-v0.10.0...web-v0.10.1) (2026-09-22)


### Features

* **agents:** full tool descriptions dialog for MCP server panels ([#353](https://github.com/keurcien/auxilia/issues/353)) ([1e51374](https://github.com/keurcien/auxilia/commit/1e513747e4e17c8d7e2fb11790d102cfd92cc20a))
* **triggers:** pick a day of month for monthly schedules ([#346](https://github.com/keurcien/auxilia/issues/346)) ([db16902](https://github.com/keurcien/auxilia/commit/db1690251e5de8e548aab4a4d9aa0fdcd9a0109d))


### Bug Fixes

* **skills:** keep warnings out of the sync confirmation dialog ([#351](https://github.com/keurcien/auxilia/issues/351)) ([e0429b0](https://github.com/keurcien/auxilia/commit/e0429b088d81efe9726ee3a376098a346271a905))

## [0.10.0](https://github.com/keurcien/auxilia/compare/web-v0.9.1...web-v0.10.0) (2026-09-21)


### ⚠ BREAKING CHANGES

* **skills:** the `create_sandbox` / `connect_sandbox` tools are gone; sandboxes are opened by the runtime, never by the model.

### Features

* **skills:** skill library sourced from git repositories, one skill set per agent graph ([#321](https://github.com/keurcien/auxilia/issues/321)) ([7a76e69](https://github.com/keurcien/auxilia/commit/7a76e692c4a258afdd3aa17a4be297274a32fc1e))

## [0.9.1](https://github.com/keurcien/auxilia/compare/web-v0.9.0...web-v0.9.1) (2026-09-14)


### Features

* **mcp:** migrate to MCP SDK v2, FastMCP client and langchain.mcp ([#328](https://github.com/keurcien/auxilia/issues/328)) ([4bbe6b3](https://github.com/keurcien/auxilia/commit/4bbe6b38054e6b7d5299447e2c6321ad9349bda1))


### Code Refactoring

* **web:** resource modules, API import boundary and useThreadSession ([#325](https://github.com/keurcien/auxilia/issues/325)) ([62f6f1c](https://github.com/keurcien/auxilia/commit/62f6f1c45c49361af4cb53d5f779d3442cd7f5fa))

## [0.9.0](https://github.com/keurcien/auxilia/compare/web-v0.8.0...web-v0.9.0) (2026-09-11)


### ⚠ BREAKING CHANGES

* **threads:** `GET /threads/{id}` no longer returns `values`, `interrupted`, `interrupt_value` or `interrupt_id`; hydrate from `GET /threads/{id}/state`. Non-app MCP tools no longer carry `structured_content` in their ToolMessage artifact.

### Features

* **threads:** bound tool results in snapshots, cap MCP artifacts, load outputs on demand ([#322](https://github.com/keurcien/auxilia/issues/322)) ([206c243](https://github.com/keurcien/auxilia/commit/206c243c3281ccc5fe8dce089d78cb53a22a5871))

## [0.8.0](https://github.com/keurcien/auxilia/compare/web-v0.7.0...web-v0.8.0) (2026-09-06)


### ⚠ BREAKING CHANGES

* **agents:** sandbox agents lose ~4KB of deepagents prompt fragments and the long `task` description, `write_file` now overwrites existing files, and a recursive sandbox-scoped `delete` tool is exposed. Existing threads see a one-time system prompt change.

### Features

* **agents:** upgrade to deepagents 0.7 with lean harness prompts ([#319](https://github.com/keurcien/auxilia/issues/319)) ([4522df3](https://github.com/keurcien/auxilia/commit/4522df37fd489bf5b7f1e6170fe305f369bae1fb))

## [0.7.0](https://github.com/keurcien/auxilia/compare/web-v0.6.5...web-v0.7.0) (2026-09-05)


### ⚠ BREAKING CHANGES

* **agents:** POST /threads/{id}/runs/stream and GET /threads/{id}/runs/{run_id}/stream are removed (use the protocol endpoints /threads/{id}/commands + /threads/{id}/stream/events); the `messages` field of GET /threads/{id} (AI SDK UIMessage shape) is removed.

### Features

* **agents:** subagent tool approvals (HITL) surface and resume like the parent's ([#317](https://github.com/keurcien/auxilia/issues/317)) ([ddc00fc](https://github.com/keurcien/auxilia/commit/ddc00fccce6ede374f8dbb26209795b6370444d8))
* **agents:** worker-native Agent Streaming Protocol, legacy SSE removed ([#313](https://github.com/keurcien/auxilia/issues/313)) ([a05cf12](https://github.com/keurcien/auxilia/commit/a05cf127b9a1ee45efbf4d47d9d15d17bf648c54))
* **chat:** render the conversation from @langchain/react views, reasoning on the chain rail ([#315](https://github.com/keurcien/auxilia/issues/315)) ([766d123](https://github.com/keurcien/auxilia/commit/766d123f4f6da73efd06dac5241feeaa8f009389))
* **chat:** subagent conversation in a tinted task band ([#316](https://github.com/keurcien/auxilia/issues/316)) ([accf730](https://github.com/keurcien/auxilia/commit/accf7301a1afb9fe0cf2146edc729dc89622442b))

## [0.6.5](https://github.com/keurcien/auxilia/compare/web-v0.6.4...web-v0.6.5) (2026-09-02)


### Features

* **agents:** checkpoint-keyed HITL approvals via interrupt ids ([#307](https://github.com/keurcien/auxilia/issues/307)) ([4982321](https://github.com/keurcien/auxilia/commit/4982321c242e15af9030a6f7db0613a57d9e64f1))
* **web:** migrate chat streaming to @langchain/react + Agent Streaming Protocol ([#312](https://github.com/keurcien/auxilia/issues/312)) ([590eeb8](https://github.com/keurcien/auxilia/commit/590eeb8a6677295d54ad0e1b562939f0ddd06d83))


### Performance Improvements

* **web:** cut streaming memory churn — memoized conversation body, SDK throttle, values trim ([#310](https://github.com/keurcien/auxilia/issues/310)) ([720e1ac](https://github.com/keurcien/auxilia/commit/720e1ac70ac94f01d26a9f6b4fa90e2915e08e4b))

## [0.6.4](https://github.com/keurcien/auxilia/compare/web-v0.6.3...web-v0.6.4) (2026-08-31)


### Bug Fixes

* **backend:** Phase 3 — permission gate, MCP auth dispatch, explicit OAuth ([#304](https://github.com/keurcien/auxilia/issues/304)) ([d246094](https://github.com/keurcien/auxilia/commit/d2460947d4d94bd9e80ee3c5ff3c4d7139e03e5a))

## [0.6.3](https://github.com/keurcien/auxilia/compare/web-v0.6.2...web-v0.6.3) (2026-08-28)


### Bug Fixes

* render user profile pictures everywhere a person is shown ([#295](https://github.com/keurcien/auxilia/issues/295)) ([7bc3b72](https://github.com/keurcien/auxilia/commit/7bc3b72fa6864868eca5df544882ac73725750ea))

## [0.6.2](https://github.com/keurcien/auxilia/compare/web-v0.6.1...web-v0.6.2) (2026-08-27)


### Features

* **agents:** persistent run errors, recovery middleware, and langchain 1.3 ([#292](https://github.com/keurcien/auxilia/issues/292)) ([2e8766e](https://github.com/keurcien/auxilia/commit/2e8766e66d1ba2c0672a915518d69dd9282e1c12))
* **models:** user-configurable reasoning effort per model ([#294](https://github.com/keurcien/auxilia/issues/294)) ([66d21ad](https://github.com/keurcien/auxilia/commit/66d21ada355c5dbe414205b29d2f88d59cf6dc13))

## [0.6.1](https://github.com/keurcien/auxilia/compare/web-v0.6.0...web-v0.6.1) (2026-08-25)


### Features

* **web:** gate attachments per model with drag & drop hints ([#290](https://github.com/keurcien/auxilia/issues/290)) ([863db4a](https://github.com/keurcien/auxilia/commit/863db4a57767ec54292bd2fabd6cb1d3f3e76ba5))
* **web:** scripted product demo video with Petrol Mono overlays ([#288](https://github.com/keurcien/auxilia/issues/288)) ([6104d38](https://github.com/keurcien/auxilia/commit/6104d3821220d84d7ab919db98d4fcea82b21671))

## [0.6.0](https://github.com/keurcien/auxilia/compare/web-v0.5.33...web-v0.6.0) (2026-08-22)


### ⚠ BREAKING CHANGES

* **sandbox:** agents.has_code_interpreter and the SANDBOX_* / OPEN_SANDBOX_* / CLOUD_RUN_SANDBOX_* env vars are removed. The migration converts an env-configured deployment into a registry row and rebinds flagged agents automatically when the env vars are still present at upgrade time.

### Features

* **sandbox:** workspace sandbox registry with per-agent bindings ([#284](https://github.com/keurcien/auxilia/issues/284)) ([61fb930](https://github.com/keurcien/auxilia/commit/61fb930791b00c92f227735bf79230ad436fb678))
* **web:** rebuild setup page on the shared Petrol Mono auth shell ([#281](https://github.com/keurcien/auxilia/issues/281)) ([78a62a4](https://github.com/keurcien/auxilia/commit/78a62a4cfb6359fa7ee063f76b1439d640c468a2))

## [0.5.33](https://github.com/keurcien/auxilia/compare/web-v0.5.32...web-v0.5.33) (2026-08-21)


### Features

* **users:** store SSO profile pictures and show avatars in users table ([#278](https://github.com/keurcien/auxilia/issues/278)) ([8a8cfdd](https://github.com/keurcien/auxilia/commit/8a8cfdd32c7be119f694b13e1c0bf71feed91c4a))


### Bug Fixes

* **web:** display DeepSeek reasoning content in chat ([#280](https://github.com/keurcien/auxilia/issues/280)) ([16f0fe8](https://github.com/keurcien/auxilia/commit/16f0fe8f719b3194ddd7d42952f1c469d0953cc2))

## [0.5.32](https://github.com/keurcien/auxilia/compare/web-v0.5.31...web-v0.5.32) (2026-08-21)


### Bug Fixes

* **web:** cap agent table inline avatars at 3 ([#276](https://github.com/keurcien/auxilia/issues/276)) ([a7fc7e4](https://github.com/keurcien/auxilia/commit/a7fc7e4307182b19bd4f01c3dbf4237a56991748))

## [0.5.31](https://github.com/keurcien/auxilia/compare/web-v0.5.30...web-v0.5.31) (2026-08-21)


### Bug Fixes

* **web:** resolve npm audit vulnerabilities via lockfile bumps ([#274](https://github.com/keurcien/auxilia/issues/274)) ([ebf59e6](https://github.com/keurcien/auxilia/commit/ebf59e6df9b29d2fdce4d1e435496c85394fb70b))

## [0.5.30](https://github.com/keurcien/auxilia/compare/web-v0.5.29...web-v0.5.30) (2026-08-20)


### Bug Fixes

* **web:** strip stale encoding headers in the backend proxy ([#270](https://github.com/keurcien/auxilia/issues/270)) ([aa2f50b](https://github.com/keurcien/auxilia/commit/aa2f50bdf798679c822eb8c0fb389d7c69010394))

## [0.5.29](https://github.com/keurcien/auxilia/compare/web-v0.5.28...web-v0.5.29) (2026-08-20)


### Performance Improvements

* **agents:** drop instructions and tool maps from the list response ([#267](https://github.com/keurcien/auxilia/issues/267)) ([69be828](https://github.com/keurcien/auxilia/commit/69be828b5a0e8c2e9ff5aec69744eb9403cb0102))

## [0.5.28](https://github.com/keurcien/auxilia/compare/web-v0.5.27...web-v0.5.28) (2026-08-19)


### Performance Improvements

* **web:** cut the /agents page request storm ([#265](https://github.com/keurcien/auxilia/issues/265)) ([ca54ad2](https://github.com/keurcien/auxilia/commit/ca54ad21707476b5a98e52fa1c7bf3e3e3263b93))

## [0.5.27](https://github.com/keurcien/auxilia/compare/web-v0.5.26...web-v0.5.27) (2026-08-19)


### Bug Fixes

* **agents:** persist MCP tool maps the editor UI already shows ([#262](https://github.com/keurcien/auxilia/issues/262)) ([6b75edd](https://github.com/keurcien/auxilia/commit/6b75edddf164bda210066a08ed5f8c0e8578c22d))

## [0.5.26](https://github.com/keurcien/auxilia/compare/web-v0.5.25...web-v0.5.26) (2026-08-17)


### Code Refactoring

* **mcp:** serve the official server catalog from the CDN ([#258](https://github.com/keurcien/auxilia/issues/258)) ([61a4b5c](https://github.com/keurcien/auxilia/commit/61a4b5cb7387a759d0521f142d355a05155a5ae6))

## [0.5.25](https://github.com/keurcien/auxilia/compare/web-v0.5.24...web-v0.5.25) (2026-08-16)


### Features

* **web:** Petrol Mono dialogs, menus, and composer ([#257](https://github.com/keurcien/auxilia/issues/257)) ([7b48896](https://github.com/keurcien/auxilia/commit/7b48896cc9d88a3dbaa012641e0d771eab5d8104))

## [0.5.24](https://github.com/keurcien/auxilia/compare/web-v0.5.23...web-v0.5.24) (2026-08-14)


### Features

* Petrol Mono redesign — app pages, docs, and MCP connection management ([#246](https://github.com/keurcien/auxilia/issues/246)) ([1014a4b](https://github.com/keurcien/auxilia/commit/1014a4b0ef978be517165c511b8e481e35d8b992))

## [0.5.23](https://github.com/keurcien/auxilia/compare/web-v0.5.22...web-v0.5.23) (2026-07-29)


### Bug Fixes

* **oom:** Only load when needed ([#243](https://github.com/keurcien/auxilia/issues/243)) ([867b2a3](https://github.com/keurcien/auxilia/commit/867b2a35e7f7e979b161036ec5646c8f5a84de9b))

## [0.5.22](https://github.com/keurcien/auxilia/compare/web-v0.5.21...web-v0.5.22) (2026-07-22)


### Features

* **models:** workspace default model ([#238](https://github.com/keurcien/auxilia/issues/238)) ([c15ad05](https://github.com/keurcien/auxilia/commit/c15ad05e361f2165c458956d050f1c5e54f25626))

## [0.5.21](https://github.com/keurcien/auxilia/compare/web-v0.5.20...web-v0.5.21) (2026-07-20)


### Features

* **models:** workspace model management with external whitelist ([#231](https://github.com/keurcien/auxilia/issues/231)) ([83be434](https://github.com/keurcien/auxilia/commit/83be434069d43438e1e5a5c0db22021567fd9d48))

## [0.5.20](https://github.com/keurcien/auxilia/compare/web-v0.5.19...web-v0.5.20) (2026-07-18)


### Features

* **mcp:** connection testing, credential management, R2 icon CDN, and new official servers ([#224](https://github.com/keurcien/auxilia/issues/224)) ([c7e48e8](https://github.com/keurcien/auxilia/commit/c7e48e8254263858b3a9654c17b61f5e9b2ebb2f))

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
