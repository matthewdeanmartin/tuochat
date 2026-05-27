# Spec: Python LLM Chat Client Specialized for GitLab Duo

## Working title

**duochat**
A Python-first, multi-UI chat client for GitLab Duo, optimized for long-form technical conversations, markdown-heavy answers, transcript durability, and future agentic workflows.

## 1. Purpose

`duochat` is a local-first chat client for interacting with GitLab Duo through GraphQL using `gql`. It is intended to be better than thin chat wrappers and more useful than IDE chat panes for serious developer work.

The app should excel at:

- high quality markdown rendering and copying
- durable conversation history stored locally
- conversation resume and replay
- great stream logging and diagnostics
- low dependency count
- token accounting and usage analytics
- multiple user interfaces over one shared core
- strong error handling and recoverability
- future extension into tool use and agentic loops

The design goal is not “yet another chatbot.” The design goal is “a dependable developer workstation for GitLab Duo.”

______________________________________________________________________

## 2. Non-goals

Version 1 should not try to be everything.

Out of scope for the initial release:

- broad provider abstraction for every LLM vendor
- plugin marketplace
- distributed multi-user server
- vector databases and RAG pipelines
- browser automation
- heavyweight desktop frameworks
- mandatory cloud sync

Those can come later if they prove useful.

______________________________________________________________________

## 3. Design principles

### Local first

All conversations, logs, request metadata, and exported transcripts should be available on disk in normal files.

### Markdown first

The model’s output is often markdown. The client should preserve it, render it well, and make it easy to copy either as raw markdown or plain text.

### Stream first

Streaming is not a cosmetic feature. It is the normal mode. The client should handle partial tokens, stream interruptions, retries, and stream logging cleanly.

### Low dependency count

Use a small, deliberate set of libraries. Avoid framework sprawl.

### One core, many UIs

The business logic should not live in the UI. Terminal, Tkinter, and web UI should all sit on the same service layer.

### Auditability

Every request and response should be traceable. Logs should help answer:

- what was sent
- what came back
- when it failed
- how many tokens were used
- whether the conversation was resumed or retried

### Agent-ready, not agent-forced

The system should start as a strong chat client but have a clean path to tool use and controlled agent loops later.

______________________________________________________________________

## 4. Recommended technology choices

Keep the stack lean.

### Core language

Python 3.12+

### Required third-party libraries

- **gql** for GraphQL transport and operations
- **python-gitlab** For init help.

### Optional third-party libraries

- **pydantic** for strongly typed config and message models
- **fastapi** for optional local web backend
- **uvicorn** for serving the web backend
- **rich** for terminal rendering, markdown, tables, logs
- **markdown-it-py** for better markdown parsing if Rich alone is not enough
- **httpx** only if needed independently of the `gql` transport stack
- **sqlite-utils** is optional, but plain `sqlite3` is preferred to reduce dependencies

### Avoid unless clearly needed

- React in the first web prototype
- Electron
- Textual, unless terminal UI complexity grows enough to justify it
- ORM libraries
- plugin systems
- Redis, Celery, background task stacks

______________________________________________________________________

## 5. High-level architecture

The app should be split into the following layers.

### 5.1 Domain layer

Pure Python models and policies:

- conversation
- message
- stream event
- token usage
- provider request/response
- tool invocation
- session metadata
- retry outcome
- export format

This layer should have no UI code and as little transport knowledge as possible.

### 5.2 Provider layer

GitLab Duo specific GraphQL client logic:

- authentication
- request construction
- GraphQL query/mutation definitions
- streaming/event handling
- usage extraction
- Duo-specific error parsing
- capability detection

This layer is where `gql` lives.

### 5.3 Application/service layer

Orchestrates workflows:

- send message
- resume conversation
- retry failed stream
- save transcript
- export transcript
- switch system prompt
- collect token stats
- run future tool calls
- run future agent loop steps

This is the heart of the app.

### 5.4 Persistence layer

Local storage for:

- conversations
- messages
- stream event logs
- request/response envelopes
- token accounting
- settings
- named system prompts
- exports

### 5.5 UI layer

Multiple front ends over the same service layer:

- terminal
- Tkinter desktop
- local web UI via FastAPI + minimal frontend

______________________________________________________________________

## 6. Functional requirements

## 6.1 Authentication and configuration

The client must support:

