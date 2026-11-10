"""Offline snapshots of the legacy and current upstream Ferret MCP tool names."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
from audit_ferret_tools import capability_report
from gateway import FERRET_READ_TOOLS, FERRET_WRITE_TOOLS, FERRET_DESTRUCTIVE_TOOLS


LEGACY = frozenset("""
search_inventory ask_inventory get_item list_items list_locations
what_needs_attention shopping_list item_history coverage_check list_loans
list_categories list_collections list_warranties inventory_report
list_maintenance lookup_barcode list_providers recently_deleted
room_scan_results lend_item loan_returned add_photo scan_room
add_from_room_scan add_item_from_photo file_warranty_claim
update_warranty_claim add_provider create_item update_item
adjust_stock record_reading move_item delete_item restore_item
create_property create_location add_maintenance complete_maintenance
delete_maintenance
""".split())

MODERN = frozenset("""
search_inventory ask_inventory get_item list_items list_locations
what_needs_attention shopping_list item_history coverage_check list_loans
list_categories list_collections list_warranties inventory_report
list_maintenance lookup_barcode list_providers recently_deleted room_scan_results
get_photo list_recalls list_templates add_photo scan_room add_from_room_scan
add_item_from_photo create_item update_item adjust_stock record_reading
restore_item complete_maintenance bulk_update_items set_recall_status
attach_label save_property save_location save_maintenance save_warranty
save_warranty_claim save_loan return_loan save_provider save_category
save_collection save_coverage_limit remove
""".split())


class ToolParityTests(unittest.TestCase):
    def test_exact_legacy_modern_union(self):
        self.assertEqual(len(LEGACY), 40)
        self.assertEqual(len(MODERN), 47)
        self.assertEqual(len(LEGACY | MODERN), 58)
        self.assertEqual(
            LEGACY | MODERN,
            FERRET_READ_TOOLS | FERRET_WRITE_TOOLS | FERRET_DESTRUCTIVE_TOOLS,
        )

    def test_legacy_audit_readonly(self):
        report = capability_report(LEGACY, FERRET_READ_TOOLS)
        self.assertEqual(report["upstream_tools"], 40)
        self.assertEqual(report["reviewed_available"], 40)
        self.assertTrue(report["legacy_maintenance_api"])
        self.assertFalse(report["modern_maintenance_api"])
        self.assertTrue(report["location_write_offered"])
        self.assertFalse(report["category_write_offered"])
        self.assertIn("add_maintenance", report["disabled_write_tools"])
        self.assertIn("delete_item", report["disabled_destructive_tools"])
        self.assertEqual(report["unsupported_upstream_tools"], [])
        self.assertEqual(report["enabled_write_tools"], [])
        self.assertEqual(report["enabled_destructive_tools"], [])

    def test_modern_audit_all_normal_writes(self):
        enabled = FERRET_READ_TOOLS | FERRET_WRITE_TOOLS
        report = capability_report(MODERN, enabled)
        self.assertEqual(report["upstream_tools"], 47)
        self.assertEqual(report["reviewed_available"], 47)
        self.assertTrue(report["modern_maintenance_api"])
        self.assertTrue(report["category_write_offered"])
        self.assertIn("save_maintenance", report["enabled_write_tools"])
        self.assertIn("remove", report["disabled_destructive_tools"])
        self.assertNotIn("remove", report["enabled_destructive_tools"])
        self.assertEqual(report["unsupported_upstream_tools"], [])

    def test_unknown_future_tool_rejected_by_policy(self):
        report = capability_report(LEGACY | {"run_shell"}, FERRET_READ_TOOLS)
        self.assertEqual(report["unsupported_upstream_tools"], ["run_shell"])
        self.assertEqual(report["reviewed_available"], 40)

    def test_explicit_destructive_allowance_is_reported(self):
        report = capability_report(LEGACY, FERRET_READ_TOOLS | {"delete_maintenance"})
        self.assertEqual(report["enabled_destructive_tools"], ["delete_maintenance"])
        self.assertIn("delete_item", report["disabled_destructive_tools"])


if __name__ == "__main__":
    unittest.main()
