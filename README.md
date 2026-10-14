# BYD 仪表飞屏助手 (byd-cluster-feipin)

在比亚迪 DiLink 4.0「**18.x / 21.x 控制器**」全液晶仪表车型上，打开被隐藏的
「**仪表全屏导航**」功能（俗称"地图飞屏"），即把导航地图直接投到仪表盘全屏显示。

本项目提供**三种形态**，命令序列完全一致：

| 形态 | 源码 | 成品 | 特点 |
|---|---|---|---|
| **PC 工具** | `byd_feipin.py` | 无需构建 | 电脑连车机热点，网页界面，零依赖 |
| **车机 App** | `android/` | **Release 里的 APK** | 装在车机上免电脑，支持**开机自动开启** |
| **USB 激活器** | `pc-exe/` | **Release 里的 exe** | 单文件 12 MB，**免装 Python / 免装 adb**，把 Android 11+ 设备切回明文 5555 |
| **root 版** | `root/` | `root/*.zip` | 车机已 root 时用。**彻底不需要 ADB**，开机自动、重启不失效 |

> ⚠️ 仅适用于 18.x / 21.x 控制器的全液晶仪表。低配机械仪表不支持。
> 请在车辆停稳 P 挡时操作，行驶中请勿使用。此类改动可能影响车机质保，风险自负。

> **车机已经 root 了？** 建议直接用 [`root/`](root/README.md) —— 不需要开无线调试、
> 不需要授权弹窗、重启不会失效，刷个几 KB 的模块就开机自动生效。
> 详见 [root/README.md](root/README.md)。

---

## 直接下载（不用自己构建）

到 **[Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest)** 下载编译好的成品：

| 文件 | 用途 |
|---|---|
| `BYD-Cluster-Feipin-v1.1.0.apk` | 车机端 App，装到车机上直接开飞屏（含开机自动开启） |
| `BYD-Wireless-ADB-Activator-v1.0.0.exe` | Windows 无线 ADB 激活器，内置 adb、免安装 |
| `BYD-Feipin-Magisk-Module-v1.1.0.zip` | **root 版开机自启模块**（Magisk / KernelSU 刷入） |

> 车机**已经 root** 的话，直接刷 Magisk 模块最省事 —— 不需要 ADB、重启也不失效，
> 详见 [`root/README.md`](root/README.md)。

仓库里**只放源码**，编译产物统一发布到 Release —— 这样 `git clone` 只有几百 KB。
想自己构建见「三、构建」。

---

## 一、它是怎么实现的

比亚迪车机里本来就自带一个**仪表调试工具** `ClusterDebug`，加上系统里的两个
Binder 服务，就能把仪表导航从「简易导航」切到「全屏导航」。社区里的小缘《Freedom》、
《迪友桌面》等工具，本质上做的就是这套动作。

涉及三个接口（均来自公开逆向资料）：

| 接口 | 作用 | 调用方式 |
|---|---|---|
| `com.byd.clusterdebug` | 车机自带的仪表调试 App，作特权代理 | `am startservice -n com.byd.clusterdebug/.ClusterDebugService` |
| `autoservice` | `INSTRUMENT_NAVI_TYPE`：仪表导航类型 | 读：`service call autoservice 5 i32 1007 i32 1086337074`<br>写：`service call autoservice 6 i32 1007 i32 1276157976 i32 <n>` |
| `AutoContainer` | 投影开关（模式号按字符串传） | `service call AutoContainer 2 i32 1000 s16 "<mode>"` |

**仪表导航类型 `<n>`**：`1`=关闭 `2`=随导航 `3`=小屏导航 `4`=**全屏导航**

**AutoContainer 模式**：`39`=简易导航 `16`=**全屏投影** `17`=半屏投影 `18`=关闭投影 `35`=Di4.0 模式（创建投影显示）

> 原理要点：18.x 的仪表默认只给「简易导航」（转向卡片）。只有把 `INSTRUMENT_NAVI_TYPE`
> 设成 `4`，并用 `35` 让车机创建出投影显示、再发 `16` 打开全屏投影，配合定制版地图启动，
> 仪表才会真正出全屏地图。

**「开启飞屏」的完整动作序列**：

```
1. am startservice -n com.byd.clusterdebug/.ClusterDebugService   # 启动调试代理
2. am start        -n com.byd.clusterdebug/.MainActivity
3. service call autoservice 6 i32 1007 i32 1276157976 i32 4        # 仪表导航类型 = 全屏
4. service call AutoContainer 2 i32 1000 s16 "35"                  # 创建 Di4.0 投影显示
   （等 1 秒）
5. service call AutoContainer 2 i32 1000 s16 "16"                  # 打开全屏投影
6. monkey -p <定制版地图包名> -c android.intent.category.LAUNCHER 1  # 启动地图
```

**关闭**：`AutoContainer "18"` 关闭投影 + `INSTRUMENT_NAVI_TYPE` 恢复为 `1`（或 `2`）。

---

## 二、环境准备

