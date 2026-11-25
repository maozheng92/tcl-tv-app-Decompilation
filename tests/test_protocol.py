"""Offline tests for the TCL+ LAN protocol recovered from TCLPlus 5.1.2.1."""
from __future__ import annotations

import asyncio
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

_PROTOCOL = (
    Path(__file__).resolve().parents[1] / "custom_components" / "tcl_tv" / "protocol.py"
)
_SPEC = importlib.util.spec_from_file_location("tcl_tv_protocol", _PROTOCOL)
assert _SPEC is not None and _SPEC.loader is not None
proto = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = proto
_SPEC.loader.exec_module(proto)


def test_tclplus_obfuscated_aes_key_is_tnscreen() -> None:
    assert proto.decode_tclplus_aes_key() == b"tnscreentnscreen"
    assert proto._AES_KEY == b"tnscreentnscreen"
    assert proto._AES_IV == bytes.fromhex("1234567890abcdef1234567890abcdef")


def test_power_key_ciphertext_matches_known_vector() -> None:
    # Vector from independent tcast / MagiConnect research; TCLPlus uses the
    # same AES-128-CBC / PKCS7 parameters after de-obfuscating the key.
    assert proto._encrypt(b"149>>20").hex() == "473d4f5e84ac1eb069f46e58e372f0d6"
    frame = proto.encode_frame("149>>20", encrypted=True)
    assert frame == bytes.fromhex("00000010473d4f5e84ac1eb069f46e58e372f0d6")


def test_encode_frame_plaintext_length_prefix() -> None:
    frame = proto.encode_frame("150>>", encrypted=False)
    assert frame[:4] == struct.pack(">I", 5)
    assert frame[4:] == b"150>>"


def test_parse_discovery_unescapes_mac() -> None:
    packet = (
        b"14:1700000000000:Living Room:TV:1:Living Room:"
        b"1111111111111111111111111111111111111111111111111111111:0:"
        b"aa&#058bb&#058cc&#058dd&#058ee&#058ff:"
        b"11&#05822&#05833&#05844&#05855&#05866:"
        b"aa&#058bb&#058cc&#058dd&#058ee&#058ff\0"
    )
    identity = proto.parse_discovery(packet)
    assert identity is not None
    assert identity.name == "Living Room"
    assert identity.protocol_version == 14
    assert identity.mac == "aa:bb:cc:dd:ee:ff"
    assert identity.active_mac == "aa:bb:cc:dd:ee:ff"
    assert proto.parse_discovery(b"not a tv") is None


def test_parse_apps_splits_records_and_system_flag() -> None:
    reply = (
        "223>>GET>>com.example.player::Player::http://tv/icon.png::1::1.0::0::0::100::1"
        ">com.tcl.settings::Settings::http://tv/s.png::1::1.0::0::0::1::0"
    )
    apps = proto.parse_apps(reply)
    assert [app.package for app in apps] == ["com.example.player", "com.tcl.settings"]
    assert apps[0].name == "Player"
    assert apps[0].system is False
    assert apps[1].system is True


def test_resolve_app_package_prefers_exact_then_unique_substring() -> None:
    apps = proto.parse_apps(
        "223>>GET>>com.example.player::云视听小电视::::1::1.0::0::0::100::1"
        ">com.tcl.settings::Settings::::1::1.0::0::0::1::0"
    )
    assert proto.resolve_app_package(apps, "com.example.player") == "com.example.player"
    assert proto.resolve_app_package(apps, "云视听小电视") == "com.example.player"
    assert proto.resolve_app_package(apps, "settings") == "com.tcl.settings"
    assert proto.resolve_app_package(apps, "com.") is None
    assert proto.resolve_app_package(apps, "") is None


def test_parse_handshake_algorithm_and_mac() -> None:
    text = (
        "159>>75Q9M Pro>>600505013:5.1.2.1>>V8-LF1>>1>>AA:BB:CC:DD:EE:FF>>1"
        ">>AA:BB:CC:DD:EE:00>>1>>4>>>>>>id-1>>10.0.0.8"
    )
    info = proto.parse_handshake(text)
    assert info.model == "75Q9M Pro"
    assert info.app_version == "5.1.2.1"
    assert info.software_version == "V8-LF1"
    assert info.mac == "aa:bb:cc:dd:ee:ff"
    assert info.algorithm == 1
    with pytest.raises(proto.TclTvError):
        proto.parse_handshake("130>>10")


