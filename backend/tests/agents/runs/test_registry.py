from app.agents.runs.registry import RunRegistry
from app.agents.runs.state import RunRecord, RunStatus


async def _seed(redis, run_id="r1", thread_id="t1"):
    reg = RunRegistry(redis)
    await reg.create(RunRecord(id=run_id, thread_id=thread_id, user_id="u1"), ttl=3600)
    return reg


async def test_create_and_get(redis):
    reg = await _seed(redis)
    got = await reg.get("r1")
    assert got is not None and got.id == "r1"
    assert await reg.get("missing") is None


async def test_list_for_thread_newest_first(redis):
    reg = RunRegistry(redis)
    for run_id in ["r1", "r2", "r3"]:
        await reg.create(RunRecord(id=run_id, thread_id="t1", user_id="u1"), ttl=3600)
    ids = [r.id for r in await reg.list_for_thread("t1")]
    assert ids == ["r3", "r2", "r1"]


async def test_active_mutex_is_exclusive_and_owner_scoped(redis):
    reg = RunRegistry(redis)
    assert await reg.claim_active("t1", "r1", ttl=30) is True
    assert await reg.claim_active("t1", "r2", ttl=30) is False
    await reg.release_active("t1", "r2")  # not the owner — no-op
    assert await reg.get_active_id("t1") == "r1"
    await reg.release_active("t1", "r1")
    assert await reg.get_active_id("t1") is None


async def test_set_status_validates_and_clears_active_set(redis):
    reg = await _seed(redis)
    assert "r1" in await reg.list_active_ids()
    await reg.set_status("r1", RunStatus.running)
    await reg.set_status("r1", RunStatus.success, error=None)
    assert (await reg.get("r1")).status == RunStatus.success
    assert await reg.list_active_ids() == []


async def test_set_status_records_error(redis):
    reg = await _seed(redis)
    await reg.set_status("r1", RunStatus.running)
    await reg.set_status("r1", RunStatus.error, error="boom")
    record = await reg.get("r1")
    assert record.status == RunStatus.error
    assert record.error == "boom"


async def test_set_status_missing_run_returns_none(redis):
    reg = RunRegistry(redis)
    assert await reg.set_status("nope", RunStatus.running) is None


async def test_heartbeat_stamps_liveness(redis):
    reg = await _seed(redis)
    assert (await reg.get("r1")).last_heartbeat is None
    await reg.heartbeat("r1")
    assert (await reg.get("r1")).last_heartbeat is not None
