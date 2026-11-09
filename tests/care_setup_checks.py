"""Synthetic checks for curated Ferret maintenance; no network or user data."""
import sys
from pathlib import Path
import unittest
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
import ferret_care_setup as care


class FakeFerret:
    def __init__(self):
        self.items = [
            {"id": "item-test-a", "name": "BambuLab X1C Example Printer",
             "categoryId": "cat-elec", "locationId": "room-office",
             "tags": ["3D-Druck", "Standort prüfen"],
             "notes": "Homebox-Lagerort: Arbeitszimmer / Noch einzuordnen"},
            {"id": "item-test-b", "name": "Ninja Luxe Café Premier Example",
             "categoryId": "cat-elec", "locationId": "room-office",
             "tags": ["Haushalt & Wohnen"], "notes": ""},
            {"id": "item-test-c", "name": "Unrelated Example Item",
             "categoryId": "cat-elec", "locationId": "room-office",
             "tags": [], "notes": ""},
        ]
        self.maintenance = []
        self.calls = []
        self.locations = [
            {"id": "room-office", "name": "Arbeitszimmer", "children": []},
        ]
        self.categories = [
            {"id": "cat-elec", "name": "Electronics", "children": []},
        ]

    def call(self, name, args=None):
        args = args or {}
        self.calls.append((name, args))
        if name == "list_items":
            return {"total": len(self.items),
                    "items": self.items[args.get("offset", 0):][:args.get("limit", 50)]}
        if name == "list_maintenance":
            return {"tasks": [x for x in self.maintenance if x["itemId"] == args.get("itemId")]}
        if name == "save_maintenance":
            task = dict(args)
            task["id"] = f"care-{len(self.maintenance) + 1}"
            self.maintenance.append(task)
            return task
        if name == "list_locations":
            return {"properties": [{"id": "home-test", "name": "Example",
                                    "locations": self.locations}]}
        if name == "save_location":
            room = {"id": "review-room", "name": args["name"], "children": []}
            parent = next(x for x in self.locations if x["id"] == args["parentId"])
            parent["children"].append(room)
            return {"id": room["id"]}
        if name == "list_categories":
            return {"categories": self.categories}
        if name == "save_category":
            category = {"id": "category-" + args["name"],
                        "name": args["name"], "children": []}
            self.categories[0]["children"].append(category)
            return category
        if name == "update_item":
            item = next(x for x in self.items if x["id"] == args["id"])
            item.update(args)
            return item
        raise AssertionError("Unexpected tool: " + name)


class Tests(unittest.TestCase):
    def test_care_dryrun_never_writes(self):
        fake = FakeFerret()
        available = frozenset(["list_maintenance", "save_maintenance"])
        counter = Counter()
        care.prepare_tasks(fake, fake.items, apply=False, available=available, summary=counter)
        self.assertEqual(counter["matched_devices"], 2)
        self.assertEqual(counter["candidate_maintenance"], 5)
        self.assertEqual(counter["would_create_maintenance"], 5)
        self.assertEqual(len(fake.maintenance), 0)
        self.assertNotIn("save_maintenance", [n for n, _ in fake.calls])

    def test_no_permission_no_write(self):
        fake = FakeFerret()
        with self.assertRaisesRegex(ValueError, "lacks save_maintenance"):
            care.prepare_tasks(fake, fake.items, apply=True,
                               available=frozenset(["list_maintenance"]), summary=Counter())
        self.assertFalse(fake.maintenance)

    def test_apply_and_rerun_idempotently(self):
        fake = FakeFerret()
        available = frozenset(["list_maintenance", "save_maintenance"])
        counter = Counter()
        care.prepare_tasks(fake, fake.items, apply=True, available=available, summary=counter)
        self.assertEqual(counter["scheduled_maintenance"], 5)
        self.assertEqual(len(fake.maintenance), 5)
        self.assertTrue(all(t["intervalUnit"] in ("month", "week") for t in fake.maintenance))
        again = Counter()
        care.prepare_tasks(fake, fake.items, apply=True, available=available, summary=again)
        self.assertEqual(again["already_scheduled"], 5)
        self.assertEqual(again["would_create_maintenance"], 0)
        self.assertEqual(len(fake.maintenance), 5)

    def test_structure_absent_tools_does_not_move_items(self):
        fake = FakeFerret()
        count = Counter()
        care.create_structure(fake, frozenset(), fake.items, apply=True, summary=count)
        self.assertEqual(count["location_structure_unavailable"], 1)
        self.assertEqual(count["technical_categories_unavailable"], 1)
        self.assertEqual(fake.items[0]["locationId"], "room-office")
        self.assertNotIn("update_item", [n for n, _ in fake.calls])

    def test_exact_review_room_and_special_categories(self):
        fake = FakeFerret()
        allowed = frozenset(["list_locations", "save_location", "update_item",
                             "list_categories", "save_category"])
        count = Counter()
        care.create_structure(fake, allowed, fake.items, apply=False, summary=count)
        self.assertEqual(count["would_move_to_review_location"], 1)
        self.assertEqual(count["moved_to_review_location"], 0)
        self.assertNotIn("save_location", [n for n, _ in fake.calls])
        care.create_structure(fake, allowed, fake.items, apply=True, summary=count)
        self.assertEqual(count["locations_created"], 1)
        self.assertEqual(count["moved_to_review_location"], 1)
        self.assertEqual(fake.items[0]["locationId"], "review-room")
        self.assertEqual(fake.items[1]["locationId"], "room-office")
        self.assertEqual(count["categories_created"], len(care.TECH_CATEGORIES))
        self.assertEqual(fake.items[0]["categoryId"], "category-3D-Druck")
        # Rerun does not create an extra location or category.
        again = Counter()
        care.create_structure(fake, allowed, fake.items, apply=True, summary=again)
        self.assertEqual(again["locations_created"], 0)
        self.assertEqual(again["categories_created"], 0)

    def test_template_patterns_match_compound_model_names(self):
        import re
        examples = [
            "BambuLab X1C 3D Drucker",
            "Ninja Luxe Café Premier Kaffeemaschine",
            "OutIn Fino",
            "Comfee Luftentfeuchter MDDF-20DEN7-WF",
            "IKEA STARKVIND Luftreiniger",
            "SwitchBot Luftreiniger mit Tischplatte",
            "EF ECOFLOW RIVER 2 MAX Tragbare Powerstation",
            "Severin Doppel-Langschlitztoaster, Edelstahl",
            "Klarstein Bolero Smart Deckenventilator",
            "Server",
        ]
        self.assertEqual(len(examples), len(care.RULES))
        for rule, name in zip(care.RULES, examples):
            self.assertRegex(name, re.compile(rule.pattern, flags=re.I))

    def test_sourced_rules_require_no_personal_ids(self):
        self.assertGreaterEqual(len(care.RULES), 9)
        for rule in care.RULES:
            self.assertFalse("000-" in rule.pattern)
            for task in rule.tasks:
                self.assertIn(task.unit, ("day", "week", "month", "year"))
                self.assertGreater(task.count, 0)
                self.assertTrue(task.title.startswith("[Pflege]"))
                self.assertNotIn("inventar.", task.source)


if __name__ == "__main__":
    unittest.main()
