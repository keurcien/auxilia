Project Overview

A lightweight web MCP client designed to host your MCP-powered AI assistants. auxilia is designed to only support remote MCP servers.
auxilia is an open-source web MCP client, designed for users and companies to host and configure their MCP-powered AI assistants. auxilia is designed support remote MCP servers only. The key idea is that all sorts of context, are provided to LLM through MCP (whether it's skills, semantic search capability, web search, etc.), to keep auxilia as simple as possible.

Core features are MCP and agent management:

- MCP: workspace admin users can add MCP servers to workspace. Workspace MCP servers are then available to all users, to be binded to any workspace agent.
- Agent : an agent is defined by instructions and MCP tools. Tools can be individually configured to be disabled or to require user approval (Human-In-The-Loop).

External integrations:

- Slack: invoke workspace agents from Slack.
- Langfuse: monitor costs, LLM generations and tool calls.
