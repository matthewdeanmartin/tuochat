"""GitLab Duo Chat provider.

Communicates with GitLab's AI API using only stdlib:
- urllib.request for GraphQL mutations and REST calls
- socket + ssl for WebSocket (Action Cable) streaming

No gql, no httpx, no requests, no websocket libraries.
"""

from __future__ import annotations

import logging
import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from tuochat import winlog
from tuochat.config import default_gitlab_user_agent, normalize_gitlab_host
from tuochat.provider.websocket import WebSocketClient
from tuochat.serialization import JSONDecodeError, json_dumps, json_dumps_bytes, json_loads

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("tuochat.provider")


def report_http_error(status_code: int, message: str) -> None:
    """Emit a Windows event for auth/authz HTTP errors (401, 403)."""
    if status_code == 401:
        logger.error(message, extra={"winlog_event_id": winlog.EV_AUTH_FAILURE})
    elif status_code == 403:
        logger.error(message, extra={"winlog_event_id": winlog.EV_AUTHZ_FAILURE})


AI_COMPLETION_SUBSCRIPTION = """\
subscription aiCompletionResponse(
  $userId: UserID
  $aiAction: AiAction
  $clientSubscriptionId: String
) {
  aiCompletionResponse(
    userId: $userId
    aiAction: $aiAction
    clientSubscriptionId: $clientSubscriptionId
  ) {
    content
    errors
    role
    requestId
    chunkId
    timestamp
  }
}"""

CURRENT_USER_QUERY = """\
query getCurrentUser {
  currentUser {
    id
    username
    duoChatAvailable
  }
}"""

AI_MESSAGES_QUERY = """\
query getAiMessages($requestIds: [ID!], $roles: [AiMessageRole!]) {
  aiMessages(requestIds: $requestIds, roles: $roles) {
    nodes {
      content
      role
      timestamp
    }
  }
}"""

DUO_CHAT_MODEL_FIELD_CANDIDATES = (
    "model",
    "modelId",
    "modelName",
    "modelProvider",
    "aiModel",
    "aiModelId",
)

DUO_CHAT_MODEL_PROBE_PLATFORM_ORIGIN = "tuochat-model-probe"


def build_ai_action_mutation(duo_model_field: str | None = None, duo_model_value: str | None = None) -> str:
    """Build the aiAction chat mutation, optionally injecting a server-side model field."""
    duo_model_line = ""
    if duo_model_field is not None:
        if duo_model_value is None:
            raise ValueError("duo_model_value is required when duo_model_field is set")
        duo_model_line = f"\n        {duo_model_field}: {json_dumps(duo_model_value)}"
    return f"""\
mutation chat(
  $question: String!
  $resourceId: AiModelID
  $clientSubscriptionId: String
  $platformOrigin: String!
  $additionalContext: [AiAdditionalContextInput!]
) {{
  aiAction(
    input: {{
      chat: {{
        resourceId: $resourceId
        content: $question
        additionalContext: $additionalContext{duo_model_line}
      }}
      clientSubscriptionId: $clientSubscriptionId
      platformOrigin: $platformOrigin
    }}
  ) {{
    requestId
    errors
  }}
}}"""


def build_duo_model_probe_mutation(field_name: str) -> str:
    """Build a one-off mutation that checks whether AiChatInput accepts a model field."""
    return f"""\
mutation probeDuoModelSupport {{
  aiAction(
    input: {{
      chat: {{
        content: "/reset"
        {field_name}: "probe"
      }}
      platformOrigin: "{DUO_CHAT_MODEL_PROBE_PLATFORM_ORIGIN}"
    }}
  ) {{
    requestId
    errors
  }}
}}"""


AIACTION_MUTATION = build_ai_action_mutation()


@dataclass
class DuoUserInfo:
    """Current user info from GitLab."""

    gid: str  # e.g. "gid://gitlab/User/1234"
    username: str
    duo_chat_available: bool


