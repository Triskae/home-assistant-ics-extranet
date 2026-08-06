#!/usr/bin/env python3
"""POC manuel pour lire le solde et l'extrait de compte ICS."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import ssl
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

BASE_URL: Final = "https://extranet2.ics.fr/V5/"
LOGIN_URL: Final = "https://extranet2.ics.fr/login_externe.php"
USER_AGENT: Final = "ICS-Extranet-Home-Assistant-POC/0.6.0"
MONEY_PATTERN: Final = re.compile(r"-?[0-9][0-9 .\u00a0]*[,.][0-9]{2}")
PAYMENT_MODE_MONTHLY: Final = "monthly"
PAYMENT_MODE_QUARTERLY: Final = "quarterly"
PAYMENT_KEYWORDS: Final = ("virement", "prelevement", "reglement", "paiement")
EXCLUDED_RECEIPT_KEYWORDS: Final = (
    "remboursement",
    "rbt",
    "regularisation",
    "solde charges",
    "avoir",
    "reception fonds",
)


class IcsError(RuntimeError):
    """Erreur lisible liée à l'extranet ICS."""


class ReceiptClassification(StrEnum):
    """Niveau de confiance attribué à une recette ICS."""

    CONFIRMED_PAYMENT = "paiement_confirmé"
    EXCLUDED_CREDIT = "crédit_exclu"
    AMBIGUOUS_RECEIPT = "recette_à_vérifier"


@dataclass(frozen=True)
class Transaction:
    operation_date: date
    label: str
    expense: Decimal | None
    receipt: Decimal | None
    balance: Decimal


@dataclass(frozen=True)
class MonthlyPayment:
    month: str
    amount: Decimal
    status: str
    detected_receipts: Decimal


@dataclass(frozen=True)
class ReceiptDetection:
    operation_date: date
    label: str
    amount: Decimal
    classification: ReceiptClassification
    reason: str


@dataclass(frozen=True)
class IcsSummary:
    fetched_at: str
    balance_due: Decimal
    monthly_recommendation: Decimal
    monthly_payments: bool
    account_period: str | None
    last_operation_date: str | None
    payments: tuple[MonthlyPayment, ...]
    receipt_detections: tuple[ReceiptDetection, ...]
    transactions: tuple[Transaction, ...]


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
            completed = self._stack.pop()
            self.tables.append(completed.rows)


class _LinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)

    @property
    def text(self) -> str:
        return _clean_text(" ".join(self.parts))


