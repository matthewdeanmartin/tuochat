# GUI

Tuochat includes a minimal graphical interface built with Tkinter. It provides the same chat and
session behavior as the terminal, in a windowed application that may be more comfortable for some
workflows.

______________________________________________________________________

## Starting

```bash
tuochat gui
```

Options are the same as `tuochat repl`:

```bash
tuochat gui --prompt "Explain this function" --resource-id gid://gitlab/Project/42
```

______________________________________________________________________

## Requirements

Tkinter is included in most Python distributions. If it is missing on Linux:

```bash
# Debian/Ubuntu
sudo apt install python3-tk

# Fedora/RHEL
sudo dnf install python3-tkinter
```

______________________________________________________________________

## Window layout

- **Tabbed notebook**: Chat, Files, Effective Context, Context Browser, Conversations, Archive,
  Search, Help, Usage, Observability, Git, GitLab, Jira, Transcript, and Errors.
- **Transcript area**: scrolling view of the conversation.
- **Input box**: multiline text entry.
- **Action bar**: send, attach files/folders/skills/custom instructions/templates, re-include a
  changed file, detach all, model toggle, safety toggles, Memory, Compact, Todo, Help, Status, and Quit.
- **Session toggles**: Stream, Mask, Verbose, Approve writes, Write here, No Writes, and Code Int.

______________________________________________________________________

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Alt+S` | Send message |
| `Alt+H` | Show help |
| `Alt+T` | Show session status |
| `Alt+Q` | Quit |

______________________________________________________________________

## Slash commands in the GUI

All slash commands available in the terminal also work in the GUI input box. Type them in the
input area and press `Alt+S` to send.

The GUI also routes several commands directly to the matching tab:

- `/help`, `/help-menu` -> Help
- `/usage` -> Usage
- `/observability` -> Observability
- `/search` -> Search
- `/context` -> Effective Context
- `/attach`, `/include`, `/include-last`, `/detach` -> Files

______________________________________________________________________

## Direct GUI controls

The GUI adds direct controls that are easier to discover than slash commands:

- **Files / Folder**: queue local files for the next request
- **Skills / Initial Instr / Template**: attach a skill, custom instructions, or a template
- **Write here / Approve writes / No Writes**: toggle write mode and persistence
- **Code Int**: enable or disable sandbox/code-interpreter prompts for the current session
- **Memory / Compact / Todo**: manage pinned workspace context without typing slash commands
- **Git / GitLab / Jira tabs**: browse and attach project context visually

______________________________________________________________________

## Conversations

The GUI shares the same conversation database as the terminal. Conversations started in the GUI
can be resumed in the terminal and vice versa. Use the Conversations, Archive, and Search tabs, or
use slash commands like `/resume` and `/search`.

______________________________________________________________________

## Themes and fonts

The GUI reads its appearance from the `[gui]` config section:

```toml
[gui]
font_family = ""
font_size = 0
theme = "system"
```

Built-in themes include `system`, `light`, `dark`, `green_terminal`, `amber_terminal`,
`solarized`, and `hot_dog_stand`.

______________________________________________________________________

## Accessibility

The GUI is usable with screen readers that support Tkinter text widgets, but the blind-first
interaction model is still strongest in the terminal REPL. See [Accessibility](accessibility.md)
for the linear picker behavior and blind mode details.
