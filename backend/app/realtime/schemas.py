from enum import Enum


class WorkspaceEventKind(str, Enum):
    agents = "agents"
    projects = "projects"
    triggers = "triggers"
    mcp_servers = "mcp_servers"
    skills = "skills"
    threads = "threads"
    runs = "runs"
    prompt_queue = "prompt_queue"
    trigger_history = "trigger_history"
