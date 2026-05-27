"""Live integration tests for GitLab Duo streaming.

These tests make real API calls to verify streaming behavior.
Requires TUOCHAT_GITLAB_HOST and TUOCHAT_GITLAB_TOKEN in .env or environment.

Run: uv run python tests_integration/test_streaming_live.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

HOST = os.environ["TUOCHAT_GITLAB_HOST"]
TOKEN = os.environ["TUOCHAT_GITLAB_TOKEN"]


def test_websocket_streaming_timing():
    """Test that WebSocket streaming delivers chunks incrementally."""
    from tuochat.provider.duo import DuoProvider

    provider = DuoProvider(host=HOST, token=TOKEN)
    provider.reset_conversation()
    user = provider.get_current_user()
    print(f"User: {user.username} ({user.gid})")
    print(f"Duo available: {user.duo_chat_available}")

    question = "What is a merge request in GitLab? Answer in exactly 3 sentences."

    print("\n--- Streaming test ---")
    print(f"Question: {question}")

    chunks = []
    t0 = time.monotonic()

    for delta in provider.chat_streaming(question):
        elapsed = time.monotonic() - t0
        chunks.append((elapsed, delta))
        print(f"  [{elapsed:7.3f}s] chunk #{len(chunks):3d}: {delta!r:.80}")

    total = time.monotonic() - t0
    print(f"\nTotal time: {total:.3f}s")
    print(f"Total chunks: {len(chunks)}")

    if len(chunks) > 1:
        spread = chunks[-1][0] - chunks[0][0]
        print(f"Time spread between first and last chunk: {spread:.3f}s")
        if spread < 0.5:
            print("WARNING: All chunks arrived nearly simultaneously — NOT truly streaming!")
        else:
            print("OK: Chunks are spread over time — streaming is working.")
    else:
        print("WARNING: Only 1 chunk received — response came all at once (polling behavior).")

    diag = provider.get_last_chat_diagnostics()
    if diag:
        print(f"\nDiagnostics mode: {diag.mode}")
        print(f"Fallback reason: {diag.fallback_reason}")


if __name__ == "__main__":
    test_websocket_streaming_timing()
