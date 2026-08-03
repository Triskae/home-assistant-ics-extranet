"""Sensor entities for ICS Extranet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ATTR_ACCOUNT_PERIOD, ATTR_TRANSACTION_COUNT
from .coordinator import IcsDataUpdateCoordinator
from .entity import IcsCoordinatorEntity
from .parser import IcsSummary

SensorValue = Decimal | date | str | None


@dataclass(frozen=True, kw_only=True)
class IcsSensorEntityDescription(SensorEntityDescription):
    """Describe an ICS sensor."""

    value_fn: Callable[[IcsSummary], SensorValue]


SENSORS: tuple[IcsSensorEntityDescription, ...] = (
    IcsSensorEntityDescription(
        key="balance_due",
        translation_key="balance_due",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        value_fn=lambda data: data.balance_due,
    ),
    IcsSensorEntityDescription(
        key="monthly_recommendation",
        translation_key="monthly_recommendation",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        value_fn=lambda data: data.monthly_recommendation,
    ),
    IcsSensorEntityDescription(
        key="last_operation",
        translation_key="last_operation",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data.last_operation_date,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ICS sensors from a config entry."""
    del hass
    coordinator: IcsDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        IcsSensor(coordinator, entry, description) for description in SENSORS
    )


class IcsSensor(IcsCoordinatorEntity, SensorEntity):
    """Representation of one ICS value."""

    entity_description: IcsSensorEntityDescription

    def __init__(
        self,
        coordinator: IcsDataUpdateCoordinator,
        entry: ConfigEntry,
        description: IcsSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> SensorValue:
        """Return the value already held in coordinator memory."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, str | int] | None:
        """Expose only compact, non-sensitive account metadata."""
        if (
            self.entity_description.key != "balance_due"
            or self.coordinator.data is None
        ):
            return None
        return {
            ATTR_ACCOUNT_PERIOD: self.coordinator.data.account_period or "",
            ATTR_TRANSACTION_COUNT: self.coordinator.data.transaction_count,
        }
