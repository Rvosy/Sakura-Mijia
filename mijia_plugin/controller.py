from __future__ import annotations

import copy
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import requests

from .cloud import Cloud, PluginError, network_scope, validate_value
from .storage import Vault, atomic_write
from .state_view import state_rows


def public_error(error: Exception) -> dict:
    if isinstance(error, PluginError):
        return {"code": error.code, "message": str(error)}
    if isinstance(error, requests.Timeout):
        return {"code": "NETWORK_TIMEOUT", "message": "米家请求超时；如为控制操作，结果未知，请先查询设备状态，勿直接重发。"}
    if isinstance(error, requests.ConnectionError):
        return {"code": "NETWORK_ERROR", "message": "无法连接米家服务，请检查网络。"}
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        return {"code": "HTTP_ERROR", "message": "米家服务返回 HTTP 错误。", "httpStatus": status}
    if type(error).__name__ == "LoginError":
        return {"code": "LOGIN_REQUIRED", "message": "登录未完成或凭据失效，请重新扫码。"}
    if type(error).__name__ == "APIError":
        code = re.search(r"code[:：= ]+(-?\d+)", str(error), re.I)
        return {"code": "MIJIA_API_ERROR", "message": "米家服务拒绝了请求。", "serviceCode": code.group(1) if code else None}
    # Do not expose raw upstream exceptions: they may contain cookies or response bodies.
    return {"code": "PLUGIN_ERROR", "message": "操作失败。", "exceptionType": type(error).__name__}


def _matches(items, key):
    for item in items:
        if item["key"] == key:
            return item
    raise PluginError("CAPABILITY_NOT_FOUND", "设备没有这项能力，请先查询设备能力。")


def _action_allowed(action):
    return "text-directive" not in action["name"] and not any(p.get("unsupported") for p in action["inputs"])


