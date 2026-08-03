import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from ics_poc import (
    ReceiptClassification,
    Transaction,
    _ask_monthly_payments,
    _extract_transactions,
    build_monthly_plan,
    build_quarterly_plan,
    detect_receipts,
    parse_money,
)


class IcsPocTest(unittest.TestCase):
    def test_parse_french_money(self) -> None:
        self.assertEqual(parse_money("1 227,24€"), Decimal("1227.24"))
        self.assertEqual(parse_money("-34,53"), Decimal("-34.53"))
        self.assertEqual(parse_money("648.08"), Decimal("648.08"))

    def test_extract_ledger(self) -> None:
        html = """
        <table class="grid">
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
            <td>20/07/2026</td><td>Votre virement</td>
            <td></td><td>200,00</td><td>400,00</td>
          </tr>
        </table>
        """

        transactions, period = _extract_transactions(html)

        self.assertEqual(period, "Exercice du 01/01/2026 au 31/12/2026")
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[-1].receipt, Decimal("200.00"))
        self.assertEqual(transactions[-1].balance, Decimal("400.00"))

    def test_monthly_plan_detects_payment_and_splits_balance(self) -> None:
        transactions = (
            Transaction(
                operation_date=date(2026, 7, 20),
                label="Votre virement du 13/07/2026",
                expense=None,
                receipt=Decimal("198.16"),
                balance=Decimal("396.33"),
            ),
        )

        plan = build_monthly_plan(Decimal("396.33"), transactions, date(2026, 8, 3))

        self.assertEqual(plan[0].status, "payé (détecté ICS)")
        self.assertEqual(plan[0].amount, Decimal("198.16"))
        self.assertEqual(plan[1].amount, Decimal("198.16"))
        self.assertEqual(plan[2].amount, Decimal("198.17"))
        self.assertEqual(sum(p.amount for p in plan[1:]), Decimal("396.33"))

    def test_detects_multiple_payment_wordings(self) -> None:
        transactions = (
            Transaction(
                operation_date=date(2026, 7, 10),
                label="Prélèvement mensuel",
                expense=None,
                receipt=Decimal("200.00"),
                balance=Decimal("400.00"),
            ),
            Transaction(
                operation_date=date(2026, 8, 10),
                label="Règlement copropriété",
                expense=None,
                receipt=Decimal("200.00"),
                balance=Decimal("200.00"),
            ),
        )

        detections = detect_receipts(transactions, date(2026, 8, 15))

        self.assertEqual(len(detections), 2)
        self.assertTrue(
            all(
                detection.classification is ReceiptClassification.CONFIRMED_PAYMENT
                for detection in detections
            )
        )

    def test_excludes_refund_and_flags_unknown_matching_amount(self) -> None:
        transactions = (
            Transaction(
                operation_date=date(2026, 7, 1),
                label="Appel trimestriel",
                expense=Decimal("600.00"),
                receipt=None,
                balance=Decimal("600.00"),
            ),
            Transaction(
                operation_date=date(2026, 7, 15),
                label="Rbt facture",
                expense=None,
                receipt=Decimal("50.00"),
                balance=Decimal("550.00"),
            ),
            Transaction(
                operation_date=date(2026, 8, 15),
                label="Crédit sans libellé connu",
                expense=None,
                receipt=Decimal("200.00"),
                balance=Decimal("350.00"),
            ),
        )

        detections = detect_receipts(transactions, date(2026, 8, 20))

        self.assertEqual(
            detections[0].classification,
            ReceiptClassification.EXCLUDED_CREDIT,
        )
        self.assertEqual(
            detections[1].classification,
            ReceiptClassification.AMBIGUOUS_RECEIPT,
        )
        plan = build_monthly_plan(
            Decimal("350.00"),
            transactions,
            date(2026, 8, 20),
            receipt_detections=detections,
        )
        self.assertFalse(
            any(payment.status == "payé (détecté ICS)" for payment in plan)
        )

    def test_quarterly_plan_keeps_full_balance(self) -> None:
        transactions = (
            Transaction(
                operation_date=date(2026, 7, 1),
                label="Appel trimestriel",
                expense=Decimal("600.00"),
                receipt=None,
                balance=Decimal("600.00"),
            ),
        )

        plan = build_quarterly_plan(
            Decimal("600.00"),
            transactions,
            date(2026, 8, 3),
        )

        self.assertEqual(plan[0].amount, Decimal("600.00"))
        self.assertEqual(plan[0].status, "à payer")
        self.assertEqual(plan[1].status, "non applicable")

    def test_payment_mode_prompt_accepts_french_answers(self) -> None:
        with patch("builtins.input", return_value="oui"):
            self.assertTrue(_ask_monthly_payments(None))
        with patch("builtins.input", return_value="non"):
            self.assertFalse(_ask_monthly_payments(None))


if __name__ == "__main__":
    unittest.main()
