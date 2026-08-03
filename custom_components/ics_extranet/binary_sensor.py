"""Monthly payment status entities for ICS Extranet."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_DETECTED_RECEIPTS,
    ATTR_MONTH,
    ATTR_PLANNED_AMOUNT,
    ATTR_STATUS,
)
from .coordinator import IcsDataUpdateCoordinator
from .entity import IcsCoordinatorEntity

MONTH_INDEXES = range(3)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the three current-quarter payment indicators."""
    del hass
    coordinator: IcsDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        IcsMonthlyPaymentBinarySensor(coordinator, entry, index)
        for index in MONTH_INDEXES
    )


class IcsMonthlyPaymentBinarySensor(IcsCoordinatorEntity, BinarySensorEntity):
    """Automatically checked month based on bank transfers visible in ICS."""

    _attr_icon = "mdi:calendar-check"
    _attr_translation_key = "quarter_payment"

    def __init__(
        self,
        coordinator: IcsDataUpdateCoordinator,
        entry: ConfigEntry,
        month_index: int,
    ) -> None:
        super().__init__(coordinator, entry, f"quarter_month_{month_index + 1}")
        self._month_index = month_index

    @property
    def translation_placeholders(self) -> dict[str, str]:
        """Include the ISO month without relying on process locale."""
        return {"month": self._payment.month}

    @property
    def is_on(self) -> bool:
        """Return whether this month is paid or otherwise settled."""
        return self._payment.is_paid

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return compact details for dashboard rendering."""
        payment = self._payment
        return {
            ATTR_MONTH: payment.month,
            ATTR_PLANNED_AMOUNT: str(payment.amount),
            ATTR_DETECTED_RECEIPTS: str(payment.detected_receipts),
            ATTR_STATUS: payment.status.value,
        }

    @property
    def _payment(self):
        return self.coordinator.data.payments[self._month_index]
