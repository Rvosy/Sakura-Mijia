from __future__ import annotations

import io
import base64
import json
import logging
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import requests
import qrcode
from mijiaAPI import apis
from mijiaAPI.miutils import gen_nonce, generate_enc_params, get_signed_nonce

from .storage import atomic_write


class PluginError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_request_context = threading.local()


@contextmanager
def network_scope(cancel: threading.Event):
    _request_context.cancel = cancel
    try:
        yield
    finally:
        _request_context.cancel = None


class TimedSession(requests.Session):
    def request(self, method, url, **kwargs):
        cancel = getattr(_request_context, "cancel", None)
        if cancel and cancel.is_set():
            raise PluginError("CANCELLED", "操作已取消。")
        # Upstream QR long polling explicitly requests 120 seconds. Other calls
        # have no timeout upstream, so bound them here without retrying writes.
        kwargs.setdefault("timeout", (5, 15))
        result = super().request(method, url, **kwargs)
        if cancel and cancel.is_set():
            raise PluginError("CANCELLED", "操作已取消。")
        result.raise_for_status()
        return result


class _Requests:
    """Only replace the pinned library's transport reference, not requests globally."""
    Session = TimedSession
    exceptions = requests.exceptions
    Response = requests.Response

    @staticmethod
    def get(url, **kwargs):
        with TimedSession() as session:
            return session.get(url, **kwargs)


apis.requests = _Requests
# The upstream logger can print full authentication records at DEBUG level.
# Plugin-owned diagnostics deliberately report categories and numeric codes only.
logging.getLogger("mijiaAPI").disabled = True


class _API(apis.mijiaAPI):
    def __init__(self, root, auth, persist):
        self._persist = persist
        # Initialize without invoking the upstream plaintext credential loader.
        # No auth file is created: _save_auth_data below owns all persistence.
        super().__init__(str(root / "unused-auth.json"))
        self.auth_data = dict(auth)
        self.locale = "zh_CN"
        self.service_login_url = "https://account.xiaomi.com/pass/serviceLogin?_json=true&sid=mijia&_locale=zh_CN"
        if self.auth_data:
            self._init_session()

    def _save_auth_data(self):
        self._persist(dict(self.auth_data))

    def _init_session(self):
        old = self.__dict__.get("session")
        if old:
            old.close()
        super()._init_session()


def parse_spec(content: dict) -> dict:
    props = content["props"]
    translations = props.get("i18n", {}).get("zh_cn", {})
    result = {"properties": [], "actions": []}
    for service in props["tree"]["services"]:
        siid = service["iid"]
        by_id = {}
        for prop in service.get("properties", []):
            piid = prop["iid"]
            item = {
                "key": f"{siid}.{piid}", "name": prop["type"],
                "service": translations.get(f"service:{siid:03d}") or service.get("description", service.get("type", "")),
                "description": translations.get(f"service:{siid:03d}:property:{piid:03d}") or prop.get("description", ""),
                "format": prop["format"], "access": prop["access"],
                "range": prop.get("valueRange"),
                "values": [{"value": v["value"], "label": translations.get(v.get("i18nKey", "")) or v.get("description", str(v["value"]))}
                           for v in prop.get("valueList", [])],
                "unit": prop.get("unit"), "siid": siid, "piid": piid,
            }
            by_id[piid] = item
            result["properties"].append(item)
        for action in service.get("actions", []):
            aiid = action["iid"]
            # Never guess parameters when the model does not describe them.
            inputs = action.get("in", [])
            result["actions"].append({
                "key": f"{siid}.{aiid}", "name": action["type"],
                "description": translations.get(f"service:{siid:03d}:action:{aiid:03d}") or action.get("description", ""),
                "siid": siid, "aiid": aiid,
                "inputs": [by_id.get(i, {"piid": i}) for i in inputs],
            })
    return result


