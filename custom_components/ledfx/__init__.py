"""LedFx custom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_SELECT_AUDIO_INPUT,
    CLEANUP_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    OPTION_CLEANUP_VERSION,
    OPTION_IS_FROM_FLOW,
    PLATFORMS,
    STOP_LISTENER,
    UPDATE_LISTENER,
    UPDATER,
)
from .helper import build_auth, get_config_value
from .updater import LedFxUpdater

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up entry configured via user interface.

    :param hass: HomeAssistant: Home Assistant object
    :param entry: ConfigEntry: Config Entry object
    :return bool: Is success
    """

    is_new: bool = get_config_value(entry, OPTION_IS_FROM_FLOW, False)

    if is_new:
        hass.config_entries.async_update_entry(entry, data=entry.data, options={})

    _updater: LedFxUpdater = LedFxUpdater(
        hass,
        get_config_value(entry, CONF_IP_ADDRESS),
        get_config_value(entry, CONF_PORT),
        build_auth(
            get_config_value(entry, CONF_USERNAME),
            get_config_value(entry, CONF_PASSWORD),
        ),
        get_config_value(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        get_config_value(entry, CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )

    # One-shot, so it can never remove entities a later release reintroduces.
    if get_config_value(entry, OPTION_CLEANUP_VERSION, 0) < CLEANUP_VERSION:
        _async_remove_stale_entities(hass, entry)

        hass.config_entries.async_update_entry(
            entry,
            options=dict(entry.options) | {OPTION_CLEANUP_VERSION: CLEANUP_VERSION},
        )

    hass.data.setdefault(DOMAIN, {})

    hass.data[DOMAIN][entry.entry_id] = {UPDATER: _updater}

    hass.data[DOMAIN][entry.entry_id][UPDATE_LISTENER] = entry.add_update_listener(
        async_update_options
    )

    # Populate the coordinator before the platforms are forwarded: every
    # entity is built from updater.devices, buttons, sensors and selects.
    #
    # This must stay inside async_setup_entry. Deferring the forward to a
    # call_later task returns True before the platforms exist, and Home
    # Assistant then has an entry it believes is loaded but whose platforms
    # were never set up - async_unload_platforms fails on the next reload and
    # the entry gets stuck in "failed_unload" with no entities.
    await _updater.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_stop(event: Event) -> None:
        """Async stop"""

        await _updater.async_stop()

    hass.data[DOMAIN][entry.entry_id][STOP_LISTENER] = hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, async_stop
    )

    return True


@callback
def _async_remove_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop registry entries for entities this integration no longer creates.

    Up to 3.1.0 every effect setting became a number, switch or select entity
    on every virtual - thousands of rows per instance, disabled by default and
    never used. They are gone now, so clear them out instead of leaving the
    registry full of entities marked "no longer being provided".

    The color pattern select is created fresh afterwards, so the old disabled
    one is removed here rather than being adopted and left switched off.

    :param hass: HomeAssistant: Home Assistant object
    :param entry: ConfigEntry: Config Entry object
    """

    registry = er.async_get(hass)

    stale: list[str] = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.domain in ("number", "switch")
        or (
            entity.domain == "select"
            and entity.unique_id != f"{entry.entry_id}-{ATTR_SELECT_AUDIO_INPUT}"
        )
    ]

    for entity_id in stale:
        registry.async_remove(entity_id)

    if stale:
        _LOGGER.info(
            "Removed %s per-effect entities that are no longer provided", len(stale)
        )


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options for entry that was configured via user interface.

    :param hass: HomeAssistant: Home Assistant object
    :param entry: ConfigEntry: Config Entry object
    """

    if entry.entry_id not in hass.data[DOMAIN]:
        return

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove entry configured via user interface.

    :param hass: HomeAssistant: Home Assistant object
    :param entry: ConfigEntry: Config Entry object
    :return bool: Is success
    """

    _data: dict | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    if _data is None:
        return True

    if is_unload := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        _updater: LedFxUpdater = _data[UPDATER]
        await _updater.async_stop()

        for key in (UPDATE_LISTENER, STOP_LISTENER):
            _listener: CALLBACK_TYPE | None = _data.get(key)

            if _listener is not None:
                _listener()

        hass.data[DOMAIN].pop(entry.entry_id)

    return is_unload
