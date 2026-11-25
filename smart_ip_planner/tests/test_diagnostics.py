"""Unit tests for core/diagnostics.py (NET-001..NET-010)."""

import unittest

from core.allocator import plan_network
from core.diagnostics import diagnose_auto_plan, diagnose_manual_network, summarize_severities
from core.models import DepartmentInput, ManualSubnetEntry, PlannerConfig, ReserveInput


class TestDiagnostics(unittest.TestCase):
    def test_auto_plan_clean_emits_net010(self):
        cfg = PlannerConfig("10.20.0.0/22", "VLSM", "first")
        depts = [
            DepartmentInput("Staff", 50, 20, 10),
            DepartmentInput("Labs", 80, 20, 20),
        ]
        plan = plan_network(cfg, depts)
        findings = diagnose_auto_plan(plan, depts)
        codes = {f.code for f in findings}
        self.assertIn("NET-010", codes)
        self.assertEqual(summarize_severities(findings)["ERROR"], 0)

    def test_auto_plan_detects_net001_net003_net005(self):
        cfg = PlannerConfig("192.168.1.0/25", "VLSM", "first")
        depts = [
            DepartmentInput("A", 100, 20, 10),
            DepartmentInput("B", 30, 0, 10),  # duplicate VLAN 10
        ]
        reserves = [ReserveInput("10.10.0.0/24", "outside")]
        plan = plan_network(cfg, depts, reserves)
        findings = diagnose_auto_plan(plan, depts)
        codes = {f.code for f in findings}
        self.assertIn("NET-001", codes)
        self.assertIn("NET-003", codes)
        self.assertIn("NET-005", codes)

    def test_manual_audit_detects_overlap_and_deficit(self):
        entries = [
            ManualSubnetEntry("Dept1", "192.168.0.0/26", 50, 10, "192.168.0.1"),
            ManualSubnetEntry("Dept2", "192.168.0.32/27", 40, 20, "192.168.0.33"),  # overlaps Dept1 + deficit 40 > 29
        ]
        findings = diagnose_manual_network("192.168.0.0/24", entries)
        codes = {f.code for f in findings}
        self.assertIn("NET-002", codes)
        self.assertIn("NET-004", codes)


if __name__ == "__main__":
    unittest.main()
