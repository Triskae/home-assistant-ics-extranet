import importlib.util
import sys
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

PARSER_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ics_extranet" / "parser.py"
)
SPEC = importlib.util.spec_from_file_location("ics_extranet_parser", PARSER_PATH)
assert SPEC is not None and SPEC.loader is not None
parser = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parser
SPEC.loader.exec_module(parser)


class IcsParserTest(unittest.TestCase):
    def test_overview_extracts_balance_and_account_url(self) -> None:
        html = """
        <p>VOUS DEVEZ</p><p>420,15€</p>
        <a href="comptabilite-syndic-token.html">VOIR L'EXTRAIT DE COMPTE</a>
        <a href="comptabilite-syndic-token.html#etat_depense">Dépenses</a>
        """

        balance, url = parser.parse_accounting_overview(
            html, "https://extranet2.ics.fr/V5/comptabilite.html"
        )

        self.assertEqual(balance, Decimal("420.15"))
        self.assertEqual(
            url,
            "https://extranet2.ics.fr/V5/comptabilite-syndic-token.html",
        )

    def test_summary_detects_payment_and_splits_quarter_charge(self) -> None:
        overview = """
        <p>VOUS DEVEZ</p><p>400,01€</p>
        <a href="comptabilite-syndic-token.html">Extrait</a>
        """
        ledger = """
        <table>
          <tr>
            <th>Date</th><th>Libellé</th><th>Dépenses</th>
            <th>Recettes</th><th>Solde</th>
          </tr>
          <tr>
            <td></td><td>Exercice du 01/01/2026 au 31/12/2026</td>
            <td></td><td></td><td></td>
          </tr>
          <tr>
            <td>01/07/2026</td><td>Appel trimestriel</td>
            <td>600,00</td><td></td><td>600,00</td>
          </tr>
          <tr>
            <td>20/07/2026</td><td>Votre virement du 15/07/2026</td>
            <td></td><td>199,99</td><td>400,01</td>
          </tr>
        </table>
        """

        summary = parser.build_summary(
            accounting_html=overview,
            accounting_url="https://extranet2.ics.fr/V5/comptabilite.html",
            ledger_html=ledger,
            today=date(2026, 8, 3),
            fetched_at=datetime(2026, 8, 3, tzinfo=UTC),
        )

        self.assertEqual(summary.balance_due, Decimal("400.01"))
        self.assertEqual(summary.monthly_recommendation, Decimal("200.00"))
        self.assertEqual(summary.charge_call_date, date(2026, 7, 1))
        self.assertTrue(summary.monthly_payments)
        self.assertTrue(summary.payments[0].is_paid)
        self.assertEqual(len(summary.receipt_detections), 1)
        self.assertEqual(
            summary.receipt_detections[0].classification,
            parser.ReceiptClassification.CONFIRMED_PAYMENT,
        )
        self.assertEqual(summary.payments[1].amount, Decimal("200.00"))
        self.assertEqual(summary.payments[2].amount, Decimal("200.00"))
        self.assertEqual(summary.transaction_count, 2)

        quarterly_summary = parser.build_summary(
            accounting_html=overview,
            accounting_url="https://extranet2.ics.fr/V5/comptabilite.html",
            ledger_html=ledger,
            today=date(2026, 8, 3),
            fetched_at=datetime(2026, 8, 3, tzinfo=UTC),
            monthly_payments=False,
        )

        self.assertEqual(
            quarterly_summary.monthly_recommendation,
            Decimal("400.01"),
        )
        self.assertFalse(quarterly_summary.monthly_payments)

    def test_monthly_plan_stays_anchored_to_quarter_charge_call(self) -> None:
        transactions = (
            parser.Transaction(
                operation_date=date(2026, 7, 1),
                label="3e échéance appel trimestriel",
                expense=Decimal("600.00"),
                receipt=None,
                balance=Decimal("600.00"),
            ),
            parser.Transaction(
                operation_date=date(2026, 7, 20),
                label="Votre virement",
                expense=None,
                receipt=Decimal("200.00"),
                balance=Decimal("400.00"),
            ),
            parser.Transaction(
                operation_date=date(2026, 7, 25),
                label="Ajustement ultérieur",
                expense=Decimal("100.00"),
                receipt=None,
                balance=Decimal("500.00"),
            ),
        )
        charge_call = parser.find_quarter_charge_call(
            transactions,
            date(2026, 8, 3),
        )

        plan = parser.build_payment_plan(
            Decimal("500.00"),
            transactions,
            date(2026, 8, 3),
            monthly_payments=True,
            charge_call=charge_call,
        )

        self.assertEqual([payment.amount for payment in plan], [Decimal("200.00")] * 3)
        self.assertEqual(plan[0].status, parser.PaymentStatus.DETECTED)
        self.assertEqual(plan[1].status, parser.PaymentStatus.DUE)

    def test_quarterly_mode_keeps_balance_undivided(self) -> None:
        transactions = (
            parser.Transaction(
                operation_date=date(2026, 7, 1),
                label="3e échéance appel trimestriel",
                expense=Decimal("600.00"),
                receipt=None,
                balance=Decimal("600.00"),
            ),
        )

        plan = parser.build_payment_plan(
            Decimal("600.00"),
            transactions,
            date(2026, 8, 3),
            monthly_payments=False,
            charge_call=transactions[0],
        )

        self.assertEqual(plan[0].amount, Decimal("600.00"))
        self.assertEqual(plan[0].status, parser.PaymentStatus.DUE)
        self.assertEqual(plan[1].amount, Decimal("0.00"))
        self.assertTrue(plan[1].is_paid)

    def test_receipt_classifier_is_tolerant_but_conservative(self) -> None:
        transactions = (
            parser.Transaction(
                operation_date=date(2026, 7, 1),
                label="Appel trimestriel",
                expense=Decimal("600.00"),
                receipt=None,
                balance=Decimal("600.00"),
            ),
            parser.Transaction(
                operation_date=date(2026, 7, 15),
                label="Prélèvement mensuel",
                expense=None,
                receipt=Decimal("200.00"),
                balance=Decimal("400.00"),
            ),
            parser.Transaction(
                operation_date=date(2026, 8, 10),
                label="Rbt facture",
                expense=None,
                receipt=Decimal("50.00"),
                balance=Decimal("350.00"),
            ),
            parser.Transaction(
                operation_date=date(2026, 8, 15),
                label="Crédit sans libellé connu",
                expense=None,
                receipt=Decimal("200.00"),
                balance=Decimal("150.00"),
            ),
        )

        detections = parser.detect_receipts(transactions, date(2026, 8, 20))

        self.assertEqual(
            [detection.classification for detection in detections],
            [
                parser.ReceiptClassification.CONFIRMED_PAYMENT,
                parser.ReceiptClassification.EXCLUDED_CREDIT,
                parser.ReceiptClassification.AMBIGUOUS_RECEIPT,
            ],
        )
        plan = parser.build_payment_plan(
            Decimal("150.00"),
            transactions,
            date(2026, 8, 20),
            monthly_payments=True,
            charge_call=transactions[0],
            receipt_detections=detections,
        )
        self.assertEqual(plan[0].status, parser.PaymentStatus.DETECTED)
        self.assertEqual(plan[1].status, parser.PaymentStatus.DUE)

    def test_no_personal_data_is_required_by_parser(self) -> None:
        self.assertEqual(parser.parse_money("1 234,56 €"), Decimal("1234.56"))


if __name__ == "__main__":
    unittest.main()