- GitLab host URL
- token or auth credential configuration
- GraphQL endpoint configuration
- TLS and cert settings if needed
- timeout settings
- stream timeout settings
- retry policy settings
- logging verbosity settings
- active system prompt selection
- UI startup mode selection

Config should be loadable from:

- environment variables
- a TOML config file
- command line overrides

Recommended path:

- `~/.config/duochat/config.toml` on Linux
- platform-appropriate config dir elsewhere

Sensitive values should not be written into normal logs.

______________________________________________________________________

## 6.2 Chat features

### Basic chat

The client must support:

- new conversation
- send user message
- receive assistant response
- stream response incrementally
- stop generation if the provider supports it
- retry last turn
- edit and resend a prior user message
- fork conversation from a prior point
- resume existing conversation

### Conversation handling

The client should allow:

- listing conversations
- searching conversations by title or contents
- filtering by date
- pinning important conversations
- assigning conversation titles
- auto-generating title from first turn
- exporting one conversation or many

### Resume behavior

Conversation resume must be first-class.

That means:

- load prior messages from local storage
- recover partial assistant output from interrupted streams
- clearly mark incomplete turns
- allow resend from the last stable turn
- optionally preserve failed attempts for debugging

______________________________________________________________________

## 6.3 Markdown support

This is one of the most important areas.

The client must support:

- headers, lists, code fences, blockquotes, tables, inline code
- fenced code blocks with language labels
- preservation of original raw markdown
- rendered view and raw view
- copy raw markdown
- copy rendered plain text
- copy individual code blocks
- copy the full answer
- easy extraction of terminal commands from responses

Nice to have:

- markdown table rendering in terminal and desktop
- clickable or copyable links in GUI/web UIs
- code block “copy” affordances in desktop/web UIs
- syntax highlighting where feasible

The storage format must preserve exact model text, not only a rendered derivative.

______________________________________________________________________

## 6.4 Copy/paste excellence

This is a core product feature.

The client should optimize for real-world workflows where users move text between:

- GitLab
- terminal
- browser
- IDE
- shell
- issue tracker
- merge request description
- commit message

Required capabilities:

- copy one message
- copy multiple selected messages
- copy full conversation
- copy as markdown
- copy as plain text
- copy only code blocks
- copy transcript with speaker labels
- quick paste-friendly transcript format

Suggested export templates:

- chat transcript
- markdown conversation
- plain text conversation
- issue-ready summary
- MR-comment-ready summary

______________________________________________________________________

## 6.5 Streaming

Streaming should be the default response mode.

The system must support:

- incremental token display
- partial message buffering
- distinction between final and partial output
- display of stream timing
- logging of stream chunks
- graceful handling of malformed chunks
- graceful handling of network interruption
- detection of duplicate stream fragments if retries cause overlap

Each stream should produce a structured event log such as:

- request started
- stream opened
- chunk received
- chunk appended
- usage updated
- stream completed
- stream failed
- stream cancelled
- retry started

Streaming logs should be useful both for debugging and for later analytics.

______________________________________________________________________

## 6.6 Logging and observability

Logging must be excellent.

There should be separate log streams for:

### App logs

Lifecycle, UI startup, config loading, normal events.

### Provider logs

GraphQL requests, response metadata, error payloads, retries.

### Stream logs

Detailed chunk-by-chunk or event-by-event stream activity.

### Conversation logs

High-level business events such as conversation created, resumed, exported.

### Token logs

Prompt tokens, completion tokens, totals, estimated cost if known.

### Security/privacy posture

Logs should support redaction modes:

- redact secrets always
- optionally redact message content
- optionally keep full content only in transcript store, not general logs

Structured JSON logs should be available, even if human-readable logs are also emitted.

Suggested on-disk layout:

```text
duochat/
  config.toml
  conversations/
  exports/
  logs/
    app.log
    provider.log
    streams.log
    tokens.log
  state/
    client.db
```

______________________________________________________________________

## 6.7 Token tracking

Token accounting must be a first-class concern, not an afterthought.

The client should track, per message and per conversation:

- input tokens
- output tokens
- cached tokens if the provider exposes them
- running totals
- tokens per minute
- average response size
- estimated cost if pricing is configured locally

If exact token usage is unavailable from Duo in some paths, the client should support:

- exact provider numbers when available
- estimated fallback mode
- explicit flag marking estimates vs provider-reported counts

