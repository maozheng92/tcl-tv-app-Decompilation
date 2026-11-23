# TCL 电视 · Home Assistant `media_player`

面向中国区 **TCL+ / T-Cast（tnscreen）** 局域网协议的电视。在 Home Assistant 中添加一台 **TV 类型的 `media_player`**，以及配套的 `remote` 实体。不经过 TCL 云账号。

协议来自对本仓库中 **TCLPlus 5.1.2.1** APK 的静态反编译，并对照 [DusKing1/ha-tcl-tv](https://github.com/DusKing1/ha-tcl-tv) 与 [jarvis2f/tcl-remote](https://github.com/jarvis2f/tcl-remote)。细节见 [docs/protocol.md](docs/protocol.md)。

## 能做什么

| 实体 | 能力 |
|---|---|
| `media_player.<电视>` | 开/关（开=可选红外遥控或 WOL，关=电源切换键）、音量读/写/加减、静音、播放/暂停键、用 `select_source` **启动已安装应用** |
| `remote.<电视>` | `remote.send_command` 发送方向键、OK、返回、主页、菜单、数字、信号源等 |

开机键：在集成条目的 **配置 / Configure** 里可选一个红外 `remote.*` 实体，并填写开机指令名（部分发射器还需设备名）。设置后，`turn_on` 会调用 `remote.send_command`；都留空则仍发 Wake-on-LAN。

**离线只表示控制链路不可达，不证明关机。** 电源键是切换。集成不知道当前前台应用、播放内容和精确亮屏状态。`select_source` 列出的是已安装应用，不是 HDMI 输入名。

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
  source: 云视听小电视
```

```yaml
action: remote.send_command
target:
  entity_id: remote.living_room
data:
  command: back
```

`remote.send_command` 可用键名：`up` `down` `left` `right` `ok` `back` `home` `menu` `power` `volume_up` `volume_down` `mute` `source` `playback` `channel_up` `channel_down` `0`–`9` 等（完整表见 `protocol.KEYS`）。

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
