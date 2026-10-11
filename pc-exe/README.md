# BYD 无线ADB激活工具（Windows 独立 exe）

**双击就能用，不需要装 Python、不需要装 adb、不需要联网。**

解决的问题：Android 11 及以上的「无线调试」是 **TLS 双向加密 + 随机端口 + 配对码**，
普通程序（包括本项目的网页工具和车机 App）连不上它，也**不监听 5555**。
本工具用 USB 线连一次，执行 `adb tcpip 5555`，把 adbd 切回**经典明文 TCP 模式**，
之后拔掉 USB 线就能无线连接。

---

## 一、怎么用

### 1. 车机（比亚迪 DiLink）

车机的「无线 adb 调试」本来就是明文 5555，**通常不需要本工具**。
只有在遇到下面情况时才用：

- 车机重启后 adb 连不上
- 恢复出厂设置后开关掉了
- 用别的方式开启后端口不是 5555

### 2. Android 11+ 手机 / 平板

**这是本工具的主战场。**

```
① USB 线把设备连到电脑（要能用数据传输的线）
② 设备上：设置 → 关于手机 → 连点「版本号」7 次 → 打开开发者选项
   → 打开「USB 调试」
③ 设备弹窗「允许 USB 调试吗？」→ 勾「始终允许」→ 确定
④ 双击 BYD-Wireless-ADB-Activator.exe
⑤ 浏览器自动打开界面，确认「设备」那栏显示 [USB] xxxxxxx 已连接
⑥ 点「一键激活无线 ADB」
⑦ 成功后会显示设备 IP 和地址，例如 192.168.1.23:5555
⑧ 拔掉 USB 线，到 PC 网页工具里填这个 IP 点「连接」
```

> ⚠️ **设备重启后本设置会失效**，需要重新跑一次。
> 这是 Android 的设计（`service.adb.tcp.port` 不持久化）。

---

## 二、界面说明

| 区块 | 作用 |
|---|---|
| ① 环境 | 显示 adb 是否就绪。内置 adb 被安全软件删了的话，点右边按钮联网重新下载 |
| ② 设备 | 列出 USB / 网络设备。**「未授权」**就是设备上还没点「允许」 |
| ③ 操作 | 一键激活 / 测试无线连接 / 尝试 adb root / 恢复 USB 模式 |
| 运行日志 | 所有 adb 命令和输出都在这，出问题时把它复制出来发我 |

**关闭浏览器页面 = 退出工具**（留了 8 秒宽限期，刷新页面不会误退）。
长期没操作（20 分钟）也会自动退出。

---

## 三、各按钮干什么

| 按钮 | 实际执行的命令 | 什么时候用 |
|---|---|---|
| 一键激活无线 ADB | `adb tcpip <port>` + 自动读设备 IP | 主要功能 |
| 测试无线连接 | `adb connect <ip>:<port>` + `echo` 往返 | 拔线后确认能不能连 |
| 尝试 adb root | `adb root` | 车机上跑 `service call` 权限不足时 |
| 恢复 USB 模式 | `adb usb` | 想关掉 TCP 监听、只留 USB |
| 定位 / 重新下载 adb | 释放内置 adb，失败则下载 platform-tools | 内置 adb 被删/被杀软拦截 |

---

## 四、它到底做了什么（安全说明）

只调用**官方 adb 命令**，等价于你手敲：

```
adb start-server
adb devices -l
adb -s <设备序列号> tcpip 5555
adb -s <设备序列号> shell ip route get 8.8.8.8     # 读 IP
adb -s <设备序列号> shell getprop ro.build.display.id  # 读固件版本
```

- **不刷机、不改固件、不写任何系统分区**
- 唯一改动的系统属性是 `service.adb.tcp.port`（标准 adb 行为，重启即恢复）
- HTTP 服务**只监听 127.0.0.1**，外部网络访问不到；每次启动生成随机令牌，链接外泄也用不了
- 所有动作都打印在日志里，可以自己核对

日志文件：`%LOCALAPPDATA%\BYD-Feipin\usb-activate.log`
adb 落地目录：`%LOCALAPPDATA%\BYD-Feipin\platform-tools\`

---

## 五、已做的验证

构建脚本会在打包后**自动跑两组自检**（失败会报出来）：

**第一组：adb 内置与可用性**

```
frozen        : True
bundle 内容   : ['adb.exe', 'AdbWinApi.dll', 'AdbWinUsbApi.dll', 'python313.dll', ...]
adb 大小      : 8273560 bytes
adb version   : rc=0  Android Debug Bridge version 1.0.41
adb devices   : rc=0  List of devices attached
                      <设备序列号>   device   model:XXXX
