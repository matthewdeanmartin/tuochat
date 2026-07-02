# Quick Start

This guide gets you from a fresh install to your first conversation in about five minutes.

______________________________________________________________________

## Step 1 - Install

```bash
uv tool install tuochat
```

See [Installation](installation.md) for other methods.

______________________________________________________________________

## Step 2 - Configure

Run the interactive setup wizard:

```bash
tuochat init
```

The wizard asks for:

- **GitLab host** - e.g. `https://gitlab.com` or your self-managed instance URL
- **Credential type** - Personal Access Token (PAT) or OAuth
- **Storage** - OS keyring (recommended) or config file

#### PAT

Create a PAT at **User / Preferences / Access Tokens** with the `ai_features` scope.

#### OAuth

Create an application at **User / Preferences / Applications / Add New** with redirect URI
`http://127.0.0.1:8765/callback`. Supply the app ID and secret when prompted (or via
`TUOCHAT_OAUTH_APP_ID` / `TUOCHAT_OAUTH_SECRET` env vars before running the wizard).

#### Changing credentials later

```bash
tuochat auth login    # re-run the credential picker
tuochat auth status   # show what is currently configured
```

If you prefer to skip the wizard, create the config file manually. The location depends on your
platform:

| Platform | Path |
|---|---|
| Linux | `~/.config/tuochat/config.toml` |
| macOS | `~/Library/Application Support/tuochat/config.toml` |
| Windows | `%APPDATA%\tuochat\config.toml` |

Minimal config (PAT path):

```toml
[gitlab]
host = "https://gitlab.com"
token = "glpat-xxxxxxxxxxxxxxxxxxxx"
token_type = "pat"
```

To use OpenRouter instead, install `tuochat[openrouter]`, run `tuochat openrouter login`, and set a
model:

```bash
tuochat openrouter login
```

```toml
[openrouter]
model = "openai/gpt-4.1-mini"
```

Then choose it with `/model openrouter`, `--model openrouter`, or the GUI Model menu.

______________________________________________________________________

## Step 3 - Start chatting

```bash
tuochat repl
```

On your very first run, tuochat offers an optional interactive tutorial. Type your question at the
`>` prompt and press **Enter** to send.

To submit a **multi-line message**, use `Ctrl-D` (Linux/macOS) or `Ctrl-Z` then `Enter` (Windows)
instead of Enter alone.

If you want a one-shot non-interactive run instead of the REPL, use:

```bash
tuochat chat new "Explain this repository"
```

______________________________________________________________________

## Step 4 - Exit

Type `/quit` or `/exit` at the prompt, or press `Ctrl-C`.

______________________________________________________________________

## What just happened?

- Your conversation was saved to a local SQLite database.
- A markdown transcript was written to your data folder (see [Files and Data](files-and-data.md)).
- Any extracted named code files were written as `.check` files for your review.

______________________________________________________________________

## Next steps

| Topic | Guide |
|---|---|
| Full configuration reference | [Configuration](configuration.md) |
| Interactive terminal usage | [Terminal Chat](terminal-chat.md) |
| Graphical interface | [GUI](gui.md) |
| Non-interactive / scripting | [Advanced CLI](advanced-cli.md) |
| Slash commands reference | [Slash Commands](slash-commands.md) |
