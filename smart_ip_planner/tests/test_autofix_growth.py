"""Unit tests for Scenario A, Scenario B, and Growth Modeling (FT-18..FT-23)."""

import unittest

from core.allocator import plan_network
from core.autofix import preview_scenario_a_expand_base, preview_scenario_b_add_department
from core.growth import simulate_growth
from core.models import DepartmentInput, PlannerConfig


class TestAutofixAndGrowth(unittest.TestCase):
    def test_scenario_a_expands_base_network(self):
        cfg = PlannerConfig("192.168.10.0/24", "VLSM", "first")
        depts = [
            DepartmentInput("Prod", 110, 20, 10),  # 132 -> /24 (256)
            DepartmentInput("Log", 65, 20, 20),    # 78 -> /25 (128)
        ]
        plan = plan_network(cfg, depts)
        self.assertFalse(plan.is_complete)

        preview = preview_scenario_a_expand_base(cfg, depts, [])
        self.assertTrue(preview.success)
        self.assertEqual(preview.new_base_cidr, "192.168.10.0/23")
        self.assertIsNotNone(preview.preview_plan)
        self.assertTrue(preview.preview_plan.is_complete)

    def test_scenario_b_preserves_existing_allocations(self):
        cfg = PlannerConfig("10.20.0.0/22", "VLSM", "first")
        depts = [
            DepartmentInput("Staff", 50, 20, 10),
            DepartmentInput("Admin", 20, 15, 20),
        ]
        saved_plan = plan_network(cfg, depts)
        new_dept = DepartmentInput("NewLab", 25, 20, 30)

        preview = preview_scenario_b_add_department(saved_plan, new_dept, [])
        self.assertTrue(preview.success)
        self.assertIsNotNone(preview.added_allocation)
        self.assertEqual(preview.unchanged_count, 2)
        # Existing subnets remain untouched
        self.assertEqual(preview.preview_plan.allocations[:2], saved_plan.allocations)

    def test_growth_modeling_verdicts_and_cost(self):
        cfg = PlannerConfig("10.30.0.0/23", "VLSM", "first")
        depts = [
            DepartmentInput("A", 20, 0, 10),  # /27 (cap 29)
            DepartmentInput("B", 10, 0, 20),  # /28 (cap 13)
        ]
        plan = plan_network(cfg, depts)
        sim = simulate_growth(plan, [], custom_hosts={"A": 25, "B": 50})
        verdicts = {item.department: item.verdict for item in sim.items}
        self.assertEqual(verdicts["A"], "sufficient")
        self.assertIn(verdicts["B"], ("expand_in_place", "relocate"))


if __name__ == "__main__":
    unittest.main()
