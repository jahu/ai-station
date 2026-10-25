"""Offline artifact checks. Run with the optional QA-tool environment."""

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import operator_qa as qa
from openpyxl import load_workbook


class WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=qa.ROOT, text=True).strip()

    def test_catalog_coverage_and_stable_unique_ids(self):
        catalog = qa.load_catalog()
        self.assertGreaterEqual(len(catalog["cases"]), 120)
        self.assertGreaterEqual(len({case["area"] for case in catalog["cases"]}), 20)
        ids = {case["id"] for case in catalog["cases"]}
        self.assertTrue({"LIB-005", "LIB-006", "LIB-007", "LIB-008", "MEM-007", "PROJECT-001"} <= ids)

    def test_workbook_exports_are_usable_feedback_without_prefilled_success(self):
        with tempfile.TemporaryDirectory() as folder:
            files = qa.export(
                Path(folder), release=self.release, base_url="http://127.0.0.1:8765", draft=True
            )
            self.assertEqual(len(files), 6)
            book = load_workbook(files[0], keep_links=False)
            self.assertEqual(
                book.sheetnames, ["Start", "Testy", "Zgłoszenia", "Retesty", "Podsumowanie", "Słownik"]
            )
            cases = qa.load_catalog()["cases"]
            page = book["Testy"]
            self.assertEqual([row[0].value for row in list(page.rows)[1:]], [case["id"] for case in cases])
            self.assertEqual({row[1].value for row in list(page.rows)[1:]}, {"Nie testowano"})
            self.assertEqual(page.freeze_panes, "E2")
            self.assertEqual(page.max_column, len(qa.HEADERS))
            self.assertIn(f"B2:B{len(cases) + 1}", str(page.data_validations))
            self.assertIn("WERSJA ROBOCZA", book["Start"]["B2"].value)
            self.assertTrue(all(book["Podsumowanie"].cell(i, 2).value.endswith(")") for i in range(3, 8)))
            # Simulate a returned workbook: answers and report linkage survive save/reopen.
            page["B2"] = "Błąd"
            page["G2"] = "Zażółć: rzeczywisty błąd po wysłaniu wiadomości"
            page["R2"] = "ZGL-001"
            book["Zgłoszenia"]["C2"] = page["A2"].value
            returned = Path(folder) / "odpowiedzi.xlsx"
            book.save(returned)
            loaded = load_workbook(returned, keep_links=False)
            self.assertEqual(loaded["Testy"]["B2"].value, "Błąd")
            self.assertEqual(loaded["Testy"]["R2"].value, "ZGL-001")
            self.assertEqual(loaded["Zgłoszenia"]["C2"].value, cases[0]["id"])
            with files[1].open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(tuple(rows[0]), qa.HEADERS)
            self.assertEqual(len(rows), len(cases) + 1)
            self.assertTrue(all(len(row) == len(qa.HEADERS) for row in rows))
            self.assertIn("\n2. ", rows[1][4])
            self.assertTrue(all(row[1] == "Nie testowano" for row in rows[1:]))
            self.assertEqual(json.loads(files[-1].read_text())["release"], self.release)

    def test_refuses_overwriting_existing_operator_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = qa.export(Path(folder), release=self.release, base_url="http://127.0.0.1:8765")
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            with self.assertRaises(FileExistsError):
                qa.export(Path(folder), release=self.release, base_url="http://127.0.0.1:8765")
            self.assertEqual(
                before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            )

    def test_duplicate_case_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = qa.load_catalog()
            catalog["cases"].append(catalog["cases"][0])
            path = Path(folder) / "duplicate.json"
            path.write_text(json.dumps(catalog))
            with self.assertRaises(ValueError):
                qa.load_catalog(path)

    def test_catalog_text_never_becomes_an_excel_or_csv_formula(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = qa.load_catalog()
            catalog["cases"][0]["title"] = '=HYPERLINK("https://example.invalid","untrusted")'
            path = Path(folder) / "input.json"
            path.write_text(json.dumps(catalog))
            files = qa.export(
                Path(folder), release=self.release, base_url="http://localhost:8765", catalog_path=path
            )
            cell = load_workbook(files[0])["Testy"]["D2"]
            self.assertEqual(cell.data_type, "s")
            with files[1].open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertTrue(rows[1][3].startswith("'="))

    def test_release_and_ui_address_must_not_hide_moving_refs_or_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            for release, url in [
                ("develop", "http://localhost:8765"),
                (self.release, "https://user:secret@example.invalid"),
            ]:
                with self.assertRaises(ValueError):
                    qa.export(Path(folder), release=release, base_url=url)


if __name__ == "__main__":
    unittest.main()
