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
  - provider: openrouter
    model_id: glm-5.2-max
    display_name: GLM 5.2 (max reasoning)
    chef: Z.ai
    chef_slug: z-ai
"""


def test_parse_valid_document():
    models = parse_whitelist(VALID_DOC)
    assert [m.model_id for m in models] == ["claude-sonnet-5", "glm-5.2-max"]
    assert models[0].multimodal is True
    assert models[1].supports_structured_output is False


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
        # An openrouter id without an OPENROUTER_MODELS mapping would only
        # crash at agent build — it must fail file validation instead.
        (
            "schema_version: 1\nmodels:\n"
            "  - provider: openrouter\n"
            "    model_id: z-ai/glm-99\n"
            "    display_name: GLM 99\n",
            "no OPENROUTER_MODELS mapping",
        ),
    ],
)
def test_parse_rejects_bad_documents(text: str, match: str):
    # Validation is all-or-nothing: one bad entry fails the whole file so a
    # broken CDN upload can never half-apply.
    with pytest.raises(ValueError, match=match):
        parse_whitelist(text)


def test_bundled_snapshot_is_valid():
    models = bundled_whitelist()
    assert len(models) >= 1
    assert all(isinstance(m, SupportedModel) for m in models)
    # The bundled snapshot must contain the models seeded by the migration.
    ids = {m.model_id for m in models}
    assert {"gpt-4o-mini", "claude-sonnet-5", "glm-5.2-max"} <= ids
