"""Sync state: remembers the highest message id written per channel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_FILENAME = ".telesync-state.json"


class State:
    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, out_dir: Path) -> "State":
        path = out_dir / STATE_FILENAME
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        data.setdefault("channels", {})
        data.setdefault("subscriptions", [])
        return cls(path, data)

    # --- subscriptions: the channel list managed via `telesync channels` ---

    def subscriptions(self) -> list[str]:
        return list(self.data.get("subscriptions", []))

    def subscribe(self, ref: str) -> bool:
        """Add a channel ref. Returns False if it was already there."""
        subs = self.data["subscriptions"]
        if ref in subs:
            return False
        subs.append(ref)
        return True

    def unsubscribe(self, ref: str) -> bool:
        """Remove a channel ref (case-insensitive, ignoring a leading @)."""
        want = ref.lstrip("@").lower()
        subs = self.data["subscriptions"]
        for existing in list(subs):
            if existing.lstrip("@").lower() == want:
                subs.remove(existing)
                return True
        return False

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def channel(self, key: str) -> dict[str, Any]:
        return self.data["channels"].setdefault(key, {"last_id": 0})

    def last_id(self, key: str) -> int:
        return int(self.channel(key).get("last_id", 0))

    def record(self, key: str, *, last_id: int, title: str | None = None,
               folder: str | None = None, last_sync: str | None = None) -> None:
        entry = self.channel(key)
        entry["last_id"] = max(int(entry.get("last_id", 0)), int(last_id))
        if title:
            entry["title"] = title
        if folder:
            entry["folder"] = folder
        if last_sync:
            entry["last_sync"] = last_sync
