"""TCL+ / T-Cast LAN remote protocol.

Recovered from TCLPlus 5.1.2.1 (versionCode 600505013, package
``com.tcl.tclhome``) and aligned with the tnscreen / MagiConnect wire
format used by Home Assistant integrations such as ha-tcl-tv.

This module has no Home Assistant imports so it can be unit-tested
directly.

Wire format (TCLPlus tcastsdk):
- UDP 6537 discovery: ``1:<ts_ms>:<name>:PHONE:1:<name>:<id>:0:0\\0``
  answered by a ``TV`` datagram whose MACs encode ``:`` as ``&#058``.
- TCP 6553: 4-byte big-endian length + body. Fields use ``>>``.
- ``159`` identity exchange is plaintext. Reply field 6 is the algorithm;
  ``1`` means later bodies are AES-128-CBC / PKCS7 with a fixed key+IV.
- Idle write queue of 5 s sends ``150>>``; 20 s without a heartbeat
  completion is treated as ``beatTimeout``.
"""
from __future__ import annotations

import asyncio
import base64
from collections import deque
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import logging
import struct
import time
import uuid

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

CONTROL_PORT = 6553
DISCOVERY_PORT = 6537
WOL_PORTS = (7778, 9)

# TCLPlus obfuscates the AES key as Base64 then XOR 0xFF
# (com.tcl.tcastsdk.util.j.b.a / AlgorithmPacketWrite).
_OBFUSCATED_AES_KEY_B64 = "i5GMnI2ampGLkYycjZqakQ=="

# IV integers from TCLPlus SecurityUtil equivalent:
# 18,52,86,120,144,171,205,239 repeated (0x12..0xEF).
_AES_IV = bytes((18, 52, 86, 120, 144, 171, 205, 239) * 2)

_SEP = ">>"
_MAX_FRAME = 1 << 20

HEARTBEAT_IDLE = 5.0
SILENCE_TIMEOUT = 20.0

# Key codes sent as ``149>><code>``.
#
# TCLPlus ``TCLRemoteControlProxy`` only has named helpers for dirs / OK /
# back / menu / home / power / vol / ch / mouse. China T-Cast firmware also
# implements digits and ``source`` (aerial-tv MT9655 ``tcast-protocol.md``).
#
# MagiConnect ``TR_KEY_RED/GREEN/YELLOW/BLUE`` (34–37) and other SDK names
# (3d, epg, display, playback, scale, picture, favorite, search, backspace,
# info, enter, dot) are **not** mapped on China firmware: the TV ignores
# ``149>>`` for those integers. TCLPlus never sends them. Do not advertise
# them as working keys. Raw integers are still accepted for experiments.
KEYS: dict[str, int] = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "0": 10,
    "up": 11,
    "down": 12,
    "left": 13,
    "right": 14,
    "ok": 15,
    "back": 16,
    "menu": 18,
    "home": 19,
    "power": 20,
    "volume_up": 21,
    "volume_down": 22,
    "mute": 23,
    "channel_up": 27,
    "channel_down": 28,
    "source": 29,
    "mouse_left": 39,
    "mouse_right": 40,
    "smart_tv": 45,
}

# MagiConnect TR_KEY_PLAYBACK. China firmware ignores 149>>26; media_player
# still sends it for the play/pause buttons so the entity features remain.
PLAYBACK_KEY = 26

RAW_KEY_MAX = 999

# Names users may try for live TV. TCLPlus H5 remotekey "0" is GOTVAPP
# (opens MagiConnect on the phone), not a TV 149 key.
LIVE_TV_NAMES = frozenset({"live", "tv", "live_tv", "直播"})


def resolve_key(name: str) -> int | None:
    """Map a ``remote.send_command`` name to a T-Cast 149 integer.

    Named keys come from ``KEYS``. Any other decimal string in 0..999 is
    sent as a raw code (named keys such as ``0`` still mean digit zero).
    """
    if name in KEYS:
        return KEYS[name]
    if name.isdigit() and len(name) <= 3:
        code = int(name)
        if 0 <= code <= RAW_KEY_MAX:
            return code
    return None


