"""Data update coordinator for ICS Extranet."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import IcsAuthenticationError, IcsClient, IcsConnectionError
from .const import (
    CONF_UPDATE_INTERVAL_DAYS,
    DEFAULT_UPDATE_INTERVAL_DAYS,
    DOMAIN,
    normalize_update_interval_days,
)
from .parser import IcsParseError, IcsSummary

_LOGGER = logging.getLogger(__name__)


class IcsDataUpdateCoordinator(DataUpdateCoordinator[IcsSummary]):
    """Coordinate a single ICS poll for all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IcsClient,
    ) -> None:
        update_interval_days = normalize_update_interval_days(
            entry.data.get(CONF_UPDATE_INTERVAL_DAYS, DEFAULT_UPDATE_INTERVAL_DAYS)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(days=update_interval_days),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> IcsSummary:
        try:
            return await self.client.async_fetch_summary(dt_util.now().date())
        except IcsAuthenticationError as error:
            raise ConfigEntryAuthFailed("ICS credentials were rejected") from error
        except (IcsConnectionError, IcsParseError) as error:
            raise UpdateFailed("Unable to update ICS Extranet data") from error


def device_info(entry: ConfigEntry, client: IcsClient) -> dr.DeviceInfo:
    """Return the shared virtual-device metadata."""
    assert entry.unique_id is not None
    return dr.DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id)},
        manufacturer="ICS",
        model="Extranet V5",
        name=f"ICS Extranet ({client.group})",
        configuration_url=client.connection_url,
    )
