---
status: accepted
date: 2026-10-22
---

# Attachments go to the sandbox, images also to the model

A file attached to a message is stored as a thread file and placed on the thread's sandbox disk, where the agent reads it or runs code on it. An image is additionally sent to the model as a vision block when the model has vision; it then still reaches the model if its upload fails (no object store). Nothing else is ever inlined in the message, and the system never guesses whether a file is "for the model" or "for the sandbox": the model sees the image and knows its path, and does whichever the user asked.

## Considered options

- **Route by intent** (classifier or composer toggle): wrong often, and the user cannot predict it.
- **Inline everything as content blocks** (the previous behaviour): providers do not reliably accept non-PDF files, the base64 blob is checkpointed forever and resent on every turn, and the sandbox never sees the file.
- **Send PDFs to providers that read them natively**: rejected for now so the rule stays one sentence. The sandbox can parse a PDF or render its pages to images itself.

## Consequences

- An image attached only to be mounted in a document still costs vision tokens on that turn.
- A file is as durable as its thread, not its sandbox: a replaced sandbox gets every thread file restored.
- Agents without a sandbox take images only; other files need a sandbox and a configured object store.
