"""Check the live QR handshake in an isolated account root, then cancel it."""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / ".deps")]
from mijia_plugin.controller import Controller

with tempfile.TemporaryDirectory(prefix="mijia-qr-check-") as temporary:
    controller = Controller(Path(temporary))
    try:
        controller.start("login")
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            state = controller.status()
            if state["hasQr"] or state["error"]:
                break
            threading.Event().wait(0.1)
        assert state["hasQr"], state.get("error")
        assert controller.qr.startswith(b"\x89PNG")
        controller.logout()
        assert not controller.vault.exists()
        print(json.dumps({"qrHandshake": "passed", "image": "PNG", "login": "not performed", "cancel": "passed"}))
    finally:
        controller.close()
