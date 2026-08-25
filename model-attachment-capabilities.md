# Per-model attachment capabilities without manual maintenance

**Question**: can we know which attachment types each model accepts (image/PDF/audio/video,
and ideally which formats) without hand-maintaining a per-model list like the current
`["deepseek", "z-ai"]` hack in the chat composer?

**Answer: yes.** The LangChain partner packages we already depend on bundle per-model
capability profiles (data sourced from [models.dev](https://models.dev), refreshed with every
package release). Every chat model instance exposes them as `model.profile` — no new
dependency, no network call, no manual list.

## What we have today

- `whitelist.yaml` carries a hand-maintained `multimodal: bool` — too coarse (image ≠ audio ≠
  PDF) and one more thing to get wrong when adding a model.
- The frontend hardcodes `noAttachments = ["deepseek", "z-ai"].includes(chefSlug)` — the thing
  we want to delete.

## The mechanism (verified against our installed versions)

`langchain_core` 1.3.2 defines `ModelProfile` (a TypedDict) and `BaseChatModel.profile`.
Partner packages bundle the data (`langchain_anthropic/data/_profiles.py` + a maintainer
`profile_augmentations.toml`) and resolve it from the model name at instantiation — a real
API key is not needed for the lookup.

Relevant fields: `image_inputs`, `pdf_inputs`, `audio_inputs`, `video_inputs`,
`image_url_inputs` (plus `tool_calling`, `structured_output`, `max_input_tokens`, … which
could replace `supports_structured_output` in the whitelist later).

Verified output on our installed packages:

| Model (package) | image | pdf | audio | video |
| --- | --- | --- | --- | --- |
| `claude-sonnet-4-5` (langchain-anthropic 1.4.3) | ✅ | ✅ | ❌ | ❌ |
| `gpt-5-mini` (langchain-openai 1.1.9) | ✅ | ✅ | ❌ | ❌ |
| `gemini-2.5-flash` (langchain-google-genai 4.2.2) | ✅ | ✅ | ✅ | ✅ |
| `deepseek-chat` (langchain-deepseek) | `profile is None` |
| `z-ai/glm-4.6` via OpenRouter (`ChatOpenAI` + base_url) | `profile == {}` |

The two gaps resolve **conservatively correct**: treating a missing/empty profile as
"no attachments" is exactly right for DeepSeek and the OpenRouter-served GLM models — the
models that caused the 400 in the first place. If an OpenRouter-served model ever *should*
accept files, `ChatOpenAI(..., profile={"image_inputs": True})` overrides explicitly
(verified working), which could be fed from an optional whitelist field for that rare case.

## What about exact formats (WEBP vs JPG, MP4…)?

No machine-readable source exposes MIME-level detail per model — not models.dev, not the
provider `/models` APIs (they expose nothing about modalities at all), not OpenRouter/LiteLLM
(modality level only). But MIME support is a property of the **provider's file-ingestion
pipeline, not the individual model**, documented per provider and very stable:

| Provider | images | pdf | audio | video |
| --- | --- | --- | --- | --- |
| Anthropic | jpeg, png, gif, webp | pdf | — | — |
| OpenAI | png, jpeg, webp, non-animated gif | pdf | (speech models only) | — |
| Google | png, jpeg, webp, heic, heif | pdf | wav, mp3, aiff, aac, ogg, flac | mp4, mpeg, mov, avi, webm, wmv, 3gpp, flv |

So: **per-model modality booleans come free from `.profile`; a tiny static
provider → modality → MIME map (one dict, ~15 lines, changes maybe once a year) turns them
into an exact `accept` list.** The cross product never needs per-model maintenance.

## Alternatives considered

- **models.dev `api.json` fetched at whitelist-sync time** — same data, but adds a runtime
  fetch + cache for something the partner packages already ship offline. Only worth it if we
  want fresher data than package releases provide.
- **LiteLLM `model_prices_and_context_window.json`** — similar coverage (`supports_vision`,
  `supports_pdf_input`, …), but a third-party repo fetch and a second naming scheme to map.
- **Provider APIs** — dead end; none of OpenAI/Anthropic/Google return input-modality info.

## Recommended wiring (not implemented yet)

1. **Backend** — in the `/models` list path, resolve each model's profile (instantiate via
   `ChatModelFactory` with a dummy key, or cache per whitelist sync) and extend
   `ModelResponse` with e.g. `inputModalities: list["image" | "pdf" | "audio" | "video"]`.
   Missing/empty profile → `[]`.
2. **Frontend** — delete the hardcoded `chefSlug` list; `noAttachments = inputModalities.length === 0`.
   Map modalities × provider MIME table into the `accept` prop of `PromptInput`, and extend
   its `matchesAccept` (currently only understands `image/*`) to validate real MIME lists so
   a drop of an unsupported *type* is rejected client-side with a toast.
3. **Whitelist** — drop `multimodal` once the above lands (or keep it as an override slot for
   OpenRouter-served models with no profile data).
4. **Backstop** — the provider 400 can still happen (stale package data); the in-progress
   run-error surfacing work covers making such failures visible in the UI instead of silent.

**Staleness caveat**: profile data updates with partner-package releases. A brand-new model
may briefly report no capabilities until the package updates — conservative (blocks uploads
that would work) rather than dangerous (never produces the 400).
