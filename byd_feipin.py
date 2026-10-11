#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BYD 仪表飞屏助手  (byd-cluster-feipin)
=========================================================
用途
    在比亚迪 DiLink 4.0「18.x 控制器」车机上，通过车机自带的「仪表调试」
    工具 ClusterDebug，配合系统 autoservice / AutoContainer 接口，打开被
    隐藏的「仪表全屏导航」功能（俗称"地图飞屏"）。

原理（来自公开逆向资料，详见 README.md）
    * com.byd.clusterdebug  车机自带的调试 App，作为特权代理
    * autoservice  binder   INSTRUMENT_NAVI_TYPE —— 仪表导航类型
          读:  service call autoservice 5 i32 1007 i32 1086337074
          写:  service call autoservice 6 i32 1007 i32 1276157976 i32 <n>
              1=关闭  2=随导航  3=小屏导航  4=全屏导航
    * AutoContainer binder  投影开关（模式号以字符串传入）
          service call AutoContainer 2 i32 1000 s16 "<mode>"
              39=简易导航  16=全屏投影  17=半屏投影  18=关闭投影  35=Di4.0模式

依赖
    仅需本机 adb（platform-tools）。若缺失，本工具可自动下载。
    运行界面使用系统浏览器，无需 tkinter / 第三方库。

运行
    python byd_feipin.py --web          # 启动网页界面（推荐）
    python byd_feipin.py --connect 192.168.10.10:5555 --on
    python byd_feipin.py --status
    python byd_feipin.py --raw "getprop ro.build.display.id"
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "BYD 仪表飞屏助手"
VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
TOOLS_DIR = BASE_DIR / "platform-tools"

DEFAULT_HOST = "192.168.10.10"
DEFAULT_PORT = 5555

# ---- 逆向得到的常量（不同固件可能有差异，可在界面"命令调试台"里自行试） ----
INSTRUMENT_DEVICE_ID = 1007
FEATURE_READ_NAVI_TYPE = 1086337074        # 0x40C03032 读 INSTRUMENT_NAVI_TYPE
FEATURE_SET_NAVI_TYPE = 1276157976         # 0x4C10A018 写 INSTRUMENT_NAVI_TYPE_SET
READ_TRANSACTION = 5
SET_TRANSACTION = 6

NAVI_TYPE = {
    1: "关闭 (Off)",
    2: "随导航 (Turn on by navi)",
    3: "小屏导航 (Small screen navi)",
    4: "全屏导航 (Full screen navi)",
}

# AutoContainer 模式
MODE_SIMPLE = "39"     # 简易导航（转向卡片）
MODE_FULL = "16"       # 全屏投影
MODE_HALF = "17"       # 半屏投影
MODE_OFF = "18"        # 关闭投影
MODE_DI4 = "35"        # Di4.0 模式（创建投影显示）

PLATFORM_TOOLS_URL = {
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}


# ============================================================
# adb 定位 / 下载
# ============================================================
def adb_name() -> str:
    return "adb.exe" if os.name == "nt" else "adb"


def find_adb() -> str | None:
    """按 环境变量 -> 项目目录 -> PATH -> 常见位置 的顺序查找 adb。"""
    env = os.environ.get("ADB") or os.environ.get("ANDROID_ADB")
    if env and Path(env).exists():
        return env

    local = TOOLS_DIR / "platform-tools" / adb_name()
    if local.exists():
        return str(local)
    local2 = TOOLS_DIR / adb_name()
    if local2.exists():
        return str(local2)

    found = shutil.which("adb")
    if found:
        return found

    for cand in (
        Path.home() / "AppData/Local/Android/Sdk/platform-tools" / adb_name(),
        Path("/usr/local/bin/adb"),
        Path("/usr/bin/adb"),
        Path("/opt/homebrew/bin/adb"),
    ):
        if cand.exists():
            return str(cand)
    return None


