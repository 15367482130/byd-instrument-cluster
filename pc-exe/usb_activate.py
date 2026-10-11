# -*- coding: utf-8 -*-
"""
BYD 无线 ADB 一键激活工具
=====================================================================
用途
----
用 USB 线把设备（车机 / Android 11+ 手机）连到电脑，点一下按钮，
工具会执行 `adb tcpip <port>`，把 adbd 从「USB 模式」切到「明文 TCP 模式」。
之后拔掉 USB 线，设备就会在 5555 端口以**明文**方式监听，
PC 端网页工具和车机端 App 都能直接连上。

背景
----
* Android <= 10（比亚迪 DiLink 属于这一档）：无线 ADB 就是明文 5555，无需本工具。
* Android >= 11 的「无线调试」是完全不同的东西：随机端口 + TLS 双向加密 + 配对码，
  普通程序连不上，也不监听 5555。本工具把它切回经典的 `adb tcpip` 明文模式。

界面
----
本程序是**单文件、零安装**的：启动后在本机 127.0.0.1 起一个只监听回环的服务，
自动用默认浏览器打开操作界面。adb 已经内置在 exe 内部，无需联网下载。

本程序只调用官方 adb 命令，不刷机、不改固件、不写任何系统分区。
=====================================================================
"""

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "BYD 无线ADB激活工具"
VERSION = "1.0"
DEFAULT_PORT = 5555
DEFAULT_HTTP_PORT = 8899
IDLE_EXIT_SEC = 20 * 60          # 无操作自动退出
BYE_GRACE_SEC = 8                # 关掉页面后等待（容忍刷新）再退出

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
ADB_NAME = "adb.exe" if IS_WIN else "adb"
ADB_SIBLINGS = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")

PLATFORM_TOOLS_URL = {
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}

# --------------------------------------------------------------------------
# 日志（环形缓冲 + 文件）
# --------------------------------------------------------------------------
_LOG_LOCK = threading.Lock()
_LOG: list = []
_LOG_MAX = 4000


def log_line(text: str) -> None:
    for line in str(text).splitlines() or [""]:
        with _LOG_LOCK:
            _LOG.append(line)
            if len(_LOG) > _LOG_MAX:
                del _LOG[: len(_LOG) - _LOG_MAX]
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(str(text).rstrip("\n") + "\n")
    except Exception:
        pass
    if sys.stdout is not None:
        try:
            print(text, flush=True)
        except Exception:
            pass


