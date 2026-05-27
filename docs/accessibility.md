# Accessibility

Tuochat is designed to be usable without sight. This page explains what is available today and
how to configure it.

______________________________________________________________________

## Blind / screen reader mode

Enable blind-friendly mode with any of:

- global `--blind` flag: `tuochat --blind repl`
- Config: `chat.blind = true`
- Slash command mid-session: `/blind on`

In blind mode, tuochat:

- Suppresses the startup logo
- Suppresses `clear-screen` operations that would scroll past content
- Uses linear numbered pickers instead of cursor-driven menus
- Makes `/help` fall through to the numbered help menu automatically
- Presents prompts as plain text with numbered options and simple verbs such as `pick`, `list`, and `back`

______________________________________________________________________

## Blind prompt toolkit behavior

Tuochat's blind-first picker system is designed for linear screen-reader use rather than cursor
navigation:

- **Small lists** are read out in full immediately.
- **Medium lists** announce the count and let you type a number, an exact name, or ask for `list`.
- **Large lists** encourage filtering first, then paging through matches.
- **Common commands** include `list`, `next`, `prev`, `pick 3`, `back`, `status`, and `help`.
- **Tree and file pickers** announce the current path and each child item so you can move through a
  directory or project structure without relying on arrow keys.

This same linear style is used for file picking, template/skill selection, conversation resume
lists, and other menu-driven workflows.

______________________________________________________________________

## Numbered selection throughout

Every list-based interaction supports picking by number. This works in both normal and blind mode,
but is especially important for screen reader users who navigate by announced text.

```text
/resume
  1. 2024-06-01 - Refactor auth module
  2. 2024-05-30 - Explain database schema
  3. 2024-05-28 - Write unit tests
Pick: 2
```

Commands that use numbered selection include `/resume`, `/search`, `/delete`, `/unarchive`,
`/model`, `/skill`, `/template`, `/custom`, `/files`, `/gl issue list`, and `/gl mr list`.

### Picker modes

The picker system is configurable for users who want an even more predictable interaction style:

```toml
[picker]
mode = "auto"      # or "paged" or "ask_one"
page_size = 10
```

- `auto` - show short lists all at once and page large ones
- `paged` - always show numbered pages
- `ask_one` - present one item at a time

If blind mode is enabled, `auto` becomes `paged` automatically.

______________________________________________________________________

## Help menu

`/help-menu` presents the help system as a numbered list of sections rather than a table:

```text
Help sections:
  1. Session and Setup
  2. Attachments and Context
  3. Conversation History
  4. Output and Safety
  5. Exit and Cleanup
Enter section number (or press Enter to exit):
```

This is announced clearly by most screen readers without requiring the user to navigate a table.

______________________________________________________________________

## No-clear-screen

Normal mode clears the terminal screen in some situations. Blind mode suppresses all clear
operations so content is never scrolled out of the screen reader's buffer.

______________________________________________________________________

## Notification bell

For long-running requests, tuochat rings the terminal bell rather than relying on a visual
spinner. Configure the threshold:

```toml
[notifications]
long_request_bell_enabled = true
long_request_bell_seconds = 20
```

______________________________________________________________________

## Progress dots

An alternative to the notification bell is the progress dot timer, which prints a `.` every
second while waiting:

```text
/dot-timer on
```

Or in config:

```toml
[chat]
dot_timer = true
```

______________________________________________________________________

## Multiline input

Tuochat does not require readline or any terminal library for multiline input. Use:

- **Linux/macOS:** `Ctrl-D` on a blank line to submit
- **Windows:** `Ctrl-Z` then `Enter` to submit

______________________________________________________________________

## Verbose context diagnostics

`/verbose on` causes tuochat to print a token budget summary before each response:

```text
Context: 4 200 / 200 000 tokens used (2%)
```

This lets you track prompt size by listening to output rather than reading a visual meter.

______________________________________________________________________

## Accessibility skill

Tuochat ships with a bundled skill that instructs Duo to assist blind users with tuochat itself:

```text
/skill blind-accessibility
```

Load it at the start of a session to have Duo produce output suited to being read aloud.

______________________________________________________________________

## GUI accessibility

The Tkinter GUI (`tuochat gui`) uses standard Tkinter widgets plus a tabbed notebook for chat,
files, context, search, help, usage, observability, Git, GitLab, Jira, transcript, and errors.
Slash commands such as `/help`, `/usage`, `/observability`, `/search`, `/context`, and `/attach`
route focus to those tabs automatically.

Screen readers that support Tkinter (for example NVDA on Windows) can read the transcript, input
box, and tab content. Keyboard navigation uses `Alt`-key shortcuts:

| Shortcut | Action |
|---|---|
| `Alt+S` | Send |
| `Alt+H` | Help |
| `Alt+T` | Status |
| `Alt+Q` | Quit |

______________________________________________________________________

## Planned improvements

An HTML interface is still on the roadmap. Real-world blind users have reported that browser-based
interfaces are often more accessible than terminal emulators for screen reader workflows.
