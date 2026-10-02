"""Create an installable archive from explicitly selected source files."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "Sakura-Mijia-0.3.1.sakplugin.zip"
OUTPUT.parent.mkdir(exist_ok=True)
files = [ROOT / name for name in ("plugin.yaml", "plugin.py", "requirements.txt", "requirements.lock", "README.md", "LICENSE", "THIRD_PARTY.md")]
files += [p for p in (ROOT / "mijia_plugin").rglob("*") if p.suffix in (".py", ".html", ".css", ".js")]
with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        archive.write(file, file.relative_to(ROOT).as_posix())
print(OUTPUT)