def log_since(n: int):
    with _LOG_LOCK:
        return list(_LOG[n:]), len(_LOG)


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """PyInstaller onefile 解包目录（内含内置 adb）。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", exe_dir()))
    return Path(__file__).resolve().parent / "vendor"


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path(tempfile.gettempdir())
    d = root / "BYD-Feipin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tools_dir() -> Path:
    d = data_dir() / "platform-tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


LOG_PATH = data_dir() / "usb-activate.log"


# --------------------------------------------------------------------------
# adb 定位 / 释放 / 下载
# --------------------------------------------------------------------------
ADB = None


def _usable(p: Path) -> bool:
    try:
        return p.is_file() and p.stat().st_size > 100_000
    except Exception:
        return False


def _install_from(src_dir: Path):
    src = src_dir / ADB_NAME
    if not _usable(src):
        return None
    dst_dir = tools_dir()
    try:
        for name in ADB_SIBLINGS:
            s = src_dir / name
            if s.is_file():
                shutil.copy2(s, dst_dir / name)
    except Exception as e:
        log_line(f"[!] 释放 adb 失败：{e}")
    d = dst_dir / ADB_NAME
    return d if _usable(d) else None


def find_candidates():
    out = []
    for d in (bundle_dir(), exe_dir(), exe_dir() / "platform-tools",
              exe_dir() / "vendor", tools_dir()):
        out.append(d / ADB_NAME)
    w = shutil.which("adb")
    if w:
        out.append(Path(w))
    home = Path.home()
    for extra in (home / "AppData/Local/Android/Sdk/platform-tools",
                  home / "Library/Android/sdk/platform-tools",
                  Path("/usr/lib/android-sdk/platform-tools"),
                  Path("/opt/homebrew/bin")):
        out.append(extra / ADB_NAME)
    return out


def ensure_adb(allow_download=True, progress=None):
    global ADB
    persistent = tools_dir() / ADB_NAME
    if _usable(persistent):
        ADB = persistent
        return ADB
    for d in (bundle_dir(), exe_dir() / "vendor", exe_dir() / "platform-tools"):
        got = _install_from(d)
        if got:
            ADB = got
            log_line(f"[+] 已从内置资源释放 adb -> {got}")
            return ADB
    for p in find_candidates():
        if _usable(p):
            ADB = p
            log_line(f"[+] 使用系统已有 adb：{p}")
            return ADB
    if allow_download:
        try:
            ADB = download_platform_tools(progress)
            return ADB
        except Exception as e:
            log_line(f"[!] 下载 platform-tools 失败：{e}")
    return None


def download_platform_tools(progress=None) -> Path:
    import platform as _pf
    url = PLATFORM_TOOLS_URL.get(_pf.system(), PLATFORM_TOOLS_URL["Windows"])
    zpath = data_dir() / "platform-tools.zip"
    log_line(f"正在下载 platform-tools：{url}")
    if progress:
        progress("正在下载 platform-tools …")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(zpath, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(f"下载 platform-tools … {done * 100 // total}%")
    tmp = data_dir() / "_pt"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    adb = _install_from(tmp / "platform-tools") or _install_from(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        zpath.unlink()
    except Exception:
        pass
    if not adb:
        raise RuntimeError("下载完成但没找到 adb")
    log_line(f"[+] 下载完成 -> {adb}")
    return adb


# --------------------------------------------------------------------------
# adb 调用
# --------------------------------------------------------------------------
def run_adb(args, timeout=60, check=False):
    if ADB is None:
        raise RuntimeError("adb 不可用")
    log_line("$ adb " + " ".join(str(a) for a in args))
    try:
        p = subprocess.run([str(ADB)] + [str(a) for a in args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 124, f"命令超时（{timeout}s）"
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if out:
        log_line(out)
    if check and p.returncode != 0:
        raise RuntimeError(out or f"adb 退出码 {p.returncode}")
    return p.returncode, out


DEV_RE = re.compile(r"^(\S+)\s+(\w+)(?:\s+(.*))?$")


def list_devices():
    _, out = run_adb(["devices", "-l"], timeout=40)
    devs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("*") or line.startswith("List of devices"):
            continue
        m = DEV_RE.match(line)
        if not m:
            continue
        serial, state, extra = m.group(1), m.group(2), m.group(3) or ""
        info = {}
        for kv in extra.split():
            if ":" in kv:
                k, v = kv.split(":", 1)
                info[k] = v
        info.update({"serial": serial, "state": state})
        devs.append(info)
    return devs


def usb_devices():
    return [d for d in list_devices() if ":" not in d["serial"]]


IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _valid_ip(s: str) -> bool:
    if not s or s.startswith("127.") or s.startswith("0.") or s.startswith("169.254."):
        return False
    if s.endswith(".255") or s == "255.255.255.255":
        return False
    try:
        parts = [int(x) for x in s.split(".")]
    except ValueError:
        return False
    return len(parts) == 4 and all(0 <= p <= 255 for p in parts)


def get_device_ip(serial):
    try:
        _, out = run_adb(["-s", serial, "shell", "ip route get 8.8.8.8"], timeout=20)
        m = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m and _valid_ip(m.group(1)):
            return m.group(1)
    except Exception:
        pass
    try:
        _, out = run_adb(["-s", serial, "shell", "ip -4 addr show"], timeout=20)
        fallback = None
        for line in out.splitlines():
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if not m:
                continue
            ip = m.group(1)
            if not _valid_ip(ip):
                continue
            iface = line.strip().split()[-1].rstrip(":")
            if re.search(r"wlan|eth|rndis|ap0|softap", iface, re.I):
                return ip
            if fallback is None:
                fallback = ip
        if fallback:
            return fallback
    except Exception:
        pass
    for prop in ("dhcp.wlan0.ipaddress", "dhcp.eth0.ipaddress",
                 "persist.sys.wifi.ip", "net.wlan0.ipaddress"):
        try:
            _, out = run_adb(["-s", serial, "shell", "getprop " + prop], timeout=15)
            if _valid_ip(out.strip()):
                return out.strip()
        except Exception:
            pass
    try:
        _, out = run_adb(["-s", serial, "shell", "ifconfig"], timeout=20)
        for m in IPV4_RE.finditer(out):
            if _valid_ip(m.group(1)):
                return m.group(1)
    except Exception:
        pass
    return None


def port_open(ip, port, timeout=2.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def local_ip_for(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ip, 9))
        v = s.getsockname()[0]
        s.close()
        return v
    except Exception:
        return "?"


def device_info(serial):
    props = {"固件版本": "ro.build.display.id", "机型": "ro.product.model",
             "品牌": "ro.product.brand", "Android": "ro.build.version.release",
             "SDK": "ro.build.version.sdk"}
    info = {}
    for label, prop in props.items():
        try:
            _, out = run_adb(["-s", serial, "shell", "getprop " + prop], timeout=15)
            info[label] = out.strip() or "?"
        except Exception:
            info[label] = "?"
    return info


# --------------------------------------------------------------------------
# 高层动作
# --------------------------------------------------------------------------
def do_activate(port, push=log_line):
    if ADB is None:
        raise RuntimeError("adb 不可用，请先点「重新下载 / 定位 adb」")

    push("启动 adb server …")
    run_adb(["start-server"], timeout=60)

    devs = list_devices()
    if not devs:
        raise RuntimeError(
            "没有检测到任何设备。\n"
            "· 确认 USB 线已插好（是数据线，不是只能充电的线）\n"
            "· 设备上确认已打开「开发者选项 → USB 调试」\n"
            "· 设备上如果弹出「允许 USB 调试吗？」，勾选「始终允许」并确定")

    usb = usb_devices()
    if not usb:
        unauth = [d for d in devs if d["state"] == "unauthorized"]
        if unauth:
            raise RuntimeError(
                "设备已连接但**未授权**。\n"
                "请在设备屏幕上点「允许 USB 调试」，勾选「始终允许」后重试。")
        raise RuntimeError("只发现了网络设备（%s），没有 USB 设备。\n请用 USB 线连接后再试。"
                           % ", ".join(d["serial"] for d in devs))

    target = usb[0]
    serial = target["serial"]
    push(f"USB 设备：{serial}   ({target.get('model', '未知机型')})")

    rc, out = run_adb(["-s", serial, "tcpip", str(port)], timeout=60)
    low = out.lower()
    if rc != 0 or "cannot" in low or "error" in low:
        raise RuntimeError(
            f"切换 TCP 模式失败：{out}\n"
            "可能原因：固件禁用了 adbd 的 tcpip 指令，或需要 root（可先试「尝试 adb root」）。")
    push(f"adbd 已切到 TCP 模式，端口 {port}")

    push("等待 adbd 重启 …")
    time.sleep(2.5)

    ip = None
    for _ in range(6):
        ip = get_device_ip(serial)
        if ip:
            break
        time.sleep(1.5)
    if not ip:
        raise RuntimeError(
            "已切到 TCP 模式，但没能自动读出设备 IP。\n"
            f"请到设备「设置 → WLAN」里查看当前 IP，用 <IP>:{port} 连接即可。")

    push(f"设备局域网 IP：{ip}")
    addr = f"{ip}:{port}"
    if not port_open(ip, port):
        push(f"[i] {addr} 暂时连不上（可能与电脑不在同一网络，属正常）")

    lhost = local_ip_for(ip)
    report = {"serial": serial, "ip": ip, "addr": addr, "local_ip": lhost,
              "info": device_info(serial)}

    push("")
    push("=" * 54)
    push("  激活完成")
    push("=" * 54)
    push(f"  设备 IP      : {ip}")
    push(f"  无线 ADB 地址 : {addr}")
    push(f"  本机 IP      : {lhost}")
    for k, v in report["info"].items():
        push(f"  {k:<12} : {v}")
    push("")
    push("  下一步：拔掉 USB 线，然后")
    push(f"   · PC 网页工具填 IP = {ip}，端口 = {port}，点「连接」")
    push(f"   · 或车机上运行「BYD飞屏助手」App（它连 127.0.0.1:{port}）")
    push("")
    push("  注意：设备重启后本设置失效，需要重跑一次本工具。")
    push("=" * 54)
    return report


def do_test_wireless(addr, push=log_line):
    push(f"测试无线连接 {addr} …")
    rc, out = run_adb(["connect", addr], timeout=30)
    low = out.lower()
    if "cannot" in low or "failed" in low or "refused" in low or "unable" in low:
        raise RuntimeError(
            f"连接失败：{out}\n"
            "· 确认已先用本工具做过一次「一键激活无线 ADB」\n"
            "· 确认电脑和设备在同一局域网（同一 WiFi，或电脑连设备热点）\n"
            "· 确认设备没有恢复出厂设置（会关掉该开关）")
    _, out2 = run_adb(["-s", addr, "shell", "echo ADB_OK"], timeout=30)
    if "ADB_OK" in out2:
        push(f"[√] {addr} 无线连接正常")
        return True
    raise RuntimeError("已 connect 但 shell 无响应，可能被防火墙或授权弹窗拦截。")


def do_restore_usb(push=log_line):
    devs = list_devices()
    target = None
    for d in devs:
        if ":" not in d["serial"] and d["state"] == "device":
            target = d["serial"]
            break
    if not target:
        for d in devs:
            if d["state"] == "device":
                target = d["serial"]
                break
    if not target:
        raise RuntimeError("没有可用设备。USB 线插好后再试。")
    run_adb(["-s", target, "usb"], check=True)
    push(f"[√] {target} 已切回 USB 模式（关闭 TCP 监听）")


def do_adb_root(push=log_line):
    _, out = run_adb(["root"], timeout=60)
    if "cannot run as root" in out or "not allowed" in out:
        push("[i] 该设备不支持 adb root（非调试版固件，属正常）")
    else:
        push(f"[√] adb root：{out or 'OK'}")
    return out


# --------------------------------------------------------------------------
# 任务调度（同一时刻只跑一个）
# --------------------------------------------------------------------------
class Runner:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy = None

    def start(self, name, fn):
        with self.lock:
            if self.busy:
                raise RuntimeError(f"正在执行「{self.busy}」，请稍候。")
            self.busy = name

        def worker():
            log_line("")
            log_line(f"──── {name} ────")
            try:
                fn()
                log_line(f"[√] {name} 完成")
            except Exception as e:
                log_line("")
                log_line("✗ " + str(e))
                with _LOG_LOCK:
                    _LOG.append("@@ERR@@")      # 前端据此弹窗提示
            finally:
                with self.lock:
                    self.busy = None
        threading.Thread(target=worker, daemon=True).start()


RUNNER = Runner()


# --------------------------------------------------------------------------
# HTTP 服务
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "BYD-AdbActivator/" + VERSION

    def log_message(self, *a):        # 静默（--windowed 下 stderr 可能是 None）
        pass

    # ---- 工具 ----
    def _json(self, obj, code=200):
        import json
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text, code=200):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return self.headers.get("X-Token") == STATE["token"]

    @property
    def _q(self):
        from urllib.parse import urlparse, parse_qs
        return parse_qs(urlparse(self.path).query)

    def _touch(self):
        STATE["last"] = time.time()
        STATE["bye_at"] = None

    # ---- GET ----
    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        self._touch()

        if path in ("/", "/index.html"):
            if self._q.get("t", [""])[0] != STATE["token"]:
                return self._html(PAGE_DENIED, 403)
            return self._html(render_page())

        if path == "/api/state":
            if not self._auth():
                return self._json({"error": "forbidden"}, 403)
            return self._json(self._state())

        if path == "/api/log":
            if not self._auth():
                return self._json({"error": "forbidden"}, 403)
            try:
                n = int(self._q.get("from", ["0"])[0])
            except Exception:
                n = 0
            items, total = log_since(n)
            return self._json({"lines": items, "next": total})

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        return self._html("<h3>404</h3>", 404)

    # ---- POST ----
    def do_POST(self):
        import json
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        self._touch()

        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except Exception:
            data = {}

        if path == "/api/bye":                      # 页面关闭信标
            STATE["bye_at"] = time.time() + BYE_GRACE_SEC
            return self._json({"ok": True})

        if not self._auth():
            return self._json({"error": "forbidden"}, 403)

        try:
            if path == "/api/activate":
                port = int(data.get("port") or DEFAULT_PORT)
                if not (1 <= port <= 65535):
                    raise RuntimeError("端口不合法")

                def job():
                    rep = do_activate(port, log_line)
                    STATE["addr"] = rep["addr"]
                RUNNER.start("激活无线 ADB", job)
                return self._json({"ok": True})

            if path == "/api/test":
                addr = str(data.get("addr") or "").strip()
                if not addr:
                    addr = STATE.get("addr") or ""
                if not addr:
                    raise RuntimeError("还没有无线地址，请先做一次「一键激活」。")
                RUNNER.start("测试无线连接", lambda: do_test_wireless(addr, log_line))
                return self._json({"ok": True})

            if path == "/api/root":
                RUNNER.start("adb root", lambda: do_adb_root(log_line))
                return self._json({"ok": True})

            if path == "/api/usb":
                RUNNER.start("恢复 USB 模式", lambda: do_restore_usb(log_line))
                return self._json({"ok": True})

            if path == "/api/fixadb":
                RUNNER.start("定位 adb", lambda: ensure_adb(True, log_line))
                return self._json({"ok": True})

            if path == "/api/refresh":
                RUNNER.start("刷新设备", lambda: log_line(devices_text()))
                return self._json({"ok": True})

            if path == "/api/quit":
                log_line("用户退出。")
                threading.Thread(target=self._shutdown_later, daemon=True).start()
                return self._json({"ok": True})

            return self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 400)

    def _shutdown_later(self):
        time.sleep(0.4)
        shutdown()

    # ---- 状态 ----
    def _state(self):
        s = {"busy": RUNNER.busy, "adb": str(ADB) if ADB else None,
             "addr": STATE.get("addr"), "log_path": str(LOG_PATH),
             "version": VERSION}
        if ADB is None:
            s["devices"] = []
            s["adb_ok"] = False
            return s
        s["adb_ok"] = True
        try:
            devs = list_devices()
        except Exception:
            devs = []
        s["devices"] = [{"serial": d["serial"], "state": d["state"],
                         "net": ":" in d["serial"],
                         "model": d.get("model", "")} for d in devs]
        for d in devs:
            if ":" in d["serial"]:
                s["addr"] = d["serial"]
        return s


def devices_text():
    try:
        devs = list_devices()
    except Exception as e:
        return f"读取设备失败：{e}"
    if not devs:
        return "未发现设备（USB 调试开了吗？线插好了吗？）"
    parts = []
    for d in devs:
        kind = "网络" if ":" in d["serial"] else "USB"
        mark = {"device": "已连接", "unauthorized": "未授权（请在设备上点允许）",
                "offline": "离线"}.get(d["state"], d["state"])
        tail = f"  {d.get('model','')}" if d.get("model") else ""
        parts.append(f"[{kind}] {d['serial']}  {mark}{tail}")
    return "；".join(parts) + "   —— 共 %d 台" % len(devs)


STATE = {"token": secrets.token_hex(8), "last": time.time(), "bye_at": None, "addr": None}


# --------------------------------------------------------------------------
# 前台页面
# --------------------------------------------------------------------------
PAGE_DENIED = """<!doctype html><meta charset="utf-8">
<body style="font-family:system-ui;background:#0f172a;color:#e6edf7;padding:40px">
<h2>403 链接已失效</h2>
<p>请重新启动本工具，用新打开的窗口操作（每次启动令牌都会变）。</p></body>"""

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{--bg:#0b1220;--card:#131c2e;--line:#22304a;--fg:#e6edf7;--dim:#8fa2c0;
        --acc:#2f6fdd;--ok:#1a9e5f;--err:#d93b3b;--warn:#c98a1a}
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(180deg,#0b1220,#0e1526 60%);color:var(--fg);
       font:14px/1.6 system-ui,"Segoe UI","Microsoft YaHei UI",sans-serif;padding:22px}
  .wrap{max-width:1000px;margin:0 auto}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:var(--dim);font-size:12.5px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
        padding:14px 16px;margin-bottom:12px}
  .card h2{font-size:13px;margin:0 0 10px;color:var(--dim);font-weight:600;
           letter-spacing:.4px;text-transform:uppercase}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  button{font:inherit;font-weight:600;cursor:pointer;border:1px solid var(--line);
         background:#1b2740;color:var(--fg);padding:9px 14px;border-radius:9px}
  button:hover{background:#243357}
  button:disabled{opacity:.45;cursor:not-allowed}
  button.primary{background:var(--acc);border-color:#3d80f0;padding:12px 18px;font-size:15px}
  button.primary:hover{background:#3d80f0}
  input{font:inherit;background:#0d1524;border:1px solid var(--line);color:var(--fg);
        padding:8px 10px;border-radius:8px;width:90px}
  .kv{font-size:12.5px;color:var(--dim)}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#63708a;margin-right:7px}
  .dot.ok{background:var(--ok)}.dot.bad{background:var(--err)}.dot.busy{background:var(--warn)}
  #devs{font-size:12.5px;color:#b9c8e2}
  pre{background:#080e1a;border:1px solid var(--line);border-radius:10px;padding:12px;
      height:300px;overflow:auto;margin:0;font:12px/1.55 Consolas,monospace;
      color:#c8d6ee;white-space:pre-wrap;word-break:break-all}
  pre .e{color:#ff8a8a}
  .pill{display:inline-block;background:#0d1524;border:1px solid var(--line);
        border-radius:999px;padding:3px 10px;font:12px Consolas,monospace;color:#9fc0ff}
  .warn{color:var(--warn)}
</style></head><body><div class="wrap">
  <h1>__TITLE__</h1>
  <div class="sub">用 USB 线连一次，把设备切到「明文 TCP」模式；之后拔线即可无线连接。<br>
   Android 11+ 的「无线调试」是 TLS 加密的，普通工具连不上，必须这样切一次。设备重启后需重跑。</div>

  <div class="card">
    <h2>① 环境</h2>
    <div class="row"><span id="adbdot" class="dot"></span>
      <span id="adbtxt" class="kv">正在检测 adb …</span>
      <button onclick="post('fixadb')">定位 / 重新下载 adb</button>
    </div>
  </div>

  <div class="card">
    <h2>② 设备</h2>
    <div class="row"><span id="devdot" class="dot"></span><span id="devs">未刷新</span>
      <button onclick="post('refresh')">刷新设备列表</button></div>
  </div>

  <div class="card">
    <h2>③ 操作</h2>
    <div class="row" style="margin-bottom:10px">
      <span class="kv">无线 ADB 端口</span><input id="port" value="5555">
      <button class="primary" id="btnAct" onclick="activate()">一键激活无线 ADB（USB 已连接时点我）</button>
    </div>
    <div class="row">
      <button id="btnTest" onclick="test()">测试无线连接</button>
      <button onclick="post('root')">尝试 adb root</button>
      <button onclick="post('usb')">恢复 USB 模式</button>
      <span class="kv">地址：<span class="pill" id="addr">—</span>
        <a href="#" onclick="copyAddr();return false" style="color:#7fb0ff">复制</a></span>
    </div>
  </div>

  <div class="card">
    <h2>运行日志</h2>
    <pre id="log">正在启动 …</pre>
  </div>
  <div class="row" style="justify-content:space-between">
    <span class="kv">关闭本页面会自动退出工具；也可点右侧按钮。</span>
    <span><button onclick="post('quit')">退出工具</button></span>
  </div>
</div>
<script>
const TOKEN = "__TOKEN__";
let from = 0, logEl = document.getElementById('log'), errShown = false;
let lines = [];

function post(name, body){
  return fetch('/api/'+name, {method:'POST',
    headers:{'Content-Type':'application/json','X-Token':TOKEN},
    body: JSON.stringify(body||{})})
   .then(r=>r.json()).then(j=>{ if(j.error){ alert(j.error); } return j; })
   .catch(e=>alert('请求失败：'+e));
}
function activate(){
  const p = parseInt(document.getElementById('port').value)||5555;
  post('activate',{port:p});
}
function test(){ post('test',{}); }
function copyAddr(){
  const a = document.getElementById('addr').textContent;
  if(!a || a==='—'){ return; }
  navigator.clipboard.writeText(a).then(()=>{
    const el=document.getElementById('addr'); const old=el.textContent;
    el.textContent='已复制 '+old; setTimeout(()=>{el.textContent=old},1200);
  });
}
function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function setLines(ls){
  for(const l of ls){
    if(l === '@@ERR@@'){ errShown = true; continue; }
    lines.push(l);
  }
  if(lines.length>1500) lines = lines.slice(-1500);
  logEl.innerHTML = lines.map(l => esc(l)).join('\n');
  logEl.scrollTop = logEl.scrollHeight;
}
function tick(){
  fetch('/api/log?from='+from,{headers:{'X-Token':TOKEN}})
    .then(r=>r.json()).then(j=>{
      if(j.lines && j.lines.length){ setLines(j.lines); }
      if(typeof j.next === 'number') from = j.next;
    }).catch(()=>{});
  fetch('/api/state',{headers:{'X-Token':TOKEN}})
    .then(r=>r.json()).then(s=>{
      const ad = document.getElementById('adbdot'), at=document.getElementById('adbtxt');
      if(s.adb_ok){ ad.className='dot ok'; at.textContent='adb：'+s.adb; }
      else { ad.className='dot bad'; at.textContent='未找到 adb —— 点右侧按钮联网获取'; }
      const devs = s.devices||[];
      const dd = document.getElementById('devdot');
      const dv = document.getElementById('devs');
      if(!devs.length){ dd.className='dot bad'; dv.textContent='未发现设备（USB 调试开了吗？线插好了吗？）'; }
      else{
        const bad = devs.some(d=>d.state!=='device');
        dd.className = 'dot ' + (bad?'busy':'ok');
        dv.textContent = devs.map(d=>'['+(d.net?'网络':'USB')+'] '+d.serial+'  '+
          ({device:'已连接',unauthorized:'未授权（请在设备上点允许）',offline:'离线'}[d.state]||d.state)+
          (d.model?'  '+d.model:'')).join('；');
      }
      const busy = !!s.busy;
      document.getElementById('btnAct').disabled = busy;
      document.getElementById('btnTest').disabled = busy;
      if(s.addr) document.getElementById('addr').textContent = s.addr;
      if(busy) dd.className='dot busy';
      document.title = (busy? '⏳ ' : '') + '__TITLE__';
    }).catch(()=>{});
}
setInterval(tick, 800); tick();

// 关闭/刷新页面 → 通知服务端（8 秒宽限期，刷新不会误退）
function bye(){ try{ navigator.sendBeacon('/api/bye','{}'); }catch(e){} }
window.addEventListener('beforeunload', bye);
window.addEventListener('pagehide', bye);
</script></body></html>"""