def download_platform_tools(log=print) -> str:
    """下载并解压 platform-tools，返回 adb 路径。"""
    url = PLATFORM_TOOLS_URL.get(platform.system())
    if not url:
        raise RuntimeError(f"不支持的系统：{platform.system()}")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = TOOLS_DIR / "platform-tools.zip"
    log(f"正在下载 platform-tools: {url}")
    urllib.request.urlretrieve(url, zip_path)
    log("下载完成，正在解压…")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(TOOLS_DIR)
    zip_path.unlink(missing_ok=True)
    adb = TOOLS_DIR / "platform-tools" / adb_name()
    if not adb.exists():
        adb = TOOLS_DIR / adb_name()
    try:
        os.chmod(adb, 0o755)
    except Exception:
        pass
    log(f"adb 就绪：{adb}")
    return str(adb)


# ============================================================
# adb 驱动
# ============================================================
class Adb:
    def __init__(self) -> None:
        self.path = find_adb()
        self.target = f"{DEFAULT_HOST}:{DEFAULT_PORT}"
        self._server_started = False

    # ---- 基础执行 ----
    def _run(self, args: list[str], timeout: int = 25) -> tuple[int, str]:
        if not self.path:
            return 127, "未找到 adb，请先点击「下载 adb」。"
        cmd = [self.path, *args]
        try:
            p = subprocess.run(
                cmd, capture_output=True, timeout=timeout, text=True,
                encoding="utf-8", errors="replace",
            )
            out = (p.stdout or "") + (p.stderr or "")
            return p.returncode, out.strip()
        except subprocess.TimeoutExpired:
            return 124, f"命令超时（{timeout}s）：{' '.join(args)}"
        except Exception as e:  # noqa: BLE001
            return 1, f"执行失败：{e}"

    def ensure_server(self) -> list[str]:
        if self._server_started:
            return []
        code, out = self._run(["start-server"], timeout=30)
        self._server_started = True
        return [f"$ adb start-server\n{out}"]

    def shell(self, cmd: str, timeout: int = 25) -> tuple[int, str]:
        self.ensure_server()
        return self._run(["shell", cmd], timeout=timeout)

    def host(self, args: list[str], timeout: int = 30) -> tuple[int, str]:
        self.ensure_server()
        return self._run(args, timeout=timeout)

    def connect(self, hostport: str) -> tuple[bool, str]:
        self.target = hostport
        self.ensure_server()
        code, out = self._run(["connect", hostport], timeout=30)
        ok = "connected" in out.lower() and "cannot" not in out.lower()
        # 连接后校验
        code2, out2 = self._run(["devices", "-l"])
        return ok, f"$ adb connect {hostport}\n{out}\n\n$ adb devices -l\n{out2}"


# ============================================================
# 工具函数
# ============================================================
def parse_parcel_int(reply: str) -> int | None:
    """从 'Parcel(00000000 00000004)' 里取出最后一组 8 位十六进制。"""
    groups = re.findall(r"([0-9a-fA-F]{8})", reply or "")
    if not groups:
        return None
    try:
        return int(groups[-1], 16)
    except ValueError:
        return None


def is_error_reply(reply: str) -> bool:
    low = (reply or "").lower()
    return any(k in low for k in (
        "exception", "permission denial", "security exception", "not found",
        "no such", "unknown", "cannot find", "unable to", "null",
    ))


def detect_map_package(adb: Adb) -> str | None:
    """列出车机上已装的定制版地图包名，优先返回高德/百度定制版。"""
    code, out = adb.shell("pm list packages")
    if code != 0:
        return None
    pkgs = [l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("package:")]
    keywords = ("autonavi", "amap", "baidu", "bmap", "tencent", "byd")
    cands = [p for p in pkgs if any(k in p.lower() for k in keywords)]
    # 优先：高德定制 / 百度定制 / 高德 / 百度
    priority = ["autonavi.minimap.byd", "byd.amap", "byd.autonavi", "autonavi"]
    cands.sort(key=lambda p: next((i for i, k in enumerate(priority) if k in p.lower()), 99))
    return cands[0] if cands else None


