"""在 Sakura 设置窗口中验证筛选、权限草稿和异步读取，使用隔离设备数据。"""
import argparse
import functools
import http.server
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--sakura", required=True, type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]


def field(key, kind="data", readonly=True, default=None):
    return dict(key=key, label=key, type=kind, readonly=readonly, default=default,
                description="", options=[], placement="row", actionIds=[])


devices = [dict(id="lamp", label="书桌灯", home="我的家", room="书房", description="我的家 / 书房", online=True, image=None),
           dict(id="fan", label="风扇", home="我的家", room="卧室", description="我的家 / 卧室", online=False, image=None),
           dict(id="other", label="另一盏灯", home="另一家庭", room="书房", description="另一家庭 / 书房", online=True, image=None)]
connection = dict(sectionId="connection", title="账号", reasonCode="READY", surface=None, collections=[],
    presentation=dict(component="connection-status", statusField="connection", imageField="qr", actionsField="available"),
    fields=[field("connection", "status"), field("qr", "image"), field("available")],
    actions=[dict(actionId=key, label=label) for key, label in [("login", "扫码登录"), ("refresh", "刷新设备"), ("logout", "退出登录")]],
    values=dict(connection=dict(state="ready", label="已连接", message=""), qr=None, available=["refresh", "logout"]))
workspace = dict(sectionId="workspace", title="设备与场景", reasonCode="READY", surface=None, collections=[],
    presentation=dict(component="module", visibleField="visible", source=(root / "mijia_plugin/workspace.js").read_text("utf-8")),
    fields=[field("items"), field("sceneItems"), field("grants", readonly=False, default={}), field("sceneGrants", readonly=False, default={}),
            field("visible", "boolean"), field("request", readonly=False, default={}), field("result")],
    actions=[dict(actionId=key, label="读取状态") for key in ["read", "read_status"]],
    values=dict(items=devices, sceneItems=[dict(id="night", label="晚安", description="我的家")],
                grants={}, sceneGrants={}, visible=True, request={}, result={}))
data = dict(schemaVersion=1, state="ready", reasonCode="READY", windowGeneration=1, coreGenerationId="fixture", plugins=[dict(
    installId="mijia-ui", pluginId="dev.sakura.mijia", name="米家", version="0.3.1", author="Sakura Community", description="米家设备",
    enabled=True, required=False, supported=True, source="user", canUninstall=True, provides=["dev.sakura.mijia"], requires=[],
    missingServices=[], state="active", reasonCode="ACTIVE", sections=[connection, workspace],
    presentation=dict(kind="extension", category="connectivity", icon="link"))])
script = """
import {createPluginSettingsFeature} from './plugin-settings.js';
import {enhanceSelect,refreshSelect,closeSelects,focusSelect} from './select-control.js';
const feature=createPluginSettingsFeature({document,window,invoke:window.nativeInvoke,onDirty:()=>{},onError:e=>{if(e)window.lastError=String(e);},
  notify:()=>{},confirmAction:async()=>true,enhanceSelect,refreshSelect,closeSelects,focusSelect,replayMotion:()=>{},
  removeOverlayAfterExit:async e=>e.remove(),showPage:()=>{},isCharacterTransitioning:()=>false,hasPendingCharacterSelection:()=>false});
feature.initialize(await window.nativeInvoke('settings_plugins_get'));window.feature=feature;feature.openPlugin('mijia-ui',true);
"""
calls = []
pending = False