def render_page() -> str:
    return (PAGE.replace("__TITLE__", f"{APP_NAME} v{VERSION}")
                .replace("__TOKEN__", STATE["token"]))


# --------------------------------------------------------------------------
# 启动 / 关闭
# --------------------------------------------------------------------------
_HTTPD = None


def shutdown():
    global _HTTPD
    if _HTTPD is not None:
        try:
            _HTTPD.shutdown()
        except Exception:
            pass


def _msgbox(title, text):
    if not IS_WIN:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x40000 | 0x10)
    except Exception:
        pass


def _pick_port(preferred):
    for p in range(preferred, preferred + 30):
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except Exception:
            continue
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(open_browser=True, http_port=DEFAULT_HTTP_PORT):
    global _HTTPD
    port = _pick_port(http_port)
    _HTTPD = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _HTTPD.daemon_threads = True
    url = f"http://127.0.0.1:{port}/?t={STATE['token']}"

    log_line(f"界面地址：{url}")
    log_line("（关闭浏览器页面即退出；无操作 20 分钟后自动退出）")

    def watchdog():
        while True:
            time.sleep(1)
            now = time.time()
            bye_at = STATE.get("bye_at")
            if bye_at and now >= bye_at:
                log_line("页面已关闭，退出。")
                shutdown()
                return
            if now - STATE.get("last", now) > IDLE_EXIT_SEC:
                log_line("长时间无操作，退出。")
                shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()

    if open_browser:
        def _open():
            try:
                ok = webbrowser.open(url)
            except Exception:
                ok = False
            if not ok:
                _msgbox(APP_NAME,
                        "没能自动打开浏览器。\n\n请手动在浏览器里访问：\n" + url +
                        "\n\n（关掉那个页面就会退出本工具）")
        threading.Timer(0.6, _open).start()

    try:
        _HTTPD.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            _HTTPD.server_close()
        except Exception:
            pass
    return 0