class IcsClient:
    def __init__(self, group: str, timeout_seconds: float = 20.0) -> None:
        self._group = group.strip().lower()
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self._group):
            raise IcsError("Le groupe ICS contient des caractères invalides.")
        self._timeout_seconds = timeout_seconds
        self._opener = build_opener(
            HTTPSHandler(context=_create_ssl_context()),
            HTTPCookieProcessor(CookieJar()),
        )

    def login(self, username: str, password: str) -> None:
        # Initialise la session et récupère les éventuels cookies publics.
        self._get(urljoin(BASE_URL, f"connexion.php?groupe={self._group}"))

        payload = urlencode(
            {"login": username, "mdp": password, "groupe": self._group}
        ).encode("utf-8")
        request = Request(
            LOGIN_URL,
            data=payload,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": urljoin(BASE_URL, f"connexion.php?groupe={self._group}"),
            },
            method="POST",
        )
        html, final_url = self._open(request)
        text = _extract_text(html).casefold()
        if "déconnexion" not in text or "connexion :" in text:
            raise IcsError(
                "Connexion refusée par ICS. Vérifie l'identifiant et le mot de passe."
            )
        if "connexion" in final_url and "initialisation" not in final_url:
            raise IcsError("ICS a renvoyé vers la page de connexion.")

    def fetch_summary(self, today: date, *, monthly_payments: bool) -> IcsSummary:
        accounting_html = self._get(urljoin(BASE_URL, "comptabilite.html"))
        balance_due = _extract_balance_due(accounting_html)
        account_url = _extract_account_url(accounting_html)
        account_html = self._get(account_url)
        transactions, account_period = _extract_transactions(account_html)
        receipt_detections = detect_receipts(transactions, today)
        if monthly_payments:
            payments = build_monthly_plan(
                balance_due,
                transactions,
                today,
                receipt_detections=receipt_detections,
            )
        else:
            payments = build_quarterly_plan(
                balance_due,
                transactions,
                today,
                receipt_detections=receipt_detections,
            )
        amounts_due = [
            payment.amount
            for payment in payments
            if payment.status in {"à payer", "aucun paiement détecté"}
        ]
        recommendation = amounts_due[0] if amounts_due else Decimal("0.00")

        return IcsSummary(
            fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            balance_due=balance_due,
            monthly_recommendation=recommendation,
            monthly_payments=monthly_payments,
            account_period=account_period,
            last_operation_date=(
                transactions[-1].operation_date.isoformat() if transactions else None
            ),
            payments=payments,
            receipt_detections=receipt_detections,
            transactions=transactions,
        )

    def _get(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        html, _ = self._open(request)
        return html

    def _open(self, request: Request) -> tuple[str, str]:
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace"), response.geturl()
        except HTTPError as error:
            raise IcsError(f"ICS a répondu avec l'erreur HTTP {error.code}.") from error
        except URLError as error:
            raise IcsError(f"Impossible de joindre ICS : {error.reason}") from error


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _create_ssl_context() -> ssl.SSLContext:
    """Crée un contexte vérifié, y compris avec Python.org sur macOS."""
    configured_path = os.getenv("SSL_CERT_FILE")
    candidates = [
        configured_path,
        "/etc/ssl/cert.pem",
        "/private/etc/ssl/cert.pem",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def _extract_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return parser.text


def parse_money(value: str) -> Decimal | None:
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


def _extract_balance_due(html: str) -> Decimal:
    text = _extract_text(html)
    match = re.search(
        r"VOUS\s+DEVEZ\s+(-?[0-9][0-9 .\u00a0]*[,.][0-9]{2})\s*€",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise IcsError("Le montant « Vous devez » est introuvable.")
    amount = parse_money(match.group(1))
    if amount is None:
        raise IcsError("Le montant dû retourné par ICS est invalide.")
    return max(amount, Decimal("0.00"))


def _extract_account_url(html: str) -> str:
    parser = _LinksParser()
    parser.feed(html)
    matches = [
        urljoin(BASE_URL, href)
        for href in parser.links
        if "comptabilite-syndic-" in href and "#" not in href
    ]
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) != 1:
        raise IcsError(
            "Impossible d'identifier un extrait de compte ICS unique "
            f"({len(unique_matches)} trouvé(s))."
        )
    return unique_matches[0]


def _extract_transactions(html: str) -> tuple[tuple[Transaction, ...], str | None]:
    parser = _TablesParser()
    parser.feed(html)
    ledger = next(
        (
            table
            for table in parser.tables
            if table
            and len(table[0]) >= 5
            and {"date", "libellé", "dépenses", "recettes", "solde"}.issubset(
                {cell.casefold() for cell in table[0]}
            )
        ),
        None,
    )
    if ledger is None:
        raise IcsError("Le tableau de l'extrait de compte est introuvable.")

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
        balance = parse_money(row[4])
        if balance is None:
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


def build_monthly_plan(
    balance_due: Decimal,
    transactions: Sequence[Transaction],
    today: date,
    *,
    receipt_detections: Sequence[ReceiptDetection] | None = None,
) -> tuple[MonthlyPayment, ...]:
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    months = [date(today.year, quarter_start_month + offset, 1) for offset in range(3)]
    receipts_by_month = {month.month: Decimal("0.00") for month in months}

    detections = (
        detect_receipts(transactions, today)
        if receipt_detections is None
        else receipt_detections
    )
    for detection in detections:
        if detection.classification is ReceiptClassification.CONFIRMED_PAYMENT:
            receipts_by_month[detection.operation_date.month] += detection.amount

    expected_amounts = _expected_monthly_amounts(transactions, today)
    if len(expected_amounts) == len(months):
        amount_by_month = dict(zip(months, expected_amounts, strict=True))
    else:
        unpaid_months = [
            month
            for month in months
            if month.month >= today.month and receipts_by_month[month.month] == 0
        ]
        split_amounts = _split_money(balance_due, len(unpaid_months))
        amount_by_month = dict(zip(unpaid_months, split_amounts, strict=True))

    result: list[MonthlyPayment] = []
    for month in months:
        detected = receipts_by_month[month.month].quantize(Decimal("0.01"))
        if detected > 0:
            amount = detected
            status = "payé (détecté ICS)"
        elif month in amount_by_month:
            amount = amount_by_month[month]
            status = (
                "aucun paiement détecté" if month.month < today.month else "à payer"
            )
        else:
            amount = Decimal("0.00")
            status = "soldé"
        result.append(
            MonthlyPayment(
                month=month.strftime("%Y-%m"),
                amount=amount,
                status=status,
                detected_receipts=detected,
            )
        )
    return tuple(result)


def build_quarterly_plan(
    balance_due: Decimal,
    transactions: Sequence[Transaction],
    today: date,
    *,
    receipt_detections: Sequence[ReceiptDetection] | None = None,
) -> tuple[MonthlyPayment, ...]:
    """Afficher le montant restant une seule fois lorsqu'il n'est pas mensualisé."""
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    months = [date(today.year, quarter_start_month + offset, 1) for offset in range(3)]
    charge_call = _find_quarter_charge_call(transactions, today)
    due_month = (
        charge_call.operation_date.month if charge_call is not None else months[0].month
    )
    detections = (
        detect_receipts(transactions, today)
        if receipt_detections is None
        else receipt_detections
    )
    detected = sum(
        (
            detection.amount
            for detection in detections
            if detection.classification is ReceiptClassification.CONFIRMED_PAYMENT
        ),
        start=Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    result: list[MonthlyPayment] = []
    for month in months:
        if month.month != due_month:
            amount = Decimal("0.00")
            status = "non applicable"
            month_detected = Decimal("0.00")
        elif balance_due <= 0 and detected > 0:
            amount = detected
            status = "payé (détecté ICS)"
            month_detected = detected
        elif balance_due <= 0:
            amount = Decimal("0.00")
            status = "soldé"
            month_detected = Decimal("0.00")
        else:
            amount = balance_due.quantize(Decimal("0.01"))
            status = "à payer"
            month_detected = detected
        result.append(
            MonthlyPayment(
                month=month.strftime("%Y-%m"),
                amount=amount,
                status=status,
                detected_receipts=month_detected,
            )
        )
    return tuple(result)


def detect_receipts(
    transactions: Sequence[Transaction], today: date
) -> tuple[ReceiptDetection, ...]:
    """Classer les recettes du trimestre sans dépendre d'un libellé exact."""
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    quarter_months = range(quarter_start_month, quarter_start_month + 3)
    expected_amounts = _expected_monthly_amounts(transactions, today)
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
            reason = f"libellé exclu : {keyword}"
        elif keyword := _matching_keyword(normalized_label, PAYMENT_KEYWORDS):
            classification = ReceiptClassification.CONFIRMED_PAYMENT
            reason = f"mot-clé de paiement : {keyword}"
        elif any(
            abs(transaction.receipt - expected) <= Decimal("0.01")
            for expected in expected_amounts
        ):
            classification = ReceiptClassification.AMBIGUOUS_RECEIPT
            reason = "montant compatible avec une mensualité, libellé inconnu"
        else:
            classification = ReceiptClassification.AMBIGUOUS_RECEIPT
            reason = "recette positive avec un libellé inconnu"

        detections.append(
            ReceiptDetection(
                operation_date=transaction.operation_date,
                label=transaction.label,
                amount=transaction.receipt,
                classification=classification,
                reason=reason,
            )
        )
    return tuple(detections)


def _expected_monthly_amounts(
    transactions: Sequence[Transaction], today: date
) -> tuple[Decimal, ...]:
    charge_call = _find_quarter_charge_call(transactions, today)
    if charge_call is None:
        return ()
    end_of_day_balance = next(
        (
            transaction.balance
            for transaction in reversed(transactions)
            if transaction.operation_date == charge_call.operation_date
        ),
        charge_call.balance,
    )
    return _split_money(max(end_of_day_balance, Decimal("0.00")), 3)


def _find_quarter_charge_call(
    transactions: Sequence[Transaction], today: date
) -> Transaction | None:
    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
    return next(
        (
            transaction
            for transaction in reversed(transactions)
            if transaction.operation_date.year == today.year
            and quarter_start_month
            <= transaction.operation_date.month
            < quarter_start_month + 3
            and "appel trimestriel" in _normalize_label(transaction.label)
        ),
        None,
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


def _split_money(amount: Decimal, count: int) -> tuple[Decimal, ...]:
    if count <= 0 or amount <= 0:
        return ()
    total_cents = int((amount * 100).to_integral_value())
    base_cents, remainder = divmod(total_cents, count)
    values = [Decimal(base_cents) / 100 for _ in range(count)]
    # Place les centimes restants sur les dernières mensualités.
    for index in range(count - remainder, count):
        if remainder:
            values[index] += Decimal("0.01")
    return tuple(value.quantize(Decimal("0.01")) for value in values)


def _json_default(value: object) -> str:
    if isinstance(value, (Decimal, date)):
        return str(value)
    raise TypeError(f"Type JSON non pris en charge : {type(value).__name__}")


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",") + " €"


def _print_summary(summary: IcsSummary) -> None:
    print("=== Résumé de votre compte ICS ===")
    print(f"Solde à payer : {_format_money(summary.balance_due)}")
    mode = "mensualisé" if summary.monthly_payments else "non mensualisé"
    print(f"Mode de paiement : {mode}")
    print(f"Paiement conseillé : {_format_money(summary.monthly_recommendation)}")
    if summary.account_period:
        print(summary.account_period)
    print()
    print("Plan du trimestre :")
    for payment in summary.payments:
        print(
            f"  {payment.month}  {_format_money(payment.amount):>12}  {payment.status}"
        )
    print()
    print("Analyse des recettes du trimestre :")
    if not summary.receipt_detections:
        print("  aucune recette positive détectée")
    for detection in summary.receipt_detections:
        print(
            f"  {detection.operation_date.isoformat()}  "
            f"{_format_money(detection.amount):>12}  "
            f"{detection.classification.value} — {detection.reason}"
        )
        print(f"    libellé ICS : {detection.label}")
    print()
    print(f"Dernière opération ICS : {summary.last_operation_date or 'inconnue'}")


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lit manuellement les charges sur un extranet ICS.",
        epilog=(
            "Le groupe est la valeur placée après 'groupe=' dans l'URL ICS. "
            "Vous pouvez aussi fournir directement l'URL complète."
        ),
    )
    parser.add_argument(
        "--group",
        default=os.getenv("ICS_GROUP"),
        help="nom du groupe ICS ou URL de connexion complète (ou ICS_GROUP)",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("ICS_USERNAME"),
        help="identifiant ICS (ou variable ICS_USERNAME)",
    )
    parser.add_argument(
        "--payment-mode",
        choices=(PAYMENT_MODE_MONTHLY, PAYMENT_MODE_QUARTERLY),
        default=os.getenv("ICS_PAYMENT_MODE"),
        help="mode de paiement : monthly ou quarterly",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="affiche un JSON exploitable au lieu du résumé",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="date de calcul au format AAAA-MM-JJ (défaut : aujourd'hui)",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = ()) -> int:
    args = _parse_args(argv)
    if not args.json:
        _print_welcome()

    try:
        group = _normalize_group_input(args.group or _ask_group())
    except IcsError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 2

    username = args.username or _ask_username()
    password = os.getenv("ICS_PASSWORD") or _ask_password()
    monthly_payments = _ask_monthly_payments(args.payment_mode)
    if not group or not username or not password:
        print("Groupe, identifiant et mot de passe obligatoires.", file=sys.stderr)
        return 2

    if not args.json:
        mode = "3 mensualités" if monthly_payments else "paiement trimestriel"
        print()
        print("Connexion à ICS en cours…")
        print(f"  Groupe détecté : {group}")
        print(f"  Mode choisi : {mode}")
        print()

    try:
        client = IcsClient(group)
        client.login(username, password)
        summary = client.fetch_summary(
            args.date,
            monthly_payments=monthly_payments,
        )
    except IcsError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                asdict(summary),
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
        )
    else:
        _print_summary(summary)
    return 0


def _print_welcome() -> None:
    print("=== Assistant ICS Extranet ===")
    print("Ce script se connecte à votre espace ICS et calcule les charges à payer.")


def _ask_group() -> str:
    print()
    print("[1/4] Où trouver le groupe ICS ?")
    print("Il se trouve dans votre adresse de connexion, juste après « groupe= ».")
    print("Exemple : connexion.php?groupe=monagence  →  groupe : monagence")
    print("Vous pouvez aussi coller directement l’adresse complète.")
    return input("Groupe ou adresse de connexion ICS : ").strip()


def _normalize_group_input(value: str) -> str:
    candidate = value.strip()
    parsed = urlparse(candidate)
    groups = parse_qs(parsed.query).get("groupe", [])
    if groups and groups[0].strip():
        candidate = groups[0]
    elif parsed.scheme or parsed.netloc:
        raise IcsError("L’adresse fournie ne contient pas de valeur après « groupe= ».")
    return candidate.strip().lower()


def _ask_username() -> str:
    print()
    print("[2/4] Compte ICS")
    print("Utilisez l’identifiant saisi habituellement sur la page de connexion ICS.")
    return input("Adresse email ou identifiant ICS : ").strip()


def _ask_password() -> str:
    print()
    print("[3/4] Mot de passe ICS")
    print("La saisie reste masquée et le mot de passe n’est pas enregistré.")
    return getpass.getpass("Mot de passe ICS : ")


def _ask_monthly_payments(configured_mode: str | None) -> bool:
    if configured_mode == PAYMENT_MODE_MONTHLY:
        return True
    if configured_mode == PAYMENT_MODE_QUARTERLY:
        return False

    print()
    print("[4/4] Mode de paiement")
    print("Oui : l’appel trimestriel est réparti en trois mensualités.")
    print("Non : le montant restant est affiché en une seule fois.")
    while True:
        answer = input("Payez-vous vos charges en 3 mensualités ? [o/n] : ")
        answer = answer.strip().casefold()
        if answer in {"o", "oui", "y", "yes"}:
            return True
        if answer in {"n", "non", "no"}:
            return False
        print("Répondez par « o » pour oui ou « n » pour non.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
