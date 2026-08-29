#!/usr/bin/env python3
"""Sanity-check the hass-ledfx REST client against a live LedFx instance.

Runs the integration's real ``custom_components/ledfx/client.py`` — no Home
Assistant install required — so what it exercises is exactly what the
integration sends.

Read-only by default::

    python3 scripts/ledfx_api_check.py --host 192.168.1.50 --port 8888

Add --write <virtual_id> to also exercise the control paths (turn on, change
brightness, apply a preset, turn off). That visibly changes your lights.

    python3 scripts/ledfx_api_check.py --host ledfx.trapdoor.me --port 443 \
        --scheme https --user me --password secret --write my-strip
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "ledfx"


def _load_client_module() -> types.ModuleType:
    """Import the integration's client.py without pulling in Home Assistant."""

    # const.py only needs homeassistant.const.Platform; stub it out.
    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []  # type: ignore[attr-defined]
        ha_const = types.ModuleType("homeassistant.const")

        class Platform(str):
            BINARY_SENSOR = "binary_sensor"
            BUTTON = "button"
            LIGHT = "light"
            NUMBER = "number"
            SELECT = "select"
            SENSOR = "sensor"
            SWITCH = "switch"

        ha_const.Platform = Platform  # type: ignore[attr-defined]
        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.const"] = ha_const

    # Register a synthetic package rooted at the component dir so client.py's
    # relative imports resolve without running the real __init__.py.
    pkg = types.ModuleType("_ledfx_component")
    pkg.__path__ = [str(COMPONENT_DIR)]  # type: ignore[attr-defined]
    sys.modules["_ledfx_component"] = pkg
    return importlib.import_module("_ledfx_component.client")


