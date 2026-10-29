"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
