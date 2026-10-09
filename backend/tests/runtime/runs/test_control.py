from uuid import UUID

from app.runtime.runs.control import RunControl


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")


async def test_cancel_signal_is_delivered(redis):
    control = RunControl("r1", redis, workspace_id=WORKSPACE_ID)
    await control.request_cancel(ttl=60)
    assert await control.wait_for_cancel(poll_seconds=0.01) is True
