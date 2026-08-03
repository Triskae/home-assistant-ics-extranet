"""Shared entity base for ICS Extranet."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import IcsDataUpdateCoordinator, device_info


class IcsCoordinatorEntity(CoordinatorEntity[IcsDataUpdateCoordinator]):
    """Base class for entities backed by the ICS coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IcsDataUpdateCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        assert entry.unique_id is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = device_info(entry, coordinator.client)
