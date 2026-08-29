"""Service-call tests against the bundled LedFx 2.x mock, inside Home Assistant.

Offline and deterministic: scripts/mock_ledfx.py is served on localhost, so no
real LedFx and no real lights are touched.

    python3 -m pytest tests/test_ha_services.py -q -o asyncio_mode=auto

These exercise the entity action paths rather than just setup. Setup-only tests
miss whole classes of breakage -- notably that ActionType is interpolated into
the dispatched method name, and on Python 3.11+ f"{ActionType.DEVICE}" renders
"ActionType.DEVICE" instead of "device", so light.turn_off raised
AttributeError: 'LedFxLight' object has no attribute '_ActionType.DEVICE_off'.
"""

from __future__ import annotations

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_IP_ADDRESS,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ledfx.const import (
    CONF_BASIC_AUTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_IS_FROM_FLOW,
)

MOCK_PATH = Path(__file__).resolve().parent.parent / "scripts" / "mock_ledfx.py"


def _load_mock():
    spec = importlib.util.spec_from_file_location("_mock_ledfx", MOCK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ledfx_server(socket_enabled):  # noqa: ANN001
    """Serve the LedFx 2.x mock on a free localhost port."""

    module = _load_mock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant,
    enable_custom_integrations,  # noqa: ANN001
    ledfx_server: int,
):
    """Set the integration up against the mock."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: "127.0.0.1",
            CONF_PORT: str(ledfx_server),
            CONF_BASIC_AUTH: False,
            CONF_TIMEOUT: 10,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        },
        options={OPTION_IS_FROM_FLOW: True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _light_entity_id(hass: HomeAssistant) -> str:
    lights = [e for e in hass.states.async_entity_ids(LIGHT_DOMAIN) if "ledfx" in e]
    assert lights, "no ledfx light entities"
    return lights[0]


async def test_light_turn_on_and_off(hass: HomeAssistant, setup_entry) -> None:  # noqa: ANN001
    """turn_on / turn_off must dispatch to _device_on / _device_off."""

    entity_id = await _light_entity_id(hass)

    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_ON

    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_light_turn_on_with_brightness(
    hass: HomeAssistant, setup_entry  # noqa: ANN001
) -> None:
    """Brightness goes through the effect update path."""

    entity_id = await _light_entity_id(hass)

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
    assert state.attributes.get(ATTR_BRIGHTNESS) == 128


async def test_light_turn_on_with_effect(
    hass: HomeAssistant, setup_entry  # noqa: ANN001
) -> None:
    """Selecting an effect from effect_list must reach the virtuals endpoint."""

    entity_id = await _light_entity_id(hass)
    effects = hass.states.get(entity_id).attributes["effect_list"]
    effect = next(e for e in effects if " - " not in e)

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, "effect": effect},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == STATE_ON
    assert state.attributes.get("effect") == effect
