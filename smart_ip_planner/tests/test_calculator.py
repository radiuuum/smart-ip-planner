"""Unit tests for core/calculator.py (Section 3.1 & FT-01)."""

import unittest

from core.calculator import (
    ValidationError,
    capacity_for_prefix,
    planned_hosts,
    prefix_for,
    validate_base_network,
)


class TestCalculator(unittest.TestCase):
    def test_exact_integer_planned_hosts_avoids_float_bug(self):
        # Section 3.1 explicitly warns: 100 * 1.1 in float gives 110.00000000000001 -> ceil 111
        self.assertEqual(planned_hosts(100, 10), 110)
        self.assertEqual(planned_hosts(50, 20), 60)
        self.assertEqual(planned_hosts(10, 0), 10)
        self.assertEqual(planned_hosts(1, 1), 2)

    def test_tz_section_31_worked_example(self):
        # 50 devices + 20% reserve -> 60 planned -> /26 (size 64, capacity 61, free 1)
        h_plan = planned_hosts(50, 20)
        self.assertEqual(h_plan, 60)
        pref = prefix_for(h_plan)
        self.assertEqual(pref, 26)
        cap = capacity_for_prefix(pref)
        self.assertEqual(cap, 61)
        self.assertEqual(cap - h_plan, 1)

    def test_small_subnets_never_produce_31_or_32(self):
        self.assertEqual(prefix_for(1), 30)
        self.assertEqual(capacity_for_prefix(30), 1)
        self.assertEqual(prefix_for(2), 29)
        self.assertEqual(capacity_for_prefix(29), 5)

    def test_base_network_validation(self):
        self.assertEqual(str(validate_base_network("10.20.0.0/22")), "10.20.0.0/22")
        self.assertEqual(str(validate_base_network("10.0.0.0/8")), "10.0.0.0/8")
        self.assertEqual(str(validate_base_network("192.168.1.0/30")), "192.168.1.0/30")

        with self.assertRaises(ValidationError) as ctx1:
            validate_base_network("192.168.1.5/24")
        self.assertEqual(ctx1.exception.code, "host_bits_set")

        with self.assertRaises(ValidationError) as ctx2:
            validate_base_network("192.168.1.0/31")
        self.assertEqual(ctx2.exception.code, "prefix_out_of_range")

        with self.assertRaises(ValidationError) as ctx3:
            validate_base_network("10.0.0.0/7")
        self.assertEqual(ctx3.exception.code, "prefix_out_of_range")


if __name__ == "__main__":
    unittest.main()