class Cloud:
    def __init__(self, root: Path, auth: dict, persist):
        self.api = _API(root, auth, persist)
        self.specs = {}
        self.image_root = root / "images"

    def image(self, model: str):
        cache = self.image_root / (quote(model, safe="") + ".json")
        try:
            value = json.loads(cache.read_text("utf-8"))
            if isinstance(value, str) and value.startswith("data:image/"):
                return value
        except (OSError, ValueError):
            pass
        # 产品图片接口以重定向返回地址，签名复用米家协议实现。
        uri = "/v2/productconfig/get_icon"
        self.api._refresh_token()
        nonce = gen_nonce()
        security = self.api.auth_data["ssecurity"]
        params = generate_enc_params(uri, "POST", get_signed_nonce(security, nonce), nonce,
                                     {"data": json.dumps({"icon_name": "icon_real", "model": model}, separators=(",", ":"))}, security)
        response = self.api.session.post(self.api.api_base_url + uri, data=params, allow_redirects=False)
        if response.status_code != 302 or not response.headers.get("Location"):
            raise PluginError("IMAGE_UNAVAILABLE", f"产品图片不可用（HTTP {response.status_code}）。")
        # 图片下载使用独立请求，不能把账号 Cookie 带到 CDN。
        image = _Requests.get(response.headers["Location"])
        mime = image.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise PluginError("IMAGE_UNAVAILABLE", "产品接口没有返回可显示的图片。")
        value = f"data:{mime};base64," + base64.b64encode(image.content).decode("ascii")
        atomic_write(cache, json.dumps(value).encode("utf-8"))
        return value

    def login(self, on_qr):
        data = self.api._get_qr_login_data()
        if not data.get("refreshed"):
            out = io.BytesIO()
            qrcode.make(data["loginUrl"]).save(out, format="PNG")
            on_qr(out.getvalue())
            self.api._complete_qr_login(data)

    def reconnect(self):
        self.api.check_new_msg()

    def catalog(self):
        homes = self.api.get_homes_list()
        devices = self.api.get_devices_list() + self.api.get_shared_devices_list()
        location = {}
        home_names = {str(h["id"]): h["name"] for h in homes}
        for home in homes:
            for room in home.get("roomlist", []) or []:
                for did in room.get("dids", []) or []:
                    location[str(did)] = (home["name"], room["name"])
        clean = {}
        for device in devices:
            did = str(device["did"])
            if did in clean:
                continue
            home, room = location.get(did, (home_names.get(str(device.get("home_id")), "共享设备"), "未分配房间"))
            clean[did] = {"did": did, "name": str(device.get("name", did)), "model": str(device.get("model", "")),
                          "home": home, "room": room, "online": device.get("isOnline")}
        return clean

    def scenes(self):
        return {f"{s['home_id']}:{s['scene_id']}": {"key": f"{s['home_id']}:{s['scene_id']}",
                "name": str(s["name"]), "home_id": str(s["home_id"]), "scene_id": str(s["scene_id"])}
                for s in self.api.get_scenes_list()}

    def spec(self, model: str):
        if model not in self.specs:
            response = _Requests.get("https://home.miot-spec.com/spec/" + quote(model, safe="."))
            match = re.search(r'<script data-page="app" type="application/json">(.*?)</script>', response.text, re.S)
            if not match:
                raise PluginError("SPEC_UNAVAILABLE", "此设备的能力描述暂不可用。")
            self.specs[model] = parse_spec(json.loads(match.group(1)))
        return self.specs[model]

    def read(self, did, props):
        return self.api.get_devices_prop([{"did": did, "siid": p["siid"], "piid": p["piid"]} for p in props])

    def write(self, did, prop, value):
        return self.api.set_devices_prop({"did": did, "siid": prop["siid"], "piid": prop["piid"], "value": value})

    def action(self, did, action, values):
        return self.api.run_action({"did": did, "siid": action["siid"], "aiid": action["aiid"], "in": values})

    def scene(self, item):
        return self.api.run_scene(item["scene_id"], item["home_id"])

    def close(self):
        session = self.api.__dict__.get("session")
        if session:
            session.close()
