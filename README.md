# tuochat

A GitLab Duo Chat client for programmers. This is Claude Code(TM) for the overly cautious, for people who are rightfully
afraid of what an LLM will do who want a feature set somewhere between a text box in a browser and Claude Code(TM) or
OpenCode.

This client is aggressively conservative about security.

- Minimally agentic. This means no tools in the usual sense, no file editing.
- The user is the "tool" and always will be. Even with non-agentic chat, LLM can ask the user to `rm -rf /` the disks or
  ask the user to "run this script and give me the results". Agentic is when the LLM can do it quietly with no human in
  the loop.
  - Installable extra of in memory execution of Lua/Javascript. User approves execution and approves attaching
    results.
- No files written in executable form. Executables are written with .check extension, eg. `hello.py.check`
- LLM does not directly execute any tools, not shell and not filesystem operations. So how did `hello.py.check` get on
  the file
  system? When enabled, fenced code is written to file system either in a quarantine folder or in current folder, but
  without the ability to overwrite a file.
- Warnings on sending high entropy strings, secrets, or words signaling classification.
- File browsing? On client side, it is easy for the user to send the directory or a rollup of files. LLM does not choose
  what files to read or browse.
- Web browsing? With `[web]` extra, there is client side URL fetch and transformation into Markdown. LLM does not choose URL.

Some features inspired by US federal, state and local government and military. That this tool exists, on its own doesn't
mean any organization approves or endorses it. If you aren't authorized to pip install from pypi or git clone arbitrary
repos on Gitlab (for example if you are an IT worker), you probably can't use this without getting permission. Follow
your organizations policies regarding the open source usage.

It is aggressively eager to do classification and records keeping.

- Asks for classification.
- Injects record keeping metadata on files.
- Includes provenance metadata.
- Basic classification and record keeping features, like headers on files.

It is aggressively accessible.

The CLI interface is accessible enough for the blind. HTML on roadmap because many real blind people report HTML is more
accessible than terminal.

Work flows

- Just ask and just read. Ordinary chat workflow. Conversations saved to folder and searchable in sqlite.
- Copy to window, copy from window. Same thing we've been doing since ChatGPT got famous.
- Write and diff workflow. For example, files are written to current folder, with `.check` extensions. The tool makes
  best guess at where to put the file so it lands next to the file that a LLM would have edited. You then use a
  diff tool to apply the LLMs suggested changes. LLM never edits code or writes an actually executable file to file
  system.
- Batch-attach-and-chat. map and code map slash commands to attach large chunks of code without attaching them one by
  one.

Other safety features

- Stdlib-only option so if your organization allows the use of python, you can run without other libraries.
- Tkinter support available without extra dependencies
- Web support with only libraries for html-to-markdown processing.
- Optional BagIt-based archive change detection so it is obvious when saved AI output was later edited by a human.
- selfcheck and self package update utility to check integrity and safety of installed components

See below for more design goals.

## Installation

You will need python version>=3.10.

Three ways to install from pypi or your organization's package repo proxy. Pick one!

```bash
uv tool install tuochat  # install development tools
pipx install tuochat # isolated global install.
```

If you can't get uv or pipx working, you can use raw pip, but it will install to your global python.

```bash
pip install tuochat # install into system or currently active python venv
```

### Advanced Install: You can clone the code.

```bash
# or clone repo and run without installing anything, not even the venv.
git clone https://gitlab.com/matthewdeanmartin/tuochat.git
python -m tuochat repl
```

### Very Advanced Install: You can clone the code and build a docker images

The safest way to try this out if you are evaluating it is to run in a docker container, which given the design and
capabilities is overkill, but if that is your organization's policy, see the Dockerfile and the scripts/ folder.

I won't be supporting a hosted docker image you can pull because I can't keep up with the rebuild schedule. Better to
pull the base image yourself.

### Advance Install: Fork

If your organization doesn't like the idea of using a opensource tool, fork it to your private namespace, edit it to
your standards, publish it to gitlab's python package repo or other pypi compatible private repo.

## Setup

Run the interactive setup wizard, which covers both configuration and credentials:

```bash
tuochat init   # first-time setup
# or
tuochat repl   # runs init and an optional tutorial on first run
```

The wizard prompts you to choose between a **Personal Access Token (PAT)** and **OAuth**,
then asks whether to store the credential in the OS keyring or in the config file.

### PAT

Create a PAT at **User / Preferences / Access Tokens** with the `ai_features` scope. Paste it
when the wizard asks.

### OAuth

Create an application at **User / Preferences / Applications / Add New**. Set the redirect URI
to `http://127.0.0.1:8765/callback` (or whatever port you like — just match it in the env var
below). Note the application ID and secret.

Supply OAuth app credentials via environment variables before running the wizard:

