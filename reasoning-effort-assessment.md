# Reasoning effort: cross-provider assessment & catalog design

*Assessed 2026-08-26. Question: can "reasoning effort" become a user-settable,
catalog-declared setting instead of being hardcoded per model (GLM 5.2
max/high pseudo-models, DeepSeek `thinking: enabled`)?*

## TL;DR

- **The knob is converging, the values are not.** Every current-gen provider now
  exposes reasoning control as an **effort enum** (token budgets are legacy:
  rejected on Claude 4.7+, deprecated on Gemini 3, never existed on
  OpenAI/DeepSeek/GLM/xAI). The de-facto superset ladder is
  `none < minimal < low < medium < high < xhigh < max` — but **no two providers
  accept the same subset**, defaults differ, and "off" doesn't exist on some
  models (Gemini 3, GLM-5.3, grok-4+, Claude Fable/Mythos 5).
- **LangChain 1.x has already standardized the parameter name**: `ChatOpenAI`,
  `ChatAnthropic` (alias `effort` → `output_config.effort`) and
  `ChatGoogleGenerativeAI` (alias `thinking_level`) all accept
  **`reasoning_effort`** as an init/call param. DeepSeek/GLM/xAI still need
  `extra_body`.
- **LangChain also ships the catalog data we need**: `model.profile` returns
  `reasoning_effort_levels` + `reasoning_effort_default` per model (verified
  locally on langchain-anthropic 1.6.1 / -openai 1.6.0 / -google-genai 4.3.5).
  It covers first-party models only — `None` for GLM via OpenRouter — so our
  whitelist must carry the levels at least for gateway models.
- **Recommendation**: add `reasoning_effort_levels` + `reasoning_effort_default`
  to the whitelist entry (same names as LangChain profiles), store the user's
  choice per thread next to `model_id`, and translate the canonical enum inside
  `ChatModelFactory`. This collapses `glm-5.2-max`/`glm-5.2-high` into one
  model and unhardcodes DeepSeek.

## Current state in auxilia

| Where | What's hardcoded |
| --- | --- |
| `backend/app/model_providers/catalog.py` `OPENROUTER_MODELS` | GLM effort baked into the *model id*: `glm-5.2-max` / `glm-5.2-high` → `extra_body={"reasoning_effort": ...}` |
| `ChatModelFactory` deepseek branch | `extra_body={"thinking": {"type": "enabled"}}`, always on |
| `ChatModelFactory` anthropic branch | adaptive models: `effort="medium"` fixed; legacy models: `budget_tokens=1024` fixed |
| `ChatModelFactory` google branch | `thinking_budget=-1` (dynamic) fixed |
| `ChatModelFactory` openai branch | nothing sent → provider default effort |
| `whitelist.yaml` | no reasoning metadata at all |

Flow today: `thread.model_id` → `ModelService.ensure_available` →
`ChatModelFactory.create(provider, model_id, api_key)`. There is no per-thread
or per-agent knob; effort is a side effect of which model you picked.

## Provider comparison (August 2026)

| Provider | Native param | Values (current models) | Default | Off? | LangChain exposure |
| --- | --- | --- | --- | --- | --- |
| OpenAI | `reasoning_effort` (chat) / `reasoning.effort` (Responses) | gpt-5.1/5.2: `none,low,medium,high(,xhigh)`; gpt-5.6: adds `max` (Responses-only) | 5.1/5.2: `none`; 5.5/5.6: `medium` | yes (`none`) | `ChatOpenAI(reasoning_effort=...)`, first-class |
| Anthropic | `output_config.effort` (+ `thinking: {type: adaptive}`) | `low,medium,high,xhigh,max` (xhigh: 4.7+/5-family) | `high` | 5-family Fable/Mythos: no; Sonnet 5/Opus 5: `type: disabled` ≤ high | `ChatAnthropic(reasoning_effort=...)` (alias `effort`), first-class; `budget_tokens` **400s on 4.7+** |
| Google | `thinkingConfig.thinkingLevel` (Gemini 3+) | `minimal,low,medium,high` — per-model subsets (3-pro-preview: `low,high` only) | model-specific (`high` for 3-pro) | **no** — thinking can't be disabled on Gemini 3.x | `ChatGoogleGenerativeAI(reasoning_effort=...)` (alias `thinking_level`); `thinking_budget` deprecated for 3+ |
| DeepSeek V4 | `thinking: {type}` + `reasoning_effort` | `low,high,max` (`medium`/`xhigh` silently coerced to `high`) | thinking on, effort `high` | yes (`thinking: disabled`) | `extra_body` only (`ChatDeepSeek` subclasses BaseChatOpenAI so `reasoning_effort` passes through) |
| Z.ai GLM 5.2 | `reasoning_effort` (top-level) + `thinking: {type}` | effective tiers: off / `high` / `max` (others coerced) | `max` | 5.2: yes; **5.3: no** (disabled → effort `low`) | via `ChatOpenAI` + `extra_body` (what we do through OpenRouter) |
| xAI Grok | `reasoning_effort` | 4.6: `low,medium,high,xhigh`; grok-4/4.1 **reject the param** (400) | `high` | no on grok-4-class | `extra_body` only |
| OpenRouter (gateway) | unified `reasoning: {effort \| max_tokens \| enabled, exclude}` | `none…max` superset, normalized per upstream (effort→Anthropic budget by % of max_tokens; xhigh→high for Gemini) | — | per upstream | `extra_body` |

