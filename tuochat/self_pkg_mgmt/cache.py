"""JSON-sidecar cache with TTL, cooloff, and per-target snoozes."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1
FILENAME = "self_pkg_mgmt.json"
DEFAULT_TTL = timedelta(hours=24)
COOLOFF = timedelta(days=14)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Cache:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, cache_dir: Path) -> Cache:
        path = cache_dir / FILENAME
        data: dict[str, Any] = {"schema": SCHEMA, "pypi": {}, "suppressed_until": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("schema") == SCHEMA:
                    data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        return cls(path=path, data=data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".sidecar.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        try:
            os.chmod(self.path, 0o600)
        except (OSError, NotImplementedError):
            pass

    #
    # Package metadata
    #

    def get_package(self, name: str) -> dict[str, Any] | None:
        return self.data.get("pypi", {}).get(name)

    def put_package(self, name: str, latest: str, published: datetime | None) -> None:
        self.data.setdefault("pypi", {})[name] = {
            "latest": latest,
            "published": format_iso(published) if published else None,
            "fetched": format_iso(utcnow()),
        }

    def is_fresh(self, name: str, ttl: timedelta = DEFAULT_TTL) -> bool:
        entry = self.get_package(name)
        if not entry:
            return False
        fetched = parse_iso(entry.get("fetched"))
        if not fetched:
            return False
        return utcnow() - fetched < ttl

    def published_age(self, name: str) -> timedelta | None:
        entry = self.get_package(name)
        if not entry:
            return None
        published = parse_iso(entry.get("published"))
        if not published:
            return None
        return utcnow() - published

    def is_in_cooloff(self, name: str) -> bool:
        age = self.published_age(name)
        if age is None:
            return False
        return age < COOLOFF

    #
    # Snooze
    #

    def snooze(self, target: str, days: int) -> None:
        until = utcnow() + timedelta(days=days)
        self.data.setdefault("suppressed_until", {})[target] = format_iso(until)

    def is_snoozed(self, target: str) -> bool:
        until_str = self.data.get("suppressed_until", {}).get(target)
        until = parse_iso(until_str)
        if not until:
            return False
        return utcnow() < until

    def prune_snoozes(self) -> None:
        now = utcnow()
        snoozes = self.data.get("suppressed_until", {})
        for key in list(snoozes.keys()):
            until = parse_iso(snoozes.get(key))
            if not until or until <= now:
                del snoozes[key]

    #
    # Audit summary
    #

    def set_audit(self, tool: str, summary: dict[str, Any]) -> None:
        self.data["last_audit_utc"] = format_iso(utcnow())
        self.data["audit_summary"] = {"tool": tool, **summary}

    def audit_is_fresh(self, ttl: timedelta = DEFAULT_TTL) -> bool:
        fetched = parse_iso(self.data.get("last_audit_utc"))
        if not fetched:
            return False
        return utcnow() - fetched < ttl

    def clear(self) -> None:
        self.data = {"schema": SCHEMA, "pypi": {}, "suppressed_until": {}}