def boot():
    """后台预热 adb。"""
    def job():
        try:
            p = ensure_adb(allow_download=False)
            if p:
                log_line(f"[√] adb 就绪：{p}")
                try:
                    _, out = run_adb(["version"], timeout=30)
                    if out:
                        log_line("    " + out.splitlines()[0])
                except Exception:
                    pass
            else:
                log_line("[!] 没找到内置 adb，可点「定位 / 重新下载 adb」联网获取。")
            log_line("")
            log_line(devices_text())
        except Exception as e:
            log_line(f"[!] adb 初始化异常：{e}")
    threading.Thread(target=job, daemon=True).start()


# --------------------------------------------------------------------------
# 自检（用于构建后验证 exe）
# --------------------------------------------------------------------------
def selftest(out_path):
    global ADB
    lines = [f"{APP_NAME} v{VERSION} 自检报告",
             f"frozen        : {is_frozen()}",
             f"python        : {sys.version.split()[0]}",
             f"exe_dir       : {exe_dir()}",
             f"bundle_dir    : {bundle_dir()}"]
    try:
        names = sorted(p.name for p in bundle_dir().iterdir())
    except Exception as e:
        names = [f"(读取失败 {e})"]
    lines += [f"bundle 内容   : {names}",
              f"data_dir      : {data_dir()}"]
    p = None
    try:
        p = ensure_adb(allow_download=False)
    except Exception as e:
        lines.append(f"ensure_adb 异常: {e}")
    lines.append(f"adb 路径      : {p}")
    if p:
        lines.append(f"adb 大小      : {p.stat().st_size} bytes")
        rc, out = run_adb(["version"], timeout=40)
        lines.append(f"adb version   : rc={rc} {out.splitlines()[0] if out else ''}")
        rc, out = run_adb(["devices", "-l"], timeout=40)
        lines.append(f"adb devices   : rc={rc}")
        lines.append("  " + (out.replace("\n", "\n  ") if out else "(空)"))
    lines.append(f"HTTP 服务     : http.server OK (ThreadingHTTPServer)")
    lines.append(f"webbrowser    : ok")
    lines.append(f"日志路径      : {LOG_PATH}")
    lines.append("-" * 50)
    lines.append("内部日志：")
    with _LOG_LOCK:
        lines += ["  " + x for x in _LOG]
    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    if sys.stdout:
        try:
            print(text)
        except Exception:
            pass
    return 0


