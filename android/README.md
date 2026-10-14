# BYD 飞屏助手（车机端 APK）

装在**车机上**的 App，不需要电脑。它通过连接车机**本机的 adbd**（`127.0.0.1:5555`）
拿到 shell 权限，再调用 `com.byd.clusterdebug` + `autoservice` / `AutoContainer`
打开被隐藏的「仪表全屏导航」。

- **一键开关**：开启 / 关闭 / 切小屏
- **开机自启**：开机后自动连接并把隐藏开关打开，之后每 5 分钟巡检一次

> 仅适用于 **18.x / 21.x 控制器**（DiLink 4.0）全液晶仪表车型。停稳 P 挡再操作，行驶中勿用。

**不想自己构建** → 直接到 [Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest)
下载 `BYD-Cluster-Feipin-v1.1.0.apk` 安装即可（下面第三节也是这个流程）。

---

## 一、为什么要自己实现 ADB

`autoservice` / `AutoContainer` 这两个 Binder 接口，普通 App 直接调用会被拒（需要
BYD 签名或 shell 权限）。社区工具（Freedom、迪友桌面）的做法是：请求一次 ADB 权限，
之后用**本机 ADB** 以 shell 身份执行命令。

本 App 用纯 Java 实现了一个最小 ADB 客户端：

```
CNXN 握手 → AUTH(token) → RSA 签名 → 车机弹「允许调试」→ CNXN 成功
         → OPEN "shell:<cmd>" → 收数据 → CLSE
```

授权用的公钥是 Android 自定义的 **524 字节结构**（`RSAPublicKey`）：

| 字段 | 长度 | 说明 |
|---|---|---|
| modulus_size_words | 4 | 固定 64 |
| n0inv | 4 | −1 / n[0] mod 2^32 |
| modulus | 256 | 小端 |
| rr | 256 | (2^2048)² mod n，小端 |
| exponent | 4 | 65537 |

Base64 后加 ` user@host` 即为 AUTH 包内容。签名用
`RSA/ECB/PKCS1Padding` 加密 `SHA1_DigestInfo || token`（ADB 的 token 是
SHA-1 预哈希长度，所以不能直接用 `SHA1withRSA`）。密钥首次运行自动生成并存本地。

---

## 二、构建

### 方式 1：一键脚本（推荐）

```bash
python build_apk.py
```

脚本会自动下载 JDK 17 与 Android SDK 组件（aapt2 / d8 / zipalign / apksigner），
然后直接产出 `BYD飞屏助手.apk`（已被 `.gitignore` 排除，构建产物不入库）。
**不需要 Android Studio，也不需要 Gradle。**

```bash
python build_apk.py --env D:\sdk     # 自定义工具目录，默认 ~/.wb-android-build
```

### 方式 2：Android Studio

新建空工程，把 `app/src/com/wb/bydfeipin/*.java` 拷进 `src/main/java/`，
`AndroidManifest.xml` 合并进去，minSdk 26 / targetSdk 33 即可。

### 安装到车机

```bash
adb connect 192.168.10.10:5555
adb install -r BYD-Cluster-Feipin-v1.1.0.apk
```

或把 APK 放进车机的「Third Party Apps」U 盘目录（带国家代码后缀）侧载。

---

## 三、使用

App 有**两条通道，命令序列完全一样**，默认 **root 优先**：

| | root 通道 | ADB 通道 |
|---|---|---|
| 用在哪 | 车机已 root（Magisk / KernelSU） | 车机没 root |
| 前置条件 | **无** | 开发者选项里打开 **连接USB后启用调试模式** + **无线ADB调试** |
| 端口 / 授权弹窗 | 不需要 | `5555` + 首次弹「允许 USB 调试」 |
| 重启后 | 自动可用 | 要重新确认无线调试是开的 |
| 实现 | `RootShell.java` —— `su -c` 直接执行 | `AdbClient.java` —— 自己实现 ADB 协议 |

### 已 root 的车机（推荐）

1. 打开本 App，点「**连接 / 授权**」—— 会自动探测 root 并走 root 通道，
   第一次会弹一次 Magisk 的授权框，允许即可。
2. 点「**开启仪表飞屏**」。之后到车机上开始导航，方向盘右侧菜单选「全屏导航」。
3. 点「**开机自动开启**」切成「开」—— 有 root 时开机就能生效，**不依赖无线调试开关**。

界面上的按钮：

| 按钮 | 作用 |
|---|---|
| 连接 / 授权 | 优先 root；没 root 时退回 ADB |
| 环境自检 | 打印 root 状态、su 路径、固件、ClusterDebug 是否存在、当前导航类型 |
| **连接方式** | 在「root 优先」/「仅 ADB」之间切换（某台固件 root 调不通时用） |
| **检测 root** | 主动探测 su，会打印 su 路径与 `id -u` 的实际输出 |

### 没 root 的车机

1. 车机「开发者选项」中打开 **连接USB后启用调试模式** 和 **无线ADB调试**。
2. 打开本 App，点「**连接 / 授权**」。
   - 车机会弹出「允许 USB 调试」，勾选**始终允许**并确定。
3. 点「**开启仪表飞屏**」。之后到车机上开始导航，方向盘右侧菜单选「全屏导航」。
4. 想开机自动生效：点「**开机自动开启**」按钮切成「开」。

「环境自检」会打印固件版本、控制器属性、ClusterDebug 是否存在、当前仪表导航类型
（1 关闭 / 2 随导航 / 3 小屏 / 4 全屏）。

