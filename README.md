# TCL 电视 · Home Assistant `media_player`

面向中国区 **TCL+ / T-Cast（tnscreen）** 局域网协议的电视。在 Home Assistant 中添加一台 **TV 类型的 `media_player`**，以及配套的 `remote` 实体。不经过 TCL 云账号。

协议来自对本仓库中 **TCLPlus 5.1.2.1** APK 的静态反编译，并对照 [DusKing1/ha-tcl-tv](https://github.com/DusKing1/ha-tcl-tv) 与 [jarvis2f/tcl-remote](https://github.com/jarvis2f/tcl-remote)。细节见 [docs/protocol.md](docs/protocol.md)。

## 能做什么

| 实体 | 能力 |
|---|---|
| `media_player.<电视>` | 开/关（开=可选红外遥控或 WOL，关=电源切换键）、音量读/写/加减、静音、播放/暂停键、`select_source` 切换**自定义输入源**、媒体浏览器 / `play_media` **启动已安装应用** |
| `remote.<电视>` | `remote.send_command` 发送国行实测有效的键：方向、OK、返回、主页、菜单、音量、电源等；`screenshot` 截图并保存到 **媒体 → Image upload** |

开机键：在集成条目的 **配置 / Configure** 里选择红外 `remote.*`（Broadlink / Harmony Hub / 小米万能遥控），再从该遥控已学习的码库中**下拉选择**设备与开机指令（实现参考 [ir_television](https://github.com/maozheng92/ir_television)）。设置后，`turn_on` 会调用 `remote.send_command`；遥控留空则仍发 Wake-on-LAN。

输入源：T-Cast **不能**枚举 HDMI 口。在同一配置菜单的 **输入源** 中手动添加、修改、删除、隐藏，并**列出全部输入源拖动排序**。每个输入源的按键序列先选类型（本集成按键或按钮实体），再勾选内容，然后为每一项填写重复次数（例如：输入源 ×1 → 右 ×2 → 确认 ×1）。可再追加另一组，以便本机键和按钮实体混用。`select_source` 只列出未隐藏的自定义输入源。

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
  command: back
```

`remote.send_command` 只列出**国行实测会响应**的键。APK 里即使有 `channelUpKeyAction` / 数字码，国行固件也可以忽略对应的 `149` 整数。

| 键名 | 码 |
|---|---:|
| `up` `down` `left` `right` `ok` `back` | 11–16 |
| `menu` `home` `power` | 18–20 |
| `volume_up` `volume_down` `mute` | 21–23 |
| `source` | 29 |
| `smart_tv` | 45（Linux TV 上 TCL+ 用来当主页） |
| `screenshot` | 不是 `149`。走 `225>>`，图片写入 **媒体 → Image upload** |

数字、频道、鼠标、彩键、info/search 等在国行上无效。需要试未收录的码时，可直接发 `149` 整数（0–999）。

```yaml
action: remote.send_command
target:
  entity_id: remote.living_room
data:
  command: screenshot
```

`screenshot`（也接受 `截图`）与其它遥控键一样用 `remote.send_command`。TCL+ 发 `225>>`，从电视 HTTP（常见端口 6554）拉图，再保存到 Home Assistant **媒体 → Image upload**。文件名是「电视名 + 时间」。视频层可能截成黑屏，OSD 仍可见。

`media_player` 静音/取消静音走 TCL+ 的静音**切换键** `149>>23`。MagiConnect 的 `131>>true/false` 在国行上可能只能静音、不能取消。

**直播不是 T-Cast 按键。** TCLPlus 5.1.2.1 的 H5 `remotekey=0`（`REMOTE_KEY_GOTVAPP`）会在手机上打开 MagiConnect（`com.tnscreen.main`），不会向电视发 `149`。要进直播，用媒体浏览器 / `play_media` 打开电视上的直播应用：

```yaml
action: media_player.play_media
target:
  entity_id: media_player.living_room
data:
  media_content_type: app
  media_content_id: 直播
```

`media_content_id` 填应用名称或包名（与电视 `223>>GET` 列表匹配）。完整键表见 `protocol.REMOTE_COMMANDS`。

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
