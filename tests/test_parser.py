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

    def test_summary_detects_payment_and_splits_remaining_balance(self) -> None:
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
        self.assertTrue(summary.payments[0].is_paid)
        self.assertEqual(summary.payments[1].amount, Decimal("200.00"))
        self.assertEqual(summary.payments[2].amount, Decimal("200.01"))
        self.assertEqual(summary.transaction_count, 2)

    def test_no_personal_data_is_required_by_parser(self) -> None:
        self.assertEqual(parser.parse_money("1 234,56 €"), Decimal("1234.56"))


if __name__ == "__main__":
    unittest.main()
