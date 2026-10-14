# BYD 仪表飞屏 · root 版

拿到 root 之后，这套东西**根本不需要 ADB**。

ADB 那一整套麻烦事 —— 开「无线 ADB 调试」、记住 5555 端口、车机上弹「允许调试」、
每次重启还要重新开一遍 —— **全都只是因为普通 App 没权限调那三个接口**。
`autoservice` 和 `AutoContainer` 会检查调用者身份，普通 App 调用直接被拒，
所以社区工具才要绕道去拿一个 shell 身份。

Root = uid 0，比 shell 还高。而且 Magisk 的 root shell 跑在**宽容（permissive）的
magisk 安全域**里，SELinux 基本不是障碍。**直接跑同一条命令就行。**

```
       ADB 版                                    root 版
┌──────────────────────┐                 ┌──────────────────────┐
│ App 请求 ADB 权限     │                 │                      │
│ → 车机弹授权弹窗      │                 │   su -c "..."        │
│ → 连 127.0.0.1:5555  │    ═══════►     │   同上，但一步到位    │
│ → 发 CNXN/AUTH/OPEN  │                 │                      │
│ → 再执行 service call │                 │                      │
└──────────────────────┘                 └──────────────────────┘
   3 个前置条件、重启失效                    零前置条件、可开机自动
```

---

## 一、最快验证（3 条命令）

把 `byd-feipin.sh` 推到车机任意位置（比如 `/data/local/tmp/`），然后：

```sh
su
cd /data/local/tmp
sh byd-feipin.sh diag      # 先自检：确认 root 能不能调通服务
```

`diag` 会打印 uid、SELinux 状态、ClusterDebug 是否安装、`autoservice` /
`AutoContainer` 是否在服务列表里，**并且实测一次读接口**：

- 能看到「解析成功，当前导航类型 = N」→ **root 身份可调用，直接往下走**
- 看到「被拒绝」→ 走本文第五节「兜底方案」

自检通过后：

```sh
sh byd-feipin.sh on        # 开启飞屏
sh byd-feipin.sh off       # 关闭
sh byd-feipin.sh small     # 切小屏导航
sh byd-feipin.sh status    # 只读当前状态
```

---

## 二、命令对照

脚本内部执行的命令，和 PC 版 / 车机 App 版**完全一致**（都是同一套逆向结果），
只是去掉了外面的 ADB 壳：

| 步骤 | 命令 |
|---|---|
| 启动调试代理 | `am startservice -n com.byd.clusterdebug/.ClusterDebugService` |
| 打开调试界面 | `am start -n com.byd.clusterdebug/.MainActivity` |
| 仪表导航类型 → 全屏 | `service call autoservice 6 i32 1007 i32 1276157976 i32 4` |
| 创建投影显示（Di4.0） | `service call AutoContainer 2 i32 1000 s16 "35"` |
| 开启全屏投影 | `service call AutoContainer 2 i32 1000 s16 "16"` |
| 回读状态 | `service call autoservice 5 i32 1007 i32 1086337074` |
| 拉起定制版地图 | `monkey -p <地图包名> -c android.intent.category.LAUNCHER 1` |

导航类型：`1` 关闭 / `2` 随导航 / `3` 小屏 / **`4` 全屏**
投影模式：`39` 简易 / **`16` 全屏** / `17` 半屏 / `18` 关闭 / `35` 创建 Di4.0 投影

想试别的参数，直接用 `raw`：

```sh
sh byd-feipin.sh raw service call AutoContainer 2 i32 1000 s16 "16"
```

---

## 三、开机自动（推荐）

### 方式 A：刷 Magisk / KernelSU 模块（最省事）

**[`byd-feipin-magisk-v1.1.0.zip`](byd-feipin-magisk-v1.1.0.zip)** ← 直接刷

刷完重启即可，开机后自动执行开启序列。日志在 `/data/adb/byd-feipin.log`。

想要「掉了自动重开」的常驻守护，改 `/data/adb/byd-feipin.conf`：

```
ENABLE=1     # 1=开机自动执行
LOOP=1       # 1=常驻守护（发现不是全屏就自动重开），默认 0
INTERVAL=60  # 巡检间隔秒数
```

改完不用重启，直接手工拉起一次：

```sh
su -c 'sh /data/adb/modules/byd-feipin/byd-feipin.sh watchdog'
```

> 模块源码在 [`magisk-module/`](magisk-module/)，改完跑
> `python root/build_module.py` 重新打包。
> 注意 `service.sh` **必须立即返回**，否则会拖住开机 —— 所以真正的逻辑是丢到后台子进程、
> 等 `sys.boot_completed` 之后再执行的。

### 方式 B：不用模块（已有注入脚本的机器）

把这一行塞进你自己的开机脚本（如 `/data/adb/service.d/xxx.sh` 或 init.d）：

