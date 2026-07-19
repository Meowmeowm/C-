#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
12306 余票监控脚本
==================

轮询 12306 官方余票查询接口，当指定车次放出指定席别（如二等座/一等座）的余票时，
通过 Bark / Server酱 / PushPlus 推送到手机，并在终端响铃 + 弹出桌面通知。

仅做"监控 + 提醒"，不会自动下单。收到通知后请立即打开 12306 APP 购票/改签。

用法:
    pip install requests
    python ticket_monitor.py --config config.json

需要在国内网络环境下运行（12306 会封锁海外 IP）。
"""

import argparse
import json
import platform
import random
import re
import subprocess
import sys
import time
from datetime import datetime

import requests

BASE = "https://kyfw.12306.cn"
INIT_URL = BASE + "/otn/leftTicket/init"
STATION_JS_URL = BASE + "/otn/resources/js/framework/station_name.js"

# 12306 会不定期更换查询接口路径，优先从 init 页面解析，失败时逐个尝试
QUERY_CANDIDATES = [
    "leftTicket/query", "leftTicket/queryZ", "leftTicket/queryA",
    "leftTicket/queryG", "leftTicket/queryO", "leftTicket/queryY",
    "leftTicket/queryE",
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Referer": INIT_URL,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# 查询结果按 "|" 分隔后各席别所在的下标
SEAT_FIELDS = {
    "商务座": 32,
    "特等座": 25,
    "一等座": 31,
    "二等座": 30,
    "高级软卧": 21,
    "软卧": 23,
    "动卧": 33,
    "硬卧": 28,
    "软座": 24,
    "硬座": 29,
    "无座": 26,
}


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def new_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(INIT_URL, timeout=15)  # 拿 JSESSIONID 等 Cookie
    except requests.RequestException as e:
        log("初始化会话失败: %s" % e)
    return s


def load_stations(session):
    """站名 -> 电报码，如 北京南 -> VNP"""
    resp = session.get(STATION_JS_URL, timeout=20)
    resp.raise_for_status()
    stations = {}
    for item in resp.text.split("@"):
        parts = item.split("|")
        if len(parts) >= 3:
            stations[parts[1]] = parts[2]
    if not stations:
        raise RuntimeError("站名数据解析失败")
    return stations


def detect_query_path(session):
    try:
        resp = session.get(INIT_URL, timeout=15)
        m = re.search(r"CLeftTicketUrl\s*=\s*'([^']+)'", resp.text)
        if m:
            return m.group(1)
    except requests.RequestException:
        pass
    return None


def query_once(session, path, date, from_code, to_code):
    """返回 (车次行列表, 错误信息)。列表元素为按 | 分隔的字段数组。"""
    url = "%s/otn/%s" % (BASE, path)
    params = {
        "leftTicketDTO.train_date": date,
        "leftTicketDTO.from_station": from_code,
        "leftTicketDTO.to_station": to_code,
        "purpose_codes": "ADULT",
    }
    try:
        resp = session.get(url, params=params, timeout=15)
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        return None, str(e)
    result = (data.get("data") or {}).get("result")
    if result is None:
        return None, data.get("messages") or "响应中无 result 字段"
    return [row.split("|") for row in result], None


def seat_available(value):
    if value == "有":
        return True, "有票"
    if value.isdigit() and int(value) > 0:
        return True, "%s张" % value
    return False, None


def notify_desktop(title, body):
    system = platform.system()
    try:
        if system == "Darwin":
            script = 'display notification "%s" with title "%s" sound name "Glass"' % (
                body.replace('"', "'"), title.replace('"', "'"))
            subprocess.run(["osascript", "-e", script], timeout=10)
        elif system == "Linux":
            subprocess.run(["notify-send", title, body], timeout=10)
        elif system == "Windows":
            ps = ("[reflection.assembly]::loadwithpartialname('System.Windows.Forms');"
                  "[reflection.assembly]::loadwithpartialname('System.Drawing');"
                  "$n=new-object system.windows.forms.notifyicon;"
                  "$n.icon=[drawing.systemicons]::Information;$n.visible=$true;"
                  "$n.showballoontip(10000,'%s','%s',"
                  "[system.windows.forms.tooltipicon]::Info)" % (
                      title.replace("'", ""), body.replace("'", "")))
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=15)
    except Exception:
        pass


def render_template(obj, mapping):
    """把 obj 里所有字符串中的 {title}/{content} 替换为实际内容"""
    if isinstance(obj, str):
        for k, v in mapping.items():
            obj = obj.replace("{%s}" % k, v)
        return obj
    if isinstance(obj, dict):
        return {k: render_template(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render_template(v, mapping) for v in obj]
    return obj


def notify_webhook(webhook, title, body):
    """调用自定义 webhook（如自建微信机器人），body 模板里可用 {title} 和 {content}"""
    mapping = {"title": title, "content": body}
    method = (webhook.get("method") or "POST").upper()
    headers = render_template(webhook.get("headers") or {}, mapping)
    payload = render_template(webhook.get("body"), mapping)
    try:
        if isinstance(payload, (dict, list)):
            requests.request(method, webhook["url"], json=payload,
                             headers=headers, timeout=15)
        else:
            requests.request(method, webhook["url"],
                             data=(payload or "").encode("utf-8"),
                             headers=headers, timeout=15)
        log("已调用自定义 webhook")
    except requests.RequestException as e:
        log("webhook 调用失败: %s" % e)


def notify_push(cfg, title, body):
    notify = cfg.get("notify", {})
    pushes = []
    if notify.get("bark_key"):
        pushes.append(("Bark", "https://api.day.app/%s/%s/%s" % (
            notify["bark_key"], requests.utils.quote(title),
            requests.utils.quote(body)), None))
    if notify.get("serverchan_sendkey"):
        pushes.append(("Server酱", "https://sctapi.ftqq.com/%s.send" %
                       notify["serverchan_sendkey"],
                       {"title": title, "desp": body}))
    if notify.get("pushplus_token"):
        pushes.append(("PushPlus", "http://www.pushplus.plus/send",
                       {"token": notify["pushplus_token"],
                        "title": title, "content": body}))
    for name, url, payload in pushes:
        try:
            if payload is None:
                requests.get(url, timeout=15)
            else:
                requests.post(url, data=payload, timeout=15)
            log("已推送到 %s" % name)
        except requests.RequestException as e:
            log("推送到 %s 失败: %s" % (name, e))
    webhook = notify.get("webhook") or {}
    if webhook.get("url"):
        notify_webhook(webhook, title, body)


def notify_all(cfg, title, body):
    print("\a", end="", flush=True)  # 终端响铃
    log("🎉 %s | %s" % (title, body))
    if cfg.get("notify", {}).get("desktop", True):
        notify_desktop(title, body)
    notify_push(cfg, title, body)


def main():
    parser = argparse.ArgumentParser(description="12306 余票监控")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    date = cfg["date"]
    watch_trains = set(t.upper() for t in cfg.get("trains", []))
    watch_seats = cfg.get("seats", ["二等座", "一等座"])
    interval = max(int(cfg.get("interval_seconds", 30)), 10)
    renotify_after = int(cfg.get("renotify_minutes", 10)) * 60

    for seat in watch_seats:
        if seat not in SEAT_FIELDS:
            sys.exit("不支持的席别: %s（可选: %s）" % (seat, "、".join(SEAT_FIELDS)))

    session = new_session()
    stations = load_stations(session)
    from_name, to_name = cfg["from"], cfg["to"]
    if from_name not in stations:
        sys.exit("找不到出发站: %s（请使用 12306 上的标准站名，如 北京南）" % from_name)
    if to_name not in stations:
        sys.exit("找不到到达站: %s" % to_name)
    from_code, to_code = stations[from_name], stations[to_name]

    query_path = detect_query_path(session) or QUERY_CANDIDATES[0]
    log("开始监控 %s %s→%s，车次: %s，席别: %s，每 %d 秒查询一次" % (
        date, from_name, to_name,
        "、".join(sorted(watch_trains)) or "全部",
        "、".join(watch_seats), interval))

    last_notified = {}   # (车次, 席别) -> 上次通知时间戳
    fail_streak = 0

    while True:
        rows, err = query_once(session, query_path, date, from_code, to_code)

        if rows is None:
            fail_streak += 1
            log("查询失败(%d): %s" % (fail_streak, err))
            if fail_streak % 3 == 0:
                # 连续失败时重建会话，并尝试其他接口路径
                session = new_session()
                idx = QUERY_CANDIDATES.index(query_path) if query_path in QUERY_CANDIDATES else -1
                query_path = detect_query_path(session) or \
                    QUERY_CANDIDATES[(idx + 1) % len(QUERY_CANDIDATES)]
                log("已重建会话，改用接口 %s" % query_path)
            time.sleep(interval)
            continue

        fail_streak = 0
        hits, statuses = [], []
        for r in rows:
            if len(r) < 34:
                continue
            code = r[3].upper()
            if watch_trains and code not in watch_trains:
                continue
            seat_desc = []
            for seat in watch_seats:
                value = r[SEAT_FIELDS[seat]]
                ok, desc = seat_available(value)
                seat_desc.append("%s:%s" % (seat, value or "-"))
                if ok and r[11] == "Y":
                    key = (code, seat)
                    now = time.time()
                    if now - last_notified.get(key, 0) >= renotify_after:
                        last_notified[key] = now
                        hits.append("%s %s %s（%s开，%s→%s）" % (
                            code, seat, desc, r[8], from_name, to_name))
            statuses.append("%s[%s]" % (code, " ".join(seat_desc)))

        if hits:
            notify_all(cfg, "12306 有票了！",
                       "；".join(hits) + "。快打开 12306 APP 购票/改签！")
        else:
            log("暂无票 | %s" % ("  ".join(statuses) if statuses else
                                "结果中没有匹配的车次，请检查车次号/站名"))

        time.sleep(interval + random.uniform(0, 3))  # 加随机抖动，降低被限流风险


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止监控")
