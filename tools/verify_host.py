"""Exercise the actual Sakura installer and isolated Plugin API v4 process."""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
import threading
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--sakura", required=True, type=Path)
parser.add_argument("--live-qr", action="store_true", help="在临时账号根验证真实二维码，不扫码登录")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(args.sakura.resolve()))
from app.plugins.installer import LocalPluginInstaller
from app.core_host.plugin_application import PluginApplicationHost
from app.core_host.runtime_logging import install_runtime_logging
from app.plugin_sdk.sakura_tools import ToolRegistry
from app.storage.runtime_roots import RuntimeRoots


class LogOutput(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.condition = threading.Condition()

    def write(self, value):
        with self.condition:
            result = super().write(value)
            self.condition.notify_all()
            return result

    def plugin_records(self):
        return [record for line in self.getvalue().splitlines()
                if line.startswith(b"SAKURA_RUNTIME_LOG_V1\t")
                for record in [json.loads(line.split(b"\t", 1)[1])]
                if record.get("plugin_id") == "dev.sakura.mijia"]


with tempfile.TemporaryDirectory(prefix="sakura-mijia-host-") as temporary:
    work = Path(temporary)
    distribution = work / "distribution"
    (distribution / "plugins/builtin").mkdir(parents=True)
    shutil.copy2(args.sakura / "VERSION", distribution / "VERSION")
    uv_dir = distribution / "python/tools"
    uv_dir.mkdir(parents=True)
    uv_name = "uv.exe" if os.name == "nt" else "uv"
    uv_source = args.sakura / "runtime" / ("Scripts" if os.name == "nt" else "bin") / uv_name
    shutil.copy2(uv_source, uv_dir / uv_name)
    roots = RuntimeRoots(distribution, work / "user")
    record = LocalPluginInstaller(roots).install(root / "dist/Sakura-Mijia-0.3.1.sakplugin.zip", "zip", initial_enabled=True)
    registry = ToolRegistry()
    log_output = LogOutput()
    bridge = install_runtime_logging(log_output)
    host = PluginApplicationHost(roots, "mijia-package-verification", registry)
    try:
        host.start()
        status = host.call_service("dev.sakura.mijia", "status")
        assert status["connected"] is False
        names = sorted(t.name for t in registry.all())
        assert len(names) == 8 and "mijia_set_property" in names
        assert registry.execute("mijia_list_devices", {}).content["error"]["code"] == "LOGIN_REQUIRED"
        with log_output.condition:
            assert log_output.condition.wait_for(lambda: any(
                r.get("custom") is True and r["severity"] == "error" and r.get("attributes", {}).get("reason_code") == "LOGIN_REQUIRED"
                for r in log_output.plugin_records()), timeout=5), "插件失败未进入 GUI 日志桥接"
            records = [r for r in log_output.plugin_records() if r.get("custom") is True]
            assert all(r["custom"] and r["plugin_name"] == "米家" for r in records)
            assert any(r["severity"] == "info" for r in records), "插件启动状态未进入 GUI 日志桥接"
        snapshot = host.settings_snapshot()
        item = next(p for p in snapshot["plugins"] if p["pluginId"] == "dev.sakura.mijia")
        assert item["state"] == "active" and item["sections"]
        sections = {s['sectionId']: s for s in item['sections']}
        assert set(sections) == {'connection', 'devices', 'scenes'}
        assert all(s['reasonCode'] == 'READY' for s in sections.values()), sections
        assert sections['connection']['fields'][1]['type'] == 'image'
        assert sections['devices']['presentation']['component'] == 'record-table'
        if args.live_qr:
            host.settings_action('dev.sakura.mijia', 'connection', 'login', {})
            deadline = time.monotonic() + 40
            while True:
                current = next(p for p in host.settings_snapshot()['plugins'] if p['pluginId'] == 'dev.sakura.mijia')
                connection = next(s for s in current['sections'] if s['sectionId'] == 'connection')
                assert connection['reasonCode'] == 'READY'
                if connection['values']['qr']:
                    assert connection['values']['qr']['dataUrl'].startswith('data:image/png;base64,')
                    break
                assert time.monotonic() < deadline, 'QR handshake timed out'
                threading.Event().wait(0.1)
            cancelled = host.settings_action('dev.sakura.mijia', 'connection', 'cancel', {})
            assert cancelled['values']['qr'] is None
            assert not host.call_service('dev.sakura.mijia', 'status')['connected']
        host.set_enabled(item['installId'], False)
        assert registry.all() == []
        print(json.dumps({"installed": record.plugin_id, "tools": names, "settings": "registered", "guiLogBridge": "passed", "cleanup": "passed"}, ensure_ascii=True))
    finally:
        host.close()
        bridge.close()