class Controller:
    def __init__(self, root: Path, *, cloud_factory=Cloud, logger=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.vault = Vault(root)
        self.policy_path = root / "permissions.json"
        self.policy = json.loads(self.policy_path.read_text("utf-8")) if self.policy_path.exists() else {"account": "", "devices": {}, "scenes": []}
        self.factory = cloud_factory
        self.logger = logger
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        self.cancel = threading.Event()
        self.epoch = 0
        self.closed = False
        self.cloud = None
        self.worker = None
        self.devices = {}
        self.scenes = {}
        self.qr = None
        self.connected = False
        self.busy = False
        self.login_state = "idle"
        self.error = None
        self.scene_error = None
        self.last_refresh = None
        self.last_operation = None

    def resume(self):
        if self.vault.exists():
            self.start("reconnect")

    def _save_policy(self):
        atomic_write(self.policy_path, json.dumps(self.policy, ensure_ascii=False, indent=2).encode("utf-8"))

    def _active(self, epoch):
        if self.closed or epoch != self.epoch or self.cancel.is_set():
            raise PluginError("CANCELLED", "操作已取消。")

    def _persist(self, epoch, auth):
        with self.lock:
            self._active(epoch)
            uid = str(auth.get("userId", ""))
            if not uid:
                raise PluginError("INVALID_ACCOUNT", "米家未返回有效账号。")
            if self.policy["account"] != uid:
                self.policy = {"account": uid, "devices": {}, "scenes": []}
                self._save_policy()
            self.vault.save(auth)

    def status(self):
        with self.lock:
            modes = self.policy["devices"]
            return {"connected": self.connected, "busy": self.busy, "loginState": self.login_state,
                    "error": copy.deepcopy(self.error), "sceneError": copy.deepcopy(self.scene_error),
                    "hasQr": self.qr is not None, "lastRefresh": self.last_refresh,
                    "deviceCount": len(self.devices),
                    "allowedCount": sum(1 for did, rule in modes.items() if did in self.devices and rule["mode"] != "hidden"),
                    "lastOperation": copy.deepcopy(self.last_operation)}

    def snapshot(self):
        with self.lock:
            return {**self.status(), "devices": [dict(d, **self.policy["devices"].get(did, {"mode": "hidden", "alias": ""}))
                    for did, d in self.devices.items()],
                    "scenes": [dict(s, allowed=key in self.policy["scenes"]) for key, s in self.scenes.items()]}

    def start(self, kind):
        with self.lock:
            if self.closed:
                raise PluginError("CANCELLED", "插件已停止。")
            if self.busy:
                return self.status()
            if kind == "refresh" and not self.connected:
                raise PluginError("LOGIN_REQUIRED", "请先扫码登录。")
            self.busy = True
            self.error = None
            self.qr = None
            epoch, cancel = self.epoch, self.cancel
            if kind in ("login", "reconnect"):
                self.login_state = "starting"
            self.worker = threading.Thread(target=self._background, args=(kind, epoch, cancel), daemon=True, name="mijia-connection")
            self.worker.start()
            return self.status()

    def _background(self, kind, epoch, cancel):
        client = None
        try:
            with self.io_lock, network_scope(cancel, 180 if kind == "login" else 90):
                with self.lock:
                    self._active(epoch)
                    client = self.cloud if kind == "refresh" else None
                if client is None:
                    client = self.factory(self.root, self.vault.read(), lambda auth: self._persist(epoch, auth))
                    if kind == "login":
                        def on_qr(png):
                            with self.lock:
                                self._active(epoch)
                                self.qr = png
                                self.login_state = "waiting"
                        client.login(on_qr)
                    else:
                        client.reconnect()
                    with self.lock:
                        self._active(epoch)
                        old = self.cloud
                        self.cloud = client
                        self.connected = True
                        self.login_state = "connected"
                        self.qr = None
                    if old and old is not client:
                        old.close()
                devices = client.catalog()
                with self.lock:
                    self._active(epoch)
                    self.devices = devices
                    self.last_refresh = time.time()
                # Some accounts/devices have no scene access; device discovery
                # remains useful, while stale scene permissions cannot execute.
                try:
                    scenes = client.scenes()
                    scene_error = None
                except Exception as error:
                    scenes, scene_error = {}, public_error(error)
                with self.lock:
                    self._active(epoch)
                    self.scenes = scenes
                    self.scene_error = scene_error
        except Exception as error:
            with self.lock:
                if epoch == self.epoch and not self.closed:
                    self.error = public_error(error)
                    self.qr = None
                    if not self.connected:
                        self.login_state = "error"
                    if self.logger:
                        self.logger.warning("米家连接操作失败", fields={"reason_code": self.error["code"]})
        finally:
            with self.lock:
                if epoch == self.epoch:
                    self.busy = False
                keep = self.cloud is client and epoch == self.epoch and not self.closed
            if client and not keep:
                client.close()

    def save_permissions(self, value):
        with self.lock:
            if not self.connected:
                raise PluginError("LOGIN_REQUIRED", "请先扫码登录。")
            devices, scenes = value.get("devices"), value.get("scenes")
            if not isinstance(devices, dict) or not isinstance(scenes, list):
                raise PluginError("INVALID_PERMISSIONS", "设备权限格式无效。")
            clean = {}
            for did, rule in devices.items():
                if did not in self.devices or not isinstance(rule, dict) or rule.get("mode") not in ("hidden", "read", "control"):
                    raise PluginError("INVALID_PERMISSIONS", "设备列表已变化，请刷新后重试。")
                alias = rule.get("alias", "")
                if not isinstance(alias, str) or len(alias) > 120:
                    raise PluginError("INVALID_ALIAS", "设备别名最多 120 个字符。")
                if rule["mode"] != "hidden" or alias.strip():
                    clean[did] = {"mode": rule["mode"], "alias": alias.strip()}
            if any(not isinstance(key, str) or key not in self.scenes for key in scenes):
                raise PluginError("INVALID_PERMISSIONS", "场景列表已变化，请刷新后重试。")
            self.policy = {**self.policy, "devices": clean, "scenes": list(dict.fromkeys(scenes))}
            self._save_policy()
            return {"saved": True}

    def logout(self):
        with self.lock:
            self.cancel.set()
            self.epoch += 1
            self.cancel = threading.Event()
            old = self.cloud
            self.cloud = None
            self.connected = self.busy = False
            self.qr = None
            self.login_state = "idle"
            self.error = self.scene_error = self.last_operation = None
            self.devices, self.scenes = {}, {}
            self.last_refresh = None
            self.vault.clear()
            self.policy = {"account": "", "devices": {}, "scenes": []}
            self._save_policy()
        if old:
            old.close()
        return {"loggedOut": True}

    def _device(self, did, write=False):
        if not self.connected:
            raise PluginError("LOGIN_REQUIRED", "请在米家插件设置中扫码登录。")
        rule = self.policy["devices"].get(did, {})
        if did not in self.devices or rule.get("mode", "hidden") == "hidden" or (write and rule.get("mode") != "control"):
            raise PluginError("DEVICE_NOT_ALLOWED", "此设备未获准执行该操作，请在插件设置中调整权限。")
        return self.devices[did]

    @contextmanager
    def _operation(self):
        with self.lock:
            epoch, cancel = self.epoch, self.cancel
            self._active(epoch)
            if not self.connected:
                raise PluginError("LOGIN_REQUIRED", "请在米家插件设置中扫码登录。")
        if not self.io_lock.acquire(blocking=False):
            raise PluginError("BUSY", "米家正在处理另一个请求，请稍后再试。")
        try:
            with self.lock:
                self._active(epoch)
                client = self.cloud
            with network_scope(cancel):
                yield client, epoch
            with self.lock:
                self._active(epoch)
        finally:
            self.io_lock.release()

    def tool(self, name, args):
        try:
            return self._tool(name, args)
        except Exception as error:
            problem = public_error(error)
            if self.logger:
                self.logger.warning("米家工具调用失败", fields={"reason_code": problem["code"]})
            return {"ok": False, "error": problem}

    def read_for_user(self, did):
        """Settings-only read. The pet's allowlist is not the owner's authority."""
        with self._operation() as (client, epoch):
            with self.lock:
                if not isinstance(did, str) or did not in self.devices:
                    raise PluginError("DEVICE_NOT_FOUND", "设备列表已变化，请刷新设备。")
                device = dict(self.devices[did])
            spec = client.spec(device["model"])
            with self.lock:
                self._active(epoch)
                if did not in self.devices:
                    raise PluginError("DEVICE_NOT_FOUND", "设备列表已变化，请刷新设备。")
            props = [p for p in spec["properties"] if "read" in p["access"]]
            if not props:
                return {"id": did, "title": device["name"], "rows": [], "message": "此设备没有可读取的属性。"}
            values = self._read_result(client.read(did, props), props)
            return {"id": did, "title": device["name"], "rows": state_rows(props, values), "message": ""}

    def _tool(self, name, args):
        if name == "status":
            state = self.status()
            return {"connected": state["connected"], "busy": state["busy"], "allowedCount": state["allowedCount"], "error": state["error"]}
        with self.lock:
            if not self.connected:
                raise PluginError("LOGIN_REQUIRED", "请在米家插件设置中扫码登录。")
            if name == "devices":
                query = str(args.get("query", "")).casefold()
                rows = []
                for did, d in self.devices.items():
                    rule = self.policy["devices"].get(did, {})
                    if rule.get("mode", "hidden") == "hidden":
                        continue
                    item = {**d, "alias": rule.get("alias", ""), "permission": rule["mode"]}
                    if query in " ".join(str(item.get(k, "")) for k in ("name", "alias", "home", "room", "model")).casefold():
                        rows.append(item)
                return {"devices": rows, "catalogUpdatedAt": self.last_refresh}
            if name == "scenes":
                return {"scenes": [s for key, s in self.scenes.items() if key in self.policy["scenes"]]}
        with self._operation() as (client, epoch):
            if name == "scene":
                with self.lock:
                    self._active(epoch)
                    key = args.get("scene")
                    if key not in self.scenes or key not in self.policy["scenes"]:
                        raise PluginError("SCENE_NOT_ALLOWED", "此场景未获准执行。")
                    item = self.scenes[key]
                raw = client.scene(item)
                # Upstream may return an empty result object on a successful
                # request; a false boolean or explicit nonzero code is failure.
                accepted = raw is True or (isinstance(raw, dict) and raw.get("code", 0) == 0)
                result = {"ok": accepted, "status": "accepted" if accepted else "rejected", "confirmed": False,
                          "message": "米家已接收场景请求，场景内各设备状态尚未确认。" if accepted else "米家拒绝了场景请求。"}
            else:
                did = args.get("device")
                with self.lock:
                    device = self._device(did, name in ("write", "action"))
                spec = client.spec(device["model"])
                # Authorization is checked again after the network/spec lookup.
                with self.lock:
                    self._active(epoch)
                    self._device(did, name in ("write", "action"))
                if name == "capabilities":
                    return {"device": did, "properties": spec["properties"],
                            "actions": [dict(a, available=_action_allowed(a)) for a in spec["actions"]]}
                if name == "read":
                    keys = args.get("properties")
                    props = [_matches(spec["properties"], key) for key in keys] if keys else [p for p in spec["properties"] if "read" in p["access"]]
                    if not props or any("read" not in p["access"] for p in props):
                        raise PluginError("NOT_READABLE", "所选属性不可读取。")
                    raw = client.read(did, props)
                    values = self._read_result(raw, props)
                    return {"device": did, "observedAt": time.time(), "properties": values}
                if name == "write":
                    prop = _matches(spec["properties"], args.get("property"))
                    if "write" not in prop["access"]:
                        raise PluginError("NOT_WRITABLE", "所选属性不可写入。")
                    value = args.get("value")
                    validate_value(prop, value)
                    raw = client.write(did, prop, value)
                    result = self._receipt(raw)
                    if result["ok"] and "read" in prop["access"]:
                        try:
                            observed = self._read_result(client.read(did, [prop]), [prop])[0]
                            result["observed"] = observed
                            result["confirmed"] = observed["code"] == 0 and type(observed.get("value")) is type(value) and observed.get("value") == value
                        except Exception as error:
                            result["readbackError"] = public_error(error)
                    if result["ok"]:
                        result["message"] = "已读回目标状态。" if result.get("confirmed") else "指令已被接收，设备状态尚未确认。"
                elif name == "action":
                    action = _matches(spec["actions"], args.get("action"))
                    values = args.get("values", [])
                    if not _action_allowed(action):
                        raise PluginError("ACTION_UNAVAILABLE", "此动作缺少参数定义或可绕过设备授权范围，未开放。")
                    if not isinstance(values, list) or len(values) != len(action["inputs"]):
                        raise PluginError("INVALID_ARGUMENTS", "动作参数数量与设备能力不符。")
                    for prop, value in zip(action["inputs"], values):
                        validate_value(prop, value)
                    result = self._receipt(client.action(did, action, values))
                elif name != "write":
                    raise PluginError("UNKNOWN_TOOL", "未知工具。")
            with self.lock:
                self._active(epoch)
                self.last_operation = {"time": time.time(), "kind": name, "ok": result["ok"], "confirmed": result.get("confirmed", False)}
            return result

    @staticmethod
    def _receipt(raw):
        if isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        code = raw.get("code") if isinstance(raw, dict) else None
        return {"ok": code in (0, 1), "status": "accepted" if code in (0, 1) else "rejected", "serviceCode": code,
                "confirmed": False, "message": "指令已被接收，完成情况尚未确认。" if code in (0, 1) else "设备未确认接收指令。"}

    @staticmethod
    def _read_result(raw, props):
        rows = raw if isinstance(raw, list) else [raw]
        by_key = {(r.get("siid"), r.get("piid")): r for r in rows if isinstance(r, dict)}
        result = []
        for prop in props:
            row = by_key.get((prop["siid"], prop["piid"]), {})
            item = {"property": prop["key"], "code": row.get("code", -1)}
            if item["code"] == 0 and "value" in row:
                item["value"] = row["value"]
            result.append(item)
        return result

    def close(self):
        with self.lock:
            self.closed = True
            self.cancel.set()
            self.epoch += 1
            client = self.cloud
            self.cloud = None
        if client:
            client.close()
        if self.worker:
            self.worker.join(timeout=1)
