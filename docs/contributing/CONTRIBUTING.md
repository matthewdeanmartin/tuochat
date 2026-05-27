# Contributing to tuochat

Thank you for considering a contribution. This document covers the technical details of the
project that are relevant to contributors.

______________________________________________________________________

## Development environment

Tuochat uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone https://gitlab.com/matthewdeanmartin/tuochat.git
cd tuochat
uv sync --all-extras        # install all deps including dev/optional
```

Run from source:

```bash
uv run python -m tuochat repl
```

______________________________________________________________________

## Code style

- **Formatter:** Black + isort (enforced by pre-commit)
- **Linters:** ruff (fast linting), pylint (deeper checks), mypy (type checking)
- **Naming:** No Hungarian notation. No `_` prefix for "private". `_` is only acceptable for
  unused variables in tuple unpacking.

Run all checks:

```bash
uv run pre-commit run --all-files
```

Or via make/just:

```bash
just lint
just typecheck
```

______________________________________________________________________

## Tests

```bash
uv run pytest test/                          # unit tests
uv run pytest tests_integration/            # integration tests (require GitLab credentials)
uv run pytest test_perf/                    # performance tests
```

Integration tests require a valid `TUOCHAT_GITLAB_TOKEN` and `TUOCHAT_GITLAB_HOST` in the
environment.

______________________________________________________________________

## Project layout

```
tuochat/
├── tuochat/              # Main package
│   ├── cli/              # CLI commands, REPL, session, pickers, rendering
│   ├── gui/              # Tkinter GUI
│   ├── context/          # Attachment handling, system prompt composition
│   ├── persistence/      # SQLite store, file archiving, BagIt
│   ├── provider/         # LLM providers (Duo via GraphQL, Eliza)
│   ├── discovery/        # Skill, template, instruction file discovery
│   ├── security/         # Output masking
│   ├── skills/           # Bundled skill markdown files
│   └── templates/        # Bundled prompt templates
├── test/                 # Unit tests
├── tests_integration/    # Integration tests
├── test_perf/            # Performance tests
├── docs/                 # Documentation (MkDocs)
└── scripts/              # Utility scripts
```

______________________________________________________________________

## Architecture notes

### Non-agentic constraint

The most important architectural constraint is that the LLM has no direct shell, filesystem, or
network tools. There is no tool-call dispatch loop, no function calling, and no autonomous shell
execution. The optional sandboxed JavaScript/Lua interpreter is the narrow exception, and it still
requires explicit user approval per execution. Contributors should not add any capability that
allows the LLM to initiate actions without a deliberate user step.

### Provider abstraction

All LLM calls go through `tuochat/provider/proxy.py`. The `duo` provider uses GitLab's GraphQL
`aiAction` mutation over a WebSocket connection. The `eliza` provider is a local chatbot used for
offline testing.

### Session state

`tuochat/cli/session.py` holds all mutable state for a chat session: the active conversation,
queued attachments, server context items, settings toggles, and the current model. The REPL in
`tuochat/cli/repl.py` reads from and writes to this session object.

### Context composition

`tuochat/context/composer.py` assembles the final request payload from:

- The conversation message history
- Queued client-side attachments
- The server-side `additionalContext` list
- The `resourceId` project scope

See [Server vs Client Context](../SERVER_VS_CLIENT.md) for the conceptual explanation.

### File writing

`tuochat/persistence/archive.py` handles extracting code blocks from responses and writing them
to disk. Key invariants enforced here:

- The `.check` extension is appended to executables
- Pre-existing files are never overwritten
- Path traversal is not possible from LLM-supplied hints

______________________________________________________________________

## Adding a slash command

1. Add the command name and help text to `tuochat/help_data.py`.
1. Add the handler in the appropriate section of `tuochat/cli/repl.py` or a commands module.
1. Add a constant to `tuochat/constants.py` if the command name is referenced in multiple places.
1. Write a unit test in `test/`.

______________________________________________________________________

## Adding a provider

Implement the `tuochat/provider/proxy.py` interface. The interface expects:

- A `send(session, message) -> Iterator[str]` method that yields response chunks
- Compatibility with streaming and non-streaming modes

______________________________________________________________________

## Documentation

Docs are built with MkDocs and hosted on ReadTheDocs. The config is in `mkdocs.yml`.

```bash
uv run mkdocs serve    # local preview at http://127.0.0.1:8000
uv run mkdocs build    # build static site to site/
```

The API reference section is generated with mkdocstrings from module docstrings and public Python
objects. Update the relevant docstrings in `tuochat/` and the `docs/api-reference.md` directives
when adding new public surfaces.
