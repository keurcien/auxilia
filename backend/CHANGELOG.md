# Changelog

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
