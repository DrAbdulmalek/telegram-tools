"""Progress tracking helpers (file-based resume support)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


class ProgressManager:
    """Tracks operation progress to a JSON file for resume support."""

    def __init__(self, progress_file: str | Path):
        self.progress_file = Path(progress_file)
        self.progress: dict = self._load()

    def _load(self) -> dict:
        if self.progress_file.exists():
            try:
                return json.loads(
                    self.progress_file.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        return {
            "copied": 0,
            "skipped": 0,
            "failed": 0,
            "last_source_id": 0,
            "start_time": None,
        }

    def save(self) -> None:
        try:
            self.progress_file.write_text(
                json.dumps(self.progress, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def update(self, **kwargs) -> None:
        self.progress.update(kwargs)
        self.save()

    @property
    def last_source_id(self) -> int:
        return self.progress.get("last_source_id", 0)

    def reset(self) -> None:
        self.progress = {
            "copied": 0,
            "skipped": 0,
            "failed": 0,
            "last_source_id": 0,
            "start_time": None,
        }
        self.save()


class Stats:
    """Collects operation statistics for reporting."""

    def __init__(self):
        self.copied = 0
        self.skipped = 0
        self.failed = 0
        self.text_copied = 0
        self.media_copied = 0
        self.errors: list[dict] = []
        self.start_time: Optional[float] = None

    def add_error(self, msg_id: int, error: Exception | str) -> None:
        self.errors.append({"msg_id": msg_id, "error": str(error)})

    def summary(self) -> str:
        elapsed = time.time() - self.start_time if self.start_time else 0
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        return (
            f"\n=== Final Report ===\n"
            f"  Copied:   {self.copied}\n"
            f"  Text:     {self.text_copied}\n"
            f"  Media:    {self.media_copied}\n"
            f"  Skipped:  {self.skipped}\n"
            f"  Failed:   {self.failed}\n"
            f"  Time:     {h:02d}:{m:02d}:{s:02d}\n"
            f"====================="
        )
