"""Pure HTML parsing and payment calculations for ICS Extranet."""

from __future__ import annotations

import re
import unicodedata
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
PAYMENT_KEYWORDS: Final = ("virement", "prelevement", "reglement", "paiement")
EXCLUDED_RECEIPT_KEYWORDS: Final = (
    "remboursement",
    "rbt",
    "regularisation",
    "solde charges",
    "avoir",
    "reception fonds",
)


class IcsParseError(ValueError):
    """Raised when ICS returns an unsupported HTML structure."""


class PaymentStatus(StrEnum):
    """Status of one month in the current-quarter plan."""

    DETECTED = "detected"
    DUE = "due"
    MISSING = "missing"
    SETTLED = "settled"


class ReceiptClassification(StrEnum):
    """Confidence level assigned to one positive ICS receipt."""

    CONFIRMED_PAYMENT = "confirmed_payment"
    EXCLUDED_CREDIT = "excluded_credit"
    AMBIGUOUS_RECEIPT = "ambiguous_receipt"


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
class ReceiptDetection:
    """Privacy-safe classification of one positive ledger receipt."""

    operation_date: date
    amount: Decimal
    classification: ReceiptClassification
    reason: str


@dataclass(frozen=True)
class IcsSummary:
    """Normalized data exposed to Home Assistant entities."""

    balance_due: Decimal
    monthly_recommendation: Decimal
    account_period: str | None
    charge_call_date: date | None
    monthly_payments: bool
    last_operation_date: date | None
    payments: tuple[MonthlyPayment, ...]
    receipt_detections: tuple[ReceiptDetection, ...]
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
    monthly_payments: bool = True,
) -> IcsSummary:
    """Build the normalized integration state from two authenticated pages."""
    balance_due, _ = parse_accounting_overview(accounting_html, accounting_url)
    transactions, account_period = parse_transactions(ledger_html)
    charge_call = find_quarter_charge_call(transactions, today)
    receipt_detections = detect_receipts(
        transactions,
        today,
        charge_call=charge_call,
    )
    payments = build_payment_plan(
        balance_due,
        transactions,
        today,
        monthly_payments=monthly_payments,
        charge_call=charge_call,
        receipt_detections=receipt_detections,
    )
    recommendation = next(
        (
            payment.amount
            for payment in payments
            if payment.status in {PaymentStatus.DUE, PaymentStatus.MISSING}
        ),
        Decimal("0.00"),
    )
    return IcsSummary(
        balance_due=balance_due,
        monthly_recommendation=recommendation,
        account_period=account_period,
        charge_call_date=(
            charge_call.operation_date if charge_call is not None else None
        ),
        monthly_payments=monthly_payments,
        last_operation_date=(transactions[-1].operation_date if transactions else None),
        payments=payments,
        receipt_detections=receipt_detections,
        transaction_count=len(transactions),
        fetched_at=fetched_at,
    )


def find_quarter_charge_call(
    transactions: Sequence[Transaction], today: date
) -> Transaction | None:
    """Return the current quarter's regular charge call, when available."""
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    quarter_months = range(quarter_start_month, quarter_start_month + 3)
    return next(
        (
            transaction
            for transaction in reversed(transactions)
            if transaction.operation_date.year == today.year
            and transaction.operation_date.month in quarter_months
            and "appel trimestriel" in _normalize_label(transaction.label)
        ),
        None,
    )


def build_payment_plan(
    balance_due: Decimal,
    transactions: Sequence[Transaction],
    today: date,
    *,
    monthly_payments: bool,
    charge_call: Transaction | None = None,
    receipt_detections: Sequence[ReceiptDetection] | None = None,
) -> tuple[MonthlyPayment, ...]:
    """Build a monthly or quarterly payment plan from the account ledger."""
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    months = [date(today.year, quarter_start_month + offset, 1) for offset in range(3)]
    receipts_by_month = {month.month: Decimal("0.00") for month in months}

    detections = (
        detect_receipts(transactions, today, charge_call=charge_call)
        if receipt_detections is None
        else receipt_detections
    )
    for detection in detections:
        if detection.classification is ReceiptClassification.CONFIRMED_PAYMENT:
            receipts_by_month[detection.operation_date.month] += detection.amount

    if not monthly_payments:
        return _build_quarterly_payment_plan(
            balance_due,
            months,
            receipts_by_month,
            charge_call,
        )

    scheduled_amounts = _monthly_scheduled_amounts(
        balance_due,
        transactions,
        months,
        today,
        charge_call,
        receipts_by_month,
    )
    result: list[MonthlyPayment] = []
    for month, scheduled_amount in zip(months, scheduled_amounts, strict=True):
        detected = receipts_by_month[month.month].quantize(Decimal("0.01"))
        if detected > 0:
            amount = detected
            status = PaymentStatus.DETECTED
        elif scheduled_amount > 0 and month.month < today.month:
            amount = scheduled_amount
            status = PaymentStatus.MISSING
        elif scheduled_amount > 0:
            amount = scheduled_amount
            status = PaymentStatus.DUE
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