def invoke(command, values=None):
    if command == "settings_plugins_get":
        return data
    calls.append((command, values))
    if command == "settings_plugins_action":
        return dict(values=dict(result={**values["values"]["request"], "state": "running" if pending else "completed",
                    "rows": [dict(group="灯光", label="电源", value="开启")], "message": ""}))
    if command == "settings_plugins_save":
        workspace["values"].update(values["values"])
        return dict(saved=True, pluginId=values["pluginId"], sectionId=values["sectionId"],
                    changePlan="applied", applicationState="applied", applicationReasonCode="READY")
    return data


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(args.sakura)))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page(viewport=dict(width=1200, height=860))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function("nativeInvoke", invoke)
        page.route("**/settings/settings.js", lambda route: route.fulfill(content_type="text/javascript", body=script))
        page.goto(f"http://127.0.0.1:{server.server_port}/desktop/frontend/settings/")
        ui = page.locator(".mijia-workspace")
        expect(ui.locator(".mijia-card")).to_have_count(3)
        ui.get_by_role("combobox", name="家庭", exact=True).click()
        page.get_by_role("option", name="我的家", exact=True).click()
        expect(ui.locator(".mijia-card")).to_have_count(2)
        ui.locator(".mijia-rooms").get_by_role("button", name="书房", exact=True).click()
        expect(ui.locator(".mijia-card")).to_have_count(1)
        ui.locator(".mijia-card").click()
        ui.get_by_role("radio", name="仅查询", exact=True).check()
        alias = ui.get_by_role("textbox", name="别名", exact=True)
        alias.fill("工作灯")
        alias.press("Enter")
        expect(ui.get_by_role("button", name="返回设备列表", exact=True)).to_be_visible()
        devices[0]["image"] = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="
        page.evaluate("window.feature.refreshCurrent()")
        expect(alias).to_be_focused()
        expect(alias).to_have_value("工作灯")
        expect(ui.get_by_role("radio", name="仅查询", exact=True)).to_be_checked()
        ui.get_by_role("button", name="读取状态", exact=True).click()
        expect(ui.locator(".mijia-state")).to_contain_text("开启")
        ui.get_by_role("button", name="返回设备列表", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.evaluate("window.feature.save()")
        saved = [values["values"] for command, values in calls if command == "settings_plugins_save"][-1]
        assert saved["grants"]["lamp"] == dict(mode="read", alias="工作灯")
        assert "sceneGrants" not in saved, "保存设备权限不应提交未编辑的场景授权"
        ui.get_by_role("searchbox").fill("工作灯")
        expect(ui.locator(".mijia-card")).to_have_count(1)
        ui.get_by_role("button", name="场景 1", exact=True).click()
        ui.locator(".mijia-card").click()
        ui.get_by_role("checkbox", name="允许桌宠执行", exact=True).check()
        ui.get_by_role("button", name="返回场景列表", exact=True).click()
        ui.get_by_role("button", name="设备 3", exact=True).click()
        ui.locator(".mijia-card").filter(has_text="书桌灯").click()
        expect(ui.get_by_role("textbox", name="别名", exact=True)).to_have_value("工作灯")
        expect(ui.get_by_role("radio", name="仅查询", exact=True)).to_be_checked()
        pending = True
        ui.get_by_role("button", name="读取状态", exact=True).click()
        expect(ui.get_by_role("button", name="正在读取…", exact=True)).to_be_disabled()
        ui.get_by_role("button", name="返回设备列表", exact=True).click()
        ui.locator(".mijia-card").filter(has_text="风扇").click()
        pending = False
        expect(ui.get_by_role("button", name="读取状态", exact=True)).to_be_enabled()
        expect(ui.locator(".mijia-state")).to_be_empty()
        ui.get_by_role("button", name="返回设备列表", exact=True).click()
        ui.get_by_role("button", name="场景 1", exact=True).click()
        ui.locator(".mijia-card").click()
        expect(ui.get_by_role("checkbox", name="允许桌宠执行", exact=True)).to_be_checked()
        page.set_viewport_size(dict(width=440, height=720))
        assert page.locator("dialog").evaluate("e => e.scrollWidth <= e.clientWidth")
        workspace["values"]["visible"] = False
        connection["values"] = dict(connection=dict(state="neutral", label="未连接", message=""), qr=None, available=["login"])
        page.evaluate("window.feature.refreshCurrent()")
        expect(ui).to_be_hidden()
        expect(page.get_by_role("button", name="扫码登录", exact=True)).to_be_visible()
        assert not errors, errors
        assert all(values["actionId"] in {"read", "read_status"} for command, values in calls if command == "settings_plugins_action")
        print(json.dumps(dict(result="passed", errors=errors)))
        browser.close()
finally:
    server.shutdown()
