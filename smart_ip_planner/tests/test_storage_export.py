"""Integration tests for SQLite repo, JSON roundtrip, Excel 4-sheet, CSV, and Cisco CLI."""

import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from core.allocator import plan_network
from core.cisco import generate_cisco_config
from core.diagnostics import diagnose_auto_plan
from i18n.translations import format_finding, get_translator
from storage.db import ProjectRepository
from storage.exporter import (
    export_plan_csv,
    export_plan_excel,
    export_project_json,
    import_project_json,
)


class TestStorageAndExport(unittest.TestCase):
    def test_sqlite_crud_and_demo_seeding(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = ProjectRepository(Path(tmp) / "test.db")
            seeded = repo.seed_demos_if_empty()
            self.assertEqual(len(seeded), 3)

            projects = repo.list_projects()
            self.assertEqual(len(projects), 3)

            first = projects[0]
            self.assertTrue(repo.rename_project(first.id, "Renamed Campus"))
            self.assertEqual(repo.get_project(first.id).name, "Renamed Campus")

            copied_id = repo.copy_project(first.id)
            self.assertIsNotNone(copied_id)
            self.assertEqual(len(repo.list_projects()), 4)

            self.assertTrue(repo.delete_project(copied_id))
            self.assertEqual(len(repo.list_projects()), 3)

    def test_json_excel_csv_and_cisco_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = ProjectRepository(Path(tmp) / "exp.db")
            repo.seed_demos_if_empty()
            proj = repo.list_projects()[0]

            raw_json = export_project_json(
                proj.name, proj.description, proj.config, proj.departments, proj.reserves
            )
            name, desc, cfg, depts, reserves = import_project_json(raw_json)
            self.assertEqual(name, proj.name)
            self.assertEqual(len(depts), len(proj.departments))

            plan = plan_network(cfg, depts, reserves)
            findings = diagnose_auto_plan(plan, depts)
            t = get_translator("kk")

            csv_bytes = export_plan_csv(plan, t)
            self.assertIn(b"10.20.0.0/", csv_bytes)

            xlsx_bytes = export_plan_excel(
                proj.name, plan, findings, t, lambda f: format_finding(f, "kk")
            )
            wb = load_workbook(io.BytesIO(xlsx_bytes))
            self.assertEqual(len(wb.sheetnames), 4)

            cisco = generate_cisco_config(plan, hostname="CAMPUS-CORE", include_dhcp=True)
            self.assertIn("hostname CAMPUS-CORE", cisco)
            self.assertIn("interface Vlan10", cisco)
            self.assertIn("ip dhcp pool", cisco)


if __name__ == "__main__":
    unittest.main()