class NonClosingAsyncClient(httpx.AsyncClient):
    """Mirror HA's HassHttpXAsyncClient: suppress context management.

    client.py wraps every request in ``async with self._client``; a plain
    AsyncClient would close itself after the first call.
    """

    async def __aenter__(self):  # noqa: D105
        return self

    async def __aexit__(self, *args: Any) -> None:  # noqa: D105
        return None


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        print(f"  \033[32mPASS\033[0m {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        print(f"  \033[31mFAIL\033[0m {name} — {detail}")

    def info(self, msg: str) -> None:
        print(f"  \033[36m····\033[0m {msg}")


async def check_read_only(client: Any, rep: Report) -> dict:
    """Exercise every GET the updater depends on. Returns collected data."""

    collected: dict = {}

    print("\nRead-only endpoints")

    try:
        info = await client.info()
        collected["info"] = info
        rep.ok("GET  /api/info", f"LedFx {info.get('version', '?')}")
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/info", repr(err))

    try:
        config = await client.config()
        collected["config"] = config
        if "configuration_version" in config:
            rep.ok(
                "GET  /api/config",
                f"configuration_version={config['configuration_version']} (V2 detected)",
            )
        elif "config" in config:
            rep.fail(
                "GET  /api/config",
                "legacy V1 shape — this LedFx predates 2.x, control paths will not work",
            )
        else:
            rep.fail("GET  /api/config", f"unexpected keys: {sorted(config)[:8]}")

        for key in ("ledfx_presets", "user_presets", "audio"):
            if key in config:
                rep.info(f"config.{key}: {len(config[key])} entries")
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/config", repr(err))

    try:
        devices = await client.devices()
        collected["devices"] = devices
        rep.ok("GET  /api/devices", f"{len(devices.get('devices', {}))} device(s)")
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/devices", repr(err))

    try:
        virtuals = await client.virtuals()
        collected["virtuals"] = virtuals
        vids = list(virtuals.get("virtuals", {}))
        rep.ok("GET  /api/virtuals", f"{len(vids)} virtual(s): {', '.join(vids[:5])}")
        for vid, virtual in virtuals.get("virtuals", {}).items():
            missing = [k for k in ("config", "effect", "is_device") if k not in virtual]
            if missing:
                rep.fail(f"  virtual '{vid}' shape", f"missing {missing}")
                break
        else:
            if vids:
                rep.ok("  virtual shape", "config/effect/is_device present")
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/virtuals", repr(err))

    try:
        scenes = await client.scenes()
        collected["scenes"] = scenes
        rep.ok("GET  /api/scenes", f"{len(scenes.get('scenes', {}))} scene(s)")
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/scenes", repr(err))

    try:
        schema = await client.schema()
        collected["schema"] = schema
        effects = sorted(schema.get("effects", {}))
        rep.ok("GET  /api/schema", f"{len(effects)} effect(s)")
        audio_enum = (
            schema.get("audio", {})
            .get("schema", {})
            .get("properties", {})
            .get("audio_device", {})
            .get("enum")
        )
        if audio_enum is None:
            rep.fail(
                "  schema.audio.audio_device.enum",
                "absent — the audio input select will have no options",
            )
        else:
            rep.ok("  schema.audio.audio_device.enum", f"{len(audio_enum)} input(s)")
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/schema", repr(err))

    try:
        colors = await client.colors()
        collected["colors"] = colors
        rep.ok(
            "GET  /api/colors",
            f"{len(colors.get('colors', {}).get('builtin', {}))} builtin colors",
        )
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/colors", repr(err))

    try:
        audio = await client.audio_devices()
        collected["audio_devices"] = audio
        rep.ok(
            "GET  /api/audio/devices",
            f"{len(audio.get('devices', {}))} input(s), active={audio.get('active_device_index')}",
        )
    except Exception as err:  # noqa: BLE001
        rep.fail("GET  /api/audio/devices", repr(err))

    return collected


async def check_write(client: Any, rep: Report, virtual_id: str, data: dict) -> None:
    """Exercise the control paths that this update repaired."""

    print(f"\nControl endpoints (virtual '{virtual_id}')")

    virtuals = data.get("virtuals", {}).get("virtuals", {})
    if virtual_id not in virtuals:
        rep.fail(
            "virtual exists",
            f"'{virtual_id}' not found. Available: {', '.join(virtuals) or '(none)'}",
        )
        return

    effects = sorted(data.get("schema", {}).get("effects", {}))
    if not effects:
        rep.fail("effect available", "no effects in schema")
        return
    effect = "rainbow" if "rainbow" in effects else effects[0]

    original = virtuals[virtual_id].get("effect") or {}

    try:
        resp = await client.device_on(virtual_id, effect)
        rep.ok(
            f"POST /api/virtuals/{virtual_id}/effects",
            f"type={resp.get('effect', {}).get('type')} (turn on)",
        )
    except Exception as err:  # noqa: BLE001
        rep.fail(f"POST /api/virtuals/{virtual_id}/effects", repr(err))
        return

    try:
        resp = await client.effect(virtual_id, effect, {"brightness": 0.5})
        got = resp.get("effect", {}).get("config", {}).get("brightness")
        if got == 0.5:
            rep.ok(f"PUT  /api/virtuals/{virtual_id}/effects", "brightness=0.5 applied")
        else:
            rep.fail(
                f"PUT  /api/virtuals/{virtual_id}/effects",
                f"brightness came back as {got!r}",
            )
    except Exception as err:  # noqa: BLE001
        rep.fail(f"PUT  /api/virtuals/{virtual_id}/effects", repr(err))

    presets = data.get("config", {}).get("ledfx_presets", {}).get(effect, {})
    if presets:
        preset_id = sorted(presets)[0]
        try:
            resp = await client.preset(virtual_id, "ledfx_presets", effect, preset_id)
            rep.ok(
                f"PUT  /api/virtuals/{virtual_id}/presets",
                f"category=ledfx_presets preset={preset_id}",
            )
        except Exception as err:  # noqa: BLE001
            rep.fail(f"PUT  /api/virtuals/{virtual_id}/presets", repr(err))
    else:
        rep.info(f"no ledfx_presets for '{effect}' — preset path not exercised")

    try:
        await client.device_off(virtual_id)
        rep.ok(f"DELETE /api/virtuals/{virtual_id}/effects", "turn off")
    except Exception as err:  # noqa: BLE001
        rep.fail(f"DELETE /api/virtuals/{virtual_id}/effects", repr(err))

    if original.get("type"):
        try:
            await client.device_on(virtual_id, original["type"])
            await client.effect(virtual_id, original["type"], original.get("config", {}))
            rep.info(f"restored previous effect '{original['type']}'")
        except Exception as err:  # noqa: BLE001
            rep.info(f"could not restore previous effect: {err!r}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="LedFx host or IP")
    parser.add_argument("--port", default="8888", help="LedFx port (default 8888)")
    parser.add_argument(
        "--scheme", default="http", choices=("http", "https"), help="URL scheme"
    )
    parser.add_argument("--user", help="Basic auth username")
    parser.add_argument("--password", help="Basic auth password")
    parser.add_argument(
        "--write",
        metavar="VIRTUAL_ID",
        help="Also exercise control paths on this virtual (changes your lights)",
    )
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--dump", metavar="FILE", help="Write collected JSON here")
    args = parser.parse_args()

    client_mod = _load_client_module()

    auth = (
        (args.user, args.password)
        if args.user is not None and args.password is not None
        else httpx.USE_CLIENT_DEFAULT
    )

    http = NonClosingAsyncClient(verify=False, follow_redirects=True)
    ledfx = client_mod.LedFxClient(
        http, f"{args.host}", args.port, auth, args.timeout
    )
    # client.py builds "http://{ip}:{port}/api"; swap the scheme for https setups.
    if args.scheme == "https":
        ledfx._url = ledfx._url.replace("http://", "https://", 1)

    print(f"Target: {ledfx._url}")

    rep = Report()
    try:
        data = await check_read_only(ledfx, rep)
        if args.write:
            await check_write(ledfx, rep, args.write, data)
        if args.dump:
            Path(args.dump).write_text(json.dumps(data, indent=2))
            print(f"\nCollected payloads written to {args.dump}")
    finally:
        await http.aclose()

    print(f"\n{rep.passed} passed, {rep.failed} failed")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
