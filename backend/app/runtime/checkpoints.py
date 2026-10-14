"""Reading a thread's LangGraph state off its checkpoints.

Every agent graph is compiled with deepagents' ``DeepAgentState``, whose
``messages`` channel is a ``DeltaChannel``: a checkpoint stores the step's
writes, and the full list only every 50th update (a ``_DeltaSnapshot``). So
``checkpoint["channel_values"]["messages"]`` is no longer the conversation —
most of the time the key is absent, and reading it raw shows an empty or
stale thread. LangGraph rebuilds the value by walking ancestor checkpoints
back to the nearest snapshot (``BaseCheckpointSaver.aget_delta_channel_history``),
and ``Pregel.aget_state`` is the public API that does the walk.

Out-of-request readers — the thread read endpoint, the protocol state
snapshot, the run result, HITL scope resolution — have a checkpointer and a
thread id, not the agent graph, so they read through a node-less *reader
graph* that declares the same channels. Two facts make that work, and both
are easy to break:

- **The reader is compiled with the checkpointer.** ``aget_state`` hydrates
  delta channels through ``self.checkpointer`` only; a checkpointer passed in
  ``configurable`` fetches the tuple but is not used to walk history
  (langgraph 1.2.11). It is also why a subagent graph compiled without a
  checkpointer cannot read its own state back.
- **``CONFIG_KEY_CHECKPOINTER`` is set in the config.** With a non-empty
  ``checkpoint_ns``, ``aget_state`` otherwise looks for a *structural*
  subgraph of that name — and a subagent invoked by the ``task`` tool is not
  one. The key makes it read the namespace directly, as langgraph does for
  nested snapshots.

Pre-migration checkpoints (a plain list under ``channel_values["messages"]``)
read unchanged: ``DeltaChannel.from_checkpoint`` takes the list as the seed.
"""

from collections.abc import AsyncIterator
from typing import Any, NamedTuple, NotRequired

from deepagents.graph import DeepAgentState
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.constants import CONFIG_KEY_CHECKPOINTER
from langgraph.graph import START, StateGraph


class _ReaderState(DeepAgentState):
    """The channels a reader materialises: deepagents' agent state plus the
    ``todos`` channel ``TodoListMiddleware`` adds on the sandbox path."""

    todos: NotRequired[list[Any]]


def _noop(state: _ReaderState) -> dict[str, Any]:  # noqa: ARG001 - a StateGraph needs one node; it never runs
    return {}


# Compiled per call, against the caller's checkpointer (see module docstring).
_READER = StateGraph(_ReaderState).add_node("noop", _noop).add_edge(START, "noop")


class CheckpointState(NamedTuple):
    """A thread's (or subagent namespace's) latest checkpoint, both ways.

    ``saved`` is the raw tuple — its ``pending_writes`` carry the HITL
    interrupts, which live outside any channel. ``values`` is the state as
    the graph would see it: the reconstructed ``messages``, plus ``todos`` and
    ``structured_response`` when set. ``saved`` is ``None`` when the thread
    has no checkpoint at all.
    """

    saved: CheckpointTuple | None
    values: dict[str, Any]

    @property
    def messages(self) -> list:
        return self.values.get("messages", [])

    @property
    def todos(self) -> list:
        return self.values.get("todos", [])

    @property
    def structured_response(self) -> Any | None:
        return self.values.get("structured_response")


EMPTY_STATE = CheckpointState(saved=None, values={})


async def iter_checkpoint_messages(
    checkpointer: BaseCheckpointSaver, thread_id: str
) -> AsyncIterator[list]:
    """Read retained history across root and subagents, newest first.

    Hydrate each exact checkpoint through the reader: raw delta channel
    values aren't transcripts. Callers must deduplicate repeated message IDs.
    Walking history also preserves usage removed by context compaction.
    """
    reader = _READER.compile(checkpointer=checkpointer)
    # AsyncPostgresSaver.alist holds its cursor lock while yielding. Exhaust
    # it before aget_state performs point reads on the same saver, otherwise
    # those reads deadlock. Retain only configs, not the large raw tuples.
    configs = [
        saved.config
        async for saved in checkpointer.alist(
            {"configurable": {"thread_id": thread_id}}
        )
    ]
    for saved_config in configs:
        config: RunnableConfig = {
            "configurable": {
                **saved_config["configurable"],
                CONFIG_KEY_CHECKPOINTER: checkpointer,
            }
        }
        snapshot = await reader.aget_state(config)
        yield snapshot.values.get("messages", [])


async def get_checkpoint_state(
    checkpointer: BaseCheckpointSaver, thread_id: str, checkpoint_ns: str = ""
) -> CheckpointState:
    """The latest checkpoint of ``thread_id`` under ``checkpoint_ns`` (``""``
    for the root agent, ``tools:<task id>`` for a subagent), with its channel
    values reconstructed. Two point reads: the tuple, then the state."""
    configurable = {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}
    saved = await checkpointer.aget_tuple(config={"configurable": configurable})
    if saved is None:
        return EMPTY_STATE
    reader = _READER.compile(checkpointer=checkpointer)
    snapshot = await reader.aget_state(
        {"configurable": {**configurable, CONFIG_KEY_CHECKPOINTER: checkpointer}}
    )
    return CheckpointState(saved=saved, values=dict(snapshot.values))
