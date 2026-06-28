from app.agents.runs.control import RunControl


async def test_cancel_signal_is_delivered(redis):
    control = RunControl("r1", redis)
    await control.request_cancel(ttl=60)
    assert await control.wait_for_cancel(poll_seconds=0.01) is True