Views should include:

- per turn usage
- per conversation totals
- daily totals
- recent 7-day totals
- exportable CSV/JSON usage reports

______________________________________________________________________

## 6.8 Local history and search

The client must store local conversation history durably.

Required features:

- full-text search over messages
- search by conversation title
- search by date range
- search by tag
- search by system prompt used
- search by model/provider metadata if applicable

Recommended storage:

- SQLite database for metadata and search indices
- plain transcript files for durable human-readable backups

This hybrid approach gives both robustness and portability.

______________________________________________________________________

## 6.9 System prompt management

System prompts should be an explicit feature, not buried in config.

The client should support:

- named system prompts
- prompt library stored locally
- prompt selection per conversation
- changing prompt for a new conversation
- forking conversation with a different system prompt
- marking favorite prompts
- exporting/importing prompt sets

Examples:

- default assistant
- code reviewer
- shell command explainer
- MR summarizer
- issue investigator
- cautious agent
- terse answer mode

The active system prompt should always be visible in the UI.

______________________________________________________________________

## 6.10 Error resilience

The client must behave well under bad conditions.

It should handle:

- expired credentials
- GraphQL schema mismatch
- transient network failures
- partial stream termination
- malformed provider data
- local persistence failures
- duplicate submit attempts
- UI crashes without transcript loss

Expected behavior:

- preserve already received tokens
- clearly distinguish failed vs complete turns
- allow retry from last stable state
- never silently discard content
- record enough context to debug failures later

______________________________________________________________________

## 7. Persistence and file formats

## 7.1 Storage model

Use a hybrid storage system.

### SQLite

Store:

- conversation metadata
- message metadata
- prompt references
- token counts
- stream events index
- tags
- search index
- retry history

### Files

Store:

- raw transcripts as markdown or JSON
- exported conversations
- structured stream traces for debugging if enabled

This lets the app remain inspectable even without special tools.

______________________________________________________________________

## 7.2 Suggested schema

### conversations

- id
- title
- created_at
- updated_at
- provider_name
- host
- system_prompt_id
- status
- tags_json

### messages

- id
- conversation_id
- role
- ordinal
- created_at
- raw_markdown
- plain_text_cache
- status
- parent_message_id optional
- retry_of_message_id optional

### usage_records

- id
- conversation_id
- message_id
- input_tokens
- output_tokens
- total_tokens
- source_kind exact_or_estimated
- recorded_at

### stream_events

- id
- conversation_id
- message_id
- seq
- event_type
- payload_json
- created_at

### system_prompts

- id
- name
- description
- content
- created_at
- updated_at
- is_favorite

______________________________________________________________________

## 8. Multi-UI strategy

## 8.1 Terminal UI

This should likely be the first polished UI because it aligns with the product’s audience.

Use `rich` for:

- markdown rendering
- panels
- progress
- status
- tables
- logs

Terminal UI modes:

- interactive chat mode
- transcript viewer mode
- history search mode
- export mode
- token usage report mode

The terminal UI should support keyboard-first workflows and fast copy/paste-friendly output.

A pure terminal mode may be enough for the first real release.

______________________________________________________________________

## 8.2 Tkinter UI

Tkinter is attractive because it is in the stdlib and keeps dependencies low.

Its role:

- lightweight desktop client
- better text selection than some terminal contexts
- local conversation browser
- split-pane message view
- prompt selector
- export and copy actions

Tkinter will not be as flashy, but it can be dependable.

Use it if desktop selection/copy workflows matter and a browser UI feels too heavy.

______________________________________________________________________

## 8.3 Web UI

A local web UI should be designed as an optional interface over the same backend.

Recommended path:

- FastAPI backend
- minimal frontend first, possibly server-rendered HTML plus a little TypeScript
- avoid React until complexity proves necessary

The web UI should support:

- conversation list
- markdown rendering
- copy buttons
- stream display
- prompt selection
- token dashboards
- transcript export

A simple server-rendered or light-HTMX-style interface may be enough early on, though if you prefer TypeScript that can still be kept small.

______________________________________________________________________

## 8.4 UI recommendation

For low dependency count and fastest time to usefulness:

### Phase 1

Terminal UI only

### Phase 2

Add local web UI

### Phase 3

Add Tkinter only if it solves actual copy/select pain better than browser and terminal

