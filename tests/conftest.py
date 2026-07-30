"""Pytest configuration for telegram_tools tests."""

import sys
from pathlib import Path

# Make src/ importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
