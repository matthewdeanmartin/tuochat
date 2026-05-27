"""OpenRouter chat provider built on the official `openrouter` SDK.

OpenRouter is opt-in via the `openrouter` extra (`pip install tuochat[openrouter]`).
The SDK is imported lazily so the rest of tuochat keeps working when the
package is not installed.

OpenRouter is stateless, so the caller is responsible for passing prior
conversation history on each call (unlike Duo, which keeps state on the
server side).  The provider rotates through a configured model list when
`OPENROUTER_ROTATE_MODELS=true`, advancing one slot per `chat()` call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from typing import Any

logger = logging.getLogger("tuochat.provider.openrouter")


class OpenRouterUnavailableError(RuntimeError):
    """Raised when the optional `openrouter` SDK is not installed."""


class OpenRouterAPIError(RuntimeError):
    """Raised when the OpenRouter API returns an error response."""


def import_openrouter_sdk() -> Any:
    """Import the official openrouter SDK or raise a friendly error."""
    try:
        import openrouter  # noqa: PLC0415
    except ImportError as exc:
        raise OpenRouterUnavailableError(
            "The 'openrouter' package is not installed. Install the extra with: " "pip install 'tuochat[openrouter]'"
        ) from exc
    return openrouter


def extract_delta_text(event: Any) -> str:
    """Pull the incremental text fragment out of a streamed event.

    OpenRouter is OpenAI-compatible, so events look like
    `{"choices": [{"delta": {"content": "..."}}]}`, but the SDK may
    expose them as dicts or as objects.  Be defensive about both.
    """
    if event is None:
        return ""

    # Dict form
    if isinstance(event, dict):
        choices = event.get("choices") or []
        if not choices:
            return ""
        first = choices[0]
        if isinstance(first, dict):
            delta = first.get("delta") or {}
            if isinstance(delta, dict):
                content = delta.get("content")
                return content if isinstance(content, str) else ""
        return ""

    # Object form (pydantic-style)
    choices = getattr(event, "choices", None)
    if not choices:
        return ""
    try:
        first = choices[0]
    except (IndexError, TypeError):
        return ""
    delta = getattr(first, "delta", None)
    if delta is None:
        return ""
    content = getattr(delta, "content", None)
    return content if isinstance(content, str) else ""


def extract_full_text(response: Any) -> str:
    """Pull the assistant message text out of a non-streaming response."""
    if response is None:
        return ""

    if isinstance(response, dict):
        choices = response.get("choices") or []
        if not choices:
            return ""
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message") or {}
            if isinstance(message, dict):
                content = message.get("content")
                return content if isinstance(content, str) else ""
        return ""

    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    try:
        first = choices[0]
    except (IndexError, TypeError):
        return ""
    message = getattr(first, "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", None)
    return content if isinstance(content, str) else ""


class OpenRouterProvider:
    """Chat provider backed by the official OpenRouter Python SDK.

    Args:
        api_key: OpenRouter API key (sk-or-...).
        models: Ordered list of model identifiers.  At least one entry is
            required.  When `rotate_models` is True the provider advances
            to the next entry on each `chat()` call, wrapping around.
        rotate_models: When True, rotate through `models` on each call.
            When False, always use `models[0]`.
        http_referer: Optional HTTP-Referer header value used for
            OpenRouter app attribution.
        x_title: Optional X-Title header value used for OpenRouter app
            attribution.
        timeout: Per-call request timeout in seconds, forwarded to the SDK
            when supported.  None leaves the SDK default in place.
    """

    def __init__(
        self,
        api_key: str,
        models: Iterable[str],
        *,
        rotate_models: bool = False,
        http_referer: str | None = None,
        x_title: str | None = None,
        timeout: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key is required.")
        model_list = [m for m in (model.strip() for model in models) if m]
        if not model_list:
            raise ValueError("At least one OpenRouter model identifier is required.")

        self.api_key = api_key
        self.models: list[str] = model_list
        self.rotate_models = rotate_models
        self.http_referer = http_referer
        self.x_title = x_title
        self.timeout = timeout
        self.next_model_index = 0
        self.last_model_used: str | None = None

    def select_model(self) -> str:
        """Return the model id to use for the next call, advancing rotation."""
        if not self.rotate_models or len(self.models) == 1:
            return self.models[0]
        chosen = self.models[self.next_model_index % len(self.models)]
        self.next_model_index = (self.next_model_index + 1) % len(self.models)
        return chosen

    def build_client(self) -> Any:
        """Construct a fresh SDK client for one call."""
        sdk = import_openrouter_sdk()
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.http_referer:
            kwargs["http_referer"] = self.http_referer
        if self.x_title:
            kwargs["x_open_router_title"] = self.x_title
        return sdk.OpenRouter(**kwargs)

    def build_messages(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None,
        system_prompt: str | None,
        additional_context: list[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        """Assemble the OpenAI-style messages payload."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if additional_context:
            ctx_lines = ["Additional context items:"]
            for item in additional_context:
                category = str(item.get("category", "CONTEXT"))
                name = str(item.get("name", ""))
                content = str(item.get("content", ""))
                ctx_lines.append(f"[{category}] {name}\n{content}")
            messages.append({"role": "system", "content": "\n\n".join(ctx_lines)})
        if history:
            for msg in history:
                role = msg.get("role")
                message_content = msg.get("content")
                if (
                    isinstance(role, str)
                    and role in {"user", "assistant", "system"}
                    and isinstance(message_content, str)
                ):
                    messages.append({"role": role, "content": message_content})
        messages.append({"role": "user", "content": question})
        return messages

    def chat(
        self,
        question: str,
        resource_id: str | None = None,  # noqa: ARG002 — accepted for signature parity
        streaming: bool = True,
        cancel: Callable[[], bool] | None = None,
        additional_context: list[dict[str, Any]] | None = None,
        history: list[dict[str, str]] | None = None,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        """Send a chat message and yield response text deltas.

        Mirrors the Duo/Eliza `chat()` shape so `session.send_chat_turn`
        can iterate the result the same way.  `history` and `system_prompt`
        are OpenRouter-specific extensions: OpenRouter is stateless so the
        caller must replay prior turns each call.
        """
        model = self.select_model()
        self.last_model_used = model
        messages = self.build_messages(
            question,
            history=history,
            system_prompt=system_prompt,
            additional_context=additional_context,
        )

        client = self.build_client()
        send_kwargs: dict[str, Any] = {
            "messages": messages,
            "model": model,
            "stream": bool(streaming),
        }
        if self.timeout is not None:
            send_kwargs["timeout"] = self.timeout

        try:
            result = client.chat.send(**send_kwargs)
        except Exception as exc:
            raise OpenRouterAPIError(f"OpenRouter request failed: {exc}") from exc

        if not streaming:
            text = extract_full_text(result)
            if text:
                yield text
            return

        try:
            for event in result:
                if cancel is not None and cancel():
                    break
                delta = extract_delta_text(event)
                if delta:
                    yield delta
        except Exception as exc:
            raise OpenRouterAPIError(f"OpenRouter stream failed: {exc}") from exc


__all__ = [
    "OpenRouterAPIError",
    "OpenRouterProvider",
    "OpenRouterUnavailableError",
    "extract_delta_text",
    "extract_full_text",
    "import_openrouter_sdk",
]
