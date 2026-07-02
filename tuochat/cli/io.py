"""Light-touch I/O seams for alternate front ends."""

from __future__ import annotations

import getpass
import io
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from contextvars import ContextVar
from typing import Any, Protocol

# The inline EOF marker character sent by Windows Ctrl+Z inside input().
# Exposed as a constant so callers can match it without hardcoding \x1a.
WINDOWS_INLINE_EOF_CHAR = "\x1a"


class PromptCallback(Protocol):
    """Callable protocol for injected prompt handlers."""

    def __call__(self, prompt: str, *, secret: bool = False) -> str: ...


prompt_handler_var: ContextVar[PromptCallback | None] = ContextVar("prompt_handler_var", default=None)

# ---------------------------------------------------------------------------
# Backend protocol and selection
# ---------------------------------------------------------------------------


class InputBackend(Protocol):
    """Minimal terminal-input backend interface."""

    supports_multiline: bool
    supports_completion: bool
    supports_history: bool

    def read_line(self, prompt: str) -> str: ...

    def configure(self, cfg: Any) -> None: ...

    def shutdown(self) -> None: ...


class ReadlineBackend:
    """stdlib input() backend with optional readline history and completion."""

    supports_multiline = False
    supports_completion = False
    supports_history = False

    def __init__(self) -> None:
        self.readline_mod: Any = None
        self.history_path: str | None = None
        self.configured = False

    def configure(self, cfg: Any) -> None:
        if self.configured:
            return
        self.configured = True
        try:
            import readline as rl_mod  # type: ignore[import]

            self.readline_mod = rl_mod
        except ImportError:
            try:
                import pyreadline3 as prl_mod  # type: ignore[import]

                self.readline_mod = prl_mod
            except ImportError:
                return

        self.supports_history = True
        self.supports_completion = True

        # History file
        no_write = getattr(cfg, "no_write", False) if cfg is not None else False
        if not no_write:
            from tuochat.config import config_dir

            history_file = config_dir() / "repl_history"
            self.history_path = str(history_file)
            try:
                self.readline_mod.read_history_file(self.history_path)
            except (FileNotFoundError, OSError, AttributeError):
                pass
            try:
                self.readline_mod.set_history_length(2000)
            except AttributeError:
                pass

        # Slash-command completion
        from tuochat.constants import KNOWN_SLASH_COMMANDS

        commands = sorted(KNOWN_SLASH_COMMANDS)

        def completer(text: str, state: int) -> str | None:
            if not text.startswith("/"):
                return None
            matches = [c for c in commands if c.lower().startswith(text.lower())]
            return matches[state] if state < len(matches) else None

        try:
            self.readline_mod.set_completer(completer)
            self.readline_mod.parse_and_bind("tab: complete")
        except AttributeError:
            pass

    def read_line(self, prompt: str) -> str:
        return input(prompt)

    def shutdown(self) -> None:
        if self.readline_mod is not None and self.history_path is not None:
            try:
                self.readline_mod.write_history_file(self.history_path)
            except OSError:
                pass