1. **电脑**：Windows / macOS / Linux，装好 Python 3.8+（本工具只用标准库）。
2. **adb**：本工具可自动下载 platform-tools。也可自行安装并把 `adb` 放进 PATH。
3. **车机**：
   - 进入「车辆设置 → 版本管理」，**连续点击「恢复出厂设置」**（不是右边的「恢复」按钮），
     进入隐藏的 ADB 调试设置界面；
   - 打开 **连接 USB 后启用调试模式** + **无线 ADB 调试**；
   - 若界面上没有这两个开关（部分车型被隐藏），有两条路：
     - 装一个「BYD 开发工具 / 无线 adb 开关」类的小工具（安装后无图标属正常），再回去点；
     - 或在拨号盘输入 `*#91532547#*` 生成二维码，交给**售后**用精诚助手扫码后当场打开这两个开关
       （3.0/4.0/5.0 车机、固件 2406 之后的版本常见这种做法）；
   - 记录车机 IP（默认 `192.168.10.10`，端口 `5555`）。
   - ⚠️ 开完**不要恢复出厂设置**，否则开关会掉。
4. **联网方式**：电脑连接**车机热点**，或与车机在同一局域网。
5. **地图**：车机上装好**高德地图定制版 / 百度地图定制版**（18.x 依赖定制版才能投仪表）。

---

## 二之二、连不上？先分清「两种无线 ADB」

这是最容易踩的坑：**同样叫"无线调试"，Android 11 前后完全是两套东西**。

| | Android ≤ 10（含比亚迪 DiLink） | Android 11+（手机 / 部分新车机） |
|---|---|---|
| 开关名字 | 连接USB后启用调试模式 / **无线 ADB 调试** | **无线调试**（Wireless debugging） |
| 端口 | **固定 5555** | **随机临时端口**（典型 37000~45000） |
| 加密 | 无，明文 | **TLS 双向加密 + 需要配对码** |
| 端口数量 | 1 个 | **2 个**：配对端口 + 连接端口 |
| 普通程序能否直连 5555 | **能** | **不能**（端口根本不是 5555，且要 TLS） |

所以：

- **在比亚迪车机上** —— 打开「无线 adb 调试」后走的就是 **5555 明文**，本工具（PC 版 &
  车机 App）**直接能连**。这也是本项目的目标场景。
- **在 Android 11+ 手机上测试** —— 你打开「无线调试」后 **5555 是不通的**，
  必然报 `ECONNREFUSED (Connection refused)`。这不是设置错，是模式不对。

**Android 11+ 上还想用本工具**，任选一种：

```bash
# 方法 1（推荐，免装 Python）：双击 BYD-Wireless-ADB-Activator.exe
#          （从 Releases 页下载）
#          USB 线连一次 → 点「一键激活无线 ADB」→ 拔线，之后就是明文 5555
```

```bash
# 方法 1b：用 Python 版做同样的事
python byd_feipin.py --tcpip 5555
# 或直接在网页界面点「开启 TCP 明文 5555（需先用 USB 线连设备）」
```

```bash
# 方法 2：用 adb 官方配对流程（拿到的是 TLS 端口，仅供 PC 版 adb 使用，App 用不了）
adb pair <设备IP>:<配对端口>      # 输入设备上显示的 6 位配对码
adb connect <设备IP>:<连接端口>
```

> **`BYD-Wireless-ADB-Activator.exe`**（[Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest) 下载）
> 是**独立的 Windows 小程序**：单文件 12 MB，
> **adb 已内置**，不装 Python、不装 adb、不联网就能跑。详细说明见
> [`pc-exe/README.md`](pc-exe/README.md)。
>
> 车机端 App 里若连接失败，会自动打印一段**环境探测报告**，直接告诉你当前是哪种模式、
> 卡在哪一步、下一步该做什么 —— 不需要猜。


---

## 三、使用步骤

### 方式 A：网页界面（推荐）

双击 **`启动.bat`**（macOS/Linux 执行 `python3 byd_feipin.py --web`），
浏览器会自动打开 `http://127.0.0.1:8765/`。

1. 填好车机 **IP / 端口**，点「连接」——首次连接车机会弹授权，勾选「始终允许」。
2. 点「**环境自检**」：会读取系统版本、控制器前缀、ClusterDebug 是否存在、当前仪表导航类型。
   - 确认是 **18.x / 21.x** 再继续。
3. 点「**开启仪表飞屏**」。
4. 到车机上打开导航并开始导航，方向盘右侧菜单选「**全屏导航**」。
5. 仪表即出现全屏地图。

「仪表截图」可抓一张仪表画面确认；「命令调试台」可手动试不同模式号。

### 方式 B：命令行

```bash
python byd_feipin.py --connect 192.168.10.10:5555   # 连接
python byd_feipin.py --status                       # 自检
python byd_feipin.py --on                           # 开启飞屏
python byd_feipin.py --off                          # 关闭飞屏
python byd_feipin.py --raw "getprop ro.build.display.id"   # 任意 shell 命令
```

### 方式 C：车机 App（免电脑，支持开机自动开启）

`android/` 是一个**可直接装到车机上运行**的 APK 工程，内置了一个纯 Java 的
ADB 客户端（不依赖 adb 可执行文件），自己连本机 `127.0.0.1:5555` 执行同样的命令序列。

