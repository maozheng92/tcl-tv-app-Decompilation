# TCL+ 局域网遥控协议（TCLPlus 5.1.2.1）

本文记录从 **TCLPlus_5.1.2.1_600505013-formal-all_default.apk**（中国区 TCL+ / `com.tcl.tclhome`）静态反编译得到的局域网电视控制协议，并对照 [DusKing1/ha-tcl-tv](https://github.com/DusKing1/ha-tcl-tv) 与 [jarvis2f/tcl-remote](https://github.com/jarvis2f/tcl-remote) 的 tnscreen / MagiConnect 描述。

仓库**不分发**反编译源码或 APK 内容；下列是协议事实与类名定位，供独立核查。

## 样本

| 项 | 值 |
|---|---|
| 文件名 | `TCLPlus_5.1.2.1_600505013-formal-all_default.apk` |
| versionName / versionCode | 5.1.2.1 / 600505013 |
| 包名（SDK 初始化读取） | `com.tcl.tclhome` |
| SDK | 混淆后的 `com.tcl.tcastsdk.*`（主要在 `classes10.dex`） |
| Flutter | `libapp.so` 中有 `TcastTvDeviceMetadata` / `tcast_tv`，遥控仍走 Java SDK |

TCLPlus 内嵌的仍是 **T-Cast / tnscreen 局域网协议**，不是另一套云遥控。云端 IoT（空调、冰箱等）与电视局域网遥控是分开的。

## 传输

| 通道 | 端口 | 证据 |
|---|---|---|
| UDP 发现 | **6537** | `Cons.DEFAULT_BROADCAST_PORT` / `TCLDeviceManager.init` 写入扫描配置 |
| TCP 控制 | **6553** | `TCLSocket` 连接写死 `6553`；`TCLDevice.connect` |
| 截图 HTTP | 6554 | `TCLShotPicProxy`（本集成未实现） |
| 语音 PCM | 4332 | `VoiceControlProxy`（本集成未实现） |

TCP 帧：

```text
[4 字节大端 payload 长度][恰好该长度的 UTF-8 或 AES 密文]
```

`DataOutputStream.writeInt` + `write(bytes)`。`TCP_NODELAY` 与 `SO_KEEPALIVE` 开启。明文用字面量 `>>` 分字段。

## AES

159 握手请求**始终明文**（`TCLDevice.a(c)` 在 `c.a == 159` 时 `ignoreAlgorithmType=true`）。

159 回复字段 6 为 `algorithmType`；值为 **1** 时后续读写使用：

| 参数 | TCLPlus 5.1.2.1 中的精确来源 |
|---|---|
| 算法 | Base64(`QUVT`) → `AES`；Base64(`QUVTL0NCQy9QS0NTNVBhZGRpbmc=`) → `AES/CBC/PKCS5Padding`（`util.d`） |
| Key | 密文 `i5GMnI2ampGLkYycjZqakQ==`，Base64 解码后逐字节 XOR `0xFF`，得到 ASCII **`tnscreentnscreen`**（`util.j.b.a`，写/读帧均调用） |
| IV | 整数数组 `{18,52,86,120,144,171,205,239}` 重复两次 → `12 34 56 78 90 AB CD EF 12 34 56 78 90 AB CD EF`（`util.j.a.a`） |
| 每帧 | 新建 Cipher，固定 IV，无跨帧 chaining |

离线向量（与 MagiConnect 研究一致）：

```text
明文 149>>20
密文 473d4f5e84ac1eb069f46e58e372f0d6
整帧 00000010473d4f5e84ac1eb069f46e58e372f0d6
```

此 APK **不再附带** `libjnitool.so`；密钥改在 Java 里混淆，结果与旧原生库相同。

## UDP 发现

上线通告（`NoticeOnlineThread`）：

```text
1:<timestamp_ms>:<clientName>:PHONE:1:<clientName>:<discoveryId>:0:0\0
```

`packetNo` 为 epoch 毫秒。电视应答 `senderType=TV`。MAC 中的冒号写成 `&#058`。协议版本 `<6` 走 V5 握手，`>=6` 走 V6（本集成实现 V6）。

## V6 握手

连接成功后立即发送（`ProtocolHandlerV6.a()`）：

```text
159>><selfName>>1>><uuid>>1
```

`selfName` 默认 `Build.MODEL`；本集成用 `HomeAssistant`。`uuid` 在 TCLPlus 里是 `Settings.Secure.android_id`。`secret` 固定字面量 `1`。

159 回复字段（从 0 计）：型号、应用版本（`code:name`）、固件、设备编号、MAC、**algorithmType**、蓝牙 MAC、TV 类型、商店、shake 掩码、语言、SN……与 ha-tcl-tv 文档一致。

## 心跳

写队列空闲 **5000 ms** 发送 `150>>`（`HeartbeatRequest` / `AbstractPacketWriter`）。心跳等待 **20000 ms**，超时原因 `beatTimeout` / code `2002`。任意非空接收帧会完成等待中的心跳。

## 本集成使用的消息

TCLPlus 遥控代理发出的按键都是 `149>><code>`（`a.a.D`，常量 `NEEDDOWNLOAD_10 = 149`）。

| 方向 | 载荷 | TCLPlus 证据 | 用途 |
|---|---|---|---|
| C→T | `149>><key>` | `TCLRemoteControlProxy.sendKeyAction` | 遥控键 |
| C→T | `150>>` | `a.b.b` | 心跳 |
| C→T | `136>>` | 电视端仍实现；**此版 APK 已删除 TCLRenderProxy** | 查音量，回复 `130>><n>` |
| C→T | `130>><n>` | 同上 | 设置音量 0–100 |
| C→T | `140>>` / `131>><true/false>` | MagiConnect 渲染代理；**此版 TCLPlus 已删除，国行 `131>>false` 可能无效** | 仅作读回；静音/取消静音发按键 23 |
| C→T | `223>>GET` | `AppManagerProxy.getAppData` / `a.a.C0099a`（ID 223） | 应用列表 |
| C→T | `223>>OPEN>><package>` | `AppManagerProxy.openApp` | 启动应用 |
| both | `159>>...` | `a.a.n` / `ProtocolHandlerV6` | 握手 |

应用列表记录：`package::name::icon[::versionCode::versionName::cache::data::code[::systemFlag]]`，应用之间用单个 `>` 分隔；`systemFlag=0` 为系统应用。本集成把应用放在媒体浏览器 / `play_media`（`app`），**不**放进 `source_list`。

TCLPlus **没有**可用的 HDMI 口清单：`TCLRemoteControlProxy` 虽有 MagiConnect 风格的「最近输入」报文（`269>>1` / `269>>2>>token`），APK 并不调用，回复也不是稳定的 HDMI1/HDMI2 名称。输入源改为用户在集成选项里手动配置，并用 `button.*` 序列切换。

## 按键（TCLPlus 具名方法）

| 方法 | 键码 |
|---|---:|
| `dirUpKeyAction` | 11 |
| `dirDownKeyAction` | 12 |
| `dirLeftKeyAction` | 13 |
| `dirRightKeyAction` | 14 |
| `okKeyAction` | 15 |
| `backKeyAction` | 16 |
| `menuKeyAction` | 18 |
| `homeKeyAction` | 19（Linux TV 能力位 15 为 1 时改 45） |
| `powerKeyAction` | 20 |
| `volUpKeyAction` | 21 |
| `volDownKeyAction` | 22 |
| `muteAction` | 23 |
| `channelUpKeyAction` | 27 |
| `channelDownKeyAction` | 28 |
| `mouseLeftKeyAction` | 39 |
| `mouseRightKeyAction` | 40 |

`sendKeyAction(int)` 的形参是任意 `int`，线上仍是 `149>><整数>`。国行固件**不会**实现 APK 里出现过的全部整数：实机确认数字 0–9、`channel_up`/`channel_down`、`mouse_left`/`mouse_right`，以及 MagiConnect 彩键/info/search/playback/enter 等均无效果。本集成只把国行会响应的键写成具名命令；仍接受 0–999 的原始整数供试验。**没有独立的 key-up 报文**；长按就是重复 `149`。

### 静音

TCLPlus `muteAction` 发 `149>>23`，是**切换**。MagiConnect `131>>true/false` 是 setter：国行上 `131>>true` 可能静音成功，`131>>false` 无效果，于是 `media_player` 只能静音不能取消。本集成静音/取消静音都走键 23：当前状态与目标不同时按一次。`140>>` 读回失败时用上次请求的状态判断是否还要再按。

### 直播

TCLPlus **没有** 直播的 `149` 整数。

- H5 `operateTVFromH5` 的 `remotekey="0"` 日志为 `REMOTE_KEY_GOTVAPP`，走的是手机 Intent `tclapp://TCL_TV.app/openwith?type=100` / 包名 `com.tnscreen.main`，不是电视按键。
- `TCLChannelProxy.startTChannel` 发的是 **`251>><url>`**（T 频道内容），不是遥控器「直播」键。
- 旧 nScreen XML（TCP 4123，`TR_KEY_TV` 字符串）与本 T-Cast 整数协议不是同一条路；MagiConnect 整数表里没有 TV/TUNER/LIST。
- 本集成不猜测 `149` 码。进直播用 `223>>OPEN`（`play_media` type `app`）。

电源键 20 是**切换**，不是幂等关机。TCLPlus 的 `awaken()` 在此版本是空实现；WOL 魔法包（广播 `255.255.255.255:7778`，6×`FF` + MAC×16）来自旧 MagiConnect SDK，本集成仍发送，是否唤醒取决于电视网卡/待机设置。

## 与 ha-tcl-tv / MagiConnect 的差异

- 密钥不再从 `libjnitool.so` JNI 取出，改为 Java Base64+XOR，**明文密钥相同**。
- 此版 TCLPlus **没有** `TCLRenderProxy` / `setVolume` 客户端序列化；音量 UI 走按键 21/22。电视端 `130`/`136` 仍被 ha-tcl-tv 在实机上验证过，本集成继续使用，失败时音量加减仍走按键。
- `TCLRemoteControlProxy.awaken` 被掏空；蓝牙唤醒回调也是空的。
- 命令类名被 ProGuard 成 `a.a.D` 等，消息 ID 常伪装成腾讯 TBS `TbsListener.ErrorCode` 常量（例如 149 = `NEEDDOWNLOAD_10`）。

## 安全

固定 AES key/IV **不是**身份认证。只应在可信局域网使用，不要把 TCP 6553 或 Home Assistant 未经加固地暴露到公网。
