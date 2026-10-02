from __future__ import annotations

import copy
import json
import sys
import threading

import pytest
import requests

from mijia_plugin.cloud import PluginError, TimedSession, network_scope, parse_spec
from mijia_plugin.controller import Controller, public_error


PROPERTY = {"key": "2.1", "name": "on", "format": "bool", "access": ["read", "write"], "values": [], "range": None, "siid": 2, "piid": 1}


class RecordingLogger:
    def __init__(self):
        self.records = []

    def record(self, level, message, fields):
        assert sys.exception() is None, "日志不能自动附带上游私密异常正文"
        self.records.append({"level": level, "message": message, "fields": fields or {}})

    def info(self, message, *, fields=None):
        self.record("info", message, fields)

    def warning(self, message, *, fields=None):
        self.record("warning", message, fields)

    def error(self, message, *, fields=None):
        self.record("error", message, fields)


class FakeCloud:
    def __init__(self, root, auth, persist):
        self.persist = persist
        self.value = False
        self.writes = []
        self.actions = []
        self.scene_calls = []
        self.uid = "account-a"
        self.ack = 0
        self.fail_read = False
        self.spec_hook = None
        self.read_code = 0

    def login(self, callback):
        callback(b"test-qr")
        self.persist({"userId": self.uid, "serviceToken": "private-token-test"})

    def reconnect(self):
        pass

    def catalog(self):
        return {"lamp": {"did": "lamp", "name": "卧室灯", "model": "test.light.v1", "home": "我的家", "room": "卧室", "online": True},
                "secret": {"did": "secret", "name": "不开放的设备", "model": "test.lock.v1", "home": "我的家", "room": "玄关", "online": True}}

    def scenes(self):
        return {"h:1": {"key": "h:1", "name": "回家", "home_id": "h", "scene_id": "1"}}

    def spec(self, model):
        if self.spec_hook:
            self.spec_hook()
        return {"properties": [copy.deepcopy(PROPERTY)], "actions": [
            {"key": "2.1", "name": "toggle", "inputs": [], "siid": 2, "aiid": 1},
            {"key": "3.1", "name": "execute-text-directive", "inputs": [], "siid": 3, "aiid": 1}]}

    def read(self, did, props):
        if self.fail_read:
            raise requests.Timeout()
        return [{"siid": p["siid"], "piid": p["piid"], "value": self.value, "code": self.read_code, "token": "must-not-escape"} for p in props]

    def write(self, did, prop, value):
        self.writes.append((did, prop["key"], value))
        self.value = value
        return {"code": self.ack, "token": "must-not-escape"}

    def action(self, did, action, values):
        self.actions.append((did, action["key"], values))
        return {"code": 1}

    def scene(self, item):
        self.scene_calls.append(item)
        return {}

    def close(self):
        pass


@pytest.fixture
def controller(tmp_path):
    c = Controller(tmp_path, cloud_factory=FakeCloud, logger=RecordingLogger())
    c.start("login")
    c.worker.join(3)
    assert c.connected and not c.busy
    yield c
    c.close()


def grant(c, mode="control", scenes=()):
    c.save_permissions({"devices": {"lamp": {"mode": mode, "alias": "床头灯"}}, "scenes": list(scenes)})


def test_permissions_filter_catalog_and_enforce_read_write_scene(controller):
    c = controller
    assert c.tool("devices", {})["devices"] == []
    assert c.tool("read", {"device": "secret"})["error"]["code"] == "DEVICE_NOT_ALLOWED"
    grant(c, "read")
    assert [d["did"] for d in c.tool("devices", {"query": "床头"})["devices"]] == ["lamp"]
    assert c.tool("read", {"device": "lamp"})["properties"][0]["value"] is False
    assert c.tool("write", {"device": "lamp", "property": "2.1", "value": True})["error"]["code"] == "DEVICE_NOT_ALLOWED"
    assert not c.cloud.writes
    assert c.tool("scene", {"scene": "h:1"})["error"]["code"] == "SCENE_NOT_ALLOWED"
    grant(c, scenes=["h:1"])
    result = c.tool("scene", {"scene": "h:1"})
    assert result["status"] == "accepted" and not result["confirmed"]


