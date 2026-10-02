from __future__ import annotations

import base64
import threading

from mijia_plugin.controller import Controller, public_error


def tool_definitions():
    device = {"type": "string", "description": "从设备列表取得的 did；不要猜测。"}
    key = {"type": "string", "description": "设备能力返回的 key，例如 2.1。"}
    definitions = [
        ("status", "mijia_status", "查询米家连接状态；未登录时请用户打开米家插件设置扫码。", {}, [], "low"),
        ("devices", "mijia_list_devices", "查找已授权的米家设备，支持名称、别名、房间、家庭搜索。同名设备须向用户澄清。", {"query": {"type": "string"}}, [], "low"),
        ("capabilities", "mijia_get_capabilities", "读取已授权设备的属性、取值范围、枚举与动作参数。控制前查询；不可猜测 key 或枚举值。", {"device": device}, ["device"], "low"),
        ("read", "mijia_get_state", "读取已授权设备的当前属性；省略 properties 时读取全部可读属性。每个属性的 code=0 才表示读取成功。", {"device": device, "properties": {"type": "array", "items": key}}, ["device"], "low"),
        ("write", "mijia_set_property", "设置获准控制的米家设备属性。value 必须符合设备能力的原始类型与取值。accepted 仅表示接收，confirmed=true 才表示读回目标状态；超时不要盲目重发。", {"device": device, "property": key, "value": {"type": ["string", "boolean", "number", "integer"]}}, ["device", "property", "value"], "high"),
        ("action", "mijia_run_action", "执行获准控制的设备动作，values 按能力 inputs 顺序提供。参数由米家校验；回执不代表动作完成，失败或超时后不要盲目重发。", {"device": device, "action": key, "values": {"type": "array", "items": {"type": ["string", "boolean", "number", "integer"]}}}, ["device", "action"], "high"),
        ("scenes", "mijia_list_scenes", "列出用户单独授权的米家手动场景。", {}, [], "low"),
        ("scene", "mijia_run_scene", "执行用户单独授权的手动场景，可能同时改变多个设备。只能使用列表返回的 key；回执不代表所有设备执行完成。", {"scene": {"type": "string"}}, ["scene"], "high"),
    ]
    for operation, name, description, properties, required, risk in definitions:
        yield operation, {"name": name, "description": description,
                          "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                          "group": "mijia", "risk": risk, "timeoutSeconds": 60}


class MijiaPlugin:
    def setup(self, context):
        self.read_result = None
        self.read_worker = None
        self.controller = Controller(context.data_path("connection"), logger=context.get("sakura.host.logging"))
        context.effect(self.close)
        context.provide("dev.sakura.mijia", self, exports=("status",))
        settings = context.get("sakura.host.settings")
        settings.register({
            "sectionId": "connection", "title": "账号", "order": 0,
            "presentation": {"component": "connection-status", "statusField": "connection", "imageField": "qr", "actionsField": "available"},
            "fields": [{"key": "connection", "label": "连接状态", "type": "status"},
                       {"key": "qr", "label": "米家 App 扫码", "type": "image"},
                       {"key": "available", "label": "可用操作", "type": "data", "readonly": True, "default": []}],
            "actions": [{"actionId": key, "label": label} for key, label in
                        [("login", "扫码登录"), ("refresh", "刷新设备"), ("cancel", "取消登录"), ("logout", "退出登录")]],
        }, load=self.settings, actions={key: self.safe(lambda _, k=key: self.connection_action(k))
                                       for key in ("login", "refresh", "cancel", "logout")})
        self.register_records(settings, "devices", "设备", [
            {"key": "name", "label": "设备", "type": "readonly"},
            {"key": "alias", "label": "别名", "type": "string", "default": ""},
            {"key": "mode", "label": "桌宠权限", "type": "select", "default": "hidden", "options": [
                {"value": "hidden", "label": "不开放"}, {"value": "read", "label": "仅查询"},
                {"value": "control", "label": "允许控制"}]}], "新设备默认不向桌宠开放。", inspect=True)
        self.register_records(settings, "scenes", "场景", [
            {"key": "name", "label": "场景", "type": "readonly"},
            {"key": "allowed", "label": "允许桌宠执行", "type": "boolean", "default": False}],
            "授权场景会开放其中的全部动作，包括未单独开放的设备。")
        host_tools = context.get("sakura.host.tools")
        for operation, descriptor in tool_definitions():
            host_tools.register(descriptor, lambda args, op=operation: self.controller.tool(op, args))
        self.controller.resume()

    def status(self):
        return self.controller.status()

    def settings(self):
        state = self.status()
        label = "已连接" if state["connected"] else "未连接"
        if state["busy"]:
            label = "等待扫码" if state["loginState"] == "waiting" else "正在连接或刷新"
        error = state["error"] or state["sceneError"]
        with self.controller.lock:
            png = self.controller.qr
        return {"connection": {"state": "working" if state["busy"] else "error" if error else "ready" if state["connected"] else "neutral",
                               "label": label, "message": error["message"] if error else ""},
                "qr": {"dataUrl": "data:image/png;base64," + base64.b64encode(png).decode("ascii"), "alt": "用米家 App 扫码，并在手机上确认"} if png else None,
                "available": (["logout"] if state["busy"] else ["refresh", "logout"]) if state["connected"] else ["cancel"] if state["busy"] else ["login"]}

    def safe(self, callback):
        def run(values):
            try:
                return callback(values)
            except Exception as error:
                problem = public_error(error)
            self.controller.report_error("米家设置操作失败", problem)
            raise RuntimeError(problem["message"]) from None
        return run

    def connection_action(self, key):
        if key == "logout" or (key == "cancel" and not self.controller.connected):
            self.controller.logout()
        elif key == "refresh" or (key == "login" and not self.controller.connected):
            self.controller.start(key)
        return {"values": self.settings()}

    def register_records(self, settings, section, title, columns, note, inspect=False):
        fields = [{"key": "items", "label": title, "type": "data", "readonly": True, "default": []},
                  {"key": "visible", "label": "已连接", "type": "boolean", "readonly": True, "default": False},
                  {"key": "grants", "label": "桌宠权限", "type": "data", "default": {}}]
        presentation = {"component": "record-table", "itemsField": "items", "valueField": "grants", "columns": columns, "note": note, "visibleField": "visible"}
        actions = {}
        if inspect:
            fields += [{"key": "request", "label": "读取请求", "type": "data", "default": {}},
                       {"key": "result", "label": "设备状态", "type": "data", "readonly": True, "default": {}}]
            presentation.update(inspectAction="read", statusAction="read_status", requestField="request", resultField="result")
            actions["read"] = self.safe(self.start_read)
            actions["read_status"] = self.safe(self.read_status)
        settings.register({"sectionId": section, "title": title, "order": 1 if inspect else 2,
                           "fields": fields, "presentation": presentation,
                           "actions": [{"actionId": key, "label": "读取状态"} for key in actions]},
                          load=lambda: self.records(section), save=self.safe(lambda values: self.save_records(section, values)), actions=actions)

    def start_read(self, values):
        request = values["request"]
        did, request_id = request["id"], request["requestId"]
        with self.controller.lock:
            result = {"id": did, "requestId": request_id, "title": "设备状态", "rows": [], "message": "", "state": "running"}
            if self.read_worker and self.read_worker.is_alive():
                self.controller.logger.warning("米家正在读取设备，未受理重复读取")
                return {"values": {"result": {**result, "state": "failed", "message": "正在读取设备，请稍后再试。"}}}
            self.read_result = result
            self.controller.logger.info("米家开始手动读取设备状态")
            def read():
                problem = None
                try:
                    outcome = {**self.controller.read_for_user(did), "state": "completed"}
                except Exception as error:
                    problem = public_error(error)
                    outcome = {"state": "failed", "message": problem["message"]}
                if problem:
                    self.controller.report_error("米家手动读取设备状态失败", problem)
                else:
                    self.controller.logger.info("米家手动读取设备状态完成", fields={"property_count": len(outcome["rows"])})
                with self.controller.lock:
                    self.read_result = {**result, **outcome}
            self.read_worker = threading.Thread(target=read, daemon=True, name="mijia-state")
            self.read_worker.start()
            return {"values": {"result": dict(result)}}

    def read_status(self, values):
        request = values.get("request", {})
        with self.controller.lock:
            if self.read_result and all(self.read_result[k] == request.get(k) for k in ("id", "requestId")):
                return {"values": {"result": dict(self.read_result)}}
        return {"values": {"result": {**request, "state": "failed", "title": "设备状态", "rows": [], "message": "读取已结束，请重新读取。"}}}

    def records(self, section):
        snapshot = self.controller.snapshot()
        items, grants = [], {}
        for item in snapshot[section]:
            key = item["did"] if section == "devices" else item["key"]
            description = " / ".join(str(item.get(k) or "") for k in ("home", "room") if item.get(k))
            items.append({"id": key, "label": item["name"], "description": description, "values": {"name": item["name"]},
                          "status": {"state": "warning", "label": "离线"} if section == "devices" and item.get("online") is False else None})
            grants[key] = {"mode": item["mode"], "alias": item["alias"]} if section == "devices" else {"allowed": item["allowed"]}
        return {"visible": snapshot["connected"], "items": items, "grants": grants, **({"request": {}, "result": {}} if section == "devices" else {})}

    def save_records(self, section, values):
        with self.controller.lock:
            policy = self.controller.policy
            devices = values["grants"] if section == "devices" else {key: value for key, value in policy["devices"].items() if key in self.controller.devices}
            scenes = [key for key, value in values["grants"].items() if value.get("allowed") is True] if section == "scenes" else [key for key in policy["scenes"] if key in self.controller.scenes]
            self.controller.save_permissions({"devices": devices, "scenes": scenes})
        return {}

    def close(self):
        self.controller.close()