Key hazards the design must absorb:

- **Silent coercion vs hard 400**: DeepSeek/GLM coerce unsupported values;
  Anthropic legacy format and grok-4 hard-fail. Never send a value the model
  wasn't declared to support.
- **"Off" is not universal**: UIs need per-model knowledge of whether `none`
  exists, else "off" must degrade to lowest effort (LiteLLM/GLM-5.3 behavior).
- **OpenAI gpt-5.6 + tools**: chat completions rejects function tools with any
  effort ≠ `none` — already handled by `OPENAI_RESPONSES_API_MODELS`.

## How other platforms model it

- **LibreChat** — per-provider param panels, no translation layer. OpenAI-style
  endpoints get a `reasoning_effort` dropdown over the full superset
  (`none…max`, default unset); Anthropic gets a `thinking` toggle +
  `thinkingBudget` slider (adaptive handling bolted on later for Opus 4.6+);
  Google gets `thinking`/`thinkingBudget`/`thinkingLevel`. Presets in
  `librechat.yaml` (`modelSpecs.list[].preset`) can pin any of these; custom
  endpoints choose a wire format via `customParams.reasoningFormat`
  (`reasoning_effort` flat vs OpenRouter-style object). *Weakness: the dropdown
  is the same superset for every model — users can pick values the model
  rejects.*
- **Open WebUI** — a free-text `reasoning_effort` string in per-model advanced
  params, passed through verbatim; broken on Ollama (which wants `think=`).
  The anti-pattern: untyped passthrough, no per-model validation.
- **LiteLLM** — the best translation prior art: unified `reasoning_effort`
  (`none…max` + `disable`), mapped per provider — verbatim for
  OpenAI/xAI/DeepSeek, → `output_config.effort` for Claude 4.6+, →
  `budget_tokens` for legacy Claude (low=1024, medium=2048, high=4096,
  xhigh=8192, max=16384), → `thinking_level` for Gemini 3 (with
  none/disable degrading to minimal since it can't turn off).
- **Vercel AI SDK 7** — unified top-level `reasoning` enum with a clean
  precedence rule: any provider-specific reasoning option makes the unified
  param ignored entirely, never merged.
- **OpenRouter** — unified `reasoning.effort`/`max_tokens` (mutually
  exclusive), normalizing effort→budget by percentage of `max_tokens` for
  budget-native upstreams.

Conclusion: **canonical enum + per-model declared subset + per-provider
translation** (LiteLLM's model, constrained LibreChat-style UI) is the design
everyone converged on. Nobody serious does raw passthrough (Open WebUI) and
nobody needs budget sliders anymore except for legacy Anthropic/Gemini models.

## Verified locally: LangChain profiles already carry the catalog data

```python
ChatAnthropic(model="claude-opus-4-8").profile
# reasoning_effort_levels: [low, medium, high, xhigh, max], default: high
ChatOpenAI(model="gpt-5.6-luna").profile
# reasoning_effort_levels: [none, low, medium, high, xhigh, max], default: medium
ChatGoogleGenerativeAI(model="gemini-3-pro-preview").profile
# reasoning_effort_levels: [low, high], default: high
ChatDeepSeek(model="deepseek-v4-pro").profile
# reasoning_output: True — no levels (package data lags the V4 API, which
# accepts low/high/max per api-docs.deepseek.com/guides/thinking_mode/)
ChatOpenAI(model="z-ai/glm-5.2", base_url=openrouter).profile
# None — gateway models have no profile
```

So profiles are a good *validation/backfill* source but can't be the source of
truth: they miss gateway models and lag provider API changes. The whitelist
(already CDN-hosted, hand-editable, release-free) is the right owner.

## Recommended design

### 1. Whitelist schema (catalog)

Add to `SupportedModel` / `whitelist.yaml`, reusing LangChain's profile names:

```yaml
- provider: openrouter
  model_id: glm-5.2
  display_name: GLM 5.2
  reasoning_effort_levels: [high, max]   # omitted/empty = no reasoning knob
  reasoning_effort_default: max
```

- Values drawn from the canonical ladder
  `none, minimal, low, medium, high, xhigh, max` (validate against a
  `Literal`). `none` in the list ⇔ thinking can be disabled — no separate
  boolean needed.
- Entries without levels render no effort picker (gpt-4o-mini, MiMo, Muse).
- Optional validator: when a LangChain profile exists for the model, warn/fail
  if the whitelist declares a level the profile doesn't (catches typos; profile
  absence or mismatch in the lenient direction is fine since profiles lag).

### 2. Where the user sets it

Per **thread**, next to the model picker (a small effort selector shown only
when the selected model declares levels), stored as a nullable
`reasoning_effort` column beside `thread.model_id`; `NULL` = catalog default.
Triggers get the same optional field. Per-agent defaults can come later —
per-thread matches how `model_id` already flows and is what
LibreChat/Claude/ChatGPT UIs train users to expect.

Validation belongs where `ModelUnavailableError` lives: `RunService.create`
checks the requested effort against the whitelist entry's levels (400 on
mismatch — never forward and rely on provider coercion, since some providers
silently coerce and others 400).

