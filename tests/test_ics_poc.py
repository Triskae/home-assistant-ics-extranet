import unittest
from datetime import date
from decimal import Decimal

from ics_poc import Transaction, _extract_transactions, build_monthly_plan, parse_money


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


if __name__ == "__main__":
    unittest.main()
