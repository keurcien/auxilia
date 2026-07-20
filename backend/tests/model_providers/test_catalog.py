import pytest

from app.model_providers.catalog import ChatModelFactory


@pytest.mark.parametrize(
    ("model_id", "expects_responses_api"),
    [
        # gpt-5.6 reasoning models reject function tools on chat completions —
        # they must go through the Responses API.
        ("gpt-5.6-luna", True),
        ("gpt-5.6-sol", True),
        ("gpt-5.6-terra", True),
        # The rest of the family works on the default chat-completions path.
        ("gpt-5.5", False),
        ("gpt-5", False),
        ("gpt-4o-mini", False),
    ],
)
def test_openai_factory_routes_gpt56_through_responses_api(
    model_id: str, expects_responses_api: bool
):
    model = ChatModelFactory().create("openai", model_id, "unit-test-key")
    assert model.use_responses_api is expects_responses_api