### 3. Translation in `ChatModelFactory`

`create(provider, model_id, api_key, reasoning_effort: str | None)`:

| Provider | Mapping |
| --- | --- |
| openai | `reasoning_effort=<value>` (first-class param; Responses API routing already handled) |
| anthropic | adaptive models: `reasoning_effort=<value>` (replaces hardcoded `effort="medium"`); legacy models: keep `budget_tokens`, LiteLLM table if we ever expose levels there |
| google | `reasoning_effort=<value>` (alias of `thinking_level`) for Gemini 3+; keep `thinking_budget=-1` when no effort chosen |
| deepseek | `extra_body={"thinking": {"type": "disabled" if value == "none" else "enabled"}, ...}` + `reasoning_effort` for low/high/max |
| openrouter (GLM) | `extra_body={"reasoning_effort": <value>}` — and **delete the `glm-5.2-max`/`glm-5.2-high` split**: one `glm-5.2` model, levels `[high, max]`, default `max`. `OPENROUTER_MODELS` becomes id → slug only. |

Precedence rule (from AI SDK 7): a model with no declared levels never gets a
reasoning param sent — no merging, no best-effort guesses.

### 4. Migration notes

- Collapsing the GLM pseudo-models changes `model_id`s stored on threads and in
  the `models` enablement table — needs a data migration (`glm-5.2-*` →
  `glm-5.2` + effort) or keeping the old ids as aliases during a deprecation
  window. The whitelist is CDN-served, so ship the backend translation first,
  then flip the YAML.
- DeepSeek default stays "thinking on, effort high" (their API default), so
  no behavior change for existing threads with `NULL` effort.
- `reasoning_effort` should flow into Langfuse metadata for cost monitoring —
  effort is the dominant cost lever on these models.

## Sources

- OpenAI: developers.openai.com/api/docs/guides/reasoning
- Anthropic: platform.claude.com/docs/en/build-with-claude/effort, …/extended-thinking
- Google: ai.google.dev/gemini-api/docs/thinking, …/gemini-3
- DeepSeek: api-docs.deepseek.com/guides/thinking_mode/
- Z.ai: docs.z.ai/guides/capabilities/thinking-mode
- xAI: docs.x.ai/developers/model-capabilities/text/reasoning
- OpenRouter: openrouter.ai/docs/use-cases/reasoning-tokens
- LibreChat: librechat.ai/docs/configuration/librechat_yaml/object_structure/model_specs
- Open WebUI: docs.openwebui.com/features/chat-conversations/chat-features/reasoning-models/ (+ issue #20921)
- LiteLLM: docs.litellm.ai/docs/reasoning_content
- Vercel AI SDK: ai-sdk.dev/docs/ai-sdk-core/reasoning
- LangChain profiles: verified locally against installed langchain-anthropic 1.6.1, langchain-openai 1.6.0, langchain-google-genai 4.3.5, langchain-deepseek 1.1.0
