from pathlib import Path

import pytest

from app.model_providers.whitelist import (
    SupportedModel,
    bundled_whitelist,
    parse_whitelist,
)


VALID_DOC = """
schema_version: 1
models:
  - provider: anthropic
    model_id: claude-sonnet-5
    display_name: Claude Sonnet 5
    multimodal: true
    supports_structured_output: true
    reasoning_effort_levels: [low, medium, high, xhigh, max]
    reasoning_effort_default: medium
  - provider: openrouter
    model_id: z-ai/glm-5.2
    display_name: GLM 5.2
    chef: Z.ai
    chef_slug: z-ai
"""


def test_parse_valid_document():
    models = parse_whitelist(VALID_DOC)
    assert [m.model_id for m in models] == ["claude-sonnet-5", "z-ai/glm-5.2"]
    assert models[0].multimodal is True
    assert models[0].reasoning_effort_levels == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    assert models[0].reasoning_effort_default == "medium"
    assert models[1].supports_structured_output is False
    # Effort metadata is optional: no levels = no effort knob.
    assert models[1].reasoning_effort_levels == []
    assert models[1].reasoning_effort_default is None


def test_chef_defaults_to_provider_and_explicit_chef_wins():
    models = parse_whitelist(VALID_DOC)
    assert models[0].chef == "Anthropic"
    assert models[0].chef_slug == "anthropic"
    assert models[1].chef == "Z.ai"
    assert models[1].chef_slug == "z-ai"


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("schema_version: 2\nmodels: []", "schema_version"),
        ("schema_version: 1\nmodels: []", "no models"),
        ("- just\n- a list", "mapping"),
        ("{invalid yaml: [", "not valid YAML"),
        (
            VALID_DOC + "  - provider: anthropic\n"
            "    model_id: claude-sonnet-5\n"
            "    display_name: Duplicate\n",
            "duplicate model_id",
        ),
        (
            "schema_version: 1\nmodels:\n"
            "  - provider: not-a-provider\n"
            "    model_id: x\n"
            "    display_name: X\n",
            "not supported",
        ),
        # Effort values come from the canonical ladder — a typo must fail the
        # file, not surface as a 400 on some provider call later.
        (
            "schema_version: 1\nmodels:\n"
            "  - provider: openai\n"
            "    model_id: gpt-5\n"
            "    display_name: GPT-5\n"
            "    reasoning_effort_levels: [ultra]\n",
            "reasoning_effort_levels",
        ),
        # The default must be one of the declared levels.
        (
            "schema_version: 1\nmodels:\n"
            "  - provider: openai\n"
            "    model_id: gpt-5\n"
            "    display_name: GPT-5\n"
            "    reasoning_effort_levels: [low, high]\n"
            "    reasoning_effort_default: medium\n",
            "not in reasoning_effort_levels",
        ),
        # Levels must follow the canonical ladder order — the picker renders
        # the list as-is.
        (
            "schema_version: 1\nmodels:\n"
            "  - provider: openai\n"
            "    model_id: gpt-5\n"
            "    display_name: GPT-5\n"
            "    reasoning_effort_levels: [high, low]\n",
            "out-of-order reasoning_effort_levels",
        ),
    ],
)
def test_parse_rejects_bad_documents(text: str, match: str):
    # Validation is all-or-nothing: one bad entry fails the whole file so a
    # broken CDN upload can never half-apply.
    with pytest.raises(ValueError, match=match):
        parse_whitelist(text)


def test_publishable_copy_matches_bundled_snapshot():
    """catalog/whitelist.yaml (uploaded to the CDN) and the bundled snapshot
    must stay byte-identical, or the CDN and offline fallback silently
    diverge (same contract as the MCP server catalog)."""
    published = Path(__file__).resolve().parents[3] / "catalog" / "whitelist.yaml"
    if not published.exists():
        pytest.skip("publishable copy not present (packaged build)")
    bundled = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "model_providers"
        / "whitelist.yaml"
    )
    assert published.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8")


def test_bundled_snapshot_is_valid():
    models = bundled_whitelist()
    assert len(models) >= 1
    assert all(isinstance(m, SupportedModel) for m in models)
    # The bundled snapshot must contain the models seeded by the migration.
    ids = {m.model_id for m in models}
    assert {"gpt-4o-mini", "claude-sonnet-5", "z-ai/glm-5.2"} <= ids
