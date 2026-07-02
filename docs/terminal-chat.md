# Terminal Chat

The interactive terminal chat (`tuochat repl`, with `interactive` as an alias) is the primary
terminal interface. It is a full-featured REPL with slash commands, file and web attachments,
conversation history, GitLab and Jira integration, and optional sandbox prompts.

______________________________________________________________________

## Starting

```bash
tuochat repl
```

`tuochat chat` is the non-interactive automation namespace, not the REPL.

Common options:

| Flag | Purpose |
|---|---|
| `--prompt "..."` | Pre-fill the system prompt |
| `--resource-id GID` | Scope Duo to a specific GitLab project |
| `--no-stream` | Disable streaming (wait for full response) |
| `--timeout N` | Override request timeout (seconds) |
| `--quiet` | Suppress repeated instructions and hints |
| `--no-banner` | Suppress the startup logo |

Use the global `--blind` flag before the command when you want blind-friendly mode:

```bash
tuochat --blind repl
```

______________________________________________________________________

## Typing and sending messages

Type your question at the `>` prompt and press **Enter**.

For multi-line messages, use the multi-line input mode:

- **Linux/macOS:** Press `Ctrl-D` on a new line to submit
- **Windows:** Press `Ctrl-Z` then `Enter` to submit

Streaming is on by default - you see the response as it arrives. Toggle it with `/stream off`.

______________________________________________________________________

## Slash commands

Type any slash command at the prompt. A short reference is shown by `/help`. The full reference
is in [Slash Commands](slash-commands.md).

Slash commands are only available in interactive mode; they are not parsed in non-interactive
`chat` or `headless` runs.

______________________________________________________________________

## Sandboxed code execution

If Duo replies with a fenced `js` / `javascript` or `lua` block and the relevant optional sandbox
runtime is installed, tuochat can offer to run that block in a restricted interpreter.

- Execution is **never automatic**; you must approve it.
- The interpreter has no filesystem, shell, or network access.
- After the run, tuochat can queue the output as an attachment for your next message.

See [Code Interpreter](code-interpreter.md).

______________________________________________________________________

## Conversation flow

Each session starts a new conversation unless you resume an existing one. Conversations are
automatically saved to the local database after each turn.

To resume a previous conversation:

```text
/resume          # pick from a numbered list
/search QUERY    # find and resume by content
```

To start fresh mid-session without exiting:

```text
/new             # start a new conversation
/clear           # same as /new, and clears the screen unless blind mode is on
```

______________________________________________________________________

## Status and diagnostics

```text
/status          # show session info: model, resource, token count, attachments
/context         # show what is in the context (attachments, server items)
/token-check     # estimate the size of the next prompt
/verbose on      # show detailed token budget on every turn
/config          # show active configuration
/doctor          # run configuration and environment checks
/about           # show version, author, and license
/shortcuts       # show keyboard shortcuts for the current input backend
/usage           # show token usage for the current week
/observability   # show 30-day Duo latency and outcome rollups
```

______________________________________________________________________

## Models

Tuochat supports three providers:

| Model | Description |
|---|---|
| `duo` | GitLab Duo Chat (default) |
| `eliza` | Local Eliza chatbot, for testing without network access |
| `openrouter` | Any configured OpenRouter model; requires the `openrouter` extra and an API key |

Switch with:

```text
/model duo
/model eliza
/model openrouter
/openrouter-model list
/openrouter-model set anthropic/claude-sonnet-4
```

______________________________________________________________________

## Notifications

If a request takes longer than 20 seconds (configurable), the terminal bell rings. This is useful
when you step away from the keyboard. Configure in `[notifications]` in your config file.

______________________________________________________________________

## Copying output

```text
/copy            # copy the most recent assistant response to the clipboard
```

______________________________________________________________________

## Retrying

```text
/retry           # re-send the last user message
```

This is useful if a request timed out or gave a poor response.

______________________________________________________________________

## Exiting

```text
/quit
/exit
/done
Ctrl-C
```
