import tempfile
import unittest
from pathlib import Path

from web_admin_app import database, product_flow, services


class ProductFlowTest(unittest.TestCase):
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
        self.a_project = services.add_project({"name": "A产线"})
        self.b_project = services.add_project({"name": "B产线"})
        self.a_stations = [
            services.add_station(
                {"project_id": self.a_project["id"], "name": f"A工位{index}"}
            )
            for index in range(1, 6)
        ]
        self.b_stations = [
            services.add_station(
                {"project_id": self.b_project["id"], "name": f"B工位{index}"}
            )
            for index in range(1, 3)
        ]

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def create_product(self, project, barcode, product_type):
        return product_flow.resolve_barcode(
            {
                "project_id": project["id"],
                "barcode": barcode,
                "material_code": product_type,
                "product_type": product_type,
                "create_if_missing": True,
            }
        )

    def complete(self, project, station, product, barcode):
        return services.add_station_completion(
            {
                "project_id": project["id"],
                "station_id": station["id"],
                "product_instance_id": product["product_instance_id"],
                "barcode": barcode,
                "barcode_used": barcode,
            }
        )

    def prepare_switched_a(self):
        product = self.create_product(self.a_project, "AOLD001", "A")
        self.complete(self.a_project, self.a_stations[0], product, "AOLD001")
        self.complete(self.a_project, self.a_stations[1], product, "AOLD001")
        switched = product_flow.switch_main_barcode(
            {
                "project_id": self.a_project["id"],
                "station_id": self.a_stations[2]["id"],
                "product_instance_id": product["product_instance_id"],
                "old_barcode": "AOLD001",
                "new_barcode": "ANEW001",
            }
        )
        self.complete(self.a_project, self.a_stations[2], product, "ANEW001")
        return product, switched

    def prepare_completed_b(self, barcode="B001", complete_second=True):
        product = self.create_product(self.b_project, barcode, "B")
        self.complete(self.b_project, self.b_stations[0], product, barcode)
        if complete_second:
            self.complete(self.b_project, self.b_stations[1], product, barcode)
        return product

    def test_main_barcode_switch_keeps_identity_and_disables_old_barcode(self):
        product, switched = self.prepare_switched_a()
        self.assertEqual(switched["product_instance_id"], product["product_instance_id"])
        self.assertEqual(switched["current_barcode"], "ANEW001")
        old = product_flow.resolve_barcode({"barcode": "AOLD001"})
        new = product_flow.resolve_barcode({"barcode": "ANEW001"})
        self.assertFalse(old["allowed_production"])
        self.assertIn("ANEW001", old["message"])
        self.assertTrue(new["allowed_production"])
        self.assertEqual(new["product_instance_id"], product["product_instance_id"])

    def test_old_alias_can_resolve_to_current_barcode_when_not_disabled(self):
        product = self.create_product(self.a_project, "AOLD-ALLOW", "A")
        self.complete(self.a_project, self.a_stations[0], product, "AOLD-ALLOW")
        self.complete(self.a_project, self.a_stations[1], product, "AOLD-ALLOW")
        product_flow.switch_main_barcode(
            {
                "project_id": self.a_project["id"],
                "station_id": self.a_stations[2]["id"],
                "product_instance_id": product["product_instance_id"],
                "old_barcode": "AOLD-ALLOW",
                "new_barcode": "ANEW-ALLOW",
                "disable_old": False,
            }
        )
        old = product_flow.resolve_barcode({"barcode": "AOLD-ALLOW"})
        self.assertTrue(old["allowed_production"])
        self.assertEqual(old["current_barcode"], "ANEW-ALLOW")
        self.assertFalse(old["is_current"])

    def test_cross_line_dependency_blocks_until_completed_b_is_bound(self):
        a_product, _ = self.prepare_switched_a()
        b_product = self.prepare_completed_b()
        product_flow.save_station_dependency(
            self.a_stations[3]["id"],
            {
                "require_previous_station": True,
                "require_barcode_switch": True,
                "required_child_project_id": self.b_project["id"],
                "required_child_material_type": "B",
                "required_child_count": 1,
                "required_child_station_ids": [
                    station["id"] for station in self.b_stations
                ],
            },
        )
        blocked = product_flow.verify_station_entry(
            {
                "product_instance_id": a_product["product_instance_id"],
                "station_id": self.a_stations[3]["id"],
            }
        )
        self.assertFalse(blocked["allowed"])
        self.assertIn("子物料不足", blocked["message"])

        product_flow.bind_child_material(
            {
                "project_id": self.a_project["id"],
                "station_id": self.a_stations[3]["id"],
                "parent_barcode": "ANEW001",
                "child_barcode": "B001",
                "child_project_id": self.b_project["id"],
                "child_material_type": "B",
                "required_station_ids": [
                    station["id"] for station in self.b_stations
                ],
            }
        )
        allowed = product_flow.verify_station_entry(
            {
                "product_instance_id": a_product["product_instance_id"],
                "station_id": self.a_stations[3]["id"],
            }
        )
        self.assertTrue(allowed["allowed"])
        self.assertNotEqual(
            a_product["product_instance_id"], b_product["product_instance_id"]
        )

    def test_incomplete_child_cannot_be_bound(self):
        self.prepare_switched_a()
        self.prepare_completed_b(complete_second=False)
        with self.assertRaisesRegex(ValueError, "B物料未完成要求工位"):
            product_flow.bind_child_material(
                {
                    "project_id": self.a_project["id"],
                    "station_id": self.a_stations[3]["id"],
                    "parent_barcode": "ANEW001",
                    "child_barcode": "B001",
                    "child_project_id": self.b_project["id"],
                    "child_material_type": "B",
                    "required_station_ids": [
                        station["id"] for station in self.b_stations
                    ],
                }
            )

    def test_child_cannot_be_bound_to_two_parents(self):
        first_a, _ = self.prepare_switched_a()
        self.prepare_completed_b()
        product_flow.bind_child_material(
            {
                "project_id": self.a_project["id"],
                "station_id": self.a_stations[3]["id"],
                "parent_barcode": "ANEW001",
                "child_barcode": "B001",
                "required_station_ids": [
                    station["id"] for station in self.b_stations
                ],
            }
        )
        second_a = self.create_product(self.a_project, "AOLD002", "A")
        self.complete(self.a_project, self.a_stations[0], second_a, "AOLD002")
        self.complete(self.a_project, self.a_stations[1], second_a, "AOLD002")
        product_flow.switch_main_barcode(
            {
                "project_id": self.a_project["id"],
                "station_id": self.a_stations[2]["id"],
                "product_instance_id": second_a["product_instance_id"],
                "old_barcode": "AOLD002",
                "new_barcode": "ANEW002",
            }
        )
        with self.assertRaisesRegex(ValueError, "已绑定到其他产品"):
            product_flow.bind_child_material(
                {
                    "project_id": self.a_project["id"],
                    "station_id": self.a_stations[3]["id"],
                    "parent_barcode": "ANEW002",
                    "child_barcode": "B001",
                    "required_station_ids": [
                        station["id"] for station in self.b_stations
                    ],
                }
            )
        self.assertNotEqual(first_a["product_instance_id"], second_a["product_instance_id"])

    def test_trace_by_old_new_and_child_barcode(self):
        self.prepare_switched_a()
        self.prepare_completed_b()
        product_flow.bind_child_material(
            {
                "project_id": self.a_project["id"],
                "station_id": self.a_stations[3]["id"],
                "parent_barcode": "ANEW001",
                "child_barcode": "B001",
                "required_station_ids": [
                    station["id"] for station in self.b_stations
                ],
            }
        )
        old_trace = product_flow.trace_by_barcode("AOLD001")
        new_trace = product_flow.trace_by_barcode("ANEW001")
        child_trace = product_flow.trace_by_barcode("B001")
        self.assertEqual(old_trace["product"]["id"], new_trace["product"]["id"])
        self.assertEqual(new_trace["product"]["current_barcode"], "ANEW001")
        self.assertEqual(len(old_trace["switch_records"]), 1)
        self.assertEqual(len(new_trace["children"]), 1)
        self.assertEqual(len(child_trace["parents"]), 1)

    def test_step_types_and_flow_configuration_are_exported(self):
        switch_step = services.add_step(
            {
                "station_id": self.a_stations[0]["id"],
                "name": "切换A主条码",
                "type": "主条码切换",
                "step_order": 1,
                "switch_disable_old": True,
            }
        )
        bind_step = services.add_step(
            {
                "station_id": self.a_stations[0]["id"],
                "name": "绑定B",
                "type": "子物料绑定",
                "step_order": 2,
                "bind_child_project_id": self.b_project["id"],
                "bind_child_material_type": "B",
                "bind_required_station_ids": [
                    station["id"] for station in self.b_stations
                ],
            }
        )
        exported = {
            step["id"]: services.station_config_step(step)
            for step in services.list_steps(self.a_stations[0]["id"])
        }
        self.assertTrue(exported[switch_step["id"]]["switch_disable_old"])
        self.assertEqual(
            exported[bind_step["id"]]["bind_required_station_ids"],
            [station["id"] for station in self.b_stations],
        )

    def test_flow_identity_step_does_not_force_part_scan_to_be_main_barcode(self):
        services.add_step(
            {
                "station_id": self.a_stations[1]["id"],
                "name": "切换主条码",
                "type": "主条码切换",
                "step_order": 1,
            }
        )
        part_step = services.add_step(
            {
                "station_id": self.a_stations[1]["id"],
                "name": "扫描普通零件",
                "type": "扫码",
                "step_order": 2,
                "is_main_barcode": False,
            }
        )
        saved = next(
            step
            for step in services.list_steps(self.a_stations[1]["id"])
            if step["id"] == part_step["id"]
        )
        self.assertFalse(saved["is_main_barcode"])

if __name__ == "__main__":
    unittest.main()