```bash
export TUOCHAT_OAUTH_APP_ID=<app-id>
export TUOCHAT_OAUTH_SECRET=<app-secret>
export TUOCHAT_OAUTH_REDIRECT=http://127.0.0.1:8765/callback  # optional, this is the default
```

Or omit them and the wizard will prompt for them interactively.

### Auth management commands

```bash
tuochat auth login    # re-run the PAT-or-OAuth / keyring-or-config picker
tuochat auth status   # show what credentials are currently configured
tuochat auth logout   # remove stored credentials
tuochat auth refresh  # exchange a refresh token for a new access token
```

### OpenRouter alternative

OpenRouter works in the terminal, headless CLI, and GUI without GitLab credentials. Install its
optional dependency, store a key, and configure at least one model:

```bash
uv tool install "tuochat[openrouter]"
tuochat openrouter login
```

```toml
[openrouter]
model = "openai/gpt-4.1-mini"
```

Select it with `/model openrouter`, `--model openrouter`, or the GUI Model menu.

### Environment variable reference

All settings can be supplied via environment instead of the config file:

```bash
TUOCHAT_GITLAB_HOST=https://gitlab.com
TUOCHAT_GITLAB_TOKEN=<glpat-…>          # PAT path

TUOCHAT_OAUTH_APP_ID=<app-id>           # OAuth path
TUOCHAT_OAUTH_SECRET=<app-secret>
TUOCHAT_OAUTH_REDIRECT=http://127.0.0.1:8765/callback
```

## Usage

Start the interactive chat:

```bash
tuochat chat
```

Start the minimal Tkinter GUI:

```bash
tuochat gui
```

To support multiline editing without additional 3rd party libraries **use `Ctrl-D` (Linux/macOS) or `Ctrl-Z`
then `Enter` (Windows).** instead of just the enter key.

The GUI keeps the same chat/session behavior but replaces terminal I/O with a scrolling transcript and multiline input
box. The first pass includes `Alt+S` to send, `Alt+H` for help, `Alt+T` for status, and `Alt+Q` to quit.

### Bundled templates

Tuochat ships with bundled `/template` prompts:

- `explain`
- `refactor`

The `ATTACHED_CODE` token reads a file from the current working directory. In the terminal, `/template` asks for a file
path. In the GUI, it opens a file picker. Safe auto-filled tokens include `DATE`, `TIME`, `DATE_TIME`, `USER_NAME`,
`USER_OS`, `WORKING_DIRECTORY`, `DIRECTORY_LISTING`, `GIT_REPO_STATUS`, `GIT_REPO_NAME`, and `GIT_REPO_ROOT`.

### Stopping the client

To exit the chat, `/quit`, or `/exit`.

## Features

- **Zero third-party runtime dependencies** (on Python 3.11+).
- **Streaming support**: See responses as they are generated.
- **Persistent history**: Conversations are saved locally in SQLite.
- **Fast and lightweight**: Minimal overhead, built with standard libraries.

## Design Goals

- Core features all accessible in a terminal.
- Not agentic. Doesn't have loops, tools or ability to overwrite files.
- Excellent chat ergonomics
- Don't lose anything

## Permissioning System

### Chat

A non agentic LLM has always been able to ask the user to copy paste test out of the window and run it.

### Undirected file writing to a data folder

The data folder is just an empty folder.

If an LLM's text is written to a folder, then the LLM can encourage the user to run the code. Tuochat will look for any
markdown fences, infer a file type and split them out from the main markdown file. This is different from regular tool
usage in that the LLM can only hint at a file name, can't control the path and can't control the file extension.

To defend against mischief, the files are either .md/.txt or affixed with .check, e.g. hello.py.check. So now it takes a
human decision to run a file, not an accidental click. This safety behavior is on by default and can be changed with the
`chat.safety_check_extension_for_executable_files` config setting.

### File writing to the CWD (current directory)

The goal here is to allow users to do prompt-diff-repeat workflows. You ask the LLM to suggest edits to a file, the LLM
replies with a markdown fenced file contents, for example

hello.py
`print("hello")`

This is then written to the CDW so the file is next to the original. The user can now do prompt-diff-repeat.

hello.py.check
`print("hello")`

The app will refuse to overwrite pre-existing files and number name clashes, e.g. hello.py.check1, hello.py.check2

This is as close as you agentic as you can get before the LLM takes the human out of the loop.

## Legal

Tuochat is about 99% written by ChatGPT, Codex, Copilot, Gemini, Claude Code. As such, the copyrightability of the code
is indeterimined and if the law says it is not copyrightable, then the code is Public Domain. Anything that is not
public domain is MIT.

GitLab is a trademark of GitLab.

ChatGPT is trademark of OpenAI.

Claud Code is trademark of Anthropic.

Tuochat is not endorsed or related to GitLab, OpenAI, Anthropic or any person or organization.
