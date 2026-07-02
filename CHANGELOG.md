# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.1] - 2026-07-02
### Fixed
- Bug fixes. Surface openrouter
- Fix error handling when response from provider is abruptly stopped.

## [0.8.0] - 2026-04-28
### Added
- Openrouter integration. My 30 day trial with Gitlab is expiring.
- Jira Integration support. Optional. Needs `[jira]` extra or `[all]`

### Changed
- Markdown extraction from markdown now will use an ad hoc escaping convention.

### Fixed
- Python 3.10 and Linux compatibility improved. More tox tests, new `make docker-test` job.

## [0.7.0] - 2026-04-10
### Added
- Memory, TODO and compact. Asks bot for 3 ways to summarize and then attaches to next conversation.
- Transcript command and tab for *exactly* what is going across the wire, no matter how long it is
- Rationalize help/status/config/capabilities/env/doctor into fewer, more focused commands.
- Error log tab and improved logging- file, stdout (for GUI) and windows event log (when available and windows extras installed)
- `--blind` has a better picker interface.

### Removed
- Dropped support for 3.9. It isn't supported anymore anyhow.
- env and capabilities commands merged with other similar commands.

## [0.6.0] - 2026-04-10
### Added
- `!` prefix to run shell command and optionally attach result in context
- Surface more git and gitlab features on GUI
- Resume command more visible for accidental exit

### Fixed
- More elements are themed
- Fewer GUIDs printed to UI
- tkinter gui refactored away from one mega file.

## [0.5.0] - 2026-04-08
### Added
- Context browser to see contents of skills, agents, etc.
- "Attach recipes"
- .gitignore for context
- "self package management"- checks for updates, security issues, self upgrade.

## [0.4.0] - 2026-04-08
### Fixed
- Missing commits from 0.3.0 release

## [0.3.0] - 2026-04-05
### Added
- OAuth 2.0 Authorization Code + PKCE (S256) flow against GitLab's `/oauth/authorize` and `/oauth/token` endpoints. Stdlib-only implementation; loopback HTTP server bound to `127.0.0.1`, CSRF state check, refresh-token exchange. Non-loopback redirect URIs are refused.
- `tuochat auth` subcommands: `login` (interactive PAT-or-OAuth picker, then keyring-or-config picker), `status`, `logout`, `refresh`.
- OS keyring / secret-store support via `keyring`. Credentials can be stored in the OS keyring instead of (or in addition to) the config file. `load_config` now checks the OS secret store automatically when no plaintext token is configured.
- PAT-prefix warning (`glpat-…`) is now shown only when `token_type = "pat"` is set; it no longer fires for OAuth tokens.
- OAuth app credentials (`TUOCHAT_OAUTH_APP_ID`, `TUOCHAT_OAUTH_SECRET`, `TUOCHAT_OAUTH_REDIRECT`) can be supplied via environment variables, keyring, or interactive prompt.
- First-run wizard (`tuochat init`) now delegates credential collection to the same PAT-or-OAuth / keyring-or-config flow used by `tuochat auth login`.
- Prompt toolkit as optional cli editor.
- Update tutorial to be more interactive.
- Faster init/config workflow.
- Synonym for /include is /attach.
- Observability. Charts for how fast or slow things have been each day of last month.
- Web. User pastes in URL, it is converted to Markdown and attached to conversation. LLM does not choose URL to browse.
- Themes, including dark-mode.

### Fixed
- Classification accepts number or acronym

## [0.2.0] - 2026-04-05
### Added
- Optional Sandboxed lua/javascript in-memory tool.
- Startup audit- Pip-audit implemented but feature-flagged off because it doesn't report severity.
- Anti-source-tamper- Check if anyone causually changed the tuochat source code after install. (Not to be confused with output tamper checking)
- Better buttons on speedbar
- Started but didn't finish accessible text list picker.
- GUI has dropdown to attach more things.

### Fixed
- Accessibility. Picker now has output reduction.
- Gitlab-python is an optional install again.
- `/context` command diagram omits fewer things

## [0.1.0] - 2026-04-04
### Added
- Added an interactive terminal chat client with streaming responses, slash commands, token diagnostics, and Duo/Eliza model switching.
- Added a minimal Tkinter GUI that shares the same conversations, prompts, and slash-command workflow as the terminal client.
- Added headless CLI flows for scripted use, including `headless ask` and `headless continue`.
- Added persistent local conversation storage in SQLite with search, resume, archive, unarchive, export, open, and delete workflows.
- Added client-side attachment tools for single files, file globs, directory maps, and full code maps.
- Added server-side GitLab context tools for resources, issues, merge requests, repository files, and arbitrary server context entries.
- Added prompt templates, custom instructions, workspace-discovered skills, and bundled skills including `blind-accessibility`, `how-to-use-tuochat`, and `code-interpreter`.
- Added blind-friendly interaction features including `/help-menu`, configurable numbered pickers, progress notifications, and reduced screen-clearing behavior.
- Added classification and records-keeping features that stamp markings into transcripts and generated code files.
- Added output safety controls including secret masking, shell-code hiding, `.check` file suffixing for executable outputs, no-overwrite guarantees, and approval prompts for file writes.
- Added no-write and write-here modes to support either centralized archival storage or prompt-diff-repeat workflows in the working tree.
- Added optional BagIt-based tamper detection for conversation archives via the `antitamper` extra.
- Added optional sandboxed JavaScript/Lua code execution with explicit user approval, bounded runtime limits, captured stdout, and optional re-attachment of results.
- Added optional startup dependency self-checks via `pip-audit`, disabled by default behind the `features.startup_audit` flag and guarded by `security.audit_enabled`.
- Added local context discovery commands for files, templates, skills, and custom instructions plus weekly usage and capability reporting commands.