成品 APK 直接从 **[Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest)**
下载 `BYD-Cluster-Feipin-v1.1.0.apk`（约 32 KB，debug 签名）：

```
adb install -r BYD-Cluster-Feipin-v1.1.0.apk
```

装好后在车机应用列表里打开「**BYD飞屏助手**」：

| 按钮 | 作用 |
|---|---|
| 连接 / 授权 | **优先走 root 通道**；没 root 时连本机 adbd（首次会弹「允许 USB 调试」，勾**始终允许**） |
| 环境自检 | 打印 root 状态、系统版本、固件、ClusterDebug 是否存在、当前导航类型 |
| 连接方式 / 检测 root | 在「root 优先」与「仅 ADB」间切换；手动探测 root |
| 开启仪表飞屏 | 执行完整开启序列 |
| 关闭飞屏 | `18` 关投影 + 导航类型恢复 `1` |
| 切换小屏导航 | 导航类型 `3` + 半屏投影 `17` |
| 开机自动开启 | 开/关守护服务（有 root 时开机就能生效，不依赖无线调试开关） |

**两条通道，命令完全一样**：

| | root 通道（有 root 时自动优先） | ADB 通道 |
|---|---|---|
| 前置条件 | 无 | 开发者选项里打开 **无线 ADB 调试** |
| 端口 / 授权弹窗 | 不需要 | 5555 + 首次授权 |
| 重启后 | 自动可用 | 需要重开无线调试 |
| 实现 | `RootShell` —— `su -c` 直接执行 | `AdbClient` —— 自己实现 ADB 协议连 `127.0.0.1:5555` |

> 万一某台固件用 root 身份反而调不通 BYD 的服务，点「连接方式」切成「仅 ADB」即可退回原路。

**开机自动开启**：打开开关后，`BootReceiver` 会在开机时拉起一个前台守护服务，
每 5 分钟巡检一次；只要发现仪表导航类型不是 `4`，就自动重新开启飞屏。
有 root 时走 `su`，**不需要无线调试开关**，比 ADB 通道可靠得多。

**横屏适配**：车机屏幕普遍是横屏且高度矮。App 会按方向自动切换布局 ——
横屏用**左右分栏**（左控制面板 / 右日志，两侧各自独立滚动，日志占满全屏高度），
竖屏保持上下结构。旋转时只重排布局不重建 Activity，日志和连接状态不会丢。

> 用 ADB 通道时有个前置条件：车机的「开发者选项」里必须已打开 **无线 ADB 调试**
> （否则 `127.0.0.1:5555` 不会监听）。这一步无法由 App 自己完成 —— 这也是
> **建议已 root 的车机直接用 root 通道**的原因。

**自己重新构建**（不需要 Android Studio / Gradle，脚本会自动下载 JDK 17 与 Android SDK）：

```bash
python android/build_apk.py                # 产物在 android/BYD飞屏助手.apk
```

（该路径已被 `.gitignore` 排除，构建产物不入库，需要分发时上传到 Release。）

---

## 四、常见问题

| 现象 | 排查 |
|---|---|
| `adb connect` 失败 | 确认电脑连的是车机热点；确认车机已开「无线 ADB 调试」；换用 `192.168.10.10:5555` |
| **`ECONNREFUSED` / connection refused** | 5555 上没人监听。设备大概率是 **Android 11+ 的「无线调试」模式**（随机端口 + TLS）→ 双击 `BYD-Wireless-ADB-Activator.exe`（[Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest) 下载），USB 连一次点「一键激活」；或 `python byd_feipin.py --tcpip 5555`。详见「二之二」 |
| 车载 App 连 `127.0.0.1:5555` 被拒 | 同上；App 会自己打印环境探测报告，照上面的「结论」做即可 |
| `devices` 里是 `unauthorized` | 车机屏幕弹的授权框点「允许/始终允许」 |
| 读取导航类型报错 | 该固件可能不支持该接口，或参数不同；换「命令调试台」手动试 |
| 设置成功但仪表不出图 | ① 控制器必须 18.x/21.x；② 必须是定制版地图；③ 方向盘菜单选「全屏导航」；④ 试 `35 → 16`、或单独发 `16` |
| 仪表出现投影但画面黑 | 打开定制版地图并开始导航；重启车机后再试一次 |
| 想恢复 | 点「关闭仪表飞屏」，或重启车机 |

---

## 五、参考来源（公开资料）

- DiPlay 项目 `docs/BYD_NAVIGATION.md`（ClusterDebug / AutoContainer / autoservice 命令细节）
- `wheregoes/byd-dolphin-hacking`（ClusterDebug 组件名、`com.byd.cluster.spi`、`fission_screencap`）
- 迪粉之家 / 迪友网：18.x 控制器仪表全屏导航教程（Freedom、迪友桌面）
- 车机自带 `ClusterDebug` 仪表调试工具

> 说明：模式号与 Binder 参数在不同固件上可能存在差异，本工具已内置「命令调试台」便于自行校准。
> 本工具仅调用车机**自带的**调试接口，不修改固件、不刷机。
