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
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ledfx.const import (
    CONF_BASIC_AUTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_IS_FROM_FLOW,
    UPDATER,
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


async def test_preset_selection_sticks(
    hass: HomeAssistant, setup_entry  # noqa: ANN001
) -> None:
    """Picking "<effect> - <preset>" must stay selected, not snap back.

    Regression guard: the preset was applied to LedFx correctly, but the light
    reported only the bare effect type, so the dropdown fell back to the plain
    effect and the choice looked like it had not taken.
    """

    entity_id = await _light_entity_id(hass)
    effects = hass.states.get(entity_id).attributes["effect_list"]

    for option in ("rainbow - slow-roll", "rainbow - my", "rainbow"):
        assert option in effects, f"{option} missing from effect_list"

        await hass.services.async_call(
            LIGHT_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: entity_id, "effect": option},
            blocking=True,
        )
        await hass.async_block_till_done()

        assert hass.states.get(entity_id).attributes["effect"] == option


async def test_preset_survives_coordinator_refresh(
    hass: HomeAssistant, setup_entry  # noqa: ANN001
) -> None:
    """The active preset is inferred from the effect config on every refresh.

    LedFx does not report which preset is active, so losing it on refresh would
    make the selection revert a few seconds after the user picked it.
    """

    entity_id = await _light_entity_id(hass)
    updater = hass.data[DOMAIN][setup_entry.entry_id][UPDATER]

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, "effect": "rainbow - slow-roll"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await updater.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).attributes["effect"] == "rainbow - slow-roll"


async def test_plain_effect_reports_no_preset(
    hass: HomeAssistant, setup_entry  # noqa: ANN001
) -> None:
    """A bare effect must not be reported with a stale preset suffix."""

    entity_id = await _light_entity_id(hass)
    updater = hass.data[DOMAIN][setup_entry.entry_id][UPDATER]

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id, "effect": "rainbow - blazing"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["effect"] == "rainbow - blazing"

    # Changing a config value away from the preset drops the preset label.
    await updater.client.effect("my-strip", "rainbow", {"brightness": 0.11})
    await updater.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).attributes["effect"] == "rainbow"


async def test_every_platform_action_dispatches(
    hass: HomeAssistant, setup_entry  # noqa: ANN001
) -> None:
    """Exercise the action of every platform, not just light.

    Each platform resolves its handler by building a method name at runtime,
    so a formatting change breaks them independently and invisibly -- setup
    still succeeds and the entity still appears.
    """

    registry = er.async_get(hass)
    entities = [
        e
        for e in registry.entities.values()
        if e.config_entry_id == setup_entry.entry_id
    ]

    # Per-effect number/switch/select entities were removed in 3.2.0.
    for domain in ("number", "switch"):
        assert not [
            e for e in entities if e.domain == domain
        ], f"{domain} entities should no longer be created"

    light_id = await _light_entity_id(hass)
    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: light_id, "effect": "rainbow"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # button -> scene activation
    buttons = [e.entity_id for e in entities if e.domain == "button"]
    assert buttons, "no scene buttons were built"
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: buttons[0]}, blocking=True
    )
    await hass.async_block_till_done()

    # select -> the audio input, plus one color pattern select per virtual
    selects = [e.entity_id for e in entities if e.domain == "select"]
    audio = [e for e in selects if e.endswith("audio_input")]
    gradients = [e for e in selects if e.endswith("_gradient")]
    assert len(audio) == 1, f"expected one audio input select, got {audio}"
    assert gradients, "no color pattern selects were built"
    audio_id = audio[0]

    options = hass.states.get(audio_id).attributes["options"]
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: audio_id, "option": options[-1]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(audio_id).state == options[-1]


async def test_gradient_select(hass: HomeAssistant, setup_entry) -> None:  # noqa: ANN001
    """The color pattern select applies a gradient to the active effect.

    One entity per virtual rather than one per effect setting: "gradient" is
    the only color key common enough to be worth an entity, and LedFx accepts
    either a gradient or a solid color for it.
    """

    light_id = await _light_entity_id(hass)
    updater = hass.data[DOMAIN][setup_entry.entry_id][UPDATER]

    gradient_id = next(
        e for e in hass.states.async_entity_ids("select") if e.endswith("_gradient")
    )

    # Unavailable while the light is off.
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: light_id}, blocking=True
    )
    await hass.async_block_till_done()
    await updater.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(gradient_id).state == "unavailable"

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: light_id, "effect": "rainbow"},
        blocking=True,
    )
    await hass.async_block_till_done()
    await updater.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(gradient_id)
    assert state.state != "unavailable", "gradient effect should expose the select"

    options = state.attributes["options"]
    assert "Ocean" in options, f"gradients missing from options: {options[:5]}"
    assert "red" in options, "solid colors should be offered too"

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: gradient_id, "option": "Ocean"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(gradient_id).state == "Ocean"

    # Survives a refresh: the value round-trips back to its name.
    await updater.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(gradient_id).state == "Ocean"