def test_owner_reads_hidden_device_without_changing_pet_permissions(controller):
    before = copy.deepcopy(controller.policy)
    result = controller.read_for_user("secret")
    assert result["rows"][0]["value"] == "关"
    assert controller.policy == before
    assert controller.tool("read", {"device": "secret"})["error"]["code"] == "DEVICE_NOT_ALLOWED"
    assert "token" not in json.dumps(result)
    controller.cloud.spec_hook = controller.logout
    with pytest.raises(PluginError, match="取消"):
        controller.read_for_user("secret")


def test_state_view_uses_device_enums_units_and_reports_partial_errors():
    from mijia_plugin.state_view import state_rows
    props = [{**PROPERTY, "description": "开关", "service": "空调"},
             {**PROPERTY, "name": "target-temperature", "unit": "celsius"},
             {**PROPERTY, "name": "mode", "values": [{"value": 2, "label": "Cool"}]},
             {**PROPERTY, "name": "temperature"}]
    rows = state_rows(props, [{"code": 0, "value": True}, {"code": 0, "value": 26},
                              {"code": 0, "value": 2}, {"code": -704042011}])
    assert [row["value"] for row in rows] == ["开", "26 ℃", "制冷", "读取失败（错误码 -704042011）"]
    assert rows[1]["label"] == "目标温度"


def test_native_read_returns_immediately_and_polls_without_saving_grants(controller):
    from plugin import MijiaPlugin
    plugin = MijiaPlugin()
    plugin.controller, plugin.read_worker, plugin.read_result = controller, None, None
    entered, finish = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert finish.wait(3)
    controller.cloud.spec_hook = block
    request = {"request": {"id": "secret", "requestId": "one"}}
    try:
        assert plugin.start_read(request)["values"]["result"]["state"] == "running"
        assert entered.wait(3)
        assert plugin.read_status(request)["values"]["result"]["state"] == "running"
        assert plugin.records("devices")["grants"]["secret"]["mode"] == "hidden"
    finally:
        finish.set()
        plugin.read_worker.join(3)
    result = plugin.read_status(request)["values"]["result"]
    assert result["state"] == "completed" and result["rows"][0]["value"] == "关"
    plugin.save_records("devices", {"grants": {"lamp": {"mode": "read", "alias": "台灯"}}})
    plugin.save_records("scenes", {"grants": {"h:1": {"allowed": True}}})
    assert controller.policy["devices"]["lamp"]["mode"] == "read"
    assert controller.policy["scenes"] == ["h:1"]


def test_connection_actions_and_records_follow_login_state(controller):
    from plugin import MijiaPlugin
    plugin = MijiaPlugin()
    plugin.controller = controller
    assert plugin.settings()["available"] == ["refresh", "logout"]
    assert plugin.records("devices")["visible"] is True
    controller.logout()
    assert plugin.settings()["available"] == ["login"]
    assert plugin.records("devices")["visible"] is False
    controller.busy, controller.login_state, controller.qr = True, "waiting", b"fixture"
    assert plugin.settings()["available"] == ["cancel"]
    assert plugin.settings()["qr"] is not None


def test_write_readback_and_no_automatic_resend(controller):
    c = controller
    grant(c)
    result = c.tool("write", {"device": "lamp", "property": "2.1", "value": True})
    assert result["ok"] and result["confirmed"]
    assert "must-not-escape" not in json.dumps(result)
    c.cloud.fail_read = True
    c.cloud.ack = 1
    result = c.tool("write", {"device": "lamp", "property": "2.1", "value": False})
    assert result["ok"] and not result["confirmed"]
    assert result["readbackError"]["code"] == "NETWORK_TIMEOUT"
    assert len(c.cloud.writes) == 2
    assert c.logger.records[-1]["fields"]["reason_code"] == "NETWORK_TIMEOUT"