def launch_package(adb: Adb, pkg: str) -> tuple[int, str]:
    return adb.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")


# ============================================================
# 业务动作
# ============================================================
def act_connect(adb: Adb, host: str, port: int) -> dict:
    ok, out = adb.connect(f"{host}:{port}")
    return {"ok": ok, "log": out}


def act_tcpip(adb: Adb, port: int = DEFAULT_PORT) -> dict:
    """把 adbd 从 USB 模式切成 TCP 明文监听（经典 adb tcpip）。

    为什么需要它：Android 11 起「无线调试」改成了 TLS 加密 + 随机临时端口
    （典型 37000-45000，且配对端口与连接端口是两个），**不再监听 5555**。
    普通程序（包括车机端 App）连 127.0.0.1:5555 会直接被拒（ECONNREFUSED）。

    执行本动作后 adbd 会改为在 <port> 上明文监听，车机端 App 与本工具即可连上。
    必须先用 USB 线连上设备（并在设备上点「允许 USB 调试」）—— 这是安全模型要求。
    """
    log: list[str] = []

    log.append("=== 当前设备 ===")
    _, out = adb.host(["devices", "-l"])
    log.append(out or "(无)")

    log.append("")
    code, out = adb.host(["-d", "tcpip", str(port)], timeout=40)
    log.append(f"$ adb -d tcpip {port}")
    log.append(out or "(无输出)")

    low = (out or "").lower()
    ok = code == 0 and ("tcp mode" in low or "restarting" in low)

    if ok:
        log.append("")
        log.append(f"[OK] adbd 已切到 TCP 明文端口 {port}。")
        log.append(f"     设备本机的 127.0.0.1:{port} 随之开始监听 —— 车机端 App 现在可以直接连。")
        log.append("     ⚠ 设备重启后会失效，需要重新执行一次。")
        log.append("     ⚠ 该端口在局域网内是明文可访问的，用完可以在车机侧关掉调试。")
    else:
        log.append("")
        log.append("[!] 切换失败，常见原因：")
        log.append("    · 没有用 USB 线连接设备 —— adb tcpip 必须走 USB 首次触发")
        log.append("    · 设备上没弹授权，或没点「允许 USB 调试」")
        log.append("    · 电脑上同时接了多个 USB 设备，先只留一个再试")
        log.append("    · 部分厂商 ROM 会忽略该指令，请改用 BYD 自带的「无线 adb 调试」开关")

    log.append("")
    log.append("=== 复查（USB 会掉一下是正常的） ===")
    _, o2 = adb.host(["devices", "-l"])
    log.append(o2 or "(无)")
    return {"ok": ok, "log": "\n".join(log)}


def act_download_adb(adb: Adb) -> dict:
    lines: list[str] = []
    try:
        adb.path = download_platform_tools(lines.append)
        return {"ok": True, "log": "\n".join(lines)}
    except Exception as e:  # noqa: BLE001
        lines.append(f"下载失败：{e}\n可手动前往 https://developer.android.com/tools/releases/platform-tools 下载后把 adb 放进 PATH。")
        return {"ok": False, "log": "\n".join(lines)}