def detect_receipts(
    transactions: Sequence[Transaction],
    today: date,
    *,
    charge_call: Transaction | None = None,
) -> tuple[ReceiptDetection, ...]:
    """Classify positive receipts without depending on one exact ICS label."""
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    quarter_months = range(quarter_start_month, quarter_start_month + 3)
    effective_charge_call = charge_call or find_quarter_charge_call(transactions, today)
    expected_amounts = _expected_monthly_amounts(
        transactions,
        effective_charge_call,
    )
    detections: list[ReceiptDetection] = []

    for transaction in transactions:
        if (
            transaction.operation_date.year != today.year
            or transaction.operation_date.month not in quarter_months
            or transaction.receipt is None
            or transaction.receipt <= 0
        ):
            continue

        normalized_label = _normalize_label(transaction.label)
        if keyword := _matching_keyword(normalized_label, EXCLUDED_RECEIPT_KEYWORDS):
            classification = ReceiptClassification.EXCLUDED_CREDIT
            reason = f"excluded_keyword:{keyword}"
        elif keyword := _matching_keyword(normalized_label, PAYMENT_KEYWORDS):
            classification = ReceiptClassification.CONFIRMED_PAYMENT
            reason = f"payment_keyword:{keyword}"
        elif any(
            abs(transaction.receipt - expected) <= Decimal("0.01")
            for expected in expected_amounts
        ):
            classification = ReceiptClassification.AMBIGUOUS_RECEIPT
            reason = "amount_matches_installment"
        else:
            classification = ReceiptClassification.AMBIGUOUS_RECEIPT
            reason = "unknown_positive_receipt"

        detections.append(
            ReceiptDetection(
                operation_date=transaction.operation_date,
                amount=transaction.receipt,
                classification=classification,
                reason=reason,
            )
        )
    return tuple(detections)


def _expected_monthly_amounts(
    transactions: Sequence[Transaction],
    charge_call: Transaction | None,
) -> tuple[Decimal, ...]:
    if charge_call is None:
        return ()
    charge_day_balance = _charge_day_balance(transactions, charge_call)
    return _split_money(max(charge_day_balance, Decimal("0.00")), 3)


def _charge_day_balance(
    transactions: Sequence[Transaction], charge_call: Transaction
) -> Decimal:
    return next(
        (
            transaction.balance
            for transaction in reversed(transactions)
            if transaction.operation_date == charge_call.operation_date
        ),
        charge_call.balance,
    )


def _normalize_label(label: str) -> str:
    decomposed = unicodedata.normalize("NFKD", label.casefold())
    return " ".join(
        "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        ).split()
    )


def _matching_keyword(label: str, keywords: Sequence[str]) -> str | None:
    return next(
        (
            keyword
            for keyword in keywords
            if re.search(rf"\b{re.escape(keyword)}\b", label)
        ),
        None,
    )


def _monthly_scheduled_amounts(
    balance_due: Decimal,
    transactions: Sequence[Transaction],
    months: Sequence[date],
    today: date,
    charge_call: Transaction | None,
    receipts_by_month: dict[int, Decimal],
) -> tuple[Decimal, ...]:
    if charge_call is not None:
        charge_day_balance = _charge_day_balance(transactions, charge_call)
        if charge_day_balance <= 0:
            return tuple(Decimal("0.00") for _ in months)
        return _split_money(charge_day_balance, 3)

    unpaid_months = [
        month
        for month in months
        if month.month >= today.month and receipts_by_month[month.month] == 0
    ]
    amount_by_month = dict(
        zip(unpaid_months, _split_money(balance_due, len(unpaid_months)), strict=True)
    )
    return tuple(amount_by_month.get(month, Decimal("0.00")) for month in months)


def _build_quarterly_payment_plan(
    balance_due: Decimal,
    months: Sequence[date],
    receipts_by_month: dict[int, Decimal],
    charge_call: Transaction | None,
) -> tuple[MonthlyPayment, ...]:
    due_month = (
        charge_call.operation_date.month if charge_call is not None else months[0].month
    )
    total_detected = sum(receipts_by_month.values(), start=Decimal("0.00")).quantize(
        Decimal("0.01")
    )
    is_settled = balance_due <= 0
    result: list[MonthlyPayment] = []
    for month in months:
        if month.month != due_month:
            amount = Decimal("0.00")
            status = PaymentStatus.SETTLED
            detected = Decimal("0.00")
        elif is_settled and total_detected > 0:
            amount = total_detected
            status = PaymentStatus.DETECTED
            detected = total_detected
        elif is_settled:
            amount = Decimal("0.00")
            status = PaymentStatus.SETTLED
            detected = Decimal("0.00")
        else:
            amount = balance_due.quantize(Decimal("0.01"))
            status = PaymentStatus.DUE
            detected = total_detected
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
