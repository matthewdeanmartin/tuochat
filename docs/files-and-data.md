# Files and Data

Tuochat saves conversations, extracted code files, and token usage data locally. This page
explains where everything goes and how to control it.

______________________________________________________________________

## Data directory

| Platform | Default path |
|---|---|
| Linux | `~/.local/share/tuochat/` |
| macOS | `~/Library/Application Support/tuochat/` |
| Windows | `%LOCALAPPDATA%\tuochat\` |

Override with the `TUOCHAT_DATA_DIR` environment variable.

Inside the data directory:

```text
tuochat/
|- tuochat.db
|- audit_state.json
|- conversations/
|  |- <conversation>/
|  |  |- data/
|  |  |  |- <conversation>.md
|  |  |  |- hello.py.check
|  |  |  \- ...
|  |  |- bagit.txt
|  |  \- tagmanifest-sha256.txt
\- logs/
```

______________________________________________________________________

## What gets saved

- **Conversation transcript** - every turn is saved to SQLite and written to markdown
- **Extracted code files** - fenced code blocks with file names can be written to separate files
- **Token usage** - tracked per conversation and aggregated for weekly reports
- **Startup audit state** - last-run state for the optional `pip-audit` startup check

______________________________________________________________________

## Code file safety

By default, extracted code files are saved with a `.check` extension added to the filename.

| What Duo suggested | What tuochat saves |
|---|---|
| `hello.py` | `hello.py.check` |
| `deploy.sh` | `deploy.sh.check` |
| `config.json` | `config.json.check` |

Tuochat never overwrites an existing file. Collisions are numbered.

All extracted files include a generated header unless you disable it in config.

______________________________________________________________________

## Two storage modes

### Mode A: Central data folder (default)

All conversation files go to the data directory. Extracted code files land in the conversation
subfolder, away from your project source tree.

### Mode B: Write-here mode

Enable with `/write-here-mode on` in the REPL or the **Write here** toggle in the GUI.

In this mode:

- Conversation transcripts go to `.tuochat/conversations/` inside the current working directory
- Extracted code files go directly into the current working directory
- `.tuochat/` is automatically excluded from git via `git info/exclude`

### Approval mode

In write-here mode, you can require confirmation before each file is written:

```text
/approve-writes on
```

Or use the **Approve writes** toggle in the GUI.

______________________________________________________________________

## Workspace memory files

When you use `/memory`, `/todo`, or `/compact`, tuochat stores pinned workspace notes under the
current working directory:

```text
.tuochat/memory.md
.tuochat/todo.md
.tuochat/compact.md
```

These files are injected into future conversations for that workspace, giving you local persistent
context without server-side memory.

______________________________________________________________________

## Disabling persistence

If you do not want any data written to disk:

```text
/no-write on
```

With no-write enabled:

- Nothing is saved to the database
- No transcript or code files are written
- Search and history are unavailable for the current session

______________________________________________________________________

## Conversation management

```bash
tuochat convo list
tuochat convo search QUERY
tuochat convo export ID
tuochat convo open ID
tuochat convo archive ID
tuochat convo delete ID
```

______________________________________________________________________

## BagIt tamper detection

If you have installed the optional `antitamper` extra, tuochat can create BagIt manifests for
stored conversations:

```text
/update-bagit
/check-bagit
```

Or from the command line:

```bash
tuochat archive bagit-update
tuochat archive bagit-check
```