```

**第二组：HTTP 界面与接口**

```
GET /  (带token): 200  len=7259  页面完整=True
GET /  (错token): 403   （应为 403）
GET /api/state : 200  ok=True
GET /api/state (无token): 403   （应为 403）
GET /api/log   : 200  ok=True
POST /api/nope : 404 {"error": "unknown endpoint"}   （应为 404）
POST /api/test (无地址应报错): 400 {"error": "还没有无线地址…"}
```

**第三组：退出逻辑**（单独实测）

```
关掉页面的信标 → 8 秒内刷新页面 → 仍在运行 ✓（宽限期生效，刷新不误退）
继续不触碰     → 自动退出，日志写入「页面已关闭，退出。」✓
点「退出工具」 → {"ok": true} → 进程退出 ✓
```

> **仍需实机确认的**：`adb tcpip` 对具体设备/固件的实际效果。
> 如果设备状态显示 `unauthorized`，必须先在设备屏幕上点「允许 USB 调试」，
> 本工具没法代劳这一步。

---

## 六、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 界面里「未发现设备」 | USB 调试没开 / 线是充电线 / 驱动没装（Windows 设备管理器里看有没有黄色感叹号） |
| 设备显示 **未授权** | 设备屏幕上有个「允许 USB 调试」弹窗，勾「始终允许」并点确定。没弹窗就拔插一次或 `adb kill-server` 重来 |
| 提示「切换 TCP 模式失败」 | 固件禁用了 adbd 的 tcpip 指令。先试「尝试 adb root」再激活 |
| 激活成功但连不上 | 电脑和设备不在同一网段。电脑连设备热点，或让两者连同一 WiFi。工具会显示本机 IP 供你比对 |
| 重启后又连不上 | 正常的，`tcpip` 设置不持久，重跑一次 |
| 杀软报毒 | PyInstaller 打包的单文件 exe 经常被误报。加白名单，或用源码方式跑：`python usb_activate.py` |
| 浏览器没自动打开 | 工具会弹窗给出地址，手动粘贴到浏览器即可 |

---

## 七、自己重新打包

```
python build_exe.py                     # 打包 + 自动自检
python build_exe.py --clean             # 先清理再打包
python build_exe.py --no-verify         # 只打包
python build_exe.py --sdk D:\android-sdk\platform-tools   # 手动指定 adb 来源
```

依赖：PyInstaller。脚本会自动在 `pc-exe/.venv/` 建一个隔离虚拟环境并安装，
**不需要预先配好任何环境变量，也不会污染系统 Python**。

adb 二进制的获取顺序：
1. `vendor/` 里已有 → 直接用
2. `--sdk` 指定的目录 / `ANDROID_HOME` / `ANDROID_SDK_ROOT` / 常见 SDK 默认位置
3. 都没有 → 联网下载 Google 官方 platform-tools

**技术选型说明**：无 GUI 依赖 —— 走「内置 HTTP 服务 + 浏览器界面」，
纯 Python 标准库实现，打包成单文件 exe，不引入任何第三方 GUI 库。
这样在**没装 tkinter** 或**没有 C# 编译器**的机器上也能构建。

---

## 八、文件清单

| 文件 | 说明 |
|---|---|
| `usb_activate.py` | 源码（adb 逻辑 + HTTP 界面） |
| `build_exe.py` | 打包 + 自动自检脚本 |
| `vendor/` | 放置 adb.exe 与两个 DLL 的目录（**不入库**，打包时自动获取） |

打包产物 `BYD-Wireless-ADB-Activator.exe` **不入库**，发布在
[Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest)：
直接下载即可用，或按上面的命令自己构建。

> `vendor/` 里的 adb.exe / AdbWinApi.dll / AdbWinUsbApi.dll 来自
> [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)，
> 版权归 Google 所有，遵循其随附的许可条款。
> 因为体积（约 8 MB）且属于第三方二进制，**不放进 Git 仓库**，
> 由 `build_exe.py` 在打包时从本地 SDK 复制或从 Google 官方下载。
