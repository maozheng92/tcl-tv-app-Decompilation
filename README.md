# TCL 电视 · Home Assistant `media_player`

面向中国区 **TCL+ / T-Cast（tnscreen）** 局域网协议的电视。在 Home Assistant 中添加一台 **TV 类型的 `media_player`**，以及配套的 `remote` 实体。不经过 TCL 云账号。

协议来自对本仓库中 **TCLPlus 5.1.2.1** APK 的静态反编译，并对照 [DusKing1/ha-tcl-tv](https://github.com/DusKing1/ha-tcl-tv) 与 [jarvis2f/tcl-remote](https://github.com/jarvis2f/tcl-remote)。细节见 [docs/protocol.md](docs/protocol.md)。

## 能做什么

| 实体 | 能力 |
|---|---|
| `media_player.<电视>` | 开/关（开=可选红外遥控或 WOL，关=电源切换键）、音量读/写/加减、静音、播放/暂停键、`select_source` 切换**自定义输入源**、媒体浏览器 / `play_media` **启动已安装应用** |
| `remote.<电视>` | `remote.send_command` 发送方向键、OK、返回、主页、菜单、数字、信号源、彩键（红/绿/黄/蓝）等 |

开机键：在集成条目的 **配置 / Configure** 里选择红外 `remote.*`（Broadlink / Harmony Hub / 小米万能遥控），再从该遥控已学习的码库中**下拉选择**设备与开机指令（实现参考 [ir_television](https://github.com/maozheng92/ir_television)）。设置后，`turn_on` 会调用 `remote.send_command`；遥控留空则仍发 Wake-on-LAN。

输入源：T-Cast **不能**枚举 HDMI 口。在同一配置菜单的 **输入源** 中手动添加、修改、删除、隐藏；每个输入源对应一串 `button.*`（例如：输入源按钮 → 右 → 确认）。`select_source` 只列出未隐藏的自定义输入源。

已安装应用**不出现在输入源列表**（与官方 Sony Bravia 集成相同）：在媒体播放器的 **媒体浏览器 → Applications** 里打开，或用 `media_player.play_media`（`media_content_type: app`）。

**离线只表示控制链路不可达，不证明关机。** 电源键是切换。集成不知道当前前台应用、播放内容和精确亮屏状态。

电视首次添加时必须已开机。控制口 TCP **6553**，发现 UDP **6537**。可直接填 IP。建议在路由器里固定地址。

> 仅用于可信局域网。协议使用应用内固定 AES 密钥，不能当作认证。不要把电视控制端口或未加固的 Home Assistant 暴露到公网。

## 安装

把 `custom_components/tcl_tv/` 复制到 Home Assistant 配置目录：

```text
<config>/custom_components/tcl_tv/manifest.json
```

集成图标来自 TCLPlus 应用的 `@mipmap/ic_app`，放在 `custom_components/tcl_tv/brand/`（Home Assistant 2026.3+ 会自动使用）。

重启 Home Assistant。设置 → 设备与服务 → 添加集成 → **TCL TV** → 填写电视 IP。

HACS 自定义仓库也可指向本仓库（类别选 Integration）。

## 示例

```yaml
action: media_player.volume_set
target:
  entity_id: media_player.living_room
data:
  volume_level: 0.2
```

```yaml
action: media_player.select_source
target:
  entity_id: media_player.living_room
data:
  source: HDMI 1
```

```yaml
action: media_player.play_media
target:
  entity_id: media_player.living_room
data:
  media_content_type: app
  media_content_id: 云视听小电视
```

`play_media` 的 `media_content_id` 可以是应用名称或 Android 包名。

```yaml
action: remote.send_command
target:
  entity_id: remote.living_room
data:
  command:
    - red
```

彩键也可用中文名：`红` `绿` `黄` `蓝`。

`remote.send_command` 可用键名（T-Cast `149>><整数>`，与 MagiConnect `TR_KEY_*` 相同）。TCL+ 手机遥控界面只画了电源/主页/菜单/音量/频道/返回/OK/方向；彩键和 EPG 等仍可通过 `sendKeyAction(int)` 发出。

| 键名 | 码 | 说明 |
|---|---:|---|
| `0`–`9` | 10, 1–9 | 数字 0 是码 10 |
| `up` `down` `left` `right` `ok` `back` | 11–16 | 方向与确认 |
| `menu` `home` `power` | 18–20 | 主页在 Linux TV 能力位下也可能是 `smart_tv`（45） |
| `volume_up` `volume_down` `mute` | 21–23 | |
| `epg` / `guide` | 24 | 节目指南 |
| `channel_up` `channel_down` `source` | 27–29 | |
| `red` `green` `yellow` `blue` | 34–37 | 彩键，中文别名 `红` `绿` `黄` `蓝` |
| `info` `search` `favorite` `picture` `scale` `display` `playback` `3d` | 41, 33, 32, 31, 30, 25, 26, 17 | MagiConnect 表中有、TCL+ UI 未画出的键 |
| `enter` `dot` `backspace` | 68, 75, 38 | |
| `mouse_left` `mouse_right` | 39–40 | |

**直播不是 T-Cast 按键。** TCLPlus 5.1.2.1 的 H5 `remotekey=0`（`REMOTE_KEY_GOTVAPP`）会在手机上打开 MagiConnect（`com.tnscreen.main`），不会向电视发 `149`。MagiConnect 恢复出的整数表也没有 `TR_KEY_TV`。要进直播，用媒体浏览器 / `play_media` 打开电视上的直播应用：

```yaml
action: media_player.play_media
target:
  entity_id: media_player.living_room
data:
  media_content_type: app
  media_content_id: 直播
```

`media_content_id` 填应用名称或包名（与电视 `223>>GET` 列表匹配）。完整键表见 `protocol.KEYS`。

## 开发

协议模块不依赖 Home Assistant：

```bash
pip install cryptography pytest pytest-asyncio
python -m pytest tests
```

反编译过程（本机，不入库）：

```bash
jadx -d /tmp/jadx-c10 -r classes10.dex
```

重点包：`com.tcl.tcastsdk.mediacontroller`（混淆后的命令/套接字）与 `TCLRemoteControlProxy`。

## 许可

MIT。TCL、TCL+、T-Cast 等名称属于相应权利人；本项目非官方。MIT 不覆盖第三方 APK 或反编译源码。
