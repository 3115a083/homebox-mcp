"""Offline migration regression tests. No calls to a real inventory."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
import migrate_to_ferret as m


class MockInventory:
    def __init__(self):
        self.events = []
        self.dest = []
        self.attachments = {}
        self.cats = [
            {"id": "cat-electronics", "name": "Electronics", "children": [
                {"id": "cat-computers", "name": "Computers", "children": []},
                {"id": "cat-cameras", "name": "Cameras", "children": []},
            ]},
            {"id": "cat-tools", "name": "Tools", "children": [
                {"id": "cat-handtools", "name": "Hand tools", "children": []},
                {"id": "cat-power", "name": "Power tools", "children": []},
            ]},
            {"id": "cat-sports", "name": "Sports & outdoors", "children": []},
            {"id": "cat-furniture", "name": "Furniture", "children": []},
            {"id": "cat-appliances", "name": "Appliances", "children": []},
        ]
        self.locations = [
            {"id": "loc-work", "name": "Arbeitszimmer", "children": []},
            {"id": "loc-kitchen", "name": "Küche", "children": []},
        ]
        self.source = [
            {"id": "hb001", "assetId": "000-001", "name": "BambuLab X1C 3D Drucker",
             "quantity": 1, "purchasePrice": 1499, "purchaseDate": "2023-09-20",
             "manufacturer": "BambuLab", "parent": {"id": "home-work"},
             "tags": [{"name": "3D-Druck"}],
             "fields": [{"name": "Erfassung", "type": "text", "textValue": "Einzelobjekt"}],
             "attachments": [
                 {"id": "photo001", "type": "photo", "title": "printer.jpg"},
                 {"id": "receipt001", "type": "receipt", "title": "private-invoice.pdf"},
                 {"id": "document001", "type": "attachment", "title": "invoice.pdf"}]},
            {"id": "hb002", "assetId": "000-002", "name": "Air filters",
             "quantity": 2, "purchasePrice": 30.11,
             "parent": {"id": "home-sort"},
             "tags": [{"name": "Haushalt & Wohnen"}],
             "fields": [{"name": "Bestandsgenauigkeit", "type": "text", "textValue": "ungefähr"}],
             "attachments": [{"id": "photo002", "type": "photo", "title": "filter.png"},
                             {"id": "receipt002", "type": "receipt", "title": "bill.jpg"}]},
        ]

    def route(self, req: httpx.Request):
        base = str(req.url)
        target = req.url.path
        method = req.method
        data = req.content
        self.events.append((method, target, data))
        if target.startswith("/home/api/v1/"):
            path = target[len("/home/api/v1/"):]
            assert req.headers.get("authorization") == "home-token"
            if method == "GET" and path == "entities":
                return httpx.Response(200, json={"items": [{"id": x["id"]} for x in self.source],
                                                  "total": len(self.source)})
            if method == "GET" and path == "entities/tree":
                return httpx.Response(200, json=[
                    {"id": "home-work", "type": "location", "name": "Arbeitszimmer",
                     "children": [{"id": "home-sort", "type": "location",
                                   "name": "Noch einzuordnen", "children": []}]},
                    {"id": "home-kitchen", "type": "location", "name": "Küche", "children": []},
                ])
            if path.startswith("entities/") and path.count("/") == 1:
                item_id = path.split("/")[1]
                found = next((x for x in self.source if x["id"] == item_id), None)
                if found:
                    return httpx.Response(200, json=found)
            if path.startswith("entities/") and "/attachments/" in path:
                assert method == "GET"
                if path.endswith("photo001"):
                    return httpx.Response(200, content=b"\xff\xd8\xff" + b"Test photo bytes",
                                          headers={"content-type": "image/jpeg"})
                if path.endswith("photo002"):
                    return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"Test photo bytes",
                                          headers={"content-type": "image/png"})
                raise AssertionError("Nonphoto bytes accessed")
        if target.startswith("/ferret/api/v1/"):
            path = target[len("/ferret/api/v1/"):]
            assert req.headers.get("authorization") == "Bearer ferret-token"
            if path == "me" and method == "GET":
                return httpx.Response(200, json={"user": {"id": "safe"}})
            if path == "categories" and method == "GET":
                return httpx.Response(200, json={"data": self.cats})
            if path == "categories" and method == "POST":
                body = __import__("json").loads(data)
                row = {"id": "cat-" + str(len(self.cats)), "name": body["name"], "children": []}
                self.cats.append(row)
                return httpx.Response(201, json=row)
            if path == "locations/tree" and method == "GET":
                return httpx.Response(200, json={"properties": [
                    {"id": "property1", "name": "Demo", "locations": self.locations}]})
            if path == "locations" and method == "POST":
                body = __import__("json").loads(data)
                row = {"id": "loc-" + str(len(self.locations)),
                       "name": body["name"], "children": []}
                parent = next((x for x in self.locations if x["id"] == body["parentId"]), None)
                (parent["children"] if parent else self.locations).append(row)
                return httpx.Response(201, json=row)
            if path == "items" and method == "GET":
                return httpx.Response(200, json={"data": self.dest, "total": len(self.dest)})
            if path == "items" and method == "POST":
                body = __import__("json").loads(data)
                body["id"] = "ferret-" + str(len(self.dest) + 1)
                self.dest.append(body)
                return httpx.Response(201, json=body)
            if path.startswith("items/") and path.endswith("/attachments") and method == "GET":
                item_id = path.split("/")[1]
                return httpx.Response(200, json={"data": self.attachments.get(item_id, [])})
            if path.startswith("items/") and path.endswith("/attachments") and method == "POST":
                item_id = path.split("/")[1]
                body = req.content
                assert b'name="kind"' in body and b"photo" in body
                assert b'name="analyze"' in body and b"false" in body
                assert b"private-invoice" not in body and b"bill.jpg" not in body
                # The actual Homebox filename should never include documents.
                new = {"id": f"img-{len(self.attachments.get(item_id, [])) + 1}"}
                name = __import__("re").search(rb'filename="([^"]+)"', body)
                assert name
                new["filename"] = name.group(1).decode()
                self.attachments.setdefault(item_id, []).append(new)
                return httpx.Response(201, json=new)
        raise AssertionError(f"Unexpected request {method} {base}")

    def clients(self):
        transport = httpx.MockTransport(self.route)
        return (
            httpx.Client(base_url="https://example.invalid/home/api/v1/",
                         headers={"Authorization": "home-token"}, transport=transport),
            httpx.Client(base_url="https://example.invalid/ferret/api/v1/",
                         headers={"Authorization": "Bearer ferret-token"}, transport=transport),
        )


class MigrationTests(unittest.TestCase):
    def test_configuration(self):
        e = {"HOMEBOX_URL": "http://homebox:7745", "HOMEBOX_TOKEN": "abc",
             "FERRET_MCP_URL": "https://ferret.example.invalid/mcp",
             "FERRET_MCP_TOKEN": "ferret_abc"}
        hb, f, hbt, ft = m.connection_settings(e)
        self.assertEqual(hb, "http://homebox:7745/api/v1/")
        self.assertEqual(f, "https://ferret.example.invalid/api/v1/")
        self.assertEqual((hbt, ft), ("abc", "ferret_abc"))
        for extra in [{"FERRET_MCP_TOKEN": "Bearer ferret_abc"},
                      {"FERRET_MCP_URL": "http://ferret.example.invalid/mcp"},
                      {"FERRET_MCP_URL": "https://host/mcp?token=abc"}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                m.connection_settings(e | extra)

    def test_exact_matching_and_collision(self):
        source = {"id": "hb001", "assetId": "000-001", "name": "Example"}
        existing = [{"id": "ferret-1", "name": "Example",
                     "notes": "Original Homebox-ID: 000-001\n\nHomebox-Objekt-ID: hb001"}]
        matched, make = m.match_existing(source, m.existing_index(existing))
        self.assertEqual(matched["id"], "ferret-1")
        self.assertFalse(make)
        with self.assertRaisesRegex(ValueError, "same name"):
            m.match_existing(source, m.existing_index([{"id": "a", "name": "Example"}]))

    def test_default_dry_run_no_writes(self):
        fake = MockInventory()
        hb, ferret = fake.clients()
        with hb, ferret:
            counts, errors = m.migrate(hb, ferret, apply=False)
        self.assertFalse(errors)
        self.assertEqual(counts["source"], 2)
        self.assertEqual(counts["would_create"], 2)
        self.assertEqual(counts["would_upload_photos"], 2)
        self.assertFalse([x for x in fake.events if x[0] == "POST"])

    def test_dry_run_with_existing_item_does_not_upload_photo(self):
        fake = MockInventory()
        fake.dest.append({
            "id": "already-1",
            "name": "BambuLab X1C 3D Drucker",
            "notes": "Homebox-ID: 000-001\n\nHomebox-Objekt-ID: hb001",
        })
        hb, ferret = fake.clients()
        with hb, ferret:
            counts, errors = m.migrate(hb, ferret, apply=False)
        self.assertFalse(errors, errors)
        self.assertEqual(counts["already_imported"], 1)
        self.assertEqual(counts["would_create"], 1)
        self.assertEqual(counts["would_upload_photos"], 2)
        self.assertEqual(len(fake.dest), 1)
        self.assertEqual(fake.attachments, {})
        self.assertFalse([event for event in fake.events if event[0] == "POST"])
        self.assertFalse([event for event in fake.events
                          if event[0] == "GET" and "/attachments/" in event[1]])

    def test_apply_then_repeat_without_duplicates_or_receipts(self):
        fake = MockInventory()
        hb, ferret = fake.clients()
        with hb, ferret:
            counts, errors = m.migrate(hb, ferret, apply=True)
            self.assertFalse(errors, errors)
            self.assertEqual(counts["created"], 2)
            self.assertEqual(counts["uploaded_photos"], 2)
            self.assertEqual(len(fake.dest), 2)
            self.assertEqual(sum(len(x) for x in fake.attachments.values()), 2)
            self.assertEqual(fake.dest[0]["purchasePriceCents"], 149900)
            self.assertNotIn("purchasePriceCents", fake.dest[1])
            self.assertIn("Standort prüfen", fake.dest[1]["tags"])
            self.assertEqual(fake.dest[1]["locationId"], "loc-2")
            self.assertNotIn("private-invoice", str(fake.dest))
            self.assertNotIn("invoice.pdf", str(fake.dest))
            again, errors = m.migrate(hb, ferret, apply=True)
        self.assertFalse(errors, errors)
        self.assertEqual(again["already_imported"], 2)
        self.assertEqual(again["already_uploaded_photos"], 2)
        self.assertEqual(len(fake.dest), 2)
        self.assertEqual(sum(len(x) for x in fake.attachments.values()), 2)
        self.assertFalse(any("receipt" in path for method, path, _ in fake.events if method == "GET"))

    def test_receipt_photo_mislabeled_is_excluded(self):
        self.assertEqual(m.source_photos({"attachments": [
            {"id": "x1", "type": "photo", "title": "scan-Rechnung.jpg"},
            {"id": "x2", "type": "photo", "title": "invoice_EN123.jpg"},
            {"id": "x3", "type": "photo", "title": "Produktfoto.jpg"},
            {"id": "x4", "type": "receipt", "title": "scan.jpg"},
            {"id": "x5", "type": "photo", "title": "Aufnahme.pdf"},
        ]}), [{"id": "x3", "type": "photo", "title": "Produktfoto.jpg"}])

    def test_photo_signatures(self):
        self.assertEqual(m.extension_for(b"\xff\xd8\xffhello"), "jpg")
        self.assertEqual(m.extension_for(b"\x89PNG\r\n\x1a\nhello"), "png")
        self.assertIsNone(m.extension_for(b"%PDF-1.5 private invoice"))
        with self.assertRaises(ValueError):
            m.photo_filename("../etc/passwd", "jpg")


if __name__ == "__main__":
    unittest.main()