class TclTvError(Exception):
    """Protocol or transport failure talking to the TV."""


@dataclass(frozen=True, slots=True)
class TvIdentity:
    """UDP discovery answer."""

    name: str
    protocol_version: int
    mac: str
    active_mac: str
    function_code: str = ""


@dataclass(frozen=True, slots=True)
class TvInfo:
    """TCP 159 handshake answer."""

    model: str
    app_version: str
    software_version: str
    mac: str
    algorithm: int
    bluetooth_mac: str = ""
    tv_type: str = ""
    device_id: str = ""


@dataclass(frozen=True, slots=True)
class TvApp:
    """Launchable app reported by ``223>>GET``."""

    package: str
    name: str
    system: bool
    icon: str = ""


def decode_tclplus_aes_key(blob: str = _OBFUSCATED_AES_KEY_B64) -> bytes:
    """Undo TCLPlus key hiding: Base64 decode, then XOR every byte with 0xFF."""
    return bytes(byte ^ 0xFF for byte in base64.b64decode(blob))


_AES_KEY = decode_tclplus_aes_key()


def _encrypt(data: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(_AES_KEY), modes.CBC(_AES_IV)).encryptor()
    return enc.update(padder.update(data) + padder.finalize()) + enc.finalize()


def _decrypt(data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(_AES_KEY), modes.CBC(_AES_IV)).decryptor()
    unpadder = padding.PKCS7(128).unpadder()
    plain = dec.update(data) + dec.finalize()
    return unpadder.update(plain) + unpadder.finalize()


def encode_frame(text: str, encrypted: bool = False) -> bytes:
    """Build one TCP frame (length prefix + optional AES body)."""
    body = text.encode()
    if encrypted:
        body = _encrypt(body)
    return struct.pack(">I", len(body)) + body


def _decode(body: bytes) -> str:
    """Decode a frame body whichever way the TV chose to send it.

    After algorithm=1 the TV usually encrypts, but the first unsolicited
    push after accept can still be plaintext, so block-sized bodies are
    tried as ciphertext first.
    """
    if body and len(body) % 16 == 0:
        with contextlib.suppress(ValueError):
            plain = _decrypt(body)
            if plain[:1].isdigit():
                return plain.decode("utf-8", "replace")
    return body.decode("utf-8", "replace")


def _decode_mac(raw: str) -> str:
    return raw.replace("&#058", ":").lower()


def parse_discovery(data: bytes) -> TvIdentity | None:
    """Parse a TV's UDP 6537 answer; ``None`` for anything else."""
    fields = data.rstrip(b"\0").decode("utf-8", "replace").split(":")
    if len(fields) < 11 or fields[3] != "TV":
        return None
    try:
        version = int(fields[0])
    except ValueError:
        return None
    return TvIdentity(
        name=fields[2],
        protocol_version=version,
        mac=_decode_mac(fields[8]),
        active_mac=_decode_mac(fields[10]),
        function_code=fields[6] if len(fields) > 6 else "",
    )


def parse_apps(reply: str) -> list[TvApp]:
    """Parse a ``223>>GET>>...`` application list."""
    _, _, records = reply.partition(f"223{_SEP}GET{_SEP}")
    apps: list[TvApp] = []
    for record in records.split(">"):
        parts = record.split("::")
        if len(parts) < 2 or not parts[0]:
            continue
        apps.append(
            TvApp(
                package=parts[0],
                name=parts[1],
                icon=parts[2] if len(parts) > 2 else "",
                system=len(parts) > 8 and parts[8] == "0",
            )
        )
    return apps


def resolve_app_package(apps: list[TvApp], media_id: str) -> str | None:
    """Match play_media id to a package: exact package, exact name, then unique substring."""
    wanted = media_id.strip() if isinstance(media_id, str) else ""
    if not wanted:
        return None
    for app in apps:
        if app.package == wanted:
            return app.package
    lowered = wanted.casefold()
    for app in apps:
        if app.name.casefold() == lowered:
            return app.package
    matches = [
        app
        for app in apps
        if lowered in app.name.casefold() or lowered in app.package.casefold()
    ]
    if len(matches) == 1:
        return matches[0].package
    return None


