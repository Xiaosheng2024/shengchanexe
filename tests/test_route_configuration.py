import sqlite3
import tempfile
import unittest
from pathlib import Path

from web_admin_app import database, product_flow, services
from web_admin_app.admin_page import HTML


class RouteConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.old_db_path = database.DB_PATH
        self.old_config_path = database.CONFIG_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "quality_control.db"
        database.CONFIG_PATH = Path(self.temp_dir.name) / "config.ini"
        database.CONFIG_PATH.write_text(
            f"[DATABASE]\ntype = sqlite\npath = {database.DB_PATH}\n",
            encoding="utf-8",
        )
        database.init_db()
        self.project = services.add_project(
            {"name": "X04C", "material_code": "X04C", "product_type": "A物料"}
        )
        services.create_route_template(
            self.project["id"], "A主线绑定B子线路线"
        )
        self.config = services.get_route_config(self.project["id"])
        self.stations = {
            station["name"]: station for station in self.config["project"]["stations"]
        }

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def station(self, suffix):
        return next(
            station
            for name, station in self.stations.items()
            if name.endswith(suffix)
        )

    def create_product(self, barcode, product_type):
        return product_flow.resolve_barcode(
            {
                "project_id": self.project["id"],
                "barcode": barcode,
                "material_code": product_type,
                "product_type": product_type,
                "create_if_missing": True,
            }
        )

    def complete(self, station, product, barcode):
        return services.add_station_completion(
            {
                "project_id": self.project["id"],
                "station_id": station["id"],
                "product_instance_id": product["product_instance_id"],
                "barcode": barcode,
                "barcode_used": barcode,
            }
        )

    def prepare_switched_a(self, old_barcode="AOLD001", new_barcode="ANEW001"):
        a1 = self.station("A主线1")
        a2 = self.station("A主线2")
        switch_station = self.station("A主条码切换")
        product = self.create_product(old_barcode, "A物料")
        self.complete(a1, product, old_barcode)
        self.complete(a2, product, old_barcode)
        product_flow.switch_main_barcode(
            {
                "project_id": self.project["id"],
                "station_id": switch_station["id"],
                "product_instance_id": product["product_instance_id"],
                "old_barcode": old_barcode,
                "new_barcode": new_barcode,
            }
        )
        self.complete(switch_station, product, new_barcode)
        return product

    def prepare_b(self, barcode="B001", complete_second=True):
        b1 = self.stations["B子线-预装1"]
        b2 = self.stations["B子线-预装2"]
        product = self.create_product(barcode, "B物料")
        self.complete(b1, product, barcode)
        if complete_second:
            self.complete(b2, product, barcode)
        return product

    def bind(self, parent_barcode="ANEW001", child_barcode="B001"):
        merge = self.station("A合并B工位")
        step = next(
            step for step in merge["steps"] if step["type"] == "子物料绑定"
        )
        return product_flow.bind_child_material(
            {
                "project_id": self.project["id"],
                "station_id": merge["id"],
                "step_id": step["id"],
                "parent_barcode": parent_barcode,
                "child_barcode": child_barcode,
                "child_project_id": step["bind_child_project_id"],
                "child_material_type": step["bind_child_material_type"],
                "required_station_ids": step["bind_required_station_ids"],
                "require_parent_switch": step["bind_require_parent_switch"],
            }
        )

    def test_template_creates_parallel_routes_and_plc_a_start(self):
        route_names = {
            station["route_name"] for station in self.config["project"]["stations"]
        }
        self.assertEqual(route_names, {"A主线", "B子线"})
        a1 = self.station("A主线1")
        self.assertEqual(a1["material_type"], "A物料")
        self.assertEqual(a1["station_role"], "PLC起点")
        self.assertEqual(a1["steps"][0]["type"], "PLC接收")
        self.assertTrue(a1["steps"][0]["is_main_barcode"])
        self.assertFalse(a1["dependency"]["require_previous_station"])
        self.assertFalse(
            self.stations["B子线-预装1"]["dependency"][
                "require_previous_station"
            ]
        )
        self.assertEqual(
            self.stations["B子线-预装1"]["station_role"], "B起点工位"
        )
        self.assertEqual(
            self.stations["B子线-预装2"]["station_role"], "B完成工位"
        )

    def test_route_migration_is_idempotent(self):
        database.init_db()
        database.init_db()
        with database.get_conn() as conn:
            station_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(stations)").fetchall()
            }
            dependency_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(station_dependencies)"
                ).fetchall()
            }
            step_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(steps)").fetchall()
            }
        self.assertTrue(
            {"route_name", "route_order", "station_role", "material_type"}
            <= station_columns
        )
        self.assertIn("require_current_barcode", dependency_columns)
        self.assertIn("bind_child_route", step_columns)

    def test_b_second_station_explicitly_depends_on_b_first(self):
        b1 = self.stations["B子线-预装1"]
        b2 = self.stations["B子线-预装2"]
        self.assertEqual(b2["dependency"]["required_station_ids"], [b1["id"]])
        self.assertFalse(b2["dependency"]["require_previous_station"])

    def test_merge_station_has_complete_binding_configuration(self):
        merge = self.station("A合并B工位")
        step = next(
            step for step in merge["steps"] if step["type"] == "子物料绑定"
        )
        self.assertEqual(step["bind_child_route"], "B子线")
        self.assertEqual(step["bind_child_material_type"], "B物料")
        self.assertEqual(
            set(step["bind_required_station_ids"]),
            {
                self.stations["B子线-预装1"]["id"],
                self.stations["B子线-预装2"]["id"],
            },
        )
        self.assertTrue(merge["dependency"]["require_current_barcode"])

    def test_binding_requires_both_b_stations_then_succeeds(self):
        self.prepare_switched_a()
        self.prepare_b(complete_second=False)
        with self.assertRaisesRegex(ValueError, "B子线-预装2"):
            self.bind()
        self.complete(
            self.stations["B子线-预装2"],
            product_flow.resolve_barcode({"barcode": "B001"}),
            "B001",
        )
        self.assertTrue(self.bind()["ok"])

    def test_duplicate_binding_to_another_a_is_rejected(self):
        self.prepare_switched_a()
        self.prepare_b()
        self.bind()
        self.prepare_switched_a("AOLD002", "ANEW002")
        with self.assertRaisesRegex(ValueError, "已绑定到其他产品"):
            self.bind("ANEW002", "B001")

    def test_a_follow_station_requires_bound_b(self):
        product = self.prepare_switched_a()
        follow = self.station("A后续工位")
        blocked = product_flow.verify_station_entry(
            {
                "product_instance_id": product["product_instance_id"],
                "station_id": follow["id"],
                "barcode": "ANEW001",
            }
        )
        self.assertFalse(blocked["allowed"])
        self.assertIn("子物料不足", blocked["message"])

    def test_normal_scan_record_never_creates_material_binding(self):
        self.prepare_switched_a()
        self.prepare_b()
        services.add_scan_record(
            {
                "project_id": self.project["id"],
                "station_id": self.station("A主线2")["id"],
                "barcode": "B001",
                "step": "普通扫码",
                "result": "OK",
            }
        )
        with database.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS total FROM material_bindings"
            ).fetchone()["total"]
        self.assertEqual(count, 0)

    def test_route_display_order_does_not_change_dependency(self):
        b1 = self.stations["B子线-预装1"]
        b2 = self.stations["B子线-预装2"]
        services.update_station(
            b2["id"],
            {
                "project_id": self.project["id"],
                "name": b2["name"],
                "route_name": "B子线",
                "route_order": 0,
                "station_role": b2["station_role"],
                "material_type": "B物料",
            },
        )
        product = self.create_product("B-ORDER", "B物料")
        blocked = product_flow.verify_station_entry(
            {
                "product_instance_id": product["product_instance_id"],
                "station_id": b2["id"],
                "barcode": "B-ORDER",
            }
        )
        self.assertFalse(blocked["allowed"])
        self.complete(b1, product, "B-ORDER")
        allowed = product_flow.verify_station_entry(
            {
                "product_instance_id": product["product_instance_id"],
                "station_id": b2["id"],
                "barcode": "B-ORDER",
            }
        )
        self.assertTrue(allowed["allowed"])

    def test_route_page_uses_station_id_for_selection_and_refresh(self):
        self.assertIn('data-page="routePage"', HTML)
        self.assertIn('data-station-id="${item.id}"', HTML)
        self.assertIn("selectedStationId = Number(stationId)", HTML)
        self.assertIn("station.id === selectedStationId", HTML)

    def test_station_management_adds_edits_and_lists_route_fields(self):
        created = services.add_station(
            {
                "project_id": self.project["id"],
                "name": "返修检查",
                "route_name": "返修线",
                "route_order": 2,
                "station_role": "普通工位",
            }
        )
        services.update_station(
            created["id"],
            {
                "project_id": self.project["id"],
                "name": "返修完成",
                "route_name": "B子线",
                "route_order": 3,
                "station_role": "B完成工位",
            },
        )
        refreshed = services.list_projects_full()
        station = next(
            item
            for project in refreshed
            if project["id"] == self.project["id"]
            for item in project["stations"]
            if item["id"] == created["id"]
        )
        self.assertEqual(station["name"], "返修完成")
        self.assertEqual(station["route_name"], "B子线")
        self.assertEqual(station["route_order"], 3)
        self.assertEqual(station["station_role"], "B完成工位")

    def test_station_management_and_tree_expose_route_controls(self):
        for element_id in (
            "stationRoute",
            "stationRouteOrder",
            "stationRole",
            "routeStationRole",
        ):
            self.assertIn(f'id="{element_id}"', HTML)
        self.assertIn("<th>路线</th><th>顺序</th>", HTML)
        self.assertIn('class="tree-node tree-route"', HTML)
        self.assertIn('const route = station.route_name || "A主线"', HTML)
        self.assertIn("routeSortValue(left.route_name)", HTML)

    def test_station_route_order_is_project_route_then_order(self):
        services.add_station(
            {
                "project_id": self.project["id"],
                "name": "A最前",
                "route_name": "A主线",
                "route_order": 0,
                "station_role": "起点工位",
            }
        )
        project = next(
            item
            for item in services.list_projects_full()
            if item["id"] == self.project["id"]
        )
        route_order_pairs = [
            (station["route_name"], station["route_order"])
            for station in project["stations"]
        ]
        route_rank = {"A主线": 1, "B子线": 2, "返修线": 3, "其他": 4}
        self.assertEqual(
            route_order_pairs,
            sorted(
                route_order_pairs,
                key=lambda item: (route_rank[item[0]], item[1]),
            ),
        )

    def test_station_route_values_reject_unknown_choices(self):
        with self.assertRaisesRegex(ValueError, "所属路线不正确"):
            services.add_station(
                {
                    "project_id": self.project["id"],
                    "name": "无效路线",
                    "route_name": "临时路线",
                }
            )
        with self.assertRaisesRegex(ValueError, "工位作用不正确"):
            services.add_station(
                {
                    "project_id": self.project["id"],
                    "name": "无效作用",
                    "station_role": "临时作用",
                }
            )


