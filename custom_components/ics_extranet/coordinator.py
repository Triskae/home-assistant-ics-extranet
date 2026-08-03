"""Data update coordinator for ICS Extranet."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import IcsAuthenticationError, IcsClient, IcsConnectionError
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
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
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=DEFAULT_UPDATE_INTERVAL,
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