class PromptToolkitBackend:
    """prompt-toolkit backend with multiline editing, history, and completion."""

    supports_multiline = True
    supports_completion = True
    supports_history = True

    def __init__(self) -> None:
        import prompt_toolkit  # type: ignore[import-not-found]  # noqa: F401  # pylint: disable=unused-import
        from prompt_toolkit import PromptSession  # type: ignore[import-not-found]
        from prompt_toolkit.history import FileHistory, InMemoryHistory  # type: ignore[import-not-found]

        self.prompt_session_class = PromptSession
        self.file_history_class = FileHistory
        self.in_memory_history_class = InMemoryHistory
        self.session: Any = None
        self.multiline_session: Any = None

    def configure(self, cfg: Any) -> None:
        from prompt_toolkit.completion import Completer, Completion  # type: ignore[import-not-found]

        from tuochat.constants import KNOWN_SLASH_COMMANDS

        commands = sorted(KNOWN_SLASH_COMMANDS)

        class SlashCompleter(Completer):
            def get_completions(self, document, complete_event):  # type: ignore[override]
                text = document.text_before_cursor
                if not text.startswith("/"):
                    return
                for cmd in commands:
                    if cmd.lower().startswith(text.lower()):
                        yield Completion(cmd[len(text) :], start_position=0)

        no_write = getattr(cfg, "no_write", False) if cfg is not None else False
        history: Any
        if no_write:
            history = self.in_memory_history_class()
        else:
            from tuochat.config import config_dir

            history_file = config_dir() / "repl_history"
            try:
                history_file.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                history = self.in_memory_history_class()
            else:
                history = self.file_history_class(str(history_file))

        self.session = self.prompt_session_class(
            history=history,
            completer=SlashCompleter(),
            complete_while_typing=False,
        )

        # Multiline session — emacs-style (prompt-toolkit default), Alt+S to submit
        from prompt_toolkit.filters import is_done  # type: ignore[import-not-found]
        from prompt_toolkit.key_binding import KeyBindings  # type: ignore[import-not-found]

        submit_kb = KeyBindings()

        # Alt+S: submit (matching Tk submit shortcut)
        @submit_kb.add("escape", "s")
        def submit_alt_s(event):  # type: ignore[misc]
            event.current_buffer.validate_and_handle()

        # Ctrl+O: insert newline (matching Tk Ctrl+O shortcut idea)
        @submit_kb.add("c-o")
        def insert_newline(event):  # type: ignore[misc]
            event.current_buffer.insert_text("\n")

        # Ctrl+Z on Windows: treat as submit (EOF) when buffer is non-empty,
        # or raise EOFError when empty — mirrors readline backend behavior.
        # pylint: disable=invalid-unary-operand-type
        @submit_kb.add("c-z", filter=~is_done)
        def ctrl_z_submit(event):  # type: ignore[misc]
            buf = event.current_buffer
            if buf.text:
                buf.validate_and_handle()
            else:
                raise EOFError

        self.multiline_session = self.prompt_session_class(
            history=history,
            completer=SlashCompleter(),
            complete_while_typing=False,
            multiline=True,
            key_bindings=submit_kb,
        )

    def read_line(self, prompt: str) -> str:
        if self.session is None:
            return input(prompt)
        return self.session.prompt(prompt)

    def read_multiline(self, prompt: str) -> str:
        """Read a full multiline message in one editor session."""
        if self.multiline_session is None:
            return input(prompt)
        return self.multiline_session.prompt(prompt)

    def shutdown(self) -> None:
        pass  # prompt-toolkit FileHistory flushes on each append


# Singleton backend, selected lazily on first configure call.
# Keep both names for compatibility with older tests and callers that
# monkeypatch the module-level backend directly.
active_backend: InputBackend | None = None
ACTIVE_BACKEND: InputBackend | None = None


def make_backend() -> InputBackend:
    try:
        return PromptToolkitBackend()
    except (ImportError, ModuleNotFoundError):
        return ReadlineBackend()


def get_backend() -> InputBackend:
    """Return the active backend (may be unconfigured until configure_interactive_io is called)."""
    global active_backend, ACTIVE_BACKEND  # noqa: PLW0603
    if active_backend is None and ACTIVE_BACKEND is not None:
        active_backend = ACTIVE_BACKEND
    if active_backend is None:
        active_backend = make_backend()
    ACTIVE_BACKEND = active_backend
    return active_backend


def configure_interactive_io(cfg: Any = None) -> None:
    """Initialise the active backend (history, completion).  Call once at CLI startup."""
    global active_backend, ACTIVE_BACKEND  # noqa: PLW0603
    backend = get_backend()
    try:
        backend.configure(cfg)
    except Exception:
        # Terminal init failed (e.g. prompt-toolkit on a non-console Windows terminal).
        # Fall back to the readline backend and configure that instead.
        if not isinstance(backend, ReadlineBackend):
            active_backend = ReadlineBackend()
            ACTIVE_BACKEND = active_backend
            active_backend.configure(cfg)


def shutdown_interactive_io() -> None:
    """Flush history and tear down the active backend.  Call once at CLI shutdown."""
    if active_backend is not None:
        active_backend.shutdown()


# ---------------------------------------------------------------------------
# Public read_prompt — selection order:
#   1. injected prompt_handler (GUI / tests)
#   2. active backend
# ---------------------------------------------------------------------------


def read_prompt(prompt: str, *, secret: bool = False) -> str:
    """Read interactive input from the active prompt handler or the console."""
    handler = prompt_handler_var.get()
    if handler is not None:
        return handler(prompt, secret=secret)
    if secret:
        return getpass.getpass(prompt)
    return get_backend().read_line(prompt)


@contextmanager
def prompt_handler(prompt_callback: PromptCallback | None):
    """Install a prompt callback for the current execution context."""
    token = prompt_handler_var.set(prompt_callback)
    try:
        yield
    finally:
        prompt_handler_var.reset(token)


@contextmanager
def redirect_standard_io(
    *,
    stdout: Any = None,
    stderr: Any = None,
):
    """Redirect stdout/stderr for the duration of a context."""
    with ExitStack() as stack:
        if stdout is not None:
            stack.enter_context(redirect_stdout(stdout))
        if stderr is not None:
            stack.enter_context(redirect_stderr(stderr))
        yield


class NullTextIO(io.TextIOBase):
    """Writable text sink that ignores all content."""

    def write(self, text: str) -> int:
        return len(text)

    def writable(self) -> bool:
        return True
