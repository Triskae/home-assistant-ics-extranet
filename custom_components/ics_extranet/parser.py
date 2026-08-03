"""Pure HTML parsing and payment calculations for ICS Extranet."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final
from urllib.parse import urljoin

MONEY_PATTERN: Final = re.compile(r"-?[0-9][0-9 .\u00a0]*[,.][0-9]{2}")
LEDGER_HEADERS: Final = {"date", "libellé", "dépenses", "recettes", "solde"}


class IcsParseError(ValueError):
    """Raised when ICS returns an unsupported HTML structure."""


class PaymentStatus(StrEnum):
    """Status of one month in the current-quarter plan."""

    DETECTED = "detected"
    DUE = "due"
    MISSING = "missing"
    SETTLED = "settled"


@dataclass(frozen=True)
class Transaction:
    """One parsed account ledger operation."""

    operation_date: date
    label: str
    expense: Decimal | None
    receipt: Decimal | None
    balance: Decimal


@dataclass(frozen=True)
class MonthlyPayment:
    """One month in the estimated current-quarter payment plan."""

    month: str
    amount: Decimal
    status: PaymentStatus
    detected_receipts: Decimal

    @property
    def is_paid(self) -> bool:
        """Return whether ICS data considers the month settled."""
        return self.status in {PaymentStatus.DETECTED, PaymentStatus.SETTLED}


@dataclass(frozen=True)
class IcsSummary:
    """Normalized data exposed to Home Assistant entities."""

    balance_due: Decimal
    monthly_recommendation: Decimal
    account_period: str | None
    last_operation_date: date | None
    payments: tuple[MonthlyPayment, ...]
    transaction_count: int
    fetched_at: datetime = field(compare=False)


@dataclass
class _TableState:
    rows: list[list[str]]
    current_row: list[str] | None = None
    current_cell_parts: list[str] | None = None


class _TablesParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[_TableState] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._stack.append(_TableState(rows=[]))
            return
        if not self._stack:
            return

        table = self._stack[-1]
        if tag == "tr":
            table.current_row = []
        elif tag in {"td", "th"} and table.current_row is not None:
            table.current_cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1].current_cell_parts is not None:
            self._stack[-1].current_cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return

        table = self._stack[-1]
        if tag in {"td", "th"} and table.current_cell_parts is not None:
            assert table.current_row is not None
            table.current_row.append(_clean_text(" ".join(table.current_cell_parts)))
            table.current_cell_parts = None
        elif tag == "tr" and table.current_row is not None:
            if any(table.current_row):
                table.rows.append(table.current_row)
            table.current_row = None
            table.current_cell_parts = None
        elif tag == "table":
            self.tables.append(self._stack.pop().rows)


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return _clean_text(" ".join(self.text_parts))


def _parse_document(html: str) -> _DocumentParser:
    parser = _DocumentParser()
    parser.feed(html)
    return parser


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def is_authenticated_page(html: str) -> bool:
    """Return whether an ICS page includes the authenticated navigation marker."""
    return "déconnexion" in _parse_document(html).text.casefold()


def parse_money(value: str) -> Decimal | None:
    """Parse an ICS French-formatted monetary value."""
    match = MONEY_PATTERN.search(value.replace("€", ""))
    if match is None:
        return None

    normalized = match.group(0).replace("\u00a0", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_accounting_overview(html: str, page_url: str) -> tuple[Decimal, str]:
    """Extract the due balance and unique account-ledger URL."""
    document = _parse_document(html)
    balance_match = re.search(
        r"VOUS\s+DEVEZ\s+(-?[0-9][0-9 .\u00a0]*[,.][0-9]{2})\s*€",
        document.text,
        flags=re.IGNORECASE,
    )
    if balance_match is None or (amount := parse_money(balance_match.group(1))) is None:
        raise IcsParseError("Unable to find the balance due in the ICS response")

    account_urls = list(
        dict.fromkeys(
            urljoin(page_url, href)
            for href in document.links
            if "comptabilite-syndic-" in href and "#" not in href
        )
    )
    if len(account_urls) != 1:
        raise IcsParseError(
            f"Expected one ICS account ledger, found {len(account_urls)}"
        )
    return max(amount, Decimal("0.00")), account_urls[0]


def parse_transactions(html: str) -> tuple[tuple[Transaction, ...], str | None]:
    """Parse the personal ledger table and ignore building-wide expense tables."""
    parser = _TablesParser()
    parser.feed(html)
    ledger = next(
        (
            table
            for table in parser.tables
            if table
            and len(table[0]) >= 5
            and LEDGER_HEADERS.issubset({cell.casefold() for cell in table[0]})
        ),
        None,
    )
    if ledger is None:
        raise IcsParseError("Unable to find the ICS account ledger table")

    period: str | None = None
    transactions: list[Transaction] = []
    for row in ledger[1:]:
        row_text = _clean_text(" ".join(row))
        if period is None and row_text.casefold().startswith("exercice du"):
            period = row_text
        if len(row) < 5:
            continue
        try:
            operation_date = datetime.strptime(row[0], "%d/%m/%Y").date()
        except ValueError:
            continue
        if (balance := parse_money(row[4])) is None:
            continue
        transactions.append(
            Transaction(
                operation_date=operation_date,
                label=row[1],
                expense=parse_money(row[2]),
                receipt=parse_money(row[3]),
                balance=balance,
            )
        )
    return tuple(transactions), period


def build_summary(
    *,
    accounting_html: str,
    accounting_url: str,
    ledger_html: str,
    today: date,
    fetched_at: datetime,
) -> IcsSummary:
    """Build the normalized integration state from two authenticated pages."""
    balance_due, _ = parse_accounting_overview(accounting_html, accounting_url)
    transactions, account_period = parse_transactions(ledger_html)
    payments = build_monthly_plan(balance_due, transactions, today)
    recommendation = next(
        (payment.amount for payment in payments if payment.status is PaymentStatus.DUE),
        Decimal("0.00"),
    )
    return IcsSummary(
        balance_due=balance_due,
        monthly_recommendation=recommendation,
        account_period=account_period,
        last_operation_date=(transactions[-1].operation_date if transactions else None),
        payments=payments,
        transaction_count=len(transactions),
        fetched_at=fetched_at,
    )


def build_monthly_plan(
    balance_due: Decimal, transactions: Sequence[Transaction], today: date
) -> tuple[MonthlyPayment, ...]:
    """Estimate the current-quarter plan from detected bank transfers."""
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    months = [date(today.year, quarter_start_month + offset, 1) for offset in range(3)]
    receipts_by_month = {month.month: Decimal("0.00") for month in months}

    for transaction in transactions:
        if (
            transaction.operation_date.year == today.year
            and transaction.operation_date.month in receipts_by_month
            and transaction.receipt is not None
            and "votre virement" in transaction.label.casefold()
        ):
            receipts_by_month[transaction.operation_date.month] += transaction.receipt

    unpaid_months = [
        month
        for month in months
        if month.month >= today.month and receipts_by_month[month.month] == 0
    ]
    amount_by_month = dict(
        zip(unpaid_months, _split_money(balance_due, len(unpaid_months)), strict=True)
    )

    result: list[MonthlyPayment] = []
    for month in months:
        detected = receipts_by_month[month.month].quantize(Decimal("0.01"))
        if detected > 0:
            amount = detected
            status = PaymentStatus.DETECTED
        elif month in amount_by_month:
            amount = amount_by_month[month]
            status = PaymentStatus.DUE
        elif month.month < today.month:
            amount = Decimal("0.00")
            status = PaymentStatus.MISSING
        else:
            amount = Decimal("0.00")
            status = PaymentStatus.SETTLED
        result.append(
            MonthlyPayment(
                month=month.isoformat()[:7],
                amount=amount,
                status=status,
                detected_receipts=detected,
            )
        )
    return tuple(result)


def _split_money(amount: Decimal, count: int) -> tuple[Decimal, ...]:
    if count <= 0 or amount <= 0:
        return ()
    total_cents = int((amount * 100).to_integral_value())
    base_cents, remainder = divmod(total_cents, count)
    values = [Decimal(base_cents) / 100 for _ in range(count)]
    for index in range(count - remainder, count):
        if remainder:
            values[index] += Decimal("0.01")
    return tuple(value.quantize(Decimal("0.01")) for value in values)