@dataclass
class ChatDiagnostics:
    """Runtime diagnostics captured for the most recent chat attempt."""

    mode: str
    request_timeout: float
    websocket_welcome_timeout: float
    websocket_subscription_timeout: float
    poll_initial_delay: float = 1.0
    poll_max_delay: float = 10.0
    subscription_id: str | None = None
    request_id: str | None = None
    fallback_reason: str | None = None
    partial_response: str = ""
    poll_attempts: int = 0
    poll_elapsed_seconds: float = 0.0
    raw_events: list[str] = field(default_factory=list)

    def add_event(self, label: str, payload: Any) -> None:
        """Append a small human-readable diagnostic event."""
        if isinstance(payload, str):
            rendered = payload
        else:
            try:
                rendered = json_dumps(payload, sort_keys=True)
            except TypeError:
                rendered = repr(payload)
        self.raw_events.append(f"{label}: {rendered}")


@dataclass(frozen=True)
class DuoChatModelProbeAttempt:
    """One server-side model-field probe against GitLab Duo chat."""

    field_name: str
    accepted: bool
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DuoChatModelSupport:
    """Whether the current GitLab instance accepts a server-side Duo model selector."""

    supported: bool
    request_field: str | None = None
    reason: str | None = None
    attempts: tuple[DuoChatModelProbeAttempt, ...] = ()


