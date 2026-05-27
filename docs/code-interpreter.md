# Code Interpreter

Tuochat can optionally execute assistant-generated JavaScript or Lua in a tightly limited sandbox.
This is not automatic agentic tool use: the user must explicitly approve each execution, and the
code runs without filesystem, shell, timer, or network access.

______________________________________________________________________

## Where it works today

The sandboxed interpreter is integrated into interactive sessions: the terminal REPL
(`tuochat repl`) and the GUI when the **Code Int** toggle is on. After a response is displayed,
tuochat looks for the first fenced code block tagged `js`, `javascript`, or `lua`.

If a matching block is found, tuochat prompts:

```text
Execute javascript code in sandbox? [y/N]
Attach output to conversation? [Y/n]
```

The second prompt queues the sandbox output as an attachment for your next message.

______________________________________________________________________

## Installation

Install the bundled interpreter extra:

```bash
pip install "tuochat[code-interpreters]"
```

Or install only the runtime you want:

```bash
pip install "tuochat[js-miniracer]"   # JavaScript via mini-racer
pip install "tuochat[js-dukpy]"       # JavaScript via dukpy
pip install "tuochat[lua]"            # Lua via lupa
```

If no compatible runtime is installed, tuochat still works normally; the sandbox run will just
fail with an import error instead of executing.

______________________________________________________________________

## Using it with the bundled skill

Tuochat ships with a bundled `code-interpreter` skill:

```text
/skill code-interpreter
```

That skill tells Duo to respond with short sandbox-friendly `js` or `lua` code blocks and embeds
the current sandbox rules into the prompt.

______________________________________________________________________

## Sandbox rules

### Supported languages

- `js` / `javascript`
- `lua`

### Hard limits

- Timeout: **500 ms**
- Memory limit: **64 MB**
- Max code size: **64 KB**
- Max stdout capture: **200 lines / 64 KB**
- Max emitted result size: **256 KB JSON**

### Environment restrictions

- No filesystem access
- No shell access
- No network access
- No imports or external modules
- Structured JSON-like input/output only

The code must call `emit(value)` exactly once to produce a final result. Intermediate logging is
captured through `console.log(...)` in JavaScript and `print(...)` in Lua.

______________________________________________________________________

## What this is for

The sandbox is useful for small computations, data transformations, and demonstrations where
executing a tiny program is clearer than asking the model to reason step by step in prose.

It is not a general-purpose Python execution environment, and it does not let the assistant access
your workstation, repository, or network.
