"""Minimal regression tests for the LedFx 2.x REST contract.

Self-contained on purpose: plain pytest + httpx.MockTransport, no Home
Assistant fixtures and no pytest-asyncio, so it runs anywhere httpx is
installed::

    python3 -m pytest tests/test_client_ledfx2.py -q

Each test pins the exact request the client puts on the wire for a method
that drifted against LedFx >= 2.x.
"""

from __future__ import annotations

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
    """Import client.py with homeassistant stubbed out."""

    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        ha.__path__ = []  # type: ignore[attr-defined]
        ha_const = types.ModuleType("homeassistant.const")
        ha_const.Platform = type(
            "Platform",
            (str,),
            {
                name.upper(): name
                for name in (
                    "binary_sensor",
                    "button",
                    "light",
                    "number",
                    "select",
                    "sensor",
                    "switch",
                )
            },
        )  # type: ignore[attr-defined]
        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.const"] = ha_const

    if "_ledfx_component" not in sys.modules:
        pkg = types.ModuleType("_ledfx_component")
        pkg.__path__ = [str(COMPONENT_DIR)]  # type: ignore[attr-defined]
        sys.modules["_ledfx_component"] = pkg
    return importlib.import_module("_ledfx_component.client")


client_module = _load_client_module()
LedFxClient = client_module.LedFxClient


class _NonClosingClient(httpx.AsyncClient):
    """Mirror HA's HassHttpXAsyncClient, which suppresses context management."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


def call(method: str, *args: Any, response: dict | None = None) -> httpx.Request:
    """Invoke a client method against a mock transport, return the request sent."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response or {"status": "success"})

    async def run() -> None:
        http = _NonClosingClient(transport=httpx.MockTransport(handler))
        ledfx = LedFxClient(http, "127.0.0.1", "8888")
        try:
            await getattr(ledfx, method)(*args)
        finally:
            await http.aclose()

    asyncio.run(run())
    assert len(seen) == 1
    return seen[0]


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_device_on_posts_to_virtuals_without_config() -> None:
    """Effects live on virtuals, and config must be omitted.

    LedFx 2.x validates effect config with PREVENT_EXTRA, so the old
    ``{"config": {"active": true}}`` body is rejected outright. Omitting
    config makes LedFx restore the effect config saved for that virtual.
    """

    request = call("device_on", "matrix", "rainbow")

    assert request.method == "POST"
    assert request.url.path == "/api/virtuals/matrix/effects"
    assert body(request) == {"type": "rainbow"}
    assert "config" not in body(request)


def test_device_off_deletes_virtual_effect() -> None:
    request = call("device_off", "matrix")

    assert request.method == "DELETE"
    assert request.url.path == "/api/virtuals/matrix/effects"


def test_delete_effect_posts_to_effects_delete() -> None:
    request = call("delete_effect", "matrix", "rainbow")

    assert request.method == "POST"
    assert request.url.path == "/api/virtuals/matrix/effects/delete"
    assert body(request) == {"type": "rainbow"}


def test_preset_puts_to_virtual_presets() -> None:
    request = call("preset", "matrix", "ledfx_presets", "rainbow", "cascade")

    assert request.method == "PUT"
    assert request.url.path == "/api/virtuals/matrix/presets"
    assert body(request) == {
        "category": "ledfx_presets",
        "effect_id": "rainbow",
        "preset_id": "cascade",
    }


def test_effect_puts_to_virtual_effects() -> None:
    request = call("effect", "matrix", "rainbow", {"brightness": 0.5})

    assert request.method == "PUT"
    assert request.url.path == "/api/virtuals/matrix/effects"
    assert body(request) == {"config": {"brightness": 0.5}, "type": "rainbow"}


def test_set_audio_device_uses_config_endpoint() -> None:
    """LedFx 2.x sets the audio input through /api/config."""

    request = call("set_audio_device", 1)

    assert request.method == "PUT"
    assert request.url.path == "/api/config"
    assert body(request) == {"audio": {"audio_device": 1}}


def test_run_scene_unchanged() -> None:
    request = call("run_scene", "party")

    assert request.method == "PUT"
    assert request.url.path == "/api/scenes"
    assert body(request) == {"action": "activate", "id": "party"}


def test_no_device_scoped_effect_or_preset_routes() -> None:
    """Nothing in the client may target /api/devices/{id}/effects|presets."""

    source = (COMPONENT_DIR / "client.py").read_text()
    assert "devices/{" not in source
    assert 'prefix: str = "virtuals" if is_virtual else "devices"' not in source


def test_preset_categories_match_ledfx_2x() -> None:
    enum_module = importlib.import_module("_ledfx_component.enum")

    assert enum_module.EffectCategory.DEFAULT.value == "ledfx_presets"
    assert enum_module.EffectCategory.CUSTOM.value == "user_presets"
