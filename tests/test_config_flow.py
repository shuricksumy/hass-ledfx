"""Config flow tests against the bundled LedFx 2.x mock.

The documented install path is Settings > Integrations > Plus > LedFx with an
IP, a port and optional basic auth. These keep that intact.

    python3 -m pytest tests/test_config_flow.py -q -o asyncio_mode=auto
"""

from __future__ import annotations

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

from custom_components.ledfx.const import CONF_BASIC_AUTH, DOMAIN

MOCK_PATH = Path(__file__).resolve().parent.parent / "scripts" / "mock_ledfx.py"


@pytest.fixture(autouse=True)
def expected_lingering_timers():
    """async_verify_access spins up a throwaway coordinator to probe the host.

    Its debouncer leaves a timer behind that the flow never gets to cancel.
    Harmless, and upstream behaviour, but Home Assistant's test harness fails
    the test over it.
    """

    return True


@pytest.fixture
def ledfx_server(socket_enabled):
    """Serve the LedFx 2.x mock on a free localhost port."""

    spec = importlib.util.spec_from_file_location("_mock_ledfx_flow", MOCK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    server = ThreadingHTTPServer(("127.0.0.1", 0), module.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


async def test_user_flow_creates_entry(
    hass: HomeAssistant,
    enable_custom_integrations,
    ledfx_server: int,
) -> None:
    """IP + port must be enough to create an entry."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IP_ADDRESS: "127.0.0.1",
            CONF_PORT: str(ledfx_server),
            CONF_BASIC_AUTH: False,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IP_ADDRESS] == "127.0.0.1"
    assert result["data"][CONF_PORT] == str(ledfx_server)

    await hass.config_entries.async_unload(result["result"].entry_id)
    await hass.async_block_till_done()


async def test_user_flow_with_basic_auth(
    hass: HomeAssistant,
    enable_custom_integrations,
    ledfx_server: int,
) -> None:
    """Ticking basic auth re-shows the form for credentials, then keeps them."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Ticking the box adds the username/password fields to the same step.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IP_ADDRESS: "127.0.0.1",
            CONF_PORT: str(ledfx_server),
            CONF_BASIC_AUTH: True,
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IP_ADDRESS: "127.0.0.1",
            CONF_PORT: str(ledfx_server),
            CONF_BASIC_AUTH: True,
            CONF_USERNAME: "user",
            CONF_PASSWORD: "secret",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "user"
    assert result["data"][CONF_PASSWORD] == "secret"

    await hass.config_entries.async_unload(result["result"].entry_id)
    await hass.async_block_till_done()


async def test_user_flow_reports_unreachable_host(
    hass: HomeAssistant,
    enable_custom_integrations,
    socket_enabled,
) -> None:
    """An unreachable LedFx must return an error, not create an entry."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_IP_ADDRESS: "127.0.0.1",
            CONF_PORT: "1",  # nothing listening
            CONF_BASIC_AUTH: False,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]
