# Security

This page describes tuochat's security model in enough detail for a security team to evaluate it.
The central goal is to provide a useful AI coding assistant while keeping the LLM firmly on the
advisory side of the human-machine boundary.

______________________________________________________________________

## Design principle: non-agentic by construction

Tuochat deliberately does not implement agentic shell/filesystem/network tooling. The LLM:

- Cannot execute shell commands, local programs, or host filesystem actions
- Cannot read files unless the user explicitly attaches them
- Cannot write, edit, or delete files directly
- Cannot choose URLs to fetch on its own
- Cannot loop, retry, or chain calls on its own

The one narrow exception is the optional sandboxed code interpreter documented below. Even there,
execution is limited to JavaScript or Lua inside a restricted runtime and still requires explicit
user approval per run.

______________________________________________________________________

## File writing controls

### The `.check` extension

When Duo's response contains fenced code blocks, tuochat can extract them to files. To prevent
accidental execution, executable file types are saved with a `.check` suffix appended.

### No-overwrite guarantee

Tuochat refuses to overwrite any pre-existing file. Collisions are resolved by incrementing a
counter.

### Approval mode

With `/approve-writes on`, tuochat prompts the user before writing each extracted file in
write-here mode.

### Path traversal prevention

Tuochat ignores path hints that would place a file outside the target directory.

______________________________________________________________________

## Sandboxed code interpreter

Tuochat can optionally execute assistant-generated `js` / `javascript` or `lua` blocks in a
restricted interpreter after the response is shown.

Security properties:

- **Opt-in install**
- **Per-run approval**
- **Language-limited**
- **No host access**
- **Bounded execution**
- **Visible output**

See [Code Interpreter](code-interpreter.md).

______________________________________________________________________

## Output masking

### Secret masking (`mask_output`, default on)

Before printing a response to the terminal, tuochat scans it for patterns that look like secrets
and replaces matches with `***REDACTED***`.

Your configured GitLab token is always included in the redaction list regardless of pattern
matching. Masking applies to terminal output only - the full text is still saved locally unless
`/no-write` is on.

### Code block hiding (`/no-code-mode`)

When `/no-code-mode on` is active, shell-like fenced code blocks are replaced on screen with a
placeholder.

______________________________________________________________________

## Input warnings

### High-entropy string detection

Before sending a prompt, tuochat scans for strings with high Shannon entropy - a statistical signal
for tokens, keys, or passwords that may have been accidentally pasted into the chat.

### Warn words

The `[warn_words]` config section lets you define phrases that should never leave your machine.

______________________________________________________________________

## Token and credential handling

Tuochat supports three credential back-ends, in order of preference:

1. **OS keyring**
1. **Config file**
1. **Environment variable**

Additional properties:

- Credentials are never hardcoded or logged
- `tuochat config` and `/config` redact token values
- PAT-prefix warnings apply only to PAT mode
- OAuth uses Authorization Code + PKCE (S256) on loopback `127.0.0.1`

______________________________________________________________________

## Data at rest

All conversation data is stored locally. The normal outbound connection is to your configured
GitLab instance.

- **Database**: SQLite3 at `data_dir/tuochat.db`
- **Transcripts**: markdown files in `data_dir/conversations/`
- **No-write mode**: `/no-write on` disables persistence for a session

______________________________________________________________________

## Tamper detection for saved archives (BagIt)

With the optional `antitamper` extra installed, tuochat can create BagIt manifests for stored
conversation archives.

```bash
tuochat archive bagit-update
tuochat archive bagit-check
```

In tuochat, BagIt is mainly a local human-edit signal: if the archive stops validating, somebody
changed the transcript or extracted files after tuochat wrote them.

______________________________________________________________________

## Supply chain and dependency policy

Tuochat keeps the runtime intentionally small, but packaged installs are not literally stdlib-only.
Optional extras such as `gitlab`, `jira`, `web`, `antitamper`, `selfcheck`, and
`code-interpreters` are all opt-in.

### Startup dependency self-check

The startup audit is available only when:

1. The optional `selfcheck` extra is installed
1. `[features].startup_audit = true`
1. `[security].audit_enabled = true`

Behavior:

- Runs at most once per local calendar day
- Stores summary state in `audit_state.json`
- Continues when `pip-audit` is unavailable or its output cannot be parsed
- Prompts only when `pip-audit` reports High or Critical findings

### On-demand supply-chain maintenance: `tuochat selfcheck`

Tuochat also ships an explicit maintenance surface for users who want to check update freshness,
run vulnerability scans on demand, or verify the installed package itself:

```bash
tuochat selfcheck check
tuochat selfcheck status
tuochat selfcheck audit
tuochat selfcheck self-check
tuochat selfcheck upgrade --dry-run
tuochat selfcheck snooze tuochat==0.7.1 --days 14
```

What these do:

- `check` refreshes update information for tuochat and its direct runtime dependencies
- `status` shows cached state without doing network work
- `audit` runs a vulnerability audit when a supported tool is available
- `self-check` verifies installed distribution integrity and checks tuochat package files for tampering
- `upgrade` performs or previews a self-upgrade using the detected install method
- `snooze` temporarily hides a specific upgrade recommendation

The integrity check is separate from BagIt archive checking: BagIt protects saved conversation
artifacts, while `self-check` focuses on the installed tuochat package itself.

See also [Dependency Provenance](dependency-provenance.md) for the runtime dependency inventory and
maintainer signal.

______________________________________________________________________

## Platform origin tracking

Every request to the GitLab Duo API includes a `platform_origin` field (default: `"tuochat"`).
This is visible in GitLab backend logs and allows organizations to audit AI usage by client.

HTTP requests that tuochat sends directly to GitLab also use a configurable `User-Agent`
header via `gitlab.user_agent`. The default value is the running tuochat version.

______________________________________________________________________

## What tuochat does NOT protect against

- A user who intentionally shares sensitive data with Duo
- GitLab Duo's own data handling policies
- Prompt injection in content fetched via `/gl file`, `/include`, or `/web`
- File permissions on the local database and transcript files
- Network-level interception between tuochat and your GitLab instance
