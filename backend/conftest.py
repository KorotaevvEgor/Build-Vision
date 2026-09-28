"""Гарантирует, что пакет `app` импортируется независимо от того, откуда запущен pytest."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
