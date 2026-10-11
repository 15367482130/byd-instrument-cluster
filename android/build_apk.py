#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BYD 仪表飞屏助手 —— Android APK 构建脚本（无需 Android Studio / Gradle）
========================================================================
直接用 aapt2 + javac + d8 + zipalign + apksigner 打包。

首次运行会自动下载：
  * JDK 17           （优先华为云镜像，Adoptium 兜底，约 180 MB）
  * Android 命令行工具 + platform(android-34) + build-tools(34.0.0)

产物：android/BYD飞屏助手.apk（minSdk 26 / targetSdk 33，debug 签名）

用法：
    python build_apk.py                # 构建
    python build_apk.py --env D:\\sdk   # 指定工具缓存目录（默认 ~/.wb-android-build）
"""

from __future__ import annotations

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
APP = HERE / "app"
BUILD = HERE / "build"
SIGNED_APK = HERE / "BYD-Feipin.apk"          # ASCII 名，避免 Java 工具链处理中文路径出错
OUT_APK = HERE / "BYD飞屏助手.apk"             # 最终交付名（构建完后由 Python 复制）

# JDK 候选源（国内镜像优先，Adoptium 兜底）
JDK_URLS = [
    "https://mirrors.huaweicloud.com/openjdk/17.0.2/openjdk-17.0.2_windows-x64_bin.zip",
    "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse",
]
CMDTOOLS_URL = {
    "Windows": "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip",
    "Darwin": "https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip",
    "Linux": "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip",
}

PLATFORM = "android-34"
BUILD_TOOLS = "34.0.0"
MIN_SDK = "26"
TARGET_SDK = "33"

EXE = ".exe" if os.name == "nt" else ""
BAT = ".bat" if os.name == "nt" else ""

JDK_HOME: Path | None = None


def log(*a) -> None:
    print("[build]", *a, flush=True)


def run(cmd, cwd=None, env=None, check=True, capture=True):
    log("$", " ".join(str(c) for c in cmd))
    p = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True, encoding="utf-8", errors="replace",
    )
    if capture and p.stdout:
        for line in p.stdout.rstrip().splitlines()[-25:]:
            print("   ", line)
    if check and p.returncode != 0:
        raise SystemExit(f"命令失败（{p.returncode}）：{' '.join(str(c) for c in cmd)}")
    return p


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1024:
        log("已存在，跳过下载：", dest.name)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    log("下载", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                print(f"\r     {got*100//total}%  ({got>>20}/{total>>20} MB)", end="", flush=True)
    print()
    tmp.replace(dest)


# ---------------------------------------------------------------- JDK
def ensure_jdk(env_dir: Path) -> Path:
    global JDK_HOME
    found = shutil.which("javac")
    if found:
        JDK_HOME = Path(found).resolve().parent.parent
        log("使用系统 JDK：", JDK_HOME)
        return JDK_HOME

    jdk_dir = env_dir / "jdk"
    javac = jdk_dir / "bin" / ("javac.exe" if os.name == "nt" else "javac")
    if not javac.exists():
        zpath = env_dir / "jdk.zip"
        last_err = None
        for url in JDK_URLS:
            try:
                download(url, zpath)
                break
            except Exception as e:      # noqa: BLE001
                last_err = e
                log("下载失败，尝试下一个源：", e)
        else:
            raise SystemExit(f"JDK 下载失败：{last_err}")
        log("解压 JDK …")
        tmp = env_dir / "jdk-tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        inner = next(tmp.iterdir())
        if jdk_dir.exists():
            shutil.rmtree(jdk_dir)
        inner.rename(jdk_dir)
        shutil.rmtree(tmp, ignore_errors=True)
    JDK_HOME = jdk_dir
    log("使用下载的 JDK：", JDK_HOME)
    return jdk_dir


def tool(name: str) -> str:
    p = JDK_HOME / "bin" / (name + EXE)
    return str(p) if p.exists() else name


# ---------------------------------------------------------------- Android SDK
def ensure_sdk(env_dir: Path) -> Path:
    sdk = env_dir / "sdk"
    sdkmanager = sdk / "cmdline-tools" / "latest" / "bin" / ("sdkmanager" + BAT)

    if not sdkmanager.exists():
        zpath = env_dir / "cmdtools.zip"
        download(CMDTOOLS_URL[platform.system()], zpath)
        log("解压 Android 命令行工具 …")
        tmp = env_dir / "cmdtools-tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        latest = sdk / "cmdline-tools" / "latest"
        latest.parent.mkdir(parents=True, exist_ok=True)
        if latest.exists():
            shutil.rmtree(latest)
        (tmp / "cmdline-tools").rename(latest)
        shutil.rmtree(tmp, ignore_errors=True)

    # 环境
    env = dict(os.environ)
    env["JAVA_HOME"] = str(JDK_HOME)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["PATH"] = str(JDK_HOME / "bin") + os.pathsep + env.get("PATH", "")

    want = [f"platforms;{PLATFORM}", f"build-tools;{BUILD_TOOLS}", "platform-tools"]
    need = (not (sdk / "platforms" / PLATFORM / "android.jar").exists()
            or not (sdk / "build-tools" / BUILD_TOOLS).exists())
    if need:
        log("接受 SDK 许可 …")
        subprocess.run([str(sdkmanager), f"--sdk_root={sdk}", "--licenses"],
                       input="y\n" * 60, text=True, env=env)
        log("安装 SDK 组件 …")
        run([str(sdkmanager), f"--sdk_root={sdk}", "--install", *want], env=env)

    return sdk


# ---------------------------------------------------------------- 构建
def build(sdk: Path) -> Path:
    bt = sdk / "build-tools" / BUILD_TOOLS
    android_jar = sdk / "platforms" / PLATFORM / "android.jar"
    if not android_jar.exists():
        raise SystemExit(f"缺少 {android_jar}")

    def btool(n):
        p = bt / (n + BAT)
        return str(p) if p.exists() else str(bt / (n + EXE))

    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "classes").mkdir(parents=True)
    (BUILD / "dex").mkdir(parents=True)
    (BUILD / "gen").mkdir(parents=True)

    # 1) 资源（本项目无 res，可跳过）
    res = APP / "res"
    has_res = res.exists() and any(res.iterdir())
    if has_res:
        run([btool("aapt2"), "compile", "--dir", str(res), "-o", str(BUILD / "res.zip")])

    # 2) 链接资源，生成未签名 APK
    unaligned = BUILD / "app.unaligned.apk"
    link_cmd = [btool("aapt2"), "link", "-o", str(unaligned),
                "-I", str(android_jar),
                "--manifest", str(APP / "AndroidManifest.xml"),
                "--java", str(BUILD / "gen"),
                "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK]
    if has_res:
        link_cmd += ["--auto-add-overlay", "-R", str(BUILD / "res.zip")]
    run(link_cmd)

    # 3) 编译 Java
    srcs = [str(p) for p in (APP / "src").rglob("*.java")]
    srcs += [str(p) for p in (BUILD / "gen").rglob("*.java")]
    run([tool("javac"), "-J-Duser.language=en", "-J-Duser.country=US",
         "-encoding", "UTF-8", "-source", "8", "-target", "8",
         "-nowarn", "-classpath", str(android_jar),
         "-d", str(BUILD / "classes"), *srcs])

    # 4) dex
    classes = [str(p) for p in (BUILD / "classes").rglob("*.class")]
    run([btool("d8"), "--lib", str(android_jar), "--min-api", MIN_SDK,
         "--output", str(BUILD / "dex"), *classes])

    # 5) 把 classes.dex 塞进 APK
    log("打包 classes.dex …")
    with zipfile.ZipFile(unaligned, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(BUILD / "dex" / "classes.dex", "classes.dex")

    # 6) 对齐
    aligned = BUILD / "app.aligned.apk"
    run([btool("zipalign"), "-f", "4", str(unaligned), str(aligned)])

    # 7) 生成调试签名并签名（密钥放在 build/ 之外，保证重复构建签名一致）
    ks = HERE / "debug.keystore"
    if not ks.exists():
        run([tool("keytool"), "-genkeypair", "-keystore", str(ks),
             "-storepass", "android", "-keypass", "android",
             "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
             "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"])

    run([btool("apksigner"), "sign",
         "--ks", str(ks), "--ks-pass", "pass:android", "--key-pass", "pass:android",
         "--out", str(SIGNED_APK), str(aligned)])

    run([btool("apksigner"), "verify", "--print-certs", str(SIGNED_APK)], check=False)

    shutil.copyfile(SIGNED_APK, OUT_APK)
    return OUT_APK


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=str(Path.home() / ".wb-android-build"))
    args = ap.parse_args()

    env_dir = Path(args.env)
    env_dir.mkdir(parents=True, exist_ok=True)

    ensure_jdk(env_dir)
    # 全局导出 JAVA_HOME —— d8.bat / apksigner.bat 这类脚本依赖它找 java
    os.environ["JAVA_HOME"] = str(JDK_HOME)
    os.environ["PATH"] = str(JDK_HOME / "bin") + os.pathsep + os.environ.get("PATH", "")

    sdk = ensure_sdk(env_dir)
    apk = build(sdk)

    log("完成 ✅  产物：", apk)
    log("大小：%.2f MB" % (apk.stat().st_size / 1048576))
    log("安装：adb install -r \"%s\"" % apk)


if __name__ == "__main__":
    main()