def test_rejected_write_never_reports_confirmation(controller):
    grant(controller)
    controller.cloud.ack = -704042011
    result = controller.tool("write", {"device": "lamp", "property": "2.1", "value": True})
    assert not result["ok"] and result["status"] == "rejected" and not result["confirmed"]


def test_cloud_owns_property_value_validation(controller):
    grant(controller)
    controller.cloud.ack = -706012043
    result = controller.tool("write", {"device": "lamp", "property": "2.1", "value": "true"})
    assert controller.cloud.writes == [("lamp", "2.1", "true")]
    assert result["ok"] is False and result["serviceCode"] == -706012043
    assert controller.logger.records[-1]["fields"]["service_code"] == -706012043


def test_permission_revoked_during_spec_fetch_prevents_write(controller):
    grant(controller)
    controller.cloud.spec_hook = lambda: grant(controller, "hidden")
    result = controller.tool("write", {"device": "lamp", "property": "2.1", "value": True})
    assert result["error"]["code"] == "DEVICE_NOT_ALLOWED"
    assert not controller.cloud.writes


def test_cloud_owns_action_validation_without_plugin_blacklist(controller):
    grant(controller)
    result = controller.tool("action", {"device": "lamp", "action": "3.1", "values": ["打开灯"]})
    assert result["status"] == "accepted"
    assert controller.cloud.actions == [("lamp", "3.1", ["打开灯"])]