def act_detect(adb: Adb) -> dict:
    log: list[str] = []
    data: dict = {}

    log.append("=== 环境 ===")
    log.append(f"adb: {adb.path or '未找到'}")

    log.append("\n=== 设备 ===")
    code, out = adb.host(["devices", "-l"])
    log.append(out)

    log.append("\n=== 系统信息 ===")
    props = {
        "Android 版本": "getprop ro.build.version.release",
        "车型/产品": "getprop ro.product.model",
        "固件版本": "getprop ro.build.display.id",
        "构建指纹": "getprop ro.build.fingerprint",
    }
    for label, c in props.items():
        _, o = adb.shell(c)
        log.append(f"{label}: {o}")
        data[label] = o

    log.append("\n=== 控制器相关属性（找 18.x / 21.x） ===")
    _, o = adb.shell("getprop | grep -iE 'ivi|controller|cluster|byd' | head -40")
    log.append(o or "(无)")
    m = re.search(r"(1[0-9]|2[0-9])\.\d", o or "")
    if m:
        log.append(f"→ 疑似控制器版本前缀：{m.group(0)}")
    data["controller_raw"] = o

    log.append("\n=== ClusterDebug 调试工具是否存在 ===")
    _, o = adb.shell("pm list packages | grep -i clusterdebug")
    log.append(o or "未发现 com.byd.clusterdebug（可能固件不同）")
    data["clusterdebug"] = bool(o.strip())

    log.append("\n=== 相关包（地图 / 容器 / 调试） ===")
    _, o = adb.shell("pm list packages | grep -iE 'autonavi|amap|baidu|bmap|tencent|xdja|clusterdebug'")
    log.append(o or "(无)")
    data["packages"] = o

    log.append("\n=== 读取当前仪表导航类型 ===")
    cmd = f"service call autoservice {READ_TRANSACTION} i32 {INSTRUMENT_DEVICE_ID} i32 {FEATURE_READ_NAVI_TYPE}"
    _, o = adb.shell(cmd)
    log.append(f"$ {cmd}\n{o}")
    n = parse_parcel_int(o)
    if n is not None:
        log.append(f"→ 当前模式 = {n}  ({NAVI_TYPE.get(n, '未知')})")
        data["navi_type"] = n
    elif is_error_reply(o):
        log.append("→ 读取失败：当前固件可能不支持该接口，或 shell 无权限。")

    return {"ok": True, "log": "\n".join(log), "data": data}


def _step(log: list[str], adb: Adb, title: str, cmd: str, timeout: int = 25) -> str:
    code, out = adb.shell(cmd, timeout=timeout)
    state = "OK " if code == 0 and not is_error_reply(out) else "!! "
    log.append(f"[{state}] {title}")
    log.append(f"      $ adb shell {cmd}")
    if out:
        log.append("      " + out.replace("\n", "\n      "))
    log.append("")
    return out


