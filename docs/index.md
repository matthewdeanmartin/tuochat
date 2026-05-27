# tuochat

Tuochat is a GitLab Duo Chat client for developers who want AI assistance in the terminal (or a
minimal GUI) with an explicit emphasis on safety, accessibility, and records keeping.

It sits between a browser chat window and a fully agentic coding tool: you get a rich workflow -
interactive `repl`, automation-friendly `chat` commands, file and web attachments, conversation
history, GitLab and Jira context, prompt templates, and search - but the LLM cannot execute code,
overwrite files, or take any action without a deliberate human step.

______________________________________________________________________

## Core features

- **Non-agentic** - no tools, no loops, no file editing by the LLM
- **Interactive REPL and automation CLI** - `tuochat repl` for live work, `tuochat chat ...` for one-shot runs
- **Streaming responses** via WebSocket
- **Persistent conversation history** in local SQLite, fully searchable
- **File and web attachments** - single files, directory maps, code bundles, and safe web-page fetch/attach
- **GitLab integration** - attach issues, MRs, and repo files as silent context
- **Jira integration** - browse projects and queue issue context for the next message
- **Prompt templates** with auto-filled variables
- **Optional sandboxed code interpreter** for JavaScript and Lua, with explicit approval
- **Classification and records keeping** for regulated environments
- **Blind-accessible** terminal UI with configurable pickers and menu-style help
- **Observability** - local 30-day latency and outcome rollups for Duo responses
- **Supply-chain safety tools** - startup `pip-audit`, installed-package integrity checks, and self-upgrade helpers
- **Headless and legacy non-interactive mode** for scripting and CI pipelines

______________________________________________________________________

## Quick links

| I want to... | Go to... |
|---|---|
| Install tuochat | [Installation](installation.md) |
| Get started in 5 minutes | [Quick Start](quickstart.md) |
| Configure it | [Configuration](configuration.md) |
| Use the terminal chat | [Terminal Chat](terminal-chat.md) |
| Use the sandboxed code interpreter | [Code Interpreter](code-interpreter.md) |
| Use the GUI | [GUI](gui.md) |
| See all slash commands | [Slash Commands](slash-commands.md) |
| Attach files and context | [Attaching Files](attaching-files.md) |
| Understand where files go | [Files and Data](files-and-data.md) |
| Search past conversations | [Searching Conversations](search.md) |
| Use it in scripts or CI | [Advanced CLI](advanced-cli.md) |
| Browse the Python API | [API Reference](api-reference.md) |
| Set up classification markings | [Classification](classification.md) |
| Use tuochat without sight | [Accessibility](accessibility.md) |
| Understand the security model | [Security](security.md) |
| Review dependency provenance | [Dependency Provenance](dependency-provenance.md) |
| Contribute code | [Contributing](contributing/CONTRIBUTING.md) |
