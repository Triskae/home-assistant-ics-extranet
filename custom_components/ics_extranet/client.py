"""Async HTTP client for the server-rendered ICS Extranet."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Final
from urllib.parse import urlencode, urljoin

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout

from .const import (
    DEFAULT_MONTHLY_PAYMENTS,
    ICS_ORIGIN,
    ICS_VERSION,
    REQUEST_TIMEOUT_SECONDS,
)
from .parser import (
    IcsParseError,
    IcsSummary,
    build_summary,
    is_authenticated_page,
    parse_accounting_overview,
)

GROUP_PATTERN: Final = re.compile(r"^[a-zA-Z0-9_-]+$")
USER_AGENT: Final = "Home-Assistant-ICS-Extranet/0.4.1"


class IcsClientError(Exception):
    """Base ICS client error."""


class IcsAuthenticationError(IcsClientError):
    """ICS rejected the supplied credentials."""


class IcsConnectionError(IcsClientError):
    """ICS could not be reached."""


class IcsClient:
    """Cookie-authenticated client scoped to one ICS account."""

    def __init__(
        self,
        *,
        session: ClientSession,
        username: str,
        password: str,
        group: str,
        monthly_payments: bool = DEFAULT_MONTHLY_PAYMENTS,
    ) -> None:
        normalized_group = group.strip().lower()
        if not GROUP_PATTERN.fullmatch(normalized_group):
            raise ValueError("ICS group contains unsupported characters")
        self._session = session
        self._username = username.strip()
        self._password = password
        self._group = normalized_group
        self._monthly_payments = monthly_payments
        self._authenticated = False

    @property
    def group(self) -> str:
        """Return the non-secret ICS agency group."""
        return self._group

    @property
    def connection_url(self) -> str:
        """Return the public login URL for this agency group."""
        return urljoin(
            ICS_ORIGIN,
            f"{ICS_VERSION}/connexion.php?{urlencode({'groupe': self._group})}",
        )

    async def async_close(self) -> None:
        """Close the dedicated cookie session."""
        await self._session.close()

    async def async_login(self) -> None:
        """Create an authenticated ICS session."""
        await self._request_text("GET", self.connection_url)
        html, _ = await self._request_text(
            "POST",
            urljoin(ICS_ORIGIN, "login_externe.php"),
            data={
                "login": self._username,
                "mdp": self._password,
                "groupe": self._group,
            },
            headers={"Referer": self.connection_url},
        )
        if not is_authenticated_page(html):
            raise IcsAuthenticationError("ICS authentication failed")
        self._authenticated = True

    async def async_fetch_summary(self, today: date) -> IcsSummary:
        """Fetch and normalize all data needed by the integration."""
        if not self._authenticated:
            await self.async_login()

        accounting_url = urljoin(ICS_ORIGIN, f"{ICS_VERSION}/comptabilite.html")
        accounting_html, final_url = await self._request_text("GET", accounting_url)
        if not is_authenticated_page(accounting_html):
            self._authenticated = False
            await self.async_login()
            accounting_html, final_url = await self._request_text("GET", accounting_url)
            if not is_authenticated_page(accounting_html):
                raise IcsAuthenticationError("ICS session could not be restored")

        _, ledger_url = parse_accounting_overview(accounting_html, final_url)
        ledger_html, _ = await self._request_text("GET", ledger_url)
        if not is_authenticated_page(ledger_html):
            self._authenticated = False
            raise IcsAuthenticationError("ICS session expired")

        return build_summary(
            accounting_html=accounting_html,
            accounting_url=final_url,
            ledger_html=ledger_html,
            today=today,
            fetched_at=datetime.now().astimezone(),
            monthly_payments=self._monthly_payments,
        )

    async def _request_text(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers=request_headers,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                response.raise_for_status()
                return await response.text(errors="replace"), str(response.url)
        except (TimeoutError, ClientResponseError, ClientError) as error:
            raise IcsConnectionError("Unable to reach ICS Extranet") from error


__all__ = [
    "IcsAuthenticationError",
    "IcsClient",
    "IcsClientError",
    "IcsConnectionError",
    "IcsParseError",
]
