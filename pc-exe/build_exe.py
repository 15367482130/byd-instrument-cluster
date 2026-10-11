# -*- coding: utf-8 -*-
"""
把 usb_activate.py 打包成一个 Windows 独立 exe（免 Python 运行）。

    python build_exe.py              # 打包
    python build_exe.py --clean      # 先清掉 build/dist 再打包

依赖：PyInstaller（本脚本会自动装到隔离虚拟环境里）+ 本仓库的 adb 二进制。
adb.exe 会被**打进 exe 内部**，所以最终用户不需要额外下载任何东西。
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "usb_activate.py"
VENDOR = HERE / "vendor"
BUILD = HERE / "build"
DIST = HERE / "dist"

NAME_ASCII = "BYD-Wireless-ADB"                  # 先输出 ASCII 名，避开工具链编码坑
OUT_NAME = "BYD无线ADB激活工具.exe"

ADB_FILES = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
PT_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"

# adb 来源（按顺序找）：环境变量指到的 SDK、项目自带的 platform-tools、常见默认安装位置
SDK_CANDIDATES = [p for p in [
    Path(os.environ["ANDROID_HOME"]) / "platform-tools"
        if os.environ.get("ANDROID_HOME") else None,
    Path(os.environ["ANDROID_SDK_ROOT"]) / "platform-tools"
        if os.environ.get("ANDROID_SDK_ROOT") else None,
    Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools"
        if os.environ.get("LOCALAPPDATA") else None,
    Path(os.environ["USERPROFILE"]) / "AppData/Local/Android/Sdk/platform-tools"
        if os.environ.get("USERPROFILE") else None,
    Path.home() / "Library/Android/sdk/platform-tools",
    Path("/usr/lib/android-sdk/platform-tools"),
    HERE.parent / "platform-tools" / "platform-tools",
    HERE.parent / "platform-tools",
] if p is not None]


# 打包用的虚拟环境；不存在就自动创建到 .venv（不再依赖任何本机绝对路径）
VENV_DIR = HERE / ".venv"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def log(*a):
    print(*a, flush=True)


def boot_python() -> str:
    """优先用项目内 .venv；没有就在旁边建一个，避免污染系统 Python。"""
    vp = venv_python()
    if vp.exists():
        return str(vp)
    log(f"创建虚拟环境 {VENV_DIR} …")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        if vp.exists():
            return str(vp)
    except subprocess.CalledProcessError as e:
        log(f"[!] 建 venv 失败（{e}），改用当前解释器")
    return sys.executable


def ensure_pyinstaller(py: str) -> None:
    try:
        subprocess.run([py, "-c", "import PyInstaller"], check=True,
                       capture_output=True)
        log("[√] PyInstaller 已就绪")
        return
    except subprocess.CalledProcessError:
        pass
    log("安装 PyInstaller …")
    subprocess.run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"], check=False)
    subprocess.run([py, "-m", "pip", "install", "-q", "pyinstaller"], check=True)
    log("[√] PyInstaller 安装完成")


def ensure_vendor(extra_sdk=None) -> None:
    """把 adb + 两个 DLL 放到 vendor/，供 --add-binary 打包。"""
    VENDOR.mkdir(parents=True, exist_ok=True)
    have = all((VENDOR / f).is_file() and (VENDOR / f).stat().st_size > 1000
               for f in ADB_FILES)
    if have:
        log(f"[√] vendor/ 已具备 adb（{(VENDOR / 'adb.exe').stat().st_size // 1024} KB）")
        return

    candidates = list(extra_sdk or []) + SDK_CANDIDATES
    for d in candidates:
        d = Path(d)
        if (d / "adb.exe").is_file():
            log(f"从本地 SDK 复制 adb：{d}")
            for f in ADB_FILES:
                if (d / f).is_file():
                    shutil.copy2(d / f, VENDOR / f)
            if (VENDOR / "adb.exe").is_file():
                log("[√] adb 就绪")
                return

    log("本地没有 adb，联网下载 platform-tools …")
    zpath = HERE / "platform-tools.zip"
    req = urllib.request.Request(PT_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(zpath, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp = HERE / "_pt"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp)
    src = tmp / "platform-tools"
    if not src.is_dir():
        src = tmp
    for f in ADB_FILES:
        if (src / f).is_file():
            shutil.copy2(src / f, VENDOR / f)
    shutil.rmtree(tmp, ignore_errors=True)
    zpath.unlink(missing_ok=True)
    if not (VENDOR / "adb.exe").is_file():
        raise SystemExit("✗ 没能获取 adb.exe")
    log("[√] adb 下载完成")


def clean() -> None:
    for d in (BUILD, DIST):
        shutil.rmtree(d, ignore_errors=True)
    log("[√] 已清理 build/ dist/")


def build(py: str) -> Path:
    sep = os.pathsep                       # Windows 上是 ';'（路径含盘符冒号，必须用分号）
    args = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--windowed",
        "--name", NAME_ASCII,
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        # 关掉用不到的重型模块，压体积
        "--exclude-module", "numpy",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "pandas",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "lib2to3",
    ]
    for f in ADB_FILES:
        p = VENDOR / f
        if p.is_file():
            args += ["--add-binary", f"{p}{sep}."]
    args.append(str(SRC))

    log("运行 PyInstaller …")
    subprocess.run(args, check=True, cwd=str(HERE))

    raw = DIST / (NAME_ASCII + ".exe")
    if not raw.is_file():
        raise SystemExit(f"✗ 没生成 {raw}")
    out = HERE / OUT_NAME
    shutil.copy2(raw, out)
    return out


def verify(exe: Path) -> bool:
    """跑内置自检：确认 exe 能启动、adb 已内置可执行、HTTP 界面可用。"""
    ok = True

    report = HERE / "_selftest.txt"
    log("运行 exe 自检（adb）…")
    subprocess.run([str(exe), "--selftest", str(report)], timeout=240, check=False)
    if not report.is_file():
        log("✗ adb 自检没产出报告")
        ok = False
    else:
        text = report.read_text(encoding="utf-8", errors="replace")
        print(text)
        if "adb 路径      : None" in text or "Android Debug Bridge" not in text:
            ok = False

    report2 = HERE / "_httptest.txt"
    log("运行 exe 自检（界面接口）…")
    subprocess.run([str(exe), "--httptest", str(report2)], timeout=300, check=False)
    if not report2.is_file():
        log("✗ 界面自检没产出报告")
        ok = False
    else:
        print(report2.read_text(encoding="utf-8", errors="replace"))
        t2 = report2.read_text(encoding="utf-8", errors="replace")
        for need in ("GET /  (带token): 200", "(错token): 403", "/api/state : 200"):
            if need not in t2:
                log(f"✗ 界面自检缺少预期结果：{need}")
                ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="先清理 build/dist")
    ap.add_argument("--no-verify", action="store_true", help="跳过自检")
    ap.add_argument("--sdk", action="append", default=[], metavar="DIR",
                    help="额外的 Android SDK / platform-tools 目录（可重复）")
    a = ap.parse_args()

    if platform.system() != "Windows":
        log(f"[!] 当前系统是 {platform.system()}，产物将是该平台的可执行文件，不是 .exe")

    if a.clean:
        clean()
    py = boot_python()
    log(f"使用 Python：{py}")
    ensure_pyinstaller(py)
    ensure_vendor(a.sdk)
    exe = build(py)
    size = exe.stat().st_size
    log(f"\n[√] 产物：{exe}  ({size / 1048576:.1f} MB)")

    if a.no_verify:
        return 0
    if verify(exe):
        log("[√] 全部自检通过：exe 可运行、adb 已内置、HTTP 界面正常")
    else:
        log("[!] 有自检项未通过，请看上面的报告")
    for f in ("_selftest.txt", "_httptest.txt"):
        (HERE / f).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
