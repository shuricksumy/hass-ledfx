"""End-to-end smoke test: load the integration in Home Assistant against a live LedFx.

Skipped unless LEDFX_HOST is set::

    LEDFX_HOST=192.168.111.50 LEDFX_PORT=8888 \
        python3 -m pytest tests/test_live_ha.py -q -o asyncio_mode=auto -s

Needs the Home Assistant test harness (requirements_test.txt). Unlike
tests/test_client_ledfx2.py this boots real HA, so it catches breakage that
request-level tests cannot -- moved HA symbols, entity descriptions that no
longer match, platforms that fail to set up.
"""

from __future__ import annotations

import os

import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ledfx.const import (
    ATTR_DEVICE_SW_VERSION,
    CONF_BASIC_AUTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_IS_FROM_FLOW,
    UPDATER,
)

HOST = os.environ.get("LEDFX_HOST")
PORT = os.environ.get("LEDFX_PORT", "8888")

pytestmark = pytest.mark.skipif(not HOST, reason="LEDFX_HOST not set")


@pytest.fixture
def allow_ledfx_host(socket_enabled):  # noqa: ANN001
    """pytest-homeassistant-custom-component pins the allowlist to 127.0.0.1."""

    pytest_socket.socket_allow_hosts([HOST, "127.0.0.1"], allow_unix_socket=True)
    yield


async def test_setup_entry_against_live_ledfx(
    hass: HomeAssistant,
    enable_custom_integrations,  # noqa: ANN001
    allow_ledfx_host,  # noqa: ANN001
) -> None:
    """The integration must set up and create entities from a real LedFx."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: HOST,
            CONF_PORT: PORT,
            CONF_BASIC_AUTH: False,
            CONF_TIMEOUT: 15,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        },
        options={OPTION_IS_FROM_FLOW: True},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id), "setup failed"
    await hass.async_block_till_done()

    updater = hass.data[DOMAIN][entry.entry_id][UPDATER]

    print(f"\nLedFx version:     {updater.data.get(ATTR_DEVICE_SW_VERSION)}")
    print(f"lights:            {len(updater.devices)}")
    print(f"color properties:  {len(updater.color_properties)}")
    print(f"scene buttons:     {len(updater.buttons)}")

    assert updater.last_update_success, "coordinator update failed"
    assert updater.devices, "no lights discovered"

    # /api/info carries the LedFx release; /api/config only has the config
    # schema version, so a value like "2.3.6" means the wrong source won.
    version = updater.data.get(ATTR_DEVICE_SW_VERSION)
    assert version and version.startswith("2."), f"unexpected version {version!r}"

    assert updater.color_properties, "no color properties parsed from schema"

    registry = er.async_get(hass)
    entities = [
        e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    ]
    by_domain: dict[str, int] = {}
    for ent in entities:
        by_domain[ent.domain] = by_domain.get(ent.domain, 0) + 1
    print(f"registered:        {by_domain}")

    for domain in ("light", "sensor", "binary_sensor", "select"):
        assert by_domain.get(domain, 0) > 0, f"no {domain} entities registered"

    # Per-effect controls were removed in 3.2.0; thousands of unused, disabled
    # registry rows per instance.
    for domain in ("number", "switch"):
        assert by_domain.get(domain, 0) == 0, f"{domain} entities should be gone"
    # One audio input select, plus one color pattern select per virtual.
    assert by_domain["select"] == 1 + by_domain["light"], (
        f"expected 1 + {by_domain['light']} selects, got {by_domain['select']}"
    )

    # Every device page must show entities; an empty device page is the
    # symptom of entity descriptions failing to build.
    device_reg = dr.async_get(hass)
    devices = [
        d
        for d in device_reg.devices.values()
        if entry.entry_id in d.config_entries
    ]
    per_device = {
        d.name: sum(1 for e in entities if e.device_id == d.id) for d in devices
    }
    empty = [name for name, count in per_device.items() if count == 0]
    print(f"devices:           {len(devices)}, empty: {empty}")
    print(f"sample device url: {devices[0].configuration_url}")
    assert not empty, f"devices with no entities: {empty}"

    lights = [e for e in entities if e.domain == "light"]
    state = hass.states.get(lights[0].entity_id)
    assert state is not None and state.state in ("on", "off")
    assert state.attributes.get("effect_list"), "light has no effect list"
    print(f"sample light:      {lights[0].entity_id} -> {state.state}")


async def test_reload_and_unload_cycle(
    hass: HomeAssistant,
    enable_custom_integrations,  # noqa: ANN001
    allow_ledfx_host,  # noqa: ANN001
) -> None:
    """Reload and unload must work on an entry that is not fresh from the flow.

    Regression guard: async_setup_entry used to defer
    async_forward_entry_setups to a call_later task for entries without
    OPTION_IS_FROM_FLOW -- i.e. every entry after the first Home Assistant
    restart. Setup returned True before any platform existed, so the next
    reload's async_unload_platforms failed and the entry got stuck in
    "failed_unload" with no entities at all.
    """

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: HOST,
            CONF_PORT: PORT,
            CONF_BASIC_AUTH: False,
            CONF_TIMEOUT: 15,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        },
        options={},  # not from the config flow: the post-restart path
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)

    def count() -> int:
        return sum(
            1 for e in registry.entities.values() if e.config_entry_id == entry.entry_id
        )

    first = count()
    print(f"\nentities after cold setup:  {first}")
    assert first > 0, "no entities created on the post-restart path"

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    print(f"entry state after reload:  {entry.state}")
    assert entry.state is ConfigEntryState.LOADED, f"reload left entry {entry.state}"
    assert count() == first, "entity count changed across reload"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    print(f"entry state after unload:  {entry.state}")
    assert entry.state is ConfigEntryState.NOT_LOADED
