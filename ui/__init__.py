"""
UI package — Gradio web interface for Telegram Tools.

The actual ``app.py`` entrypoint lives at the repository root for
convenience (``python app.py``). This thin module re-exports it so
that the UI can also be launched programmatically:

    from telegram_tools.ui import app, launch
    launch()
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path

__all__ = ["app", "launch", "build_app"]


def _load_root_app() -> "gr.Blocks":  # type: ignore[name-defined]
    """Execute the top-level ``app.py`` and return its ``app`` object."""
    root = Path(__file__).resolve().parents[2]
    app_path = root / "app.py"
    if not app_path.exists():
        raise FileNotFoundError(
            f"Expected Gradio entrypoint at {app_path} but it was not found."
        )
    namespace = runpy.run_path(str(app_path), run_name="__main__")
    return namespace["app"]


def build_app():
    """Build (but do not launch) the Gradio Blocks instance."""
    return _load_root_app()


def launch(
    server_name: str | None = None,
    server_port: int | None = None,
    share: bool | None = None,
    **kwargs,
) -> None:
    """Launch the web UI with sensible defaults (overridable via env)."""
    blocks = _load_root_app()
    blocks.launch(
        server_name=server_name or os.environ.get("HOST", "0.0.0.0"),
        server_port=server_port or int(os.environ.get("PORT", 7860)),
        share=share if share is not None else os.environ.get("SHARE", "").lower() in ("1", "true"),
        show_error=True,
        **kwargs,
    )


# Lazily build on import — keeps `python -m telegram_tools.ui` cheap.
app = None


if __name__ == "__main__":  # pragma: no cover
    launch()