class LegacyStationRouteMigrationTest(unittest.TestCase):
    def setUp(self):
        self.old_db_path = database.DB_PATH
        self.old_config_path = database.CONFIG_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "legacy.db"
        database.CONFIG_PATH = Path(self.temp_dir.name) / "config.ini"
        database.CONFIG_PATH.write_text(
            f"[DATABASE]\ntype = sqlite\npath = {database.DB_PATH}\n",
            encoding="utf-8",
        )
        with sqlite3.connect(database.DB_PATH) as conn:
            conn.executescript(
                """
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE stations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, name)
                );
                INSERT INTO projects(id, name, created_at)
                VALUES (1, 'X04C旧项目', '2026-01-01 00:00:00');
                INSERT INTO stations(id, project_id, name, created_at)
                VALUES
                    (3, 1, '旧工位3', '2026-01-01 00:00:00'),
                    (7, 1, '旧工位7', '2026-01-01 00:00:00');
                """
            )

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def test_old_station_rows_are_preserved_and_migration_is_repeatable(self):
        database.init_db()
        database.init_db()
        with database.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, name, route_name, route_order, station_role
                FROM stations ORDER BY id
                """
            ).fetchall()
        self.assertEqual([row["id"] for row in rows], [3, 7])
        self.assertEqual([row["name"] for row in rows], ["旧工位3", "旧工位7"])
        self.assertTrue(all(row["route_name"] == "A主线" for row in rows))
        self.assertEqual([row["route_order"] for row in rows], [3, 7])
        self.assertTrue(all(row["station_role"] == "普通工位" for row in rows))


if __name__ == "__main__":
    unittest.main()
