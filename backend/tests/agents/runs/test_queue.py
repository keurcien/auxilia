from app.agents.runs.queue import RunQueue


async def test_fifo_order(redis):
    queue = RunQueue(redis)
    for run_id in ["a", "b", "c"]:
        await queue.enqueue(run_id)
    assert await queue.dequeue(timeout=1) == "a"
    assert await queue.dequeue(timeout=1) == "b"
    assert await queue.dequeue(timeout=1) == "c"


async def test_dequeue_timeout_returns_none(redis):
    queue = RunQueue(redis)
    assert await queue.dequeue(timeout=0.1) is None
