#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包 root/ 目录下的 Magisk / KernelSU 模块。

    python root/build_module.py                 # 产出 byd-feipin-magisk-v<版本>.zip
    python root/build_module.py --out D:\\x.zip  # 指定输出路径
    python root/build_module.py --no-copy       # 不覆盖模块目录里的脚本副本

做三件事：
  1. 把 root/byd-feipin.sh 复制进 magisk-module/（模块必须自带一份）
  2. 校验所有脚本是 LF 换行（CRLF 会导致 Android 上执行失败）
  3. 打成 zip（module.prop 位于压缩包根目录，符合 Magisk 规范）
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE / "magisk-module"
MAIN = HERE / "byd-feipin.sh"

# 必须放在压缩包根目录的条目
REQUIRED = ("module.prop", "service.sh", "customize.sh", "byd-feipin.sh")

# 需要是 LF 结尾的脚本
LF_FILES = ("byd-feipin.sh", "service.sh", "customize.sh")


def log(msg: str) -> None:
    print(msg, flush=True)


def module_version() -> str:
    text = (MODULE / "module.prop").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^version=(.+)$", text, re.M)
    return (m.group(1).strip() if m else "dev")


def copy_main() -> None:
    if not MAIN.is_file():
        log(f"✗ 找不到主脚本：{MAIN}")
        sys.exit(1)
    dst = MODULE / "byd-feipin.sh"
    shutil.copyfile(MAIN, dst)
    log(f"[√] 已复制 byd-feipin.sh -> {dst.relative_to(HERE.parent)}")


def check_lf() -> None:
    for name in LF_FILES:
        p = MODULE / name
        if not p.is_file():
            log(f"✗ 缺少脚本：{name}")
            sys.exit(1)
        raw = p.read_bytes()
        if b"\r\n" in raw:
            # 直接修掉，别让用户踩坑
            p.write_bytes(raw.replace(b"\r\n", b"\n"))
            log(f"[!] {name} 含 CRLF，已自动改成 LF（CRLF 在 Android 上会执行失败）")
    log("[√] 换行符检查通过（全部 LF）")


def check_prop() -> None:
    text = (MODULE / "module.prop").read_text(encoding="utf-8", errors="replace")
    need = ("id=", "name=", "version=", "versionCode=", "author=", "description=")
    missing = [k for k in need if not re.search(rf"^{re.escape(k)}", text, re.M)]
    if missing:
        log(f"✗ module.prop 缺少字段：{', '.join(missing)}")
        sys.exit(1)
    # versionCode 必须是整数
    m = re.search(r"^versionCode=(.+)$", text, re.M)
    if m and not m.group(1).strip().isdigit():
        log("✗ module.prop 的 versionCode 必须是整数")
        sys.exit(1)
    log("[√] module.prop 字段完整")


def build_zip(out: Path) -> Path:
    files = sorted(p for p in MODULE.rglob("*") if p.is_file())
    # 排除 Windows 上的临时/备份文件
    files = [p for p in files if not p.name.startswith(".") and "~" not in p.name]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            arc = p.relative_to(MODULE).as_posix()
            zi = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o755 if p.suffix == ".sh" else 0o644) << 16
            z.writestr(zi, p.read_bytes())
    return out


def verify_zip(zp: Path) -> bool:
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        log(f"[√] 压缩包内 {len(names)} 个条目")
        for n in names:
            log(f"      {n}")
        ok = True
        for r in REQUIRED:
            if r not in names:
                log(f"✗ 缺少必需条目：{r}")
                ok = False
        # 校验内部脚本仍是 LF
        for n in names:
            if n.endswith(".sh") and b"\r\n" in z.read(n):
                log(f"✗ {n} 在压缩包里含 CRLF")
                ok = False
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="输出 zip 路径")
    ap.add_argument("--no-copy", action="store_true", help="不覆盖模块目录里的 byd-feipin.sh")
    a = ap.parse_args()

    ver = module_version()
    out = Path(a.out) if a.out else HERE / f"byd-feipin-magisk-{ver}.zip"

    log(f"打包 BYD 飞屏 Magisk 模块 {ver}")
    log(f"  源目录 : {MODULE}")
    log("")

    if not a.no_copy:
        copy_main()
    check_lf()
    check_prop()

    zp = build_zip(out)
    log("")
    log(f"[√] 产物：{zp}  ({zp.stat().st_size / 1024:.1f} KB)")
    log("")
    ok = verify_zip(zp)

    log("")
    if ok:
        log("[√] 校验通过，可以直接在 Magisk / KernelSU 里刷入")
    else:
        log("[!] 校验未通过，见上面的错误")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