That is probably the least risky sequencing.

______________________________________________________________________

## 9. GitLab Duo provider integration

This app is specialized for GitLab Duo, so the provider layer should not pretend everything is generic if it is not.

Responsibilities:

- encapsulate Duo GraphQL operations
- normalize provider responses to internal message models
- normalize stream events
- detect provider capabilities
- preserve raw provider payloads for debugging when enabled
- make auth and endpoint configuration explicit

The GraphQL client should expose a narrow internal API like:

- `start_conversation(...)`
- `send_message(...)`
- `stream_message(...)`
- `resume_conversation(...)`
- `fetch_usage(...)` if supported
- `health_check(...)`

The rest of the app should not have to know raw GraphQL details.

______________________________________________________________________

## 10. CLI behavior

Even with multiple UIs, a good CLI matters.

Example commands:

```bash
duochat chat
duochat chat --prompt code-reviewer
duochat resume <conversation-id>
duochat history
duochat search "terraform drift"
duochat export <conversation-id> --format markdown
duochat prompts list
duochat prompts use code-reviewer
duochat usage report --last 7d
duochat web
duochat doctor
```

`doctor` is important. It should verify:

- config found
- token present
- endpoint reachable
- GraphQL schema accessible
- local db writable
- log directory writable

______________________________________________________________________

## 11. Security and privacy

The app should assume transcripts may contain sensitive source code or internal discussion.

Requirements:

- secrets never logged in plaintext
- configurable transcript retention
- local-only by default
- optional encryption at rest later if justified
- redact mode for debug exports
- explicit warning before exporting full conversation bundles

______________________________________________________________________

## 12. Roadmap

## Phase 0: exploration spike

Goal: prove Duo connectivity and data model.

Deliverables:

- minimal `gql` connection
- one request/response path
- config loading
- raw GraphQL payload inspection
- stream feasibility test
- initial message and conversation models

Exit criteria:

- can send a message and save response locally

______________________________________________________________________

## Phase 1: durable terminal chat MVP

Goal: a serious local chat client, even if only terminal-based.

Deliverables:

- terminal UI with `rich`
- local SQLite + file transcript persistence
- markdown rendering
- copy-friendly transcript export
- conversation list and resume
- stream support
- structured logging
- token tracking where possible
- prompt library with active prompt selection
- retry and partial stream recovery

Exit criteria:

- user can do real work daily from terminal without losing history

______________________________________________________________________

## Phase 2: history, search, and transcript excellence

Goal: make it a knowledge workstation.

Deliverables:

- full-text search
- tags and titles
- better export formats
- code-block extraction
- issue/MR summary export templates
- token dashboards
- usage reports
- better failure recovery tools

Exit criteria:

- old conversations are genuinely reusable and easy to mine

______________________________________________________________________

## Phase 3: local web UI

Goal: improve readability and copy/paste.

Deliverables:

- FastAPI local backend
- browser conversation viewer
- live streaming display
- copy buttons for messages and code blocks
- prompt selector
- token usage dashboard

Exit criteria:

- web UI is pleasant enough to become primary for some users

______________________________________________________________________

## Phase 4: tool calling foundation

Goal: prepare for workflows beyond plain chat.

Deliverables:

- internal tool interface
- tool registry
- safe local tool invocation model
- tool execution logs
- user approval policy
- transcript capture of tool inputs/outputs
- tool call rendering in UIs

Initial tools might include:

- read file
- grep/search files
- shell command proposal
- fetch MR/issue context from GitLab
- summarize local diff

Exit criteria:

- assistant can request tools and the client can execute them safely and visibly

______________________________________________________________________

## Phase 5: agentic loops

Goal: controlled multi-step work, not chaos.

Deliverables:

- loop controller
- max steps
- max token budget
- max wall clock budget
- user approval gates
- retry/backoff policy
- structured step log
- resumable agent session
- dry-run mode

Modes:

- suggest-only
- ask-before-each-tool
- auto-run-safe-tools
- bounded autonomous loop

Exit criteria:

- the client can perform short, auditable task loops without becoming opaque

______________________________________________________________________

## Phase 6: advanced prompt and session management

Goal: make behavior tunable and repeatable.

Deliverables:

- named profiles combining prompt + model/options
- per-project defaults
- session templates
- imported/exported prompt packs
- shared prompt metadata
- prompt diffing/versioning