class DuoProvider:
    """GitLab Duo Chat provider using stdlib only."""

    def __init__(
        self,
        host: str,
        token: str,
        token_type: str = "pat",  # nosec B107
        platform_origin: str = "tuochat",
        user_agent: str | None = None,
        timeout: int = 120,
        websocket_welcome_timeout: int = 20,
        websocket_subscription_timeout: int = 20,
        opener: urllib.request.OpenerDirector | None = None,
        proxy_host_port: tuple[str, int] | None = None,
    ) -> None:
        # Validate original host scheme before normalization forces it to https
        parsed_orig = urlparse(host)
        if parsed_orig.scheme and parsed_orig.scheme not in ("http", "https"):
            raise ValueError(f"GitLab host must use http:// or https://, got: {parsed_orig.scheme}://")

        self.host = normalize_gitlab_host(host)
        # Final check that it resolved to a valid origin
        parsed = urlparse(self.host)
        if parsed.scheme != "https":
            raise ValueError(f"GitLab host must resolve to https://, got: {parsed.scheme}://")
        self.token = token
        self.token_type = token_type  # nosec B105
        self.platform_origin = platform_origin
        self.user_agent = default_gitlab_user_agent() if user_agent is None else user_agent
        self.timeout = timeout
        self.websocket_welcome_timeout = websocket_welcome_timeout
        self.websocket_subscription_timeout = websocket_subscription_timeout
        self.ssl_ctx = create_ssl_context()
        # Optional proxy configuration (from ProxyProbe)
        self.opener = opener  # urllib opener pre-configured for proxy strategy
        self.proxy_host_port = proxy_host_port  # (host, port) for WebSocket CONNECT
        self.user_info: DuoUserInfo | None = None
        self.last_chat_diagnostics: ChatDiagnostics | None = None
        self.duo_chat_model_support: DuoChatModelSupport | None = None

    def timeout_summary(self) -> dict[str, float]:
        """Return the active timeout settings."""
        return {
            "request_timeout": float(self.timeout),
            "websocket_welcome_timeout": float(self.websocket_welcome_timeout),
            "websocket_subscription_timeout": float(self.websocket_subscription_timeout),
            "poll_initial_delay": 1.0,
            "poll_max_delay": 10.0,
        }

    def get_last_chat_diagnostics(self) -> ChatDiagnostics | None:
        """Return diagnostics for the most recent chat attempt."""
        return self.last_chat_diagnostics

    def new_chat_diagnostics(self, mode: str) -> ChatDiagnostics:
        """Create and store a fresh diagnostics container."""
        self.last_chat_diagnostics = ChatDiagnostics(
            mode=mode,
            request_timeout=float(self.timeout),
            websocket_welcome_timeout=float(self.websocket_welcome_timeout),
            websocket_subscription_timeout=float(self.websocket_subscription_timeout),
        )
        return self.last_chat_diagnostics

    # --- HTTP helpers ---

    def auth_headers(self) -> dict[str, str]:
        """Return auth headers based on token type."""
        if self.token_type == "oauth":  # nosec B105
            return {"Authorization": f"Bearer {self.token}"}
        return {"PRIVATE-TOKEN": self.token}

    def request_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Return GitLab request headers including auth and the configured user agent."""
        merged: dict[str, str] = {}
        if self.user_agent:
            merged["User-Agent"] = self.user_agent
        merged.update(self.auth_headers())
        if headers:
            merged.update(headers)
        return merged

    def urlopen(self, req: urllib.request.Request, timeout: int) -> Any:
        """Open a request using the configured opener (proxy-aware) or default urlopen."""
        if self.opener is not None:
            return self.opener.open(req, timeout=timeout)
        return urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout)  # nosec B310

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a GraphQL request to GitLab."""
        body = json_dumps_bytes({"query": query, "variables": variables or {}})
        headers = self.request_headers({"Content-Type": "application/json"})
        url = f"{self.host}/api/graphql"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with self.urlopen(req, self.timeout) as resp:
                body = resp.read()
                result = json_loads(body)
                if self.last_chat_diagnostics is not None:
                    self.last_chat_diagnostics.add_event("graphql_response", result)
                return result
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            report_http_error(e.code, f"GraphQL request failed ({e.code}): {error_body}")
            raise DuoAPIError(f"GraphQL request failed ({e.code}): {error_body}") from e

    def rest_get(self, path: str) -> dict[str, Any]:
        """GET a REST API endpoint."""
        url = f"{self.host}{path}"
        headers = self.request_headers()
        req = urllib.request.Request(url, headers=headers)
        try:
            with self.urlopen(req, 30) as resp:
                return json_loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            report_http_error(e.code, f"REST request failed ({e.code}): {error_body}")
            raise DuoAPIError(f"REST request failed ({e.code}): {error_body}") from e

    # --- Discovery & validation ---

    def get_instance_version(self) -> str:
        """Get the GitLab instance version."""
        data = self.rest_get("/api/v4/version")
        return data.get("version", "unknown")

    def validate_token(self) -> dict[str, Any]:
        """Validate the PAT and return token info."""
        return self.rest_get("/api/v4/personal_access_tokens/self")

    def get_current_user(self) -> DuoUserInfo:
        """Get the current user's info (cached)."""
        if self.user_info is not None:
            return self.user_info

        result = self.graphql(CURRENT_USER_QUERY)
        user = result.get("data", {}).get("currentUser", {})
        if not user:
            errors = result.get("errors", [])
            msg = errors[0].get("message", "Unknown error") if errors else "No currentUser in response"
            raise DuoAPIError(f"Failed to get current user: {msg}")

        self.user_info = DuoUserInfo(
            gid=user["id"],
            username=user.get("username", ""),
            duo_chat_available=user.get("duoChatAvailable", False),
        )
        return self.user_info

    def probe_duo_chat_model_support(self, *, refresh: bool = False) -> DuoChatModelSupport:
        """Probe whether GitLab Duo chat accepts a dedicated server-side model field."""
        if self.duo_chat_model_support is not None and not refresh:
            return self.duo_chat_model_support

        attempts: list[DuoChatModelProbeAttempt] = []
        for field_name in DUO_CHAT_MODEL_FIELD_CANDIDATES:
            result = self.graphql(build_duo_model_probe_mutation(field_name))
            errors = result.get("errors") or []
            if not errors:
                support = DuoChatModelSupport(
                    supported=True,
                    request_field=field_name,
                    reason="GitLab accepted a dedicated Duo chat model field.",
                    attempts=tuple(
                        [
                            *attempts,
                            DuoChatModelProbeAttempt(field_name=field_name, accepted=True),
                        ]
                    ),
                )
                self.duo_chat_model_support = support
                return support

            first_error = errors[0]
            message = str(first_error.get("message", "Unknown GraphQL error"))
            error_code = first_error.get("extensions", {}).get("code")
            accepted = error_code != "argumentNotAccepted"
            attempt = DuoChatModelProbeAttempt(
                field_name=field_name,
                accepted=accepted,
                error_code=error_code,
                error_message=message,
            )
            attempts.append(attempt)
            if accepted:
                support = DuoChatModelSupport(
                    supported=True,
                    request_field=field_name,
                    reason=message,
                    attempts=tuple(attempts),
                )
                self.duo_chat_model_support = support
                return support

        support = DuoChatModelSupport(
            supported=False,
            reason="GitLab rejected every known Duo chat model field on AiChatInput.",
            attempts=tuple(attempts),
        )
        self.duo_chat_model_support = support
        return support

    def resolve_ai_action_mutation(self, duo_model: str | None = None) -> str:
        """Resolve the chat mutation for the current request."""
        if duo_model is None:
            return AIACTION_MUTATION

        support = self.probe_duo_chat_model_support()
        if not support.supported or support.request_field is None:
            raise DuoAPIError("This GitLab instance does not support server-side Duo model selection.")

        return build_ai_action_mutation(duo_model_field=support.request_field, duo_model_value=duo_model)

    # --- Chat ---

    def chat_streaming(
        self,
        question: str,
        resource_id: str | None = None,
        cancel: Callable[[], bool] | None = None,
        additional_context: list[dict[str, Any]] | None = None,
        duo_model: str | None = None,
    ) -> Generator[str, None, None]:
        """Send a chat message and yield response text incrementally.

        Yields delta strings (the new text since the last yield).
        Uses GraphqlChannel over Action Cable (WebSocket) for streaming.

        *cancel* is an optional callable that returns True when the caller
        wants to abort.  The streaming loop checks it between WebSocket
        reads so that Ctrl+C can break out without waiting for the next
        server-side chunk.
        """
        diagnostics = self.new_chat_diagnostics("streaming")
        user = self.get_current_user()
        subscription_id = str(uuid.uuid4())
        diagnostics.subscription_id = subscription_id

        # Build cable URL
        parsed = urlparse(self.host)
        scheme = "wss"
        cable_host = parsed.hostname
        port_str = f":{parsed.port}" if parsed.port else ""
        cable_url = f"{scheme}://{cable_host}{port_str}/-/cable"

        ws_headers = {
            "Origin": f"{parsed.scheme}://{cable_host}{port_str}",
            **self.request_headers(),
        }

        ws = WebSocketClient(
            cable_url,
            headers=ws_headers,
            timeout=self.timeout,
            proxy=self.proxy_host_port,
        )
        try:
            ws.connect()
            diagnostics.add_event("websocket_connected", {"url": cable_url, "headers": sorted(ws_headers)})

            # Wait for Action Cable welcome
            self.cable_wait_welcome(ws, timeout=self.websocket_welcome_timeout, diagnostics=diagnostics)

            # Subscribe via GraphqlChannel with the subscription query in the identifier.
            # GitLab.com uses AnyCable which requires this approach rather than
            # the AiCompletionResponseChannel used by self-hosted instances.
            identifier = json_dumps(
                {
                    "channel": "GraphqlChannel",
                    "query": AI_COMPLETION_SUBSCRIPTION,
                    "variables": {
                        "userId": user.gid,
                        "aiAction": "CHAT",
                        "clientSubscriptionId": subscription_id,
                    },
                    "operationName": "aiCompletionResponse",
                }
            )
            ws.send(json_dumps({"command": "subscribe", "identifier": identifier}))
            diagnostics.add_event("websocket_subscribe", {"channel": "GraphqlChannel"})
            self.cable_wait_confirm(ws, timeout=self.websocket_subscription_timeout, diagnostics=diagnostics)

            # Send the mutation via HTTP
            variables: dict[str, Any] = {
                "question": question,
                "resourceId": resource_id or None,
                "clientSubscriptionId": subscription_id,
                "platformOrigin": self.platform_origin,
            }
            if additional_context:
                variables["additionalContext"] = additional_context
            result = self.graphql(self.resolve_ai_action_mutation(duo_model), variables)
            diagnostics.add_event("ai_action_result", result)

            errors = result.get("data", {}).get("aiAction", {}).get("errors", [])
            if errors:
                raise DuoAPIError(f"aiAction errors: {errors}")

            request_id = result.get("data", {}).get("aiAction", {}).get("requestId")
            diagnostics.request_id = request_id
            logger.debug("aiAction requestId: %s", request_id)
            if not request_id:
                raise DuoAPIError("No requestId returned from aiAction")

            # Stream response chunks from GraphqlChannel.
            # Each intermediate chunk is *cumulative* (the full response
            # up to that point) and chunks may arrive out of order.  We
            # buffer out-of-order chunks and process them in chunkId
            # order, yielding only the new text beyond what we've already
            # emitted.  The final chunk (chunkId=null) carries the full
            # response.
            #
            # Use a short socket timeout so we can poll the cancel callback
            # between reads.  This lets Ctrl+C break out promptly even on
            # Windows where signals don't interrupt blocking socket calls.
            CANCEL_POLL_INTERVAL = 0.3  # seconds
            if cancel is not None:
                ws.set_recv_timeout(CANCEL_POLL_INTERVAL)

            accumulated = ""
            next_expected = 1  # next chunkId we want to process
            pending: dict[int, str] = {}  # out-of-order chunks waiting
            buffered_chunks: list[str] = []
            chunk_mode = "unknown"

            def emit_sequential_chunk(content: str) -> Generator[str, None, None]:
                nonlocal accumulated, chunk_mode, buffered_chunks
                if not content:
                    return

                if chunk_mode == "unknown":
                    buffered_chunks.append(content)
                    if len(buffered_chunks) < 2:
                        return
                    chunk_mode = "cumulative" if buffered_chunks[1].startswith(buffered_chunks[0]) else "fragments"
                    chunks_to_process = buffered_chunks
                    buffered_chunks = []
                else:
                    chunks_to_process = [content]

                if chunk_mode == "cumulative":
                    for item in chunks_to_process:
                        if cancel is not None and cancel():
                            return
                        if len(item) > len(accumulated) and item.startswith(accumulated):
                            delta = item[len(accumulated) :]
                            accumulated = item
                            diagnostics.partial_response = accumulated
                            yield delta
                    return

                for item in chunks_to_process:
                    if cancel is not None and cancel():
                        return
                    accumulated += item
                    diagnostics.partial_response = accumulated
                    yield item

            while True:
                if cancel is not None and cancel():
                    diagnostics.add_event("cancelled", "user requested cancellation")
                    break

                try:
                    raw = ws.recv()
                except socket.timeout:
                    # Short-timeout expired — loop back to check cancel()
                    continue
                if raw is None:
                    break
                diagnostics.add_event("websocket_message", raw)

                try:
                    data = json_loads(raw)
                except JSONDecodeError:
                    logger.warning("Skipping malformed WebSocket frame: %r", raw[:120])
                    continue
                msg_type = data.get("type")

                if msg_type == "ping":
                    continue
                if msg_type == "disconnect":
                    reason = data.get("reason", "unknown")
                    logger.warning("Action Cable disconnect: %s", reason)
                    break

                # Extract aiCompletionResponse from GraphqlChannel message
                message = data.get("message")
                if not isinstance(message, dict):
                    continue

                result_data = message.get("result", {})
                if not isinstance(result_data, dict):
                    continue
                ai_resp = result_data.get("data", {}).get("aiCompletionResponse")
                if not ai_resp:
                    continue

                ai_errors = ai_resp.get("errors")
                if ai_errors:
                    raise DuoAPIError(f"Chat stream error: {ai_errors}")

                content = ai_resp.get("content") or ""
                chunk_id = ai_resp.get("chunkId")

                # chunkId is null on the final message
                if chunk_id is None:
                    # Final chunk carries the authoritative full response.
                    # Yield whatever we haven't emitted yet.
                    if content and len(content) > len(accumulated):
                        delta = content[len(accumulated) :]
                        yield delta
                    diagnostics.partial_response = content
                    break

                # Intermediate chunks are cumulative — each contains the
                # full response text up to that point.  Buffer and process
                # in chunkId order so we yield correct deltas.
                try:
                    seq = int(chunk_id)
                except (TypeError, ValueError):
                    # Unexpected chunkId format — compute delta as fallback
                    if content and len(content) > len(accumulated):
                        delta = content[len(accumulated) :]
                        accumulated = content
                        diagnostics.partial_response = accumulated
                        yield delta
                    continue

                pending[seq] = content

                # Flush consecutive chunks, yielding only new text
                while next_expected in pending:
                    yield from emit_sequential_chunk(pending.pop(next_expected))
                    next_expected += 1

            # Unsubscribe
            ws.send(json_dumps({"command": "unsubscribe", "identifier": identifier}))

        finally:
            ws.close()

    def chat_polling(
        self,
        question: str,
        resource_id: str | None = None,
        additional_context: list[dict[str, Any]] | None = None,
        duo_model: str | None = None,
    ) -> str:
        """Send a chat message and poll for the complete response.

        Fallback for when WebSocket is unavailable.
        Returns the complete response text.
        """
        diagnostics = self.new_chat_diagnostics("polling")
        subscription_id = str(uuid.uuid4())
        diagnostics.subscription_id = subscription_id
        variables: dict[str, Any] = {
            "question": question,
            "resourceId": resource_id or None,
            "clientSubscriptionId": subscription_id,
            "platformOrigin": self.platform_origin,
        }
        if additional_context:
            variables["additionalContext"] = additional_context

        result = self.graphql(self.resolve_ai_action_mutation(duo_model), variables)
        diagnostics.add_event("ai_action_result", result)
        errors = result.get("data", {}).get("aiAction", {}).get("errors", [])
        if errors:
            raise DuoAPIError(f"aiAction errors: {errors}")

        request_id = result.get("data", {}).get("aiAction", {}).get("requestId")
        diagnostics.request_id = request_id
        if not request_id:
            raise DuoAPIError("No requestId returned from aiAction")

        # Poll for the response with exponential backoff
        delay = 1.0
        max_delay = 10.0
        elapsed = 0.0

        while elapsed < self.timeout:
            time.sleep(delay)
            elapsed += delay
            diagnostics.poll_attempts += 1
            diagnostics.poll_elapsed_seconds = elapsed

            poll_result = self.graphql(
                AI_MESSAGES_QUERY,
                {
                    "requestIds": [request_id],
                    "roles": ["ASSISTANT"],
                },
            )
            diagnostics.add_event("poll_result", poll_result)

            nodes = poll_result.get("data", {}).get("aiMessages", {}).get("nodes", [])
            if nodes:
                content = nodes[0].get("content", "")
                diagnostics.partial_response = content
                return content

            delay = min(delay * 2, max_delay)
            logger.debug("Polling for response (%.1fs elapsed)...", elapsed)

        raise DuoAPIError(f"Timed out waiting for response after {self.timeout}s")

    def reset_conversation(self) -> None:
        """Tell the Duo backend to clear its server-side conversation history.

        Sends a '/reset' message via aiAction, which GitLab Duo interprets as
        a request to start a fresh thread.  The response is intentionally
        discarded — we only care that the server receives the signal.
        """
        variables = {
            "question": "/reset",
            "resourceId": None,
            "clientSubscriptionId": str(uuid.uuid4()),
            "platformOrigin": self.platform_origin,
        }
        try:
            result = self.graphql(AIACTION_MUTATION, variables)
            errors = result.get("data", {}).get("aiAction", {}).get("errors", [])
            if errors:
                logger.warning("reset_conversation: aiAction errors: %s", errors)
            else:
                logger.debug("reset_conversation: sent /reset to Duo backend")
        except Exception as exc:  # noqa: BLE001
            logger.warning("reset_conversation: failed to send /reset: %s", exc)

    def chat(
        self,
        question: str,
        resource_id: str | None = None,
        streaming: bool = True,
        cancel: Callable[[], bool] | None = None,
        additional_context: list[dict[str, Any]] | None = None,
        duo_model: str | None = None,
    ) -> Iterator[str]:
        """Send a chat message and return response text.

        If streaming=True, yields incremental deltas via WebSocket.
        If streaming=False, yields the complete response as a single string.
        Falls back to polling if WebSocket fails.

        *cancel* is an optional callable; when it returns True the streaming
        loop will exit promptly.
        """
        if streaming:
            try:
                yield from self.chat_streaming(
                    question,
                    resource_id,
                    cancel=cancel,
                    additional_context=additional_context,
                    duo_model=duo_model,
                )
                return
            except (ConnectionError, OSError) as e:
                if self.last_chat_diagnostics is not None:
                    self.last_chat_diagnostics.fallback_reason = str(e)
                    self.last_chat_diagnostics.add_event("streaming_fallback", str(e))
                logger.warning(
                    "WebSocket streaming failed, falling back to polling: %s",
                    e,
                    extra={"winlog_event_id": winlog.EV_NETWORK_FAILURE},
                )

        # Polling fallback
        response = self.chat_polling(question, resource_id, additional_context=additional_context, duo_model=duo_model)
        yield response

    # --- Action Cable helpers ---

    @staticmethod
    def cable_wait_welcome(
        ws: WebSocketClient, timeout: float = 10.0, diagnostics: ChatDiagnostics | None = None
    ) -> None:
        """Wait for the Action Cable welcome message."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            msg = ws.recv()
            if msg is None:
                raise ConnectionError("WebSocket closed before welcome")
            if diagnostics is not None:
                diagnostics.add_event("websocket_handshake", msg)
            data = json_loads(msg)
            if data.get("type") == "welcome":
                logger.debug("Action Cable welcome received")
                return
            if data.get("type") == "disconnect":
                raise ConnectionError(f"Action Cable disconnect: {data.get('reason', 'unknown')}")
        raise ConnectionError("Timed out waiting for Action Cable welcome")

    @staticmethod
    def cable_wait_confirm(
        ws: WebSocketClient, timeout: float = 10.0, diagnostics: ChatDiagnostics | None = None
    ) -> None:
        """Wait for subscription confirmation."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            msg = ws.recv()
            if msg is None:
                raise ConnectionError("WebSocket closed during subscribe")
            if diagnostics is not None:
                diagnostics.add_event("websocket_subscribe_wait", msg)
            data = json_loads(msg)
            if data.get("type") == "confirm_subscription":
                logger.debug("Subscription confirmed")
                return
            if data.get("type") == "reject_subscription":
                logger.error(
                    "Action Cable subscription rejected by server",
                    extra={"winlog_event_id": winlog.EV_AUTHZ_FAILURE},
                )
                raise PermissionError("Action Cable subscription rejected")
            if data.get("type") == "ping":
                continue
        raise ConnectionError("Timed out waiting for subscription confirmation")


class DuoAPIError(Exception):
    """Error from the GitLab Duo API."""


def create_ssl_context() -> ssl.SSLContext:
    """Create an HTTPS client context, preferring TLS 1.3 when available."""
    ctx = ssl.create_default_context()
    tls_version = getattr(ssl, "TLSVersion", None)
    if tls_version is not None and hasattr(tls_version, "TLSv1_3"):
        try:
            ctx.maximum_version = tls_version.TLSv1_3
        except (AttributeError, ValueError):
            pass
    return ctx
