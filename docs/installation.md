# Installation

Tuochat requires Python 3.9 or later. The base package works without `python-gitlab`; install the
optional extras when you want Jira support, richer web rendering, tamper-detection tooling,
startup self-checks, or sandbox runtimes.

______________________________________________________________________

## Recommended: uv

[uv](https://docs.astral.sh/uv/) is the recommended way to install tuochat. It handles isolated
environments automatically.

```bash
uv tool install tuochat
```

This installs tuochat as a globally available tool in an isolated environment.

______________________________________________________________________

## pip / pipx

```bash
pip install tuochat          # into the current environment or system Python
pipx install tuochat         # isolated global install via pipx
```

______________________________________________________________________

## From source

```bash
git clone https://gitlab.com/matthewdeanmartin/tuochat.git
cd tuochat
python -m tuochat repl
```

No virtual environment is required to run from source if you are on Python 3.11+.

______________________________________________________________________

## Optional extras

Some features require optional dependencies. Install them with the appropriate extra:

| Extra | What it enables | Install command |
|---|---|---|
| `gitlab` | GitLab project discovery and `/gl` artifact commands via `python-gitlab` | `pip install "tuochat[gitlab]"` |
| `jira` | Jira project and issue browsing via `/jira` | `pip install "tuochat[jira]"` |
| `web` | Richer `/web` and `/web-preview` rendering engines | `pip install "tuochat[web]"` |
| `antitamper` | BagIt-based archive change diagnostics | `pip install "tuochat[antitamper]"` |
| `fast` | Faster JSON/TOML parsing (`orjson`, `rtoml`) | `pip install "tuochat[fast]"` |
| `selfcheck` | `pip-audit` startup security scanning support | `pip install "tuochat[selfcheck]"` |
| `code-interpreters` | Sandboxed JavaScript and Lua execution support | `pip install "tuochat[code-interpreters]"` |
| `js-miniracer` | JavaScript sandbox via MiniRacer only | `pip install "tuochat[js-miniracer]"` |
| `js-dukpy` | JavaScript sandbox via DukPy only | `pip install "tuochat[js-dukpy]"` |
| `lua` | Lua sandbox via Lupa only | `pip install "tuochat[lua]"` |
| `all` | All bundled optional extras | `pip install "tuochat[all]"` |

Installing `selfcheck` only makes the `pip-audit` integration available. The startup audit is still
**disabled by default** until you enable `[features].startup_audit = true` in your config.

______________________________________________________________________

## Platform notes

Tuochat runs on Linux, macOS, and Windows. The GUI (`tuochat gui`) requires Tkinter, which is
included in most Python distributions. On some Linux systems you may need to install it separately:

```bash
# Debian/Ubuntu
sudo apt install python3-tk

# Fedora/RHEL
sudo dnf install python3-tkinter
```

______________________________________________________________________

## Verifying the installation

```bash
tuochat --version
tuochat doctor
```

`doctor` checks the local configuration, paths, environment variables, and code-interpreter runtime
availability.
