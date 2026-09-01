"""StreamFilter: mirrors the client's `subscription.js` matching semantics."""

from app.agents.protocol.filter import StreamFilter


def _event(method: str, namespace: list[str], name: str | None = None) -> dict:
    data = {"name": name} if name is not None else {}
    return {"method": method, "params": {"namespace": namespace, "data": data}}


def test_channel_matching():
    sink = StreamFilter(channels=("messages", "lifecycle"))
    assert sink.matches(_event("messages", []))
    assert sink.matches(_event("lifecycle", []))
    assert not sink.matches(_event("values", []))
    # input.requested maps to the `input` channel.
    assert not sink.matches(_event("input.requested", []))
    assert StreamFilter(channels=("input",)).matches(_event("input.requested", []))


def test_unknown_methods_never_match():
    assert not StreamFilter(channels=("messages",)).matches(
        _event("brand-new-method", [])
    )


def test_named_custom_channels():
    assert StreamFilter(channels=("custom",)).matches(_event("custom", [], name="a2a"))
    assert StreamFilter(channels=("custom:a2a",)).matches(
        _event("custom", [], name="a2a")
    )
    assert not StreamFilter(channels=("custom:other",)).matches(
        _event("custom", [], name="a2a")
    )


def test_wildcard_namespaces_deliver_everything():
    sink = StreamFilter(channels=("messages",))
    assert sink.matches(_event("messages", ["tools:abc", "tools:def"]))


def test_namespace_prefix_with_dynamic_suffix_normalization():
    """A filter prefix of `tools` matches a server namespace `tools:<uuid>` —
    the dynamic suffix is stripped, mirroring the client's normalization."""
    sink = StreamFilter(channels=("messages",), namespaces=(("tools",),))
    assert sink.matches(_event("messages", ["tools:abc"]))
    assert not sink.matches(_event("messages", ["subagents:abc"]))
    # A concrete filter segment must match literally.
    exact = StreamFilter(channels=("messages",), namespaces=(("tools:abc",),))
    assert exact.matches(_event("messages", ["tools:abc"]))
    assert not exact.matches(_event("messages", ["tools:def"]))


def test_depth_bounds_distance_below_prefix():
    sink = StreamFilter(channels=("messages",), namespaces=((),), depth=1)
    assert sink.matches(_event("messages", []))
    assert sink.matches(_event("messages", ["tools:a"]))
    assert not sink.matches(_event("messages", ["tools:a", "tools:b"]))