def test_decode_prefers_aes_when_block_sized() -> None:
    cipher = proto._encrypt(b"130>>40")
    assert proto._decode(cipher) == "130>>40"
    assert proto._decode(b"150>>YES") == "150>>YES"


def test_named_keys_match_tclplus_remote_proxy() -> None:
    assert proto.KEYS["up"] == 11
    assert proto.KEYS["down"] == 12
    assert proto.KEYS["left"] == 13
    assert proto.KEYS["right"] == 14
    assert proto.KEYS["ok"] == 15
    assert proto.KEYS["back"] == 16
    assert proto.KEYS["menu"] == 18
    assert proto.KEYS["home"] == 19
    assert proto.KEYS["power"] == 20
    assert proto.KEYS["volume_up"] == 21
    assert proto.KEYS["volume_down"] == 22
    assert proto.KEYS["mute"] == 23
    assert proto.KEYS["channel_up"] == 27
    assert proto.KEYS["channel_down"] == 28
    assert proto.KEYS["smart_tv"] == 45
    assert proto.KEYS["source"] == 29
    assert proto.KEYS["mouse_left"] == 39
    assert proto.PLAYBACK_KEY == 26
    assert "red" not in proto.KEYS
    assert "playback" not in proto.KEYS
    assert "enter" not in proto.KEYS
    assert proto.resolve_key("red") is None
    assert proto.resolve_key("直播") is None
    assert proto.resolve_key("0") == 10
    assert proto.resolve_key("183") == 183
    assert proto.resolve_key("1000") is None
    assert "直播" in proto.LIVE_TV_NAMES


async def _fake_tv(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    volume = 25
    apps = "223>>GET>>com.example.player::Player::icon"
    while True:
        try:
            header = await reader.readexactly(4)
        except asyncio.IncompleteReadError:
            break
        (length,) = struct.unpack(">I", header)
        body = await reader.readexactly(length)
        text = proto._decode(body)
        if text.startswith("159>>"):
            reply = proto.encode_frame(
                "159>>FakeTV>>1:test>>SW>>0>>aa:bb:cc:dd:ee:ff>>1",
                encrypted=False,
            )
        elif text.startswith("136"):
            reply = proto.encode_frame(f"130>>{volume}", encrypted=True)
        elif text.startswith("130>>"):
            volume = int(text.split(">>")[1])
            reply = proto.encode_frame(f"130>>{volume}", encrypted=True)
        elif text.startswith("140"):
            reply = proto.encode_frame("131>>false", encrypted=True)
        elif text.startswith("223>>GET"):
            reply = proto.encode_frame(apps, encrypted=True)
        elif text.startswith("150"):
            reply = proto.encode_frame("150>>YES", encrypted=True)
        else:
            reply = proto.encode_frame("150>>YES", encrypted=True)
        writer.write(reply)
        await writer.drain()
    writer.close()


@pytest.mark.asyncio
async def test_client_handshake_volume_and_apps() -> None:
    server = await asyncio.start_server(_fake_tv, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    assert port  # bind succeeded
    # Client always uses CONTROL_PORT; patch it for the test.
    original = proto.CONTROL_PORT
    proto.CONTROL_PORT = port
    client = proto.TclTvClient("127.0.0.1", "HomeAssistant", "testid")
    try:
        info = await client.connect()
        assert info.model == "FakeTV"
        assert info.algorithm == 1
        assert info.mac == "aa:bb:cc:dd:ee:ff"
        assert await client.get_volume() == 25
        await client.set_volume(40)
        assert await client.get_volume() == 40
        assert await client.get_mute() is False
        apps = await client.get_apps()
        assert apps[0].package == "com.example.player"
        await client.send_key(20)
    finally:
        await client.close()
        proto.CONTROL_PORT = original
        server.close()
        await server.wait_closed()