```sh
( until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 2; done
  sleep 15
  sh /data/local/tmp/byd-feipin.sh on ) >/dev/null 2>&1 &
```

### 方式 C：改造现有车机 App（体验最好，但要改代码）

现有的车机 App 已经写好了界面和开机服务，**只需要把里面「ADB 层」换成「root 层」**：

| 现在 | 改成 |
|---|---|
| `AdbManager.get()` 连 `127.0.0.1:5555`，走 `AdbClient` 的 CNXN/AUTH 握手 | `Runtime.getRuntime().exec("su")` 起一个 root shell，命令写进 stdin |
| 需要「无线 ADB 调试」开关 + 授权弹窗 | 只需要 root 授权一次（Magisk 弹一次即可勾「记住」） |
| `ClusterController` 里的命令字符串 | **一个字都不用改** |

`ClusterController` 里那些 `service call ...` 本来就是 shell 命令，
换成 root shell 直接照跑。要我改的话说一声。

---

## 四、和 ADB 版的取舍

| | ADB 版 | root 版 |
|---|---|---|
| 前置条件 | 开无线调试 + 记住端口 + 授权弹窗 | 无 |
| 重启后 | **失效**，要重开无线调试 | 自动恢复 |
| 开机自动 | 靠 App 常驻守护，还可能被系统杀 | 模块 `service.sh`，最可靠 |
| 需要 root | 不需要 | 需要 |
| 车机质保 | 影响（开调试） | 影响（root 更明显） |
| 换台车 | 复制 exe/APK 就能用 | 每台车都得 root |

**结论**：你自己的车、已经 root —— 用 root 版。要给别人用 —— 还是 ADB 版省事。

---

## 五、兜底方案

万一 `diag` 显示 **root 身份被拒绝**（少数固件会检查 SELinux 上下文而不是 uid），
按顺序试：

**① 换 SELinux 上下文调用**

较新的 Magisk（`su` 支持 `-Z/--context`，见官方 `docs/tools.md`）可以指定上下文：

```sh
su -Z u:r:shell:s0 -c 'service call autoservice 5 i32 1007 i32 1086337074'
```

> 注意：老的 Magisk 版本里 `-Z` 是**为了兼容 SuperSU 而保留但被静默忽略**的，
> 先用 `su --help` 看看有没有这个参数。

**② 退回 ADB 路线，但用 root 把 ADB 变成全自动**

这是最稳的兜底 —— root 能一次性解决 ADB 版最烦的两个问题：

```sh
# 免授权弹窗：把自己的公钥写进去
cat /data/misc/adb/adb_keys

# 开机就监听明文 5555
setprop service.adb.tcp.port 5555
stop adbd; start adbd
```

写进开机脚本后，**车机每次开机 5555 都在监听、也不会弹授权框**，
原来的 PC 工具 / App 就能无缝连上，等于把 ADB 版的三个痛点全抹平了。

**③ 直接触发 ClusterDebug 的界面**

有些固件里 `ClusterDebug` 的 Activity 本身就能开飞屏，
`am start -n com.byd.clusterdebug/.MainActivity` 之后手动点一遍，看是否生效。

---

## 六、常见问题

| 现象 | 处理 |
|---|---|
| `su: not found` | 没装 Magisk/KernelSU，或 su 不在 PATH。试 `/system/xbin/su`、`/system/bin/su` |
| 脚本报语法错 | 多半是从 Windows 传过去带了 CRLF。`sed -i 's/\r$//' byd-feipin.sh` |
| 开机没生效 | 看 `/data/adb/byd-feipin.log`；确认配置里 `ENABLE=1`；确认模块在 Magisk 里已启用 |
| 仪表不出图 | ① 确认控制器是 18.x/21.x；② 确认方向盘右侧菜单选了「全屏导航」；③ 确认装的是**定制版**地图 |
| 导航类型写进去了但没投影 | 单独试 `raw service call AutoContainer 2 i32 1000 s16 "16"`，看返回 |
| 重启后恢复原样 | 正常。仪表服务重启会重置，靠模块的 `service.sh` 或 `LOOP=1` 守护补上 |

---

## 七、文件说明

| 文件 | 说明 |
|---|---|
| `byd-feipin.sh` | 主脚本，可直接推车机运行（`on/off/small/status/diag/raw/watchdog`） |
| `magisk-module/` | Magisk / KernelSU 模块源码 |
| `byd-feipin-magisk-v1.1.0.zip` | 打包好的可刷入模块 |
| `build_module.py` | 重新打包（会自动复制主脚本并校验 LF 换行） |

---

## 免责声明

只调用车机自带的官方 `am` / `service` / `monkey` 命令与 BYD 自带的调试接口，
**不刷机、不改固件、不写系统分区**。
仪表导航类型与投影模式号来自公开逆向资料，**不同固件可能有差异**，
所有命令都可以用 `raw` 子命令逐条验证。使用风险自负。
