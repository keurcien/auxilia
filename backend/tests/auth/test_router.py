import pytest

from app.auth.router import is_same_origin_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/agents/123?tab=chat", True),
        ("/", True),
        ("//evil.com", False),
        ("/\\evil.com", False),
        ("https://evil.com", False),
        ("agents", False),
        ("/\t/evil.com", False),
        ("/\n/evil.com", False),
    ],
)
def test_is_same_origin_path(path: str, expected: bool) -> None:
    assert is_same_origin_path(path) is expected