def act_on(adb: Adb, map_pkg: str | None = None) -> dict:
    log: list[str] = []
    log.append(">>> 开始开启「仪表全屏导航（飞屏）」\n")

    log.append("① 启动仪表调试代理（车机自带的 ClusterDebug）")
    _step(log, adb, "启动调试服务", "am startservice -n com.byd.clusterdebug/.ClusterDebugService")
    _step(log, adb, "打开调试界面", "am start -n com.byd.clusterdebug/.MainActivity")

    log.append("② 把仪表导航类型设为「全屏导航」(4)")
    _step(
        log, adb, "写入 INSTRUMENT_NAVI_TYPE=4",
        f"service call autoservice {SET_TRANSACTION} i32 {INSTRUMENT_DEVICE_ID} "
        f"i32 {FEATURE_SET_NAVI_TYPE} i32 4",
    )

    log.append("③ 触发投影（35 创建 Di4.0 投影显示 -> 16 全屏投影）")
    _step(log, adb, "创建投影显示 (35)", f'service call AutoContainer 2 i32 1000 s16 "{MODE_DI4}"')
    time.sleep(1.0)
    _step(log, adb, "开启全屏投影 (16)", f'service call AutoContainer 2 i32 1000 s16 "{MODE_FULL}"')

    log.append("④ 启动定制版地图（触发仪表出图）")
    pkg = map_pkg or detect_map_package(adb)
    if pkg:
        log.append(f"      使用地图包：{pkg}")
        code, out = launch_package(adb, pkg)
        log.append(f"      $ adb shell monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        if out:
            log.append("      " + out.replace("\n", "\n      "))
        log.append("")
    else:
        log.append("      !! 未找到定制版地图包，请手动在车机上打开导航后把地图投到仪表。\n")

    log.append("⑤ 回读校验")
    _, o = adb.shell(
        f"service call autoservice {READ_TRANSACTION} i32 {INSTRUMENT_DEVICE_ID} i32 {FEATURE_READ_NAVI_TYPE}"
    )
    n = parse_parcel_int(o)
    log.append(f"      当前仪表导航类型 = {n}  ({NAVI_TYPE.get(n, '未知')})" if n else f"      {o}")

    log.append("\n完成。若仪表未出现地图：确认控制器为 18.x/21.x；确认方向盘右侧菜单已选「全屏导航」；"
               "或在界面下方「命令调试台」手动试 16/17/35 不同组合。")
    return {"ok": True, "log": "\n".join(log)}


def act_off(adb: Adb, restore: int = 1) -> dict:
    log: list[str] = []
    log.append(">>> 关闭「仪表全屏导航（飞屏）」\n")
    log.append("① 关闭投影 (18)")
    _step(log, adb, "关闭投影", f'service call AutoContainer 2 i32 1000 s16 "{MODE_OFF}"')
    log.append(f"② 恢复仪表导航类型为 {restore} ({NAVI_TYPE.get(restore, '')})")
    _step(
        log, adb, f"写入 INSTRUMENT_NAVI_TYPE={restore}",
        f"service call autoservice {SET_TRANSACTION} i32 {INSTRUMENT_DEVICE_ID} "
        f"i32 {FEATURE_SET_NAVI_TYPE} i32 {restore}",
    )
    log.append("完成。如仪表仍残留画面，可重启车机一次。")
    return {"ok": True, "log": "\n".join(log)}


def act_small(adb: Adb) -> dict:
    log: list[str] = []
    log.append(">>> 切换为「小屏导航」\n")
    _step(
        log, adb, "写入 INSTRUMENT_NAVI_TYPE=3",
        f"service call autoservice {SET_TRANSACTION} i32 {INSTRUMENT_DEVICE_ID} "
        f"i32 {FEATURE_SET_NAVI_TYPE} i32 3",
    )
    _step(log, adb, "半屏投影 (17)", f'service call AutoContainer 2 i32 1000 s16 "{MODE_HALF}"')
    return {"ok": True, "log": "\n".join(log)}


def act_shot(adb: Adb) -> dict:
    log: list[str] = []
    remote = "/data/local/tmp/cluster.png"
    local = BASE_DIR / "cluster_shot.png"
    code, out = adb.shell(f"fission_screencap -d 1 -p {remote}", timeout=30)
    log.append(f"$ adb shell fission_screencap -d 1 -p {remote}\n{out}")
    if code != 0:
        return {"ok": False, "log": "\n".join(log) +
                "\n截图失败：该固件可能没有 fission_screencap，或仪表不是 1 号显示。"
                "\n可试试：adb shell screencap -p /sdcard/c.png 然后 adb pull。"}
    code, out = adb.host(["pull", remote, str(local)])
    log.append(f"$ adb pull {remote} {local}\n{out}")
    if local.exists():
        return {"ok": True, "log": "\n".join(log), "image": f"data:image/png;base64,{_b64(local)}"}
    return {"ok": False, "log": "\n".join(log)}


def act_raw(adb: Adb, cmd: str) -> dict:
    code, out = adb.shell(cmd, timeout=30)
    return {"ok": code == 0, "log": f"$ adb shell {cmd}\n{out}"}


def _b64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode()


ACTIONS = {
    "connect": act_connect,
    "tcpip": act_tcpip,
    "download_adb": act_download_adb,
    "detect": act_detect,
    "on": act_on,
    "off": act_off,
    "small": act_small,
    "shot": act_shot,
    "raw": act_raw,
}


# ============================================================
# 网页界面（本地 HTTP 服务）
# ============================================================
class Handler(BaseHTTPRequestHandler):
    adb: Adb = None          # 注入
    token: str = ""

    def log_message(self, *a):  # 静音
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace("__TOKEN__", self.token)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/ping":
            self._send(200, b'{"ok":true}', "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        if self.headers.get("X-Token") != self.token:
            self._send(403, b'{"ok":false,"log":"token error"}', "application/json")
            return
        if self.path != "/api/action":
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            self._send(400, b'{"ok":false,"log":"bad request"}', "application/json")
            return

        name = req.get("name")
        params = req.get("params") or {}
        fn = ACTIONS.get(name)
        if not fn:
            self._send(404, json.dumps({"ok": False, "log": f"未知动作 {name}"}).encode(), "application/json")
            return
        try:
            if name == "connect":
                res = fn(self.adb, str(params.get("host", DEFAULT_HOST)), int(params.get("port", DEFAULT_PORT)))
            elif name == "tcpip":
                res = fn(self.adb, int(params.get("port", DEFAULT_PORT)))
            elif name == "download_adb":
                res = fn(self.adb)
            elif name == "raw":
                res = fn(self.adb, str(params.get("cmd", "")))
            elif name == "on":
                res = fn(self.adb, params.get("map_pkg") or None)
            elif name == "off":
                res = fn(self.adb, int(params.get("restore", 1)))
            else:
                res = fn(self.adb)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": f"执行异常：{e}"}
        self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"), "application/json")


def serve(adb: Adb, port: int = 8765, open_browser: bool = True) -> None:
    Handler.adb = adb
    Handler.token = secrets.token_urlsafe(18)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n{APP_NAME} v{VERSION}")
    print(f"界面地址：{url}")
    print("（关闭本窗口即停止服务）\n")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


# ============================================================
# CLI
# ============================================================
def main() -> None:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}")
    ap.add_argument("--web", action="store_true", help="启动网页界面（默认）")
    ap.add_argument("--port", type=int, default=8765, help="本地界面端口")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--connect", metavar="HOST:PORT", help="连接车机，如 192.168.10.10:5555")
    ap.add_argument("--on", action="store_true", help="开启仪表全屏导航（飞屏）")
    ap.add_argument("--off", action="store_true", help="关闭仪表全屏导航")
    ap.add_argument("--status", action="store_true", help="自检并读取当前状态")
    ap.add_argument("--raw", metavar="CMD", help="执行任意 adb shell 命令")
    ap.add_argument("--tcpip", nargs="?", const=DEFAULT_PORT, type=int, metavar="PORT",
                    help="把 adbd 切到 TCP 明文监听（需 USB 连接设备），默认 5555。"
                         "Android 11+ 无线调试模式下连不上时用这个")
    args = ap.parse_args()

    adb = Adb()

    if args.tcpip:
        _print_tcpip = act_tcpip(adb, args.tcpip)
        print(_print_tcpip["log"])
        if not _print_tcpip["ok"]:
            sys.exit(1)
        return

    if args.connect:
        host, _, port = args.connect.partition(":")
        ok, out = adb.connect(f"{host}:{port or DEFAULT_PORT}")
        print(out)
        if not ok:
            sys.exit(1)
        return  # 仅连接

    def _print(res: dict) -> None:
        print(res.get("log", ""))

    if args.on:
        if not adb.path:
            print("未找到 adb。请先运行 --web 并点击「下载 adb」，或手动安装 platform-tools。"); sys.exit(1)
        _print(act_on(adb)); return
    if args.off:
        _print(act_off(adb)); return
    if args.status:
        _print(act_detect(adb)); return
    if args.raw:
        _print(act_raw(adb, args.raw)); return

    # 默认：网页界面
    serve(adb, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
