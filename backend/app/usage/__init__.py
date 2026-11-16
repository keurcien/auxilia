"""LLM usage ledger: one row per model call, priced when it happened.

The per-conversation estimate (`app/runtime/api/costs.py`) reconstructs cost
from checkpoints on demand, which cannot answer "what did this trigger cost
last month" across thousands of threads. The ledger can: the runtime records
every model call as it completes (`recorder.py`), history from before the
ledger existed is imported once from checkpoints (`backfill.py`), and rows
outlive the threads, agents, projects and triggers they are attributed to.
"""