> **为什么不干脆只用 root？** 因为要照顾没 root 的车机。App 做成自动选择：
> 有 root 就用最省事的那条路，没有就退回 ADB，命令和结果完全一致。

---

## 三之二、屏幕适配说明

车机屏幕基本都是**横屏且高度矮**。如果沿用竖排布局（标题 + 状态 + 三排按钮 + 日志），
固定内容一超屏，日志区会被挤成 **0 高度**，整页又无法滚动 —— 表现就是「上下滑不动」。

本 App 按屏幕方向自动切换布局：

| 方向 | 布局 | 滚动行为 |
|---|---|---|
| **横屏**（宽 > 高） | 左右分栏：左控制面板 / 右日志 | 两侧各自独立滚动，互不干扰；日志占满整屏高度 |
| **竖屏** | 上下结构：上控制面板 / 下日志 | 面板内容超出可滚，日志占剩余空间 |

实现要点：

- 根布局不再是裸 `LinearLayout`，而是**两个 `ScrollView`**（控制面板、日志面板）；
- 横屏用 `layout_weight` 0.44 / 0.56 分栏，高度 `MATCH_PARENT`，不再依赖竖向剩余空间；
- 清单里声明 `android:configChanges="orientation|screenSize|..."`
  + `resizeableActivity="true"`，旋转时**只重排布局不重建 Activity**，
  日志与连接状态不会丢（`onConfigurationChanged` 里保留文本后重新 `buildUi()`）；
- 返回键改为**退到后台**（`moveTaskToBack`），避免车机上误触把连接状态清掉。

---

## 四、代码结构

v1.1.0 起把「执行命令」这件事抽成了一层接口，root 与 ADB 只是它的两个实现：

```
ClusterController（命令序列，一个字没改）
        │  只依赖
        ▼
      Shell  ← 接口：shell(cmd) / isConnected() / close() / mode()
      ╱     ╲
RootShell    AdbClient
(su -c)      (自实现 ADB 协议)
        ╲     ╱
       AdbManager   ← 优先 root，失败退回 ADB，并缓存连接
```

| 文件 | 作用 |
|---|---|
| `Shell.java` | **新增**：执行命令的统一接口（root / ADB 两个实现） |
| `RootShell.java` | **新增**：`su -c` 执行命令。探测 su 路径、缓存探测结果、带超时的一次性执行 |
| `AdbClient.java` | 最小 ADB 协议客户端（握手 / RSA 授权 / shell 执行），实现 `Shell` |
| `RsaKeyUtil.java` | RSA 密钥生成、Android 524 字节公钥编码、token 签名 |
| `AdbManager.java` | 通道选择与连接缓存：**优先 root，其次 ADB** |
| `ClusterController.java` | 飞屏命令序列（与 PC 版一致） |
| `MainActivity.java` | 主界面（纯代码构建 UI，横竖屏自适应：横屏左右分栏） |
| `EnvProbe.java` | 本机环境探测：先判断 root，再区分「明文 5555」与「Android 11+ 无线调试 TLS」 |
| `FeipinService.java` | 前台服务：开机后自动连接 + 每 5 分钟巡检（有 root 时走 root） |
| `BootReceiver.java` | 开机广播 → 拉起守护服务 |
| `Prefs.java` | 配置与密钥存储（含 `prefer_root` / `root_ok`） |

> `RootShell` 走的是「一条命令起一个 `su` 进程」而不是常驻 shell。
> 原因是 Magisk 的 `su` 在管道环境下可能分配 PTY 并把命令回显出来，
> 常驻方案得靠标记行解析输出、容易串行；一次性执行最稳。

---

## 五、排障

| 现象 | 原因 / 处理 |
|---|---|
| 有 root 但连接失败 | 点「**检测 root**」看 `su` 的实际输出；若 su 可用但仍调不通 BYD 服务，点「**连接方式**」切成「仅 ADB」 |
| `ECONNREFUSED` / `Connection refused` | 5555 没有服务监听。**最常见原因**：设备处于 **Android 11+「无线调试」模式** —— 该模式用 TLS 加密 + 37000~45000 的随机端口，**不监听 5555**。解法：电脑 USB 连设备后运行 **`BYD-Wireless-ADB-Activator.exe`**（[Releases](https://github.com/15367482130/byd-instrument-cluster/releases/latest) 下载，单文件免安装）点「一键激活无线 ADB」；PC 版 Python 工具也有「开启 TCP 明文 5555」按钮。<br>**比亚迪车机不走这一步** —— 它的「无线 adb 调试」开关本身就是 5555 明文。 |
| 连接失败「等待授权超时」 | 车机没弹授权框，或没点允许；确认无线 ADB 已开 |
| 连接失败「adbd 拒绝了连接」 | 无线调试开关没打开，或端口不是 5555 |
| 一直连不上 | 部分固件重启后要重新打开「无线ADB调试」；也可能被系统杀掉 adbd |
| 授权对话框不出现 | 清除本 App 数据后重试；或在开发者选项里「撤销 USB 调试授权」 |
| 命令返回 permission denial | 该固件 Binder 接口不同，用 PC 版工具的「命令调试台」手动试模式号 |
| 开机没自动生效 | 有些车机限制自启，可在系统设置里把本 App 加入后台白名单 |
| 横屏时滑不动 / 日志看不见 | 已修复：横屏改为左右分栏。若用的旧版 APK，重新装 Release 里的最新 APK |

> 若本 App 在某些固件上连不上 adbd，**PC 版工具（byd_feipin.py）始终可用**，
> 两者命令完全一致。