def parse_handshake(text: str) -> TvInfo:
    """Parse a ``159>>...`` handshake reply."""
    fields = text.split(_SEP)
    if len(fields) < 7 or fields[0] != "159":
        raise TclTvError(f"short or invalid 159 reply: {fields!r}")
    app_field = fields[2]
    app_version = app_field.partition(":")[2] or app_field
    return TvInfo(
        model=fields[1],
        app_version=app_version,
        software_version=fields[3],
        mac=fields[5].lower(),
        algorithm=int(fields[6]) if fields[6].isdigit() else -1,
        bluetooth_mac=fields[7].lower() if len(fields) > 7 else "",
        tv_type=fields[8] if len(fields) > 8 else "",
        device_id=fields[17] if len(fields) > 17 else "",
    )


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, host: str, answer: asyncio.Future[TvIdentity]) -> None:
        self._host = host
        self._answer = answer

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] != self._host or self._answer.done():
            return
        if (identity := parse_discovery(data)) is not None:
            self._answer.set_result(identity)


async def async_probe(host: str, timeout: float = 3.0) -> TvIdentity:
    """Unicast a discovery announcement to ``host`` and return its identity."""
    loop = asyncio.get_running_loop()
    answer: asyncio.Future[TvIdentity] = loop.create_future()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _DiscoveryProtocol(host, answer), local_addr=("0.0.0.0", 0)
    )
    me = f"ha-{uuid.uuid4().hex[:12]}"
    packet = f"1:{int(time.time() * 1000)}:{me}:PHONE:1:{me}:{me}:0:0\0".encode()
    try:
        transport.sendto(packet, (host, DISCOVERY_PORT))
        async with asyncio.timeout(timeout):
            return await answer
    except TimeoutError as err:
        raise TclTvError(
            f"{host} did not answer TCL discovery on UDP {DISCOVERY_PORT}"
        ) from err
    finally:
        transport.close()


async def async_wake(macs: list[str], repeats: int = 5) -> None:
    """Broadcast magic packets (TCL MagiConnect uses UDP 7778, 5 x 1 s).

    TCLPlus 5.1.2.1 emptied ``TCLRemoteControlProxy.awaken``; the TV-side
    WOL listener is unchanged, so this still matches the older SDK.
    """
    payloads = [
        b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "")) * 16
        for mac in macs
        if mac
    ]
    if not payloads:
        return
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("0.0.0.0", 0), allow_broadcast=True
    )
    try:
        for attempt in range(repeats):
            for payload in payloads:
                for port in WOL_PORTS:
                    transport.sendto(payload, ("255.255.255.255", port))
            if attempt < repeats - 1:
                await asyncio.sleep(1)
    finally:
        transport.close()


