import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / ".deps"))
SAKURA = Path(os.environ.get("SAKURA_SOURCE", ROOT.parent / "sakura"))
sys.path.insert(2, str(SAKURA / "app" / "plugins"))
