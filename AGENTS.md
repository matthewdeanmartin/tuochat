Use uv, don't use the system python. E.g. uv run.

Never use hungarian notation, in particular _ prefix for "private"
Do not use _ as the start of a variable name for any hungarian reason.
Do not use _ as the start of any class, function, etc to indicate private.

It is okay to use _ to mean unused variable or to make ruff happy with an unused variable, for example in tuple
unpacking. That is it.

## Codex Sandbox Notes for Windows PowerShell

These notes are specifically for Codex running on Windows in a PowerShell sandbox.

### General rules

- Prefer `uv run ...` for Python commands in this repo.
- In the Codex sandbox, do not assume normal access to user-level cache directories, temp directories, or pytest default scratch paths.
- When a command fails in a way that looks environmental, try a workspace-local override before assuming the code is broken.

### `uv` in the sandbox

- `uv` may fail trying to initialize its default cache under a user profile path such as `C:\Users\<name>\AppData\Local\uv\cache`.
- The reliable workaround is to set a workspace-local cache directory:
  - PowerShell: `$env:UV_CACHE_DIR='.uv-cache'; uv run ...`
- Do this proactively for verification commands if you already know the environment is touchy.
- This is especially important when using `uv run pytest`, `uv run python -m compileall`, or ad hoc `uv run python -c ...`.

### pytest in the sandbox

- pytest may fail because its default temp or cleanup directories point at protected Windows locations like:
  - `C:\Users\<name>\AppData\Local\Temp\pytest-of-<name>`
- Even if tests run, pytest teardown can still fail during temp cleanup.
- A first mitigation is to force a repo-local base temp:
  - PowerShell: `$env:UV_CACHE_DIR='.uv-cache'; uv run pytest --basetemp=tmp_pytest ...`
- This can still fail in some sandboxes during cleanup if the directory becomes unreadable to pytest.
- pytest cache warnings under `.pytest_cache` may also be environmental rather than product bugs.
- If pytest is blocked by sandbox temp/cache permissions, prefer a targeted `uv run python` smoke check for the specific config/helper logic you changed.

### Workspace-local smoke tests

- When pytest temp handling is broken, use workspace-local files instead of `tempfile.TemporaryDirectory()`.
- Example pattern:
  - create a small folder under the repo like `tmp_config_smoke`
  - write the needed file there
  - run `uv run python -` or `uv run python -c ...`
  - remove the folder afterward
- Do not use system temp locations when the sandbox has already shown permission issues.

### PowerShell quoting

- For multi-line Python snippets, prefer a PowerShell here-string piped into `uv run python -`:
  - `@' ...python... '@ | uv run python -`
- This avoids brittle escaping and unterminated-string problems that happen with long `-c` one-liners.
- If the command also needs the local uv cache, prefix it with:
  - `$env:UV_CACHE_DIR='.uv-cache';`

### Ripgrep and Windows paths

- `rg` may hit permission-denied directories outside the immediate target tree and still produce useful results.
- Narrow the search root when possible.
- For regexes containing quotes or parentheses, PowerShell quoting can break the pattern. Use single-quoted regex strings where possible.

### Interpreting failures

- Distinguish product failures from sandbox failures.
- Strong sandbox indicators:
  - `Access is denied`
  - failures under `AppData\Local\uv\cache`
  - failures under `AppData\Local\Temp\pytest-of-...`
  - pytest cache or teardown warnings unrelated to the code under test
- If one test fails because of a pre-existing expectation mismatch and others pass, call that out explicitly instead of attributing it to your change.

### Practical command patterns that worked

- Compile check:
  - `$env:UV_CACHE_DIR='.uv-cache'; uv run python -m compileall tuochat`
- Targeted pytest with local basetemp:
  - `$env:UV_CACHE_DIR='.uv-cache'; uv run pytest --basetemp=tmp_pytest test\\test_provider_duo.py -q`
- Inline smoke test with here-string:
  - `$env:UV_CACHE_DIR='.uv-cache'; @' ...python... '@ | uv run python -`

### Cleanup guidance

- If you create a workspace-local scratch directory for validation, remove it afterward.
- If removal needs escalation, request it cleanly rather than leaving clutter.
- Keep notes in the final report about which verification was blocked by sandbox behavior and what fallback validation you used instead.
