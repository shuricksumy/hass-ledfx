"""Select component."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.components.select import (
    ENTITY_ID_FORMAT,
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_SELECT_AUDIO_INPUT,
    ATTR_SELECT_AUDIO_INPUT_NAME,
    ATTR_SELECT_AUDIO_INPUT_OPTIONS,
    ATTR_STATE,
)
from .entity import LedFxEntity
from .exceptions import LedFxError
from .updater import LedFxEntityDescription, LedFxUpdater, async_get_updater

PARALLEL_UPDATES = 0

OPTIONS_MAP: Final = {
    ATTR_SELECT_AUDIO_INPUT: ATTR_SELECT_AUDIO_INPUT_OPTIONS,
}

SELECTS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key=ATTR_SELECT_AUDIO_INPUT,
        name=ATTR_SELECT_AUDIO_INPUT_NAME,
        icon="mdi:audio-input-stereo-minijack",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=True,
    ),
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LedFx select entry.

    :param hass: HomeAssistant: Home Assistant object
    :param config_entry: ConfigEntry: ConfigEntry object
    :param async_add_entities: AddEntitiesCallback: AddEntitiesCallback callback object
    """

    updater: LedFxUpdater = async_get_updater(hass, config_entry.entry_id)

    @callback
    def add_select(entity: LedFxEntityDescription) -> None:
        """Add select.

        :param entity: LedFxEntityDescription: Select object
        """

        async_add_entities(
            [
                LedFxSelect(
                    f"{config_entry.entry_id}-{entity.description.key}",
                    entity,
                    updater,
                )
            ]
        )

    for select in SELECTS:
        add_select(
            LedFxEntityDescription(description=select, device_info=updater.device_info)
        )


class LedFxSelect(LedFxEntity, SelectEntity):
    """LedFx select entry."""

    _options_key: str

    def __init__(
        self,
        unique_id: str,
        entity: LedFxEntityDescription,
        updater: LedFxUpdater,
    ) -> None:
        """Initialize select.

        :param unique_id: str: Unique ID
        :param entity: LedFxEntityDescription object
        :param updater: LedFxUpdater: LedFx updater object
        """

        LedFxEntity.__init__(
            self, unique_id, entity.description, updater, ENTITY_ID_FORMAT
        )

        self._attr_device_info = entity.device_info

        self._attr_current_option = updater.data.get(entity.description.key, None)

        self._options_key = (
            OPTIONS_MAP[entity.description.key]
            if entity.description.key in OPTIONS_MAP
            else f"{entity.description.key}_options"
        )

        options: dict | list = updater.data.get(self._options_key, [])
        self._attr_options = (
            list(options.values()) if isinstance(options, dict) else options
        )

        self._attr_available = bool(
            updater.data.get(ATTR_STATE, False) and len(self._attr_options) > 0
        )

    def _handle_coordinator_update(self) -> None:
        """Update state."""

        current_option = self._updater.data.get(self.entity_description.key, False)
        options: dict | list = self._updater.data.get(self._options_key, [])
        options = list(options.values()) if isinstance(options, dict) else options

        is_available: bool = bool(
            self._updater.data.get(ATTR_STATE, False) and len(options) > 0
        )

        if (
            self._attr_current_option == current_option
            and self._attr_options == options
            and self._attr_available == is_available
        ):
            return

        self._attr_available = is_available
        self._attr_current_option = current_option
        self._attr_options = options

        self.async_write_ha_state()

    async def _audio_input_change(self, option: str) -> bool:
        """Audio input

        :param option: str: Option value
        :return bool: Result
        """

        options: dict = self._updater.data.get(self._options_key, {})
        if option_ids := [_id for _id, name in options.items() if name == option]:
            try:
                await self._updater.client.set_audio_device(int(option_ids[0]))

                return True
            except LedFxError as _e:
                _LOGGER.debug("Audio input update error: %r", _e)

        return False

    async def async_select_option(self, option: str) -> None:
        """Select option

        :param option: str: Option
        """

        if action := getattr(self, f"_{self.entity_description.key}_change"):
            if await action(option):
                self._updater.data[self.entity_description.key] = option
                self._attr_current_option = option

            self.async_write_ha_state()
