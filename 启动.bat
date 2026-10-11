@echo off
chcp 65001 >nul
title BYD 仪表飞屏助手
setlocal

rem 依次尝试：py 启动器 → python（PATH 里）→ 报错提示
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)

if not defined PY (
  echo.
  echo  [x] 没有找到 Python。
  echo.
  echo      请先安装 Python 3.8 或更高版本：https://www.python.org/downloads/
  echo      安装时记得勾选 "Add python.exe to PATH"。
  echo.
  echo      如果只是想把设备切到明文 5555，可以直接用免安装的：
  echo          pc-exe\BYD无线ADB激活工具.exe
  echo.
  pause
  exit /b 1
)

"%PY%" "%~dp0byd_feipin.py" --web

echo.
echo 服务已停止，按任意键关闭窗口。
pause >nul