Exit criteria:

- users can swap working styles easily and reproduce successful setups

______________________________________________________________________

## 13. Tool calling design sketch

The client should define an internal interface like:

```python
class Tool(Protocol):
    name: str
    description: str

    def schema(self) -> dict: ...
    def invoke(self, arguments: dict) -> "ToolResult": ...
```

Key principles:

- tool calls are explicit in transcript
- tool outputs are logged
- tools have safety levels
- some tools always require approval
- timeouts are mandatory
- failures become structured events, not crashes

Suggested tool safety classes:

- read-only local
- read/write local
- network read
- network write
- shell execution

The UI should make tool activity obvious.

______________________________________________________________________

## 14. Agent loop design sketch

A future agent loop should be conservative.

Loop controller responsibilities:

- maintain step counter
- maintain budget counter
- enforce tool policy
- append intermediate results to transcript
- allow stop/resume
- allow human intervention
- summarize state after interruption

Pseudo-flow:

1. user defines task
1. system prompt and agent policy selected
1. model responds with next action or answer
1. if tool requested, client validates and maybe asks approval
1. tool executes, result appended
1. loop continues until done, max steps, or abort

This should be logged so well that a failed run is still useful.

______________________________________________________________________

## 15. Logging detail recommendations

Structured logs should include correlation IDs:

- session_id
- conversation_id
- message_id
- request_id
- stream_id
- retry_id

Every provider call should be traceable across logs.

Example event types:

- `config.loaded`
- `provider.request.started`
- `provider.request.completed`
- `provider.request.failed`
- `stream.opened`
- `stream.chunk_received`
- `stream.chunk_appended`
- `stream.completed`
- `stream.failed`
- `conversation.saved`
- `conversation.resumed`
- `usage.recorded`
- `tool.invoked`
- `tool.completed`
- `agent.step.started`
- `agent.step.completed`

This will pay off enormously when debugging streaming weirdness.

______________________________________________________________________

## 16. Error handling policy

For each user-visible action, define:

- expected failure modes
- retryability
- user message
- log severity
- persisted state changes

Examples:

### network timeout

- show partial response if any
- mark turn incomplete
- offer retry/resume

### auth failure

- do not retry blindly
- prompt for config/credential fix
- keep unsent draft if possible

### malformed provider payload

- save raw payload in debug logs
- mark turn failed
- allow resend from previous stable state

### db write failure

- write emergency transcript file fallback
- notify user persistence is degraded

That emergency fallback is worth having.

______________________________________________________________________

## 17. Testing strategy

Keep testing practical.

### Unit tests

- models
- config loading
- transcript serialization
- token accounting
- prompt management
- stream chunk assembler
- retry policy
- error mapping

### Integration tests

- GraphQL provider with recorded fixtures
- local db operations
- transcript export
- web endpoints if web UI exists

### Manual/operator testing

- long markdown responses
- interrupted streams
- copy/paste across UIs
- large conversation resume
- bad token / bad endpoint behavior

Recorded provider fixtures will be important because Duo integration may be finicky.

______________________________________________________________________

## 18. Suggested project layout

```text
duochat/
  pyproject.toml
  src/
    duochat/
      __init__.py
      cli.py
      config.py
      models/
      services/
      provider/
        gitlab_duo.py
        graphql_ops.py
      persistence/
        db.py
        transcripts.py
      prompts/
      ui/
        terminal/
        web/
        tkinter/
      logging/
      tools/
      agents/
  tests/
  docs/
```

______________________________________________________________________

## 19. Minimum lovable product

If you want the shortest path to something genuinely useful, build this:

- terminal UI
- `gql` Duo provider
- local persistence
- streaming
- markdown rendering
- copy/export
- resume
- token tracking
- prompt library
- strong logs
- doctor command

That already sounds like a product.

______________________________________________________________________

## 20. Final recommendation

Do **not** start with three UIs at once.

Start with a strong core plus a terminal UI. Build the transcript store, streaming logs, prompt management, and resume behavior first. Those are the real product. A web UI can come later and will be much easier once the core is clean.

The strongest differentiators here are not “pretty frontend.” They are:

- trustworthy transcript durability
- excellent markdown and copy workflows
- stream visibility
- token accounting
- error resilience
- prompt control
- a clean path to tools and agentic loops

That is what would make this feel better than the average chat pane.
