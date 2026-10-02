"""Human-readable property values from each device's MIoT description."""
from __future__ import annotations

import re

NAMES = {
    "on": "电源", "mode": "模式", "temperature": "温度", "target-temperature": "目标温度",
    "relative-humidity": "相对湿度", "brightness": "亮度", "color-temperature": "色温",
    "fan-level": "风速", "battery-level": "电量", "power-consumption": "耗电量",
    "electric-power": "功率", "voltage": "电压", "electric-current": "电流",
    "pm2.5-density": "PM2.5", "co2-density": "二氧化碳浓度", "status": "状态",
    "fault": "故障", "horizontal-swing": "左右扫风", "vertical-swing": "上下扫风",
    "child-lock": "童锁", "light": "灯", "air-conditioner": "空调", "switch": "开关",
    "outlet": "插座", "environment": "环境", "indicator-light": "指示灯", "battery": "电池",
}
UNITS = {"percentage": "%", "celsius": "℃", "kelvin": "K", "fahrenheit": "℉",
         "watt": "W", "kilowatt-hour": "kWh", "volt": "V", "ampere": "A",
         "micrograms-per-cubic-meter": "μg/m³", "ppm": "ppm", "seconds": "秒",
         "minutes": "分钟", "hours": "小时", "lux": "lx", "pascal": "Pa",
         "none": "", "": ""}
ENUMS = {"auto": "自动", "cool": "制冷", "heat": "制热", "dry": "除湿", "fan": "送风",
         "sleep": "睡眠", "silent": "静音", "low": "低", "medium": "中", "high": "高",
         "idle": "待机", "charging": "充电中", "completed": "已完成"}
PRIMARY = {"on", "mode", "temperature", "target-temperature", "relative-humidity", "brightness",
           "color-temperature", "fan-level", "battery-level", "status", "fault", "electric-power",
           "pm2.5-density", "co2-density", "horizontal-swing", "vertical-swing", "child-lock"}


def short_name(value):
    parts = str(value).split(":")
    return parts[3] if len(parts) > 4 and parts[0] == "urn" else str(value)


def label(description, name):
    if description and re.search(r"[\u3400-\u9fff]", description):
        return description
    return NAMES.get(short_name(name), description or short_name(name))


def property_value(prop, result):
    if result.get("code") != 0:
        return f"读取失败（错误码 {result.get('code', -1)}）"
    if "value" not in result:
        return "未返回数值"
    value = result["value"]
    for option in prop.get("values", []):
        if type(option["value"]) is type(value) and option["value"] == value:
            text = option["label"]
            return ENUMS.get(str(text).casefold(), str(text))
    if type(value) is bool:
        return ("开" if value else "关") if short_name(prop["name"]) == "on" else ("是" if value else "否")
    if value is None:
        return "无数据"
    if not isinstance(value, (str, int, float)):
        return "此属性返回了复合数据，暂不支持显示"
    unit = UNITS.get(prop.get("unit") or "", prop.get("unit") or "")
    text = str(value)
    return f"{text} {unit}" if unit else text


def state_rows(props, values):
    has_primary = any(short_name(p["name"]) in PRIMARY for p in props)
    return [{"group": label(p.get("service", ""), p.get("service", "")),
             "label": label(p.get("description", ""), p["name"]),
             "value": property_value(p, value),
             "secondary": has_primary and short_name(p["name"]) not in PRIMARY} for p, value in zip(props, values)]
