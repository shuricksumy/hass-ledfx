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
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ledfx.const import (
    ATTR_DEVICE_SW_VERSION,
    CONF_BASIC_AUTH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPTION_IS_FROM_FLOW,
    UPDATER,
)
from custom_components.ledfx.enum import Version

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
    print(f"API version:       {updater.version}")
    print(f"lights:            {len(updater.devices)}")
    print(f"effect properties: {len(updater.effect_properties)}")
    print(f"numbers:           {len(updater.numbers)}")
    print(f"switches:          {len(updater.switches)}")
    print(f"selects:           {len(updater.selects)}")
    print(f"scene buttons:     {len(updater.buttons)}")

    assert updater.last_update_success, "coordinator update failed"
    assert updater.version == Version.V2, "LedFx 2.x should be detected"
    assert updater.devices, "no lights discovered"

    # /api/info carries the LedFx release; /api/config only has the config
    # schema version, so a value like "2.3.6" means the wrong source won.
    version = updater.data.get(ATTR_DEVICE_SW_VERSION)
    assert version and version.startswith("2."), f"unexpected version {version!r}"

    # Regression guard: HA rebuilds entity descriptions through
    # homeassistant.util.frozen_dataclass_compat, which broke the isinstance()
    # dispatch in _prepare_device_fields and left every effect control missing.
    assert updater.effect_properties, "no effect properties parsed from schema"
    assert updater.numbers, "no effect number controls built"
    assert updater.switches, "no effect switch controls built"
    assert updater.selects, "no effect select controls built"

    registry = er.async_get(hass)
    entities = [
        e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    ]
    by_domain: dict[str, int] = {}
    for ent in entities:
        by_domain[ent.domain] = by_domain.get(ent.domain, 0) + 1
    print(f"registered:        {by_domain}")

    for domain in ("light", "sensor", "binary_sensor", "select", "number", "switch"):
        assert by_domain.get(domain, 0) > 0, f"no {domain} entities registered"

    lights = [e for e in entities if e.domain == "light"]
    state = hass.states.get(lights[0].entity_id)
    assert state is not None and state.state in ("on", "off")
    assert state.attributes.get("effect_list"), "light has no effect list"
    print(f"sample light:      {lights[0].entity_id} -> {state.state}")
