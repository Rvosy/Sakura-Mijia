"""Install this ZIP in an isolated profile for the actual Sakura desktop app."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--sakura", required=True, type=Path)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
sakura = args.sakura.resolve()
root = repo / ".acceptance"
if root.exists():
    raise SystemExit("验收目录已存在，未覆盖。")
sys.path.insert(0, str(sakura))
from app.plugins.installer import LocalPluginInstaller
from app.plugins.inventory import PluginDesiredStateStore, PluginInventory
from app.storage.runtime_roots import RuntimeRoots
from app.core_host.plugin_application import PluginApplicationHost
from app.plugin_sdk.sakura_tools import ToolRegistry

root.mkdir()
config = root / "config"
config.mkdir()
(config / "system_config.yaml").write_text("config_version: 1\n", encoding="utf-8")
(config / "characters.yaml").write_text("current_character_id: ''\n", encoding="utf-8")
(config / "ui.json").write_text(json.dumps({"schema_version": 1, "domain": "ui", "settings": {
    "first_run_guide_completed": True,
}}, ensure_ascii=False), encoding="utf-8")
os.environ["PATH"] = str(Path(sys.executable).parent / "Scripts") + os.pathsep + os.environ.get("PATH", "")
roots = RuntimeRoots(sakura, root)
record = LocalPluginInstaller(roots).install(repo / "dist/Sakura-Mijia-0.3.0.sakplugin.zip", "zip", initial_enabled=True)
desired = PluginDesiredStateStore(root)
inventory = PluginInventory(roots, desired).scan()
desired.write({r.plugin_id: r.plugin_id == "dev.sakura.mijia" for r in inventory.records if r.plugin_id})
host = PluginApplicationHost(roots, "mijia-desktop-acceptance", ToolRegistry())
try:
    host.start()
    assert host.call_service("dev.sakura.mijia", "status")["connected"] is False
    assert any(p["pluginId"] == "dev.sakura.mijia" and p["state"] == "active" for p in host.settings_snapshot()["plugins"])
finally:
    host.close()

def ps(value):
    return "'" + str(value).replace("'", "''") + "'"

launcher = f"""$ErrorActionPreference = 'Stop'
if (@(Get-Process -Name sakura -ErrorAction SilentlyContinue).Count -gt 0) {{
    Write-Host '请先从托盘退出正在运行的 Sakura，再启动米家验收环境。'
    exit 1
}}
$mijiaStart = [System.Diagnostics.ProcessStartInfo]::new()
$mijiaStart.FileName = {ps(sakura / 'desktop/src-tauri/target/debug/sakura.exe')}
$mijiaStart.WorkingDirectory = {ps(sakura)}
$mijiaStart.UseShellExecute = $false
$mijiaStart.EnvironmentVariables['SAKURA_RUNTIME_USER_ROOT'] = {ps(root)}
[System.Diagnostics.Process]::Start($mijiaStart) | Out-Null
"""
(repo / "dist/启动米家验收.ps1").write_text(launcher, encoding="utf-8-sig")
(repo / "dist/启动米家验收.bat").write_text('@echo off\nchcp 65001 >nul\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0启动米家验收.ps1"\nif errorlevel 1 pause\n', encoding="utf-8")
print(json.dumps({"userRoot": str(root), "installed": record.plugin_id, "verified": "active", "launcher": str(repo / "dist/启动米家验收.bat")}, ensure_ascii=True))
