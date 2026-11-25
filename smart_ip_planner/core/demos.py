"""Three built-in synthetic demo projects (FT-27)."""

from __future__ import annotations

from core.models import DepartmentInput, PlannerConfig, ReserveInput


def get_demo_projects() -> list[dict]:
    """Return 3 synthetic demo projects illustrating key capabilities of Smart IP Planner."""
    return [
        {
            "name": "Демо 1: Университет кампусы (VLSM тиімділігі)",
            "description": "6 бөлімшесі бар оқу корпусы. VLSM мен FLSM үнемдеуін салыстыруға арналған оңтайлы жоспар.",
            "config": PlannerConfig(
                base_cidr="10.20.0.0/22",
                method="VLSM",
                gateway_policy="first",
                default_reserve_pct=20,
            ),
            "departments": [
                DepartmentInput(name="Студенттік Wi-Fi", vlan_id=10, hosts=200, growth_reserve_pct=20),
                DepartmentInput(name="Компьютерлік сыныптар", vlan_id=20, hosts=95, growth_reserve_pct=20),
                DepartmentInput(name="Оқытушылар корпусы", vlan_id=30, hosts=50, growth_reserve_pct=20),
                DepartmentInput(name="Әкімшілік бөлімі", vlan_id=40, hosts=22, growth_reserve_pct=15),
                DepartmentInput(name="Серверлік бөлме", vlan_id=50, hosts=12, growth_reserve_pct=25),
                DepartmentInput(name="Бейнебақылау (CCTV)", vlan_id=60, hosts=18, growth_reserve_pct=10),
            ],
            "reserves": [],
        },
        {
            "name": "Демо 2: Резервтері бар кеңсе (Фрагментация)",
            "description": "Қолмен бекітілген DMZ және VoIP резервтері бар желі. Бос блоктар фрагментациясы мен NET-003/NET-007 диагностикасын көрсетеді.",
            "config": PlannerConfig(
                base_cidr="192.168.0.0/23",
                method="VLSM",
                gateway_policy="first",
                default_reserve_pct=20,
            ),
            "departments": [
                DepartmentInput(name="Сату бөлімі", vlan_id=110, hosts=80, growth_reserve_pct=20),
                DepartmentInput(name="IT және әзірлеу", vlan_id=120, hosts=45, growth_reserve_pct=25),
                DepartmentInput(name="Бухгалтерия", vlan_id=130, hosts=18, growth_reserve_pct=15),
                DepartmentInput(name="Қонақтар Wi-Fi", vlan_id=140, hosts=25, growth_reserve_pct=0),
            ],
            "reserves": [
                ReserveInput(cidr="192.168.0.128/26", note="DMZ серверлері (қолмен резерв)"),
                ReserveInput(cidr="192.168.1.64/27", note="IP-телефония (VoIP)"),
                ReserveInput(cidr="172.16.0.0/24", note="Сыртқы филиал (NET-003 тексеруі)"),
            ],
        },
        {
            "name": "Демо 3: Тар пул (А сценарийі — автокеңейту)",
            "description": "Базалық /24 желісіне сыймайтын сұраныс. NET-001 қатесін және А сценарийі арқылы автоматты кеңейтуді көрсетеді.",
            "config": PlannerConfig(
                base_cidr="192.168.10.0/24",
                method="VLSM",
                gateway_policy="last",
                default_reserve_pct=20,
            ),
            "departments": [
                DepartmentInput(name="Өндірістік цех", vlan_id=201, hosts=110, growth_reserve_pct=20),
                DepartmentInput(name="Логистика қоймасы", vlan_id=202, hosts=65, growth_reserve_pct=20),
                DepartmentInput(name="Инженерлік бөлім", vlan_id=203, hosts=40, growth_reserve_pct=20),
                DepartmentInput(name="Қауіпсіздік қызметі", vlan_id=204, hosts=15, growth_reserve_pct=10),
            ],
            "reserves": [],
        },
    ]
