# Attaching Files and Context

Tuochat gives you several ways to load content into a conversation. It is important to understand
the difference between **client-side** attachments (visible in the chat) and **server-side**
context (sent silently to Duo). See [Server vs Client Context](SERVER_VS_CLIENT.md) for a
detailed explanation.

______________________________________________________________________

## Client-side attachments (visible in chat)

These commands add content to your *next* user message. The content is visible in the chat
transcript, counted in token estimates, and saved in the conversation history.

Attachment discovery respects supported ignore files in the workspace: `.gitignore`,
`.agentignore`, `.claudeignore`, and `.copilotignore`. These files use gitignore-style syntax and
apply to `/include`, folder picks, `/map`, `/code-map`, recipes, and directory-style file listings.

### Single file: `/include` or `/attach`

```text
/include src/auth.py
/attach src/auth.py
/include 3
```

The file's contents are prepended to the next message you send. Binary files and ignored files are
rejected.

### Directory listing: `/map`

```text
/map
/map "*.py" 50
```

Attaches a directory listing without sending file contents.

### Full code bundle: `/code-map`

```text
/code-map
/code-map "src/**/*.py"
```

Attaches a recursive file tree plus the full contents of every matching text file.

### Web page attachment: `/web` and `/web-preview`

```text
/web https://docs.python.org/3/library/pathlib.html
/web-preview https://example.com/blog/post
```

`/web` fetches a page and queues a markdown rendering for the next request. `/web-preview` shows a
short preview first and asks for confirmation before attaching it.

By default, tuochat uses a safety-oriented policy here: HTTPS only, public IPs only, limited
redirects, and capped response sizes. See [Configuration](configuration.md) for the `[web_attach]`
section.

### Built-in attachment bundles: `/recipes` and `/recipe`

```text
/recipes
/recipe python-overview
/recipe python-debug
```

Recipes are reusable bundles of common project files. They are useful when you want to attach a
language- or stack-specific overview without manually building a `/map` or `/code-map`.

### Detaching and re-attaching

```text
/detach src/auth.py
/detach all
/include-last
```

______________________________________________________________________

## Server-side context (silent, persistent)

These commands load content into a side channel that is sent to Duo on every subsequent turn
without appearing in the visible transcript.

### GitLab artifacts

```text
/gl issue 42
/gl mr 17
/gl file src/auth.py
```

### Arbitrary content

```text
/server-add FILE my-notes.txt
```

### Inspecting and clearing

```text
/gl current
/server-current-items
/gl remove my-notes.txt
/server-clear
```

______________________________________________________________________

## Jira issue attachments

```text
/jira
/jira status
/jira auth
```

`/jira` lets you pick a Jira project and one or more issues, then queues them as visible
attachments for your next message. It requires the optional `jira` extra plus Jira credentials in
config or environment variables.

______________________________________________________________________

## Skills

A skill is a markdown file that tunes Duo's behavior for a particular task. Skills are loaded into
the visible conversation.

```text
/skills
/skill explain
/skill 2
```

Skill files are discovered from your config directory, bundled tuochat skills, and supported
workspace skill roots.

______________________________________________________________________

## Templates

A template is a prompt with named placeholders that are filled in automatically or by you.

```text
/template
/template explain
```

Built-in templates include `explain` and `refactor`.

In non-interactive mode, supply template variables with `--var NAME=value`:

```bash
tuochat chat new --template refactor --var TARGET_FILE=src/auth.py
```

______________________________________________________________________

## Custom instructions

Custom instructions let you prepend standing guidance to every new conversation.

```text
/custom
/custom my-prefs
/custom off
/custom status
```

Custom instructions apply to the *next* new conversation, not the current one.

______________________________________________________________________

## Estimating prompt size

Before sending a large attachment, check that it fits:

```text
/token-check
```