class TclTvClient:
    """One authenticated TCP 6553 control session."""

    def __init__(
        self,
        host: str,
        client_name: str,
        client_id: str,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        self.host = host
        self.info: TvInfo | None = None
        self._client_name = client_name
        self._client_id = client_id
        self._on_disconnect = on_disconnect
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._encrypted = False
        self._pending: dict[str, deque[asyncio.Future[str]]] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._last_tx = 0.0
        self._last_rx = 0.0
        self._closed = False

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._closed

    async def connect(self, timeout: float = 5.0) -> TvInfo:
        """Open the socket, run the 159 identity exchange, start keepalive."""
        try:
            async with asyncio.timeout(timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, CONTROL_PORT
                )
                self._write(
                    f"159>>{self._client_name}>>1>>{self._client_id}>>1",
                    plain=True,
                )
                while True:
                    text = _decode(await self._read_frame())
                    if text.startswith("159" + _SEP):
                        break
                    _LOGGER.debug("%s pre-handshake frame: %s", self.host, text[:80])
        except (OSError, TimeoutError, asyncio.IncompleteReadError, TclTvError) as err:
            await self.close()
            raise TclTvError(
                f"cannot open TCL control session to {self.host}: {err!r}"
            ) from err
        except asyncio.CancelledError:
            await self.close()
            raise

        info = parse_handshake(text)
        self.info = info
        self._encrypted = info.algorithm == 1
        self._last_rx = time.monotonic()
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._read_loop(), name=f"tcl_tv read {self.host}"),
            loop.create_task(
                self._keepalive_loop(), name=f"tcl_tv keepalive {self.host}"
            ),
        ]
        return info

    async def close(self) -> None:
        """Tear the session down; ``on_disconnect`` fires only for established links."""
        if self._closed:
            return
        self._closed = True
        established = bool(self._tasks)
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        for queue in self._pending.values():
            for fut in queue:
                if not fut.done():
                    fut.set_exception(TclTvError("connection closed"))
        self._pending.clear()
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
        if established and self._on_disconnect is not None:
            self._on_disconnect()

    async def send_key(self, code: int) -> None:
        await self._send(f"149>>{code}")

    async def get_volume(self) -> int:
        reply = await self._request("136>>", "130")
        return int(reply.split(_SEP)[1])

    async def set_volume(self, level: int) -> None:
        await self._send(f"130>>{max(0, min(100, level))}")

    async def get_mute(self) -> bool | None:
        try:
            reply = await self._request("140>>", "131")
        except TclTvError:
            return None
        flag = reply.split(_SEP)[1].strip().lower() if _SEP in reply else ""
        if flag in ("true", "1"):
            return True
        if flag in ("false", "0"):
            return False
        return None

    async def set_mute(self, mute: bool) -> None:
        await self._send(f"131>>{'true' if mute else 'false'}")

    async def get_apps(self) -> list[TvApp]:
        reply = await self._request("223>>GET", "223", timeout=15.0)
        return parse_apps(reply)

    async def launch_app(self, package: str) -> None:
        await self._send(f"223>>OPEN>>{package}")

    def _write(self, text: str, plain: bool = False) -> None:
        if self._writer is None or self._closed:
            raise TclTvError("not connected")
        self._writer.write(encode_frame(text, encrypted=self._encrypted and not plain))
        self._last_tx = time.monotonic()

    async def _send(self, text: str) -> None:
        self._write(text)
        try:
            await self._writer.drain()  # type: ignore[union-attr]
        except OSError as err:
            await self.close()
            raise TclTvError(f"send to {self.host} failed: {err!r}") from err

    async def _request(self, text: str, reply_id: str, timeout: float = 5.0) -> str:
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        queue = self._pending.setdefault(reply_id, deque())
        queue.append(fut)
        try:
            await self._send(text)
            async with asyncio.timeout(timeout):
                return await fut
        except TimeoutError as err:
            raise TclTvError(f"{self.host} did not answer {text!r}") from err
        finally:
            with contextlib.suppress(ValueError):
                queue.remove(fut)

    async def _read_frame(self) -> bytes:
        assert self._reader is not None
        (length,) = struct.unpack(">I", await self._reader.readexactly(4))
        if length >= _MAX_FRAME:
            raise TclTvError(f"oversized frame ({length} bytes)")
        return await self._reader.readexactly(length)

    async def _read_loop(self) -> None:
        try:
            while True:
                text = _decode(await self._read_frame())
                self._last_rx = time.monotonic()
                reply_id = text.split(_SEP, 1)[0]
                queue = self._pending.get(reply_id)
                delivered = False
                while queue:
                    fut = queue.popleft()
                    if not fut.done():
                        fut.set_result(text)
                        delivered = True
                        break
                if delivered:
                    continue
                if reply_id != "150":
                    _LOGGER.debug("%s unsolicited: %s", self.host, text[:120])
        except (OSError, asyncio.IncompleteReadError, TclTvError) as err:
            _LOGGER.debug("%s read loop ended: %r", self.host, err)
        finally:
            await self.close()

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            if now - self._last_rx > SILENCE_TIMEOUT:
                _LOGGER.debug(
                    "%s silent for %.0fs, dropping link", self.host, now - self._last_rx
                )
                await self.close()
                return
            if now - self._last_tx >= HEARTBEAT_IDLE:
                try:
                    await self._send("150>>")
                except TclTvError:
                    return