def httptest(out_path):
    """端到端验证内置 HTTP 服务：起服务 → 打各种接口 → 关服务 → 出报告。"""
    import json
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    lines = [f"{APP_NAME} v{VERSION} 界面自检报告"]
    try:
        ap = ensure_adb(allow_download=False)
        lines.append(f"adb 预加载      : {ap}")
    except Exception as e:
        lines.append(f"adb 预加载失败  : {e}")
    port = _pick_port(DEFAULT_HTTP_PORT + 1)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    base = f"http://127.0.0.1:{port}"
    tok = STATE["token"]
    lines.append(f"http 端口      : {port}")

    def req(path, token=None, method="GET", payload=None):
        h = {"X-Token": token} if token else {}
        data = json.dumps(payload).encode() if payload is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        r = Request(base + path, headers=h, data=data, method=method)
        try:
            with urlopen(r, timeout=90) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    st, body = req(f"/?t={tok}")
    lines.append(f"GET /  (带token): {st}  len={len(body)}  "
                 f"页面完整={'一键激活无线 ADB' in body and '__TOKEN__' not in body}")
    st, _ = req("/?t=bad")
    lines.append(f"GET /  (错token): {st}   （应为 403）")

    st, body = req("/api/state", tok)
    has_busy = '"busy"' in body
    lines.append(f"GET /api/state : {st}  ok={st == 200 and has_busy}")
    lines.append("  " + body[:400].replace("\n", " "))
    st, _ = req("/api/state")
    lines.append(f"GET /api/state (无token): {st}   （应为 403）")

    st, body = req("/api/log?from=0", tok)
    lines.append(f"GET /api/log   : {st}  ok={'next' in body}")

    st, body = req("/api/refresh", tok, "POST", {})
    lines.append(f"POST /api/refresh : {st} {body[:120]}")
    time.sleep(2.0)
    st, body = req("/api/log?from=0", tok)
    try:
        ls = json.loads(body).get("lines", [])
    except Exception:
        ls = []
    lines.append(f"运行日志行数   : {len(ls)}")
    for x in ls[:14]:
        lines.append("  | " + x[:150])

    st, body = req("/api/nope", tok, "POST", {})
    lines.append(f"POST /api/nope : {st} {body[:120]}   （应为 404）")

    st, body = req("/api/test", tok, "POST", {})
    lines.append(f"POST /api/test (无地址应报错): {st} {body[:200]}")

    httpd.shutdown()
    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    if sys.stdout:
        try:
            print(text)
        except Exception:
            pass
    return 0


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        i = argv.index("--selftest")
        out = argv[i + 1] if len(argv) > i + 1 else "selftest.txt"
        return selftest(out)
    if "--httptest" in argv:
        i = argv.index("--httptest")
        out = argv[i + 1] if len(argv) > i + 1 else "httptest.txt"
        return httptest(out)

    log_line("")
    log_line("=" * 54)
    log_line(f"{APP_NAME} v{VERSION} 启动")
    if "--cli" in argv:
        boot_ok = ensure_adb(allow_download=True, progress=log_line)
        if not boot_ok:
            return 1
        try:
            do_activate(DEFAULT_PORT, log_line)
            return 0
        except Exception as e:
            log_line("✗ " + str(e))
            return 1

    try:
        boot()
        return serve(open_browser="--no-browser" not in argv)
    except Exception as e:
        log_line("[FATAL] " + traceback.format_exc())
        _msgbox(APP_NAME, f"启动失败：\n{e}\n\n日志：\n{LOG_PATH}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
