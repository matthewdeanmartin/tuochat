# Slash Commands

Slash commands are available in interactive terminal and GUI sessions. Type a command at the
prompt and press Enter (or `Alt+S` in the GUI).

Type `/help` for a quick summary, or `/help-menu` for a numbered menu (useful in blind mode).

______________________________________________________________________

## Help and setup

| Command | Description |
|---|---|
| `/help [topic]` | Show help, optionally for a specific topic |
| `/help-menu` | Show accessible menu-style help with numbered sections |
| `/status` | Show session info: model, resource, token count, attachments |
| `/config [json]` | Show active configuration |
| `/doctor` | Run configuration checks |
| `/about` | Show version, author, and license text |
| `/setup` | Re-run the configuration wizard |
| `/shortcuts` | Show keyboard shortcuts for the current input backend |
| `/model [duo\|eliza]` | Switch between GitLab Duo and the local Eliza test chatbot |
| `/tutorial [lesson]` | Run the interactive tutorial |
| `/observability [text\|json]` | Show 30-day Duo latency and outcome data |

______________________________________________________________________

## Attachments and context

These commands add content to your next message or to the persistent server context. See
[Attaching Files](attaching-files.md) and [Server vs Client Context](SERVER_VS_CLIENT.md) for
the distinction.

### Client-side attachments (visible in chat)

| Command | Description |
|---|---|
| `/files` | List files that can be included |
| `/include [path\|N]` | Attach a file; content is prepended to your next message |
| `/attach [path\|N]` | Synonym for `/include` |
| `/include-last` | Re-include the last file if it has changed since last attach |
| `/map [glob] [limit]` | Attach a directory listing |
| `/code-map [glob] [limit]` | Attach a full code bundle: file tree + file contents |
| `/web URL` | Fetch a web page and queue it as a markdown attachment |
| `/web-preview URL` | Preview a web fetch before attaching it |
| `/recipes` | List built-in attachment bundles |
| `/recipe NAME` | Preview and attach a built-in bundle |
| `/detach [path\|N\|all]` | Remove a pending attachment before sending |
| `/context [mode]` | Show a summary of current context and attachments |
| `/token-check` | Estimate the size of the next prompt |
| `/timeout [seconds]` | Show or set the request timeout |

### Skills, templates, and instructions

| Command | Description |
|---|---|
| `/skills` | List available skills |
| `/skill [path\|N]` | Load a skill into the conversation |
| `/template [path\|N]` | Run a prompt template with variable substitution |
| `/custom [path\|N\|off\|status]` | Set or clear custom instructions for the next new conversation |
| `/agent-prompts` | List discovered agent prompt files such as `AGENTS.md` and `CLAUDE.md` |
| `/agent-prompt [path\|auto\|none]` | Control which discovered agent prompt file is folded into the system prompt |

______________________________________________________________________

## GitLab and Jira context

These commands load GitLab content into the **server-side** context - it is sent to Duo silently
on every turn but does not appear in the visible chat transcript.

| Command | Description |
|---|---|
| `/resource [list\|pick N\|set PATH\|clear]` | Manage the GitLab project resource |
| `/gl issue [list\|IID]` | Attach a GitLab issue to server context |
| `/gl mr [list\|IID]` | Attach a merge request to server context |
| `/gl file PATH [ref]` | Attach a repo file to server context |
| `/gl current` | Show what is in the current server context |
| `/gl remove NAME` | Remove a specific item from server context |
| `/server-add CATEGORY NAME` | Add arbitrary content to server context |
| `/server-remove NAME` | Remove a server context entry by name |
| `/server-current-items` | List all server context entries |
| `/server-query` | Query server context |
| `/server-retrieve` | Retrieve a server context item |
| `/server-clear` | Clear all server context |
| `/server-get-item-content` | Get the content of a server context item |
| `/jira` | Browse Jira projects/issues and queue selected issues as visible attachments |
| `/jira status` | Show Jira config and install state |
| `/jira auth` | Validate Jira credentials and show the authenticated user |
| `/jira clear` | Clear Jira session cache |
| `/git` | Show local git repository status |

______________________________________________________________________

## Output and display settings

| Command | Description |
|---|---|
| `/stream on\|off` | Toggle streaming |
| `/mask on\|off` | Toggle sensitive data masking in terminal output |
| `/dot-timer on\|off` | Toggle progress dots during slow requests |
| `/blind on\|off` | Toggle blind-friendly mode |
| `/no-code-mode on\|off` | Hide shell-like code blocks on screen |
| `/verbose [on\|off]` | Toggle detailed token budget diagnostics |
| `/retry` | Re-send the last user message |
| `/copy` | Copy the latest assistant response to the clipboard |

______________________________________________________________________

## Safety and persistence

| Command | Description |
|---|---|
| `/no-write on\|off` | Disable all local persistence |
| `/write-here-mode on\|off` | Write extracted files to the current directory instead of the central data folder |
| `/approve-writes on\|off` | Prompt for confirmation before write-here mode writes a file |

______________________________________________________________________

## Workspace memory helpers

| Command | Description |
|---|---|
| `/memory [text\|clear]` | Save or clear pinned workspace notes under `.tuochat\memory.md` |
| `/todo [clear]` | Generate or clear a pinned workspace todo list |
| `/compact` | Save a compact conversation summary to `.tuochat\compact.md` and start fresh |

______________________________________________________________________

## Conversation management

| Command | Description |
|---|---|
| `/new` | Start a fresh conversation |
| `/clear` | Clear chat and start fresh |
| `/title [new_title]` | Show or set the current conversation title |
| `/classify [marking]` | Set the document classification marking |
| `/archive` | Archive the current conversation |
| `/unarchive [N\|all]` | Restore archived conversations |
| `/resume [id\|N]` | Resume a saved conversation |
| `/delete [id\|N]` | Delete a conversation |
| `/search [query]` | Search conversations and optionally resume one |
| `/open` | Open the current conversation's folder |
| `/usage` | Show token usage for the current week |
| `/log` | Show a log of slash commands used this session |
| `/history` | Alias for `/log` |

______________________________________________________________________

## Archive and tamper detection

| Command | Description |
|---|---|
| `/update-bagit` | Refresh archive-change metadata for stored conversations |
| `/check-bagit` | Check whether saved archives changed since the last BagIt update |

Requires the optional `antitamper` extra. See [Security](security.md).

______________________________________________________________________

## Danger zone

| Command | Description |
|---|---|
| `/nuke` | Delete all centralized tuochat data (conversations, database, files) |
| `/quit` | Exit |
| `/exit` | Exit |
| `/done` | Alias for `/quit` |
