"""Run with Sakura's bundled Python; dependencies live in this repo's .deps."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / ".deps")]
import pytest

raise SystemExit(pytest.main(["-q", str(ROOT / "tests"), *sys.argv[1:]]))
