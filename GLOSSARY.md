# auxilia

A web MCP client where users chat with configured agents. Agents may run code in a sandbox and exchange files with the user through the thread.

## Language

### Files

**Attachment**:
A file the user adds to a message in a thread.
_Avoid_: Upload, input file

**Artifact**:
A file the agent produces for the user during a turn.
_Avoid_: Output, deliverable, download

**Thread file**:
An attachment or an artifact, as kept on the thread and placed on its sandbox. Thread files in the object store outlive the sandbox; without one, artifacts are temporary and expire with it.
_Avoid_: Sandbox file, workspace file