def test_cancel_login_drops_late_credentials(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Delayed(FakeCloud):
        def login(self, callback):
            callback(b"test-qr")
            entered.set()
            assert release.wait(3)
            self.persist({"userId": "late", "serviceToken": "must-not-save"})
    c = Controller(tmp_path, cloud_factory=Delayed, logger=RecordingLogger())
    c.start("login")
    assert entered.wait(2)
    worker = c.worker
    c.logout()
    release.set()
    worker.join(3)
    assert not c.vault.exists()
    assert not c.connected and c.qr is None
    c.close()


def test_account_change_clears_permissions_and_logout_deletes_auth(controller):
    c = controller
    grant(c, scenes=["h:1"])
    c._persist(c.epoch, {"userId": "account-b", "serviceToken": "new"})
    assert c.policy["devices"] == {} and c.policy["scenes"] == []
    c.logout()
    assert not c.vault.exists() and not c.snapshot()["devices"]


def test_permissions_and_credentials_survive_restart(controller):
    grant(controller)
    c = Controller(controller.root, cloud_factory=FakeCloud, logger=RecordingLogger())
    try:
        c.resume()
        c.worker.join(3)
        assert c.tool("devices", {})["devices"][0]["alias"] == "床头灯"
        assert c.vault.read()["serviceToken"] == "private-token-test"
        if c.vault.path.suffix == ".dpapi":
            assert b"private-token-test" not in c.vault.path.read_bytes()
    finally:
        c.close()


def test_busy_does_not_queue_device_writes(controller):
    grant(controller)
    with controller.io_lock:
        assert controller.tool("write", {"device": "lamp", "property": "2.1", "value": True})["error"]["code"] == "BUSY"
    assert not controller.cloud.writes


def test_scene_failure_keeps_device_catalog_but_removes_stale_scene(controller):
    grant(controller, scenes=["h:1"])
    def fail():
        raise requests.ConnectionError("do-not-expose-cookie")
    controller.cloud.scenes = fail
    controller.start("refresh")
    controller.worker.join(3)
    assert controller.connected and controller.devices and not controller.scenes
    assert controller.status()["sceneError"]["code"] == "NETWORK_ERROR"
    assert any(r["level"] == "error" and r["fields"].get("reason_code") == "NETWORK_ERROR" for r in controller.logger.records)
    assert "do-not-expose-cookie" not in json.dumps(controller.logger.records)
    assert controller.tool("scene", {"scene": "h:1"})["error"]["code"] == "SCENE_NOT_ALLOWED"


def test_spec_preserves_action_parameter_definitions():
    raw = {"props": {"tree": {"services": [{"iid": 2, "properties": [{"iid": 1, "type": "level", "description": "Level", "format": "uint8", "access": ["write"], "valueRange": [0, 10, 2]}], "actions": [{"iid": 1, "type": "set-level", "in": [1]}]}]}}}
    spec = parse_spec(raw)
    prop = spec["actions"][0]["inputs"][0]
    assert prop["key"] == "2.1"
    assert prop["range"] == [0, 10, 2] and prop["format"] == "uint8"


def test_transport_sets_timeout_and_cancel_prevents_send(monkeypatch):
    calls = []
    def send(self, method, url, **kwargs):
        calls.append(kwargs)
        response = requests.Response()
        response.status_code = 200
        return response
    monkeypatch.setattr(requests.Session, "request", send)
    cancel = threading.Event()
    with network_scope(cancel), TimedSession() as session:
        session.get("https://example.invalid")
        assert calls[0]["timeout"] == (5, 15)
        session.get("https://example.invalid", timeout=120)
        assert calls[1]["timeout"] == 120
        cancel.set()
        with pytest.raises(PluginError):
            session.post("https://example.invalid")
    assert len(calls) == 2


def test_upstream_errors_never_echo_secret_bodies():
    from mijiaAPI.errors import APIError, LoginError
    for error in [APIError(-1, "serviceToken=hidden"), LoginError(-2, "Cookie: private"), ValueError("secret-body")]:
        public = json.dumps(public_error(error))
        assert "hidden" not in public and "private" not in public and "secret-body" not in public


def test_connection_failure_is_logged_without_raw_authentication_response(tmp_path):
    from mijiaAPI.errors import APIError
    class Failed(FakeCloud):
        def login(self, callback):
            raise APIError(-10005, "private-auth-response")
    logger = RecordingLogger()
    c = Controller(tmp_path, cloud_factory=Failed, logger=logger)
    try:
        c.start("login")
        c.worker.join(3)
        assert not c.busy and not c.connected
        failure = logger.records[-1]
        assert failure["level"] == "error"
        assert failure["fields"]["serviceCode"] == "-10005"
        assert "private-auth-response" not in json.dumps(logger.records)
    finally:
        c.close()


def test_gui_read_and_settings_failures_use_host_logger(controller):
    from plugin import MijiaPlugin
    plugin = MijiaPlugin()
    plugin.controller, plugin.read_worker, plugin.read_result = controller, None, None
    controller.cloud.fail_read = True
    request = {"request": {"id": "secret", "requestId": "failed-read"}}
    plugin.start_read(request)
    plugin.read_worker.join(3)
    assert plugin.read_status(request)["values"]["result"]["state"] == "failed"
    assert controller.logger.records[-1]["fields"]["reason_code"] == "NETWORK_TIMEOUT"
    with pytest.raises(RuntimeError):
        plugin.safe(lambda values: controller.save_permissions(values))({"devices": {"missing": {"mode": "read"}}, "scenes": []})
    assert controller.logger.records[-1]["fields"]["reason_code"] == "INVALID_PERMISSIONS"


def test_partial_read_failure_and_lifecycle_are_logged_without_poll_noise(controller):
    from plugin import MijiaPlugin
    plugin = MijiaPlugin()
    plugin.controller = controller
    assert controller.tool("status", {})["connected"] is True
    count = len(controller.logger.records)
    plugin.settings()
    plugin.records("devices")
    assert len(controller.logger.records) == count
    assert all(r["level"] == "info" for r in controller.logger.records)
    grant(controller)
    controller.cloud.read_code = -704042011
    result = controller.tool("read", {"device": "lamp"})
    assert result["properties"][0]["code"] == -704042011
    failure = next(r for r in controller.logger.records if r["level"] == "error")
    assert failure["fields"] == {"property": "2.1", "service_code": -704042011}
    assert "must-not-escape" not in json.dumps(controller.logger.records)
