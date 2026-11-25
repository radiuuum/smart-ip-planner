"""All 19 acceptance tests from Section 8.1 + demo checks (Section 9) + performance (<1s for 200 depts)."""

from __future__ import annotations

import io
import ipaddress
import pathlib
import random
import re
import tempfile
import time
import unittest

from openpyxl import load_workbook

from core.allocator import plan_flsm, plan_vlsm
from core.analytics import compare_methods, compute_metrics
from core.diagnostics import diagnose_manual_network, run_diagnostics
from core.growth import simulate_growth
from core.models import Department, ReservedBlock
from core.proposals import propose_scenario_a, propose_scenario_b
from core.sizing import planned_hosts, prefix_for, validate_inputs
from services.exporter import export_cisco_config, export_csv, export_excel
from services.storage import (
    ProjectStorage,
    export_project_json,
    import_project_json,
    load_demo_projects,
)
from strings import T, T_RU


class TestAcceptanceTZ(unittest.TestCase):
    """Exact verification of all 19 acceptance scenarios in Section 8.1 of the TZ."""

    def test_01_subnet_sizes_and_integer_math(self):
        # (50, 20%), (5, 0), (1, 0), (100, 10%) -> /26, /29, /30, /25; H_plan(100,10) == 110
        self.assertEqual(prefix_for(planned_hosts(50, 20)), 26)
        self.assertEqual(prefix_for(planned_hosts(5, 0)), 29)
        self.assertEqual(prefix_for(planned_hosts(1, 0)), 30)
        h_plan_100 = planned_hosts(100, 10)
        self.assertEqual(h_plan_100, 110)
        self.assertEqual(prefix_for(h_plan_100), 25)

    def test_02_boundary_h_plan_61_and_62(self):
        self.assertEqual(prefix_for(61), 26)
        self.assertEqual(prefix_for(62), 25)

    def test_03_reference_vlsm_192_168_0_0_24(self):
        base = ipaddress.IPv4Network("192.168.0.0/24")
        depts = [
            Department("D1", 10, 100, 0),
            Department("D2", 20, 50, 0),
            Department("D3", 30, 25, 0),
            Department("D4", 40, 10, 0),
            Department("D5", 50, 5, 0),
        ]
        plan = plan_vlsm(base, depts)
        self.assertTrue(plan.is_complete)
        nets = [str(s.network) for s in plan.subnets]
        self.assertEqual(
            nets,
            [
                "192.168.0.0/25",
                "192.168.0.128/26",
                "192.168.0.192/27",
                "192.168.0.224/28",
                "192.168.0.240/29",
            ],
        )
        metrics = compute_metrics(plan)
        self.assertEqual(metrics.free_outside, 8)

    def test_04_flsm_same_data_in_24(self):
        base = ipaddress.IPv4Network("192.168.0.0/24")
        depts = [
            Department("D1", 10, 100, 0),
            Department("D2", 20, 50, 0),
            Department("D3", 30, 25, 0),
            Department("D4", 40, 10, 0),
            Department("D5", 50, 5, 0),
        ]
        plan = plan_flsm(base, depts)
        self.assertFalse(plan.is_complete)
        self.assertEqual(len(plan.subnets), 2)
        self.assertEqual(len(plan.unallocated), 3)
        comp = compare_methods(base, depts)
        self.assertEqual(comp.flsm_min_pool_prefix, 22)

    def test_05_vlsm_savings_same_data(self):
        base = ipaddress.IPv4Network("192.168.0.0/24")
        depts = [
            Department("D1", 10, 100, 0),
            Department("D2", 20, 50, 0),
            Department("D3", 30, 25, 0),
            Department("D4", 40, 10, 0),
            Department("D5", 50, 5, 0),
        ]
        comp = compare_methods(base, depts)
        self.assertEqual(comp.a_flsm, 640)
        self.assertEqual(comp.a_vlsm, 248)
        self.assertEqual(comp.savings_addresses, 392)
        self.assertAlmostEqual(comp.savings_pct, 61.25, places=2)
        self.assertEqual(comp.flsm_min_pool_prefix, 22)
        self.assertEqual(comp.vlsm_min_pool_prefix, 24)

    def test_06_manual_reserve_inside_base(self):
        base = ipaddress.IPv4Network("192.168.1.0/24")
        res = [ReservedBlock(ipaddress.IPv4Network("192.168.1.0/26"), "DMZ")]
        depts = [Department("IT", 10, 40, 20), Department("Office", 20, 20, 20)]
        plan = plan_vlsm(base, depts, res)
        self.assertTrue(plan.is_complete)
        for s in plan.subnets:
            self.assertFalse(s.network.overlaps(res[0].network))

    def test_07_shortage_triggers_net005(self):
        base = ipaddress.IPv4Network("192.168.1.0/24")
        depts = [
            Department("Big1", 10, 150, 0),  # /24 (256)
            Department("Big2", 20, 50, 0),   # /26 (64)
        ]
        plan = plan_vlsm(base, depts)
        self.assertFalse(plan.is_complete)
        findings = run_diagnostics(plan)
        codes = [f.code for f in findings]
        self.assertIn("NET-005", codes)
        net005 = next(f for f in findings if f.code == "NET-005")
        self.assertIn("/23", net005.recommendation)

    def test_08_manual_mode_net002_net003_net004_net006(self):
        rows = [
            {"department": "A", "vlan_id": 10, "subnet": "192.168.1.0/26", "gateway": "192.168.1.1", "hosts": 20},
            {"department": "B", "vlan_id": 10, "subnet": "192.168.1.32/27", "gateway": "192.168.1.32", "hosts": 10},
            {"department": "C", "vlan_id": 30, "subnet": "10.0.0.0/24", "gateway": "10.0.0.1", "hosts": 10},
        ]
        findings = diagnose_manual_network("192.168.1.0/24", rows)
        codes = {f.code for f in findings}
        self.assertIn("NET-002", codes)
        self.assertIn("NET-003", codes)
        self.assertIn("NET-004", codes)
        self.assertIn("NET-006", codes)

    def test_09_invalid_inputs_trigger_net001(self):
        # Invalid IPv4
        _, _, _, f1 = validate_inputs("999.1.1.0/24", [{"name": "A", "hosts": 10, "reserve_pct": 0}])
        self.assertTrue(any(f.code == "NET-001" for f in f1))
        # Host bits set
        _, _, _, f2 = validate_inputs("192.168.1.5/24", [{"name": "A", "hosts": 10, "reserve_pct": 0}])
        self.assertTrue(any(f.code == "NET-001" and "192.168.1.0/24" in f.recommendation for f in f2))
        # Hosts <= 0
        _, _, _, f3 = validate_inputs("192.168.1.0/24", [{"name": "A", "hosts": 0, "reserve_pct": 0}])
        self.assertTrue(any(f.code == "NET-001" for f in f3))
        # Empty table
        _, _, _, f4 = validate_inputs("192.168.1.0/24", [])
        self.assertTrue(any(f.code == "NET-001" for f in f4))
        # VLAN out of 1..4094
        _, _, _, f5 = validate_inputs("192.168.1.0/24", [{"name": "A", "vlan_id": 5000, "hosts": 10, "reserve_pct": 0}])
        self.assertTrue(any(f.code == "NET-001" for f in f5))

    def test_10_determinism_on_shuffled_rows(self):
        base = ipaddress.IPv4Network("10.10.0.0/20")
        depts = [
            Department("A", 10, 50, 20),
            Department("B", 20, 120, 10),
            Department("C", 30, 15, 20),
            Department("D", 40, 50, 20),
        ]
        p1 = plan_vlsm(base, depts)
        p2 = plan_vlsm(base, list(reversed(depts)))
        self.assertEqual(p1.subnets, p2.subnets)
        self.assertEqual(p1.free_blocks, p2.free_blocks)

    def test_11_pool_100_percent_full_emits_net007_warning(self):
        base = ipaddress.IPv4Network("192.168.1.0/25")  # 128 IPs
        depts = [Department("A", 10, 60, 0), Department("B", 20, 60, 0)]  # 64 + 64 = 128
        plan = plan_vlsm(base, depts)
        self.assertTrue(plan.is_complete)
        findings = run_diagnostics(plan)
        net007 = next(f for f in findings if f.code == "NET-007")
        self.assertEqual(net007.level, "WARNING")

    def test_12_fragmentation_two_non_adjacent_27_for_26_triggers_net010(self):
        # /25 (0..127): reserve .0/27 and .64/27 -> remaining free are .32/27 and .96/27 (total 64, largest 32)
        base = ipaddress.IPv4Network("192.168.1.0/25")
        res = [
            ReservedBlock(ipaddress.IPv4Network("192.168.1.0/27"), "R1"),
            ReservedBlock(ipaddress.IPv4Network("192.168.1.64/27"), "R2"),
        ]
        depts = [Department("Need26", 10, 50, 0)]  # needs /26 (64)
        plan = plan_vlsm(base, depts, res)
        self.assertFalse(plan.is_complete)
        findings = run_diagnostics(plan)
        self.assertIn("NET-010", {f.code for f in findings})

    def test_13_scenario_b_add_20_hosts_preserves_existing(self):
        demos = load_demo_projects()
        office = demos[0]
        base = ipaddress.IPv4Network(office["base"])
        depts = [Department.from_dict(d) for d in office["departments"]]
        saved = plan_vlsm(base, depts)
        preview = propose_scenario_b(saved, Department("NewDept", 60, 20, 20), [])
        self.assertTrue(preview.success)
        self.assertIsNotNone(preview.added_subnet)
        self.assertEqual(preview.diff.changed_count, 0)
        self.assertEqual(preview.new_plan.subnets[: len(saved.subnets)], saved.subnets)

    def test_14_growth_plus_50_pct_on_office_demo(self):
        demos = load_demo_projects()
        office = demos[0]
        base = ipaddress.IPv4Network(office["base"])
        depts = [Department.from_dict(d) for d in office["departments"]]
        plan = plan_vlsm(base, depts)
        report = simulate_growth(plan, [], growth_pct=50)
        self.assertEqual(report.need_expand_count, 2)
        expanded = {r.department for r in report.rows if r.verdict != "ok"}
        self.assertEqual(expanded, {"Әкімшілік", "Бухгалтерия"})
        for r in report.rows:
            if r.department in expanded:
                self.assertEqual(r.verdict, "move")
        self.assertEqual(report.diff.changed_count, 2)

    def test_15_save_and_load_json_and_sqlite(self):
        demos = load_demo_projects()
        office = demos[0]
        raw_json = export_project_json(office)
        loaded_json = import_project_json(raw_json)
        self.assertEqual(loaded_json, office)

        with tempfile.TemporaryDirectory() as tmp:
            store = ProjectStorage(pathlib.Path(tmp) / "test.db")
            pid = store.save_project(office)
            rec = store.get_project(pid)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["data"], office)

    def test_16_export_excel_4_kazakh_sheets(self):
        demos = load_demo_projects()
        office = demos[0]
        base = ipaddress.IPv4Network(office["base"])
        depts = [Department.from_dict(d) for d in office["departments"]]
        plan = plan_vlsm(base, depts)
        metrics = compute_metrics(plan)
        comp = compare_methods(base, depts)
        findings = run_diagnostics(plan)

        xlsx = export_excel(plan, metrics, comp, findings, lang="kk")
        wb = load_workbook(io.BytesIO(xlsx))
        self.assertEqual(wb.sheetnames, ["Жоспар", "Талдау", "Диагностика", "Салыстыру"])
        # Verify Kazakh letters preserved without corruption
        ws_plan = wb["Жоспар"]
        dept_names = [ws_plan.cell(row=r, column=1).value for r in range(2, ws_plan.max_row + 1)]
        self.assertIn("Әкімшілік", dept_names)
        self.assertIn("Қауіпсіздік", dept_names)

        # Also verify CSV utf-8-sig & Cisco bonus
        csv_bytes = export_csv(plan, lang="kk")
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        cisco_txt = export_cisco_config(plan, hostname="OFFICE-SW1")
        self.assertIn("interface Vlan10", cisco_txt)

    def test_17_200_random_inputs_invariants(self):
        rng = random.Random(42)
        for idx in range(200):
            base_prefix = rng.choice([18, 20, 22])
            base = ipaddress.IPv4Network(f"10.{idx % 200}.0.0/{base_prefix}")
            res_list = []
            if idx % 3 == 0:
                sub = list(base.subnets(new_prefix=base_prefix + 3))[rng.randint(0, 7)]
                res_list.append(ReservedBlock(sub, "R"))
            n_depts = rng.randint(2, 10)
            depts = [
                Department(f"D{i}", i + 1, rng.randint(2, 120), rng.choice([0, 10, 20, 30]))
                for i in range(n_depts)
            ]
            plan = plan_vlsm(base, depts, res_list)
            # Invariants: all inside base, no overlaps with each other or reserves, capacity >= planned_hosts
            for i, s1 in enumerate(plan.subnets):
                self.assertTrue(s1.network.subnet_of(base))
                self.assertGreaterEqual(s1.capacity, s1.planned_hosts)
                for r in res_list:
                    self.assertFalse(s1.network.overlaps(r.network))
                for s2 in plan.subnets[i + 1 :]:
                    self.assertFalse(s1.network.overlaps(s2.network))

    def test_18_no_reserves_contiguous_packing(self):
        base = ipaddress.IPv4Network("10.0.0.0/20")
        depts = [
            Department("A", 1, 300, 10),
            Department("B", 2, 150, 20),
            Department("C", 3, 60, 0),
            Department("D", 4, 25, 10),
            Department("E", 5, 10, 0),
        ]
        plan = plan_vlsm(base, depts)
        self.assertTrue(plan.is_complete)
        # Adjacent subnets must have zero gap between broadcast + 1 and next network_address
        for i in range(len(plan.subnets) - 1):
            cur_end = int(plan.subnets[i].network.broadcast_address)
            nxt_start = int(plan.subnets[i + 1].network.network_address)
            self.assertEqual(cur_end + 1, nxt_start)

    def test_19_all_strings_keys_exist_and_format_cleanly(self):
        # Scan all project Python files for t["..."] / T["..."] keys
        root = pathlib.Path(__file__).resolve().parent.parent
        pattern = re.compile(r'\b[tT]\["([a-zA-Z0-9_.]+)"\]')
        used_keys: set[str] = set()
        for py_file in root.rglob("*.py"):
            if "tests" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8")
            used_keys.update(pattern.findall(text))

        self.assertGreater(len(used_keys), 30)
        for key in used_keys:
            self.assertIn(key, T, f"Missing key in T (kk): {key}")
            self.assertIn(key, T_RU, f"Missing key in T_RU (ru): {key}")

    def test_demo_projects_match_section_9_numbers(self):
        demos = load_demo_projects()
        self.assertEqual([d["name"] for d in demos], ["Шағын кеңсе", "Университет", "Мәселелі желі"])

        # 9.1 Шағын кеңсе: 144/256 (56.25%), util 64.3%, VLSM savings 55%
        d0 = demos[0]
        p0 = plan_vlsm(ipaddress.IPv4Network(d0["base"]), [Department.from_dict(x) for x in d0["departments"]])
        m0 = compute_metrics(p0)
        c0 = compare_methods(ipaddress.IPv4Network(d0["base"]), [Department.from_dict(x) for x in d0["departments"]])
        self.assertEqual(m0.allocated, 144)
        self.assertAlmostEqual(m0.fill_pct, 56.25, places=2)
        self.assertAlmostEqual(m0.utilization_pct, 64.34, places=1)
        self.assertAlmostEqual(c0.savings_pct, 55.0, places=2)

        # 9.2 Университет: 4 672 addresses, complete, no ERROR
        d1 = demos[1]
        res1 = [ReservedBlock(ipaddress.IPv4Network(r["network"]), r["note"]) for r in d1["reserved"]]
        p1 = plan_vlsm(ipaddress.IPv4Network(d1["base"]), [Department.from_dict(x) for x in d1["departments"]], res1)
        self.assertTrue(p1.is_complete)
        self.assertEqual(compute_metrics(p1).allocated, 4672)
        self.assertFalse(any(f.level == "ERROR" for f in run_diagnostics(p1)))

        # 9.3 Мәселелі желі: NET-005 (lack 96, /23), NET-004 (VLAN 20), 2 unallocated
        d2 = demos[2]
        res2 = [ReservedBlock(ipaddress.IPv4Network(r["network"]), r["note"]) for r in d2["reserved"]]
        p2 = plan_vlsm(ipaddress.IPv4Network(d2["base"]), [Department.from_dict(x) for x in d2["departments"]], res2)
        self.assertFalse(p2.is_complete)
        self.assertEqual(len(p2.unallocated), 2)
        f2 = run_diagnostics(p2)
        self.assertIn("NET-004", {f.code for f in f2})
        self.assertIn("NET-005", {f.code for f in f2})
        # Scenario A expands /24 -> /23
        prev_a = propose_scenario_a(p2, [Department.from_dict(x) for x in d2["departments"]], res2)
        self.assertTrue(prev_a.success)
        self.assertEqual(str(prev_a.new_base), "172.16.0.0/23")

    def test_performance_200_departments_under_1_second(self):
        base = ipaddress.IPv4Network("10.0.0.0/12")
        depts = [Department(f"Dept-{i}", i + 1, (i % 80) + 5, 20) for i in range(200)]
        t0 = time.perf_counter()
        plan = plan_vlsm(base, depts)
        _ = compute_metrics(plan)
        _ = run_diagnostics(plan)
        elapsed = time.perf_counter() - t0
        self.assertTrue(plan.is_complete)
        self.assertLess(elapsed, 1.0, f"Too slow: {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
