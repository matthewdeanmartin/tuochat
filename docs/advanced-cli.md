# Advanced CLI Reference

This page covers the non-interactive command surfaces: the preferred automation-first `chat`
namespace, the older `headless` namespace, diagnostics, conversation management, and supply-chain
maintenance commands.

______________________________________________________________________

## Global flags

These flags apply to every `tuochat` command:

| Flag | Description |
|---|---|
| `--version` | Print the version and exit |
| `--debug` | Enable debug logging |
| `--config PATH` | Use a specific config file |
| `--no-banner`, `--no-logo` | Suppress the startup logo |
| `--quiet` | Suppress repeated instructions and hints |
| `--blind` | Enable blind-friendly mode |

______________________________________________________________________

## Interactive vs non-interactive

```bash
tuochat repl                 # interactive REPL
tuochat gui                  # interactive Tk GUI
tuochat chat ...             # preferred automation namespace
tuochat headless ...         # older non-interactive namespace
```

______________________________________________________________________

## Setup and diagnostics

```bash
tuochat init [--force]
tuochat config [json]
tuochat doctor [--format text|json]
tuochat usage [--format text|json]
tuochat observability [--format text|json]
```

`doctor` includes config validation, path checks, environment variables, proxy variables, `.env`
discovery, and code-interpreter runtime readiness.

______________________________________________________________________

## Preferred automation surface: `chat`

`tuochat chat` is the main non-interactive interface. It is designed for scripts, CI, editor
integrations, and one-turn automation.

### `chat new`

Create a conversation and optionally send the first message.

```bash
tuochat chat new "What does this function do?"
tuochat chat new --file prompt.txt
tuochat chat new --stdin < prompt.txt
tuochat chat new "Explain this code" --include src/auth.py
```

| Flag | Description |
|---|---|
| `MESSAGE` | Prompt text (positional argument) |
| `--file PATH` | Read prompt from a file |
| `--stdin` | Read prompt from standard input |
| `--include PATH` | Attach a local file |
| `--web URL` | Fetch a web page and attach it |
| `--skill NAME` | Attach a discovered skill |
| `--template NAME` | Render a discovered template |
| `--var NAME=value` | Supply a template variable |
| `--output-file PATH` | Write the final response text to a file |
| `--no-stream` | Disable streaming |
| `--timeout N` | Override request timeout |
| `--model duo\|eliza\|openrouter` | Select the provider |
| `--cwd PATH` | Set the working directory for the turn and save it on the conversation |
| `--format markdown\|json` | Output format |
| `--system-prompt TEXT` | Override the system prompt |
| `--resource-id GID` | Scope Duo to a GitLab project/group |

### `chat send`

Send one message to an existing conversation and exit.

```bash
tuochat chat send --conversation latest "Follow-up question"
tuochat chat send -c abcd1234 --include diff.patch
```

Additional flags:

| Flag | Description |
|---|---|
| `--conversation ID_OR_LATEST` | Conversation ID prefix or `latest` |
| `--restore-cwd`, `--no-restore-cwd` | Re-enter the saved conversation cwd before resolving relative paths |
| `--fail-if-missing` | Exit with an error instead of creating a new conversation |

### `chat show` and `chat latest`

```bash
tuochat chat show --conversation latest
tuochat chat latest
```

These return conversation metadata and state in markdown or JSON.

______________________________________________________________________

## Legacy non-interactive surface: `headless`

Headless mode remains supported, but `tuochat chat ...` is the more feature-rich automation
surface.

### `headless ask`

```bash
tuochat headless ask "What does this function do?"
tuochat headless ask --file prompt.txt
tuochat headless ask --stdin < prompt.txt
tuochat headless ask "Explain this code" --include src/auth.py
```

| Flag | Description |
|---|---|
| `MESSAGE` | Prompt text (positional argument) |
| `--file PATH` | Read prompt from a file |
| `--stdin` | Read prompt from standard input |
| `--include PATH` | Attach a file to the prompt |
| `--web URL` | Fetch a web page and attach it |
| `--skill NAME` | Load a skill before the prompt |
| `--template NAME` | Use a prompt template |
| `--var NAME=value` | Supply a template variable |
| `--json` | Output the response as JSON |
| `--output-file PATH` | Write the response to a file |
| `--no-stream` | Wait for the full response before printing |
| `--timeout N` | Request timeout in seconds |
| `--model duo\|eliza\|openrouter` | Select the provider |
| `--system-prompt TEXT` | Override the system prompt |
| `--resource-id GID` | Scope Duo to a GitLab project |

### `headless continue`

```bash
tuochat headless continue CONVERSATION_ID "Follow-up question"
```

Accepts the same flags as `headless ask`, except `--system-prompt` and `--resource-id`.

______________________________________________________________________

## Conversation management

These commands operate on the conversation database without starting an interactive session.

```bash
tuochat convo list [--limit N] [--archived]
tuochat convo resume [ID]
tuochat convo search QUERY [--limit N] [--title TEXT] [--after ISO_DATE] [--before ISO_DATE]
tuochat convo export [ID]
tuochat convo open [ID]
tuochat convo archive [ID]
tuochat convo unarchive [ID|--all]
tuochat convo delete [ID]
```

**Aliases** for common operations:

```bash
tuochat history      # same as: tuochat convo list
tuochat resume [ID]  # same as: tuochat convo resume
tuochat search QUERY # same as: tuochat convo search
tuochat export [ID]  # same as: tuochat convo export
```

______________________________________________________________________

## Context discovery

These commands list what is available for attachments, without starting a chat session.

```bash
tuochat context files [--format text|json]
tuochat context skills [--format text|json]
tuochat context templates [--format text|json]
tuochat context custom-instructions [--format text|json]
```

______________________________________________________________________

## Archive and tamper detection

```bash
tuochat archive bagit-update
tuochat archive bagit-check [--format text|json]
```

Requires the optional `antitamper` extra.

______________________________________________________________________

## Supply-chain maintenance

The `selfcheck` command passes through to tuochat's self-management CLI:

```bash
tuochat selfcheck check
tuochat selfcheck status
tuochat selfcheck audit
tuochat selfcheck self-check
tuochat selfcheck upgrade --dry-run
tuochat selfcheck snooze tuochat==0.7.1 --days 14
tuochat selfcheck clear-cache
```

From a user standpoint:

- `check` refreshes update information for tuochat and its direct dependencies
- `status` shows the cached state
- `audit` runs a vulnerability audit when a supported tool is available
- `self-check` verifies installed package integrity and tuochat file tampering
- `upgrade` performs or previews a self-upgrade using the detected install method
- `snooze` suppresses a specific upgrade suggestion temporarily

______________________________________________________________________

## Scripting examples

**Ask a question and capture the response:**

```bash
tuochat chat new "Summarize the changes in this diff" \
  --include changes.diff \
  --output-file summary.md
```

**Use a template in a CI pipeline:**

```bash
tuochat chat new \
  --template explain \
  --var ATTACHED_CODE=src/new_feature.py \
  --format json > explanation.json
```

**Search and get the latest conversation ID:**

```bash
tuochat convo search "refactor auth" --limit 1
```

**Continue the most recent conversation:**

```bash
CONV_ID=$(tuochat convo list --limit 1 --format json | jq -r '.[0].id')
tuochat chat send -c "$CONV_ID" "What else should I consider?"
```
