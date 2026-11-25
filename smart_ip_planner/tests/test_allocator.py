"""Unit tests for core/allocator.py (VLSM, FLSM, determinism, reserves, metrics)."""

import unittest

from core.allocator import plan_network
from core.models import DepartmentInput, PlannerConfig, ReserveInput


class TestAllocator(unittest.TestCase):
    def test_vlsm_determinism_regardless_of_input_order(self):
        cfg = PlannerConfig(base_cidr="10.20.0.0/22", method="VLSM", gateway_policy="first")
        depts_a = [
            DepartmentInput("Alpha", 50, 20, 10),
            DepartmentInput("Beta", 200, 20, 20),
            DepartmentInput("Gamma", 12, 25, 30),
            DepartmentInput("Delta", 50, 20, 40),
        ]
        depts_b = list(reversed(depts_a))

        plan_a = plan_network(cfg, depts_a)
        plan_b = plan_network(cfg, depts_b)

        self.assertTrue(plan_a.is_complete)
        self.assertEqual(plan_a.allocations, plan_b.allocations)
        self.assertEqual(plan_a.free_blocks, plan_b.free_blocks)

    def test_gateway_first_vs_last(self):
        depts = [DepartmentInput("LAN", 10, 0, 10)]
        p_first = plan_network(PlannerConfig("192.168.1.0/24", "VLSM", "first"), depts)
        p_last = plan_network(PlannerConfig("192.168.1.0/24", "VLSM", "last"), depts)

        a1 = p_first.allocations[0]
        a2 = p_last.allocations[0]
        self.assertEqual(a1.subnet_cidr, "192.168.1.0/28")
        self.assertEqual(a1.gateway_ip, "192.168.1.1")
        self.assertEqual(a1.first_host_ip, "192.168.1.2")
        self.assertEqual(a1.last_host_ip, "192.168.1.14")

        self.assertEqual(a2.gateway_ip, "192.168.1.14")
        self.assertEqual(a2.first_host_ip, "192.168.1.1")
        self.assertEqual(a2.last_host_ip, "192.168.1.13")

    def test_manual_reserves_excluded_and_out_of_base_flagged(self):
        cfg = PlannerConfig("192.168.0.0/24", "VLSM", "first")
        depts = [DepartmentInput("Office", 50, 20, 10)]
        reserves = [
            ReserveInput("192.168.0.0/26", "DMZ"),
            ReserveInput("10.0.0.0/24", "Outside"),
        ]
        plan = plan_network(cfg, depts, reserves)
        self.assertTrue(plan.is_complete)
        # First /26 is reserved, so Office gets 192.168.0.64/26
        self.assertEqual(plan.allocations[0].subnet_cidr, "192.168.0.64/26")
        self.assertEqual(len(plan.invalid_reserves), 1)
        self.assertEqual(plan.invalid_reserves[0][1], "outside_base")

    def test_flsm_and_vlsm_comparison(self):
        cfg = PlannerConfig("10.0.0.0/23", "FLSM", "first")
        depts = [
            DepartmentInput("Big", 100, 20, 10),   # 120 -> /25 (128)
            DepartmentInput("Small", 10, 0, 20),   # 10 -> /28 (16) in VLSM, /25 (128) in FLSM
        ]
        plan = plan_network(cfg, depts, include_comparison=True)
        self.assertTrue(plan.is_complete)
        self.assertEqual(plan.allocations[0].prefix, 25)
        self.assertEqual(plan.allocations[1].prefix, 25)
        self.assertIsNotNone(plan.comparison)
        self.assertEqual(plan.comparison.vlsm_required_addresses, 144)
        self.assertEqual(plan.comparison.flsm_required_addresses, 256)
        self.assertGreater(plan.comparison.vlsm_savings_pct, 40.0)

    def test_incomplete_plan_reports_unallocated_reason(self):
        cfg = PlannerConfig("192.168.10.0/25", "VLSM", "first")  # 128 IPs
        depts = [
            DepartmentInput("D1", 60, 0, 1),  # /26 (64)
            DepartmentInput("D2", 60, 0, 2),  # /26 (64)
            DepartmentInput("D3", 10, 0, 3),  # /28 (16) -> no space
        ]
        plan = plan_network(cfg, depts)
        self.assertFalse(plan.is_complete)
        self.assertEqual(len(plan.unallocated), 1)
        self.assertEqual(plan.unallocated[0].department, "D3")
        self.assertEqual(plan.unallocated[0].reason_code, "insufficient_space")


if __name__ == "__main__":
    unittest.main()
