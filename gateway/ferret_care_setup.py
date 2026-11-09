"""Optional Ferret care and structure setup. No Homebox access or private inventory in source.

Uses only Ferret MCP: explicit --apply for writes, server-advertised tool checks,
and exact item-to-task matching. Rerunnable: existing tasks and locations are
looked up first. Only generic publicly documented device-care templates live
in this repository. No household identifiers, photos or credentials are saved.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import os
import re
import sys

from ferret_mcp_transport import FerretMCP


@dataclass(frozen=True)
class Task:
    title: str
    count: int
    unit: str
    steps: str
    source: str


@dataclass(frozen=True)
class Rule:
    pattern: str
    tasks: tuple[Task, ...]


# Frequencies from manufacturers unless explicitly labeled "Vorsorge".
# Indicator-triggered treatments are only scheduled as checks, NEVER as
# automatic descaling or preventive replacements.
RULES = (
    Rule(r"\bBambuLab\s+X1C\b", (
        Task("[Pflege] X1C Carbonstäbe prüfen", 1, "month",
             "X-Achsen-Carbonstäbe auf Staub prüfen; nur bei Bedarf mit Isopropanol und fusselfreiem Tuch reinigen. NIEMALS ölen oder fetten. Bei ABS/ASA etwa nach 5 Rollen zusätzlich kontrollieren.",
             "https://manuals.plus/m/ee63137aa736cad783cb4074617c21844f05d650827f463b343481b8ecd1466d"),
        Task("[Pflege] X1C Z-Spindeln reinigen und fetten", 3, "month",
             "Z-Gewindespindeln von Partikeln befreien und nach Anleitung dünn mit geeignetem Fett schmieren. Die X-Achsen-Carbonstäbe nicht schmieren.",
             "https://manuals.plus/m/ee63137aa736cad783cb4074617c21844f05d650827f463b343481b8ecd1466d"),
        Task("[Pflege] X1C Werkzeugkopf und Führungen prüfen", 1, "month",
             "Druckraum, Extruder, Düse, Wischer, Ventilatoren und Y/Z-Stahlführungen auf Abrieb/Filamentreste prüfen. Reinigen oder Teile ersetzen nur bei Bedarf und nach X1C-Anleitung.",
             "https://manuals.plus/m/ee63137aa736cad783cb4074617c21844f05d650827f463b343481b8ecd1466d"),
    )),
    Rule(r"\bNinja\s+Luxe\s+Caf[eé]\s+Premier\b", (
        Task("[Pflege] Ninja Luxe Café Reinigung prüfen", 1, "week",
             "Nach JEDER Benutzung Siebträger, Siebeinsatz, Milchkanne/Schneebesen und Dampfdüse gemäß ES601EU-Anleitung reinigen. Dieser Wochentermin ist nur eine Erinnerung, keine Ersetzung der täglichen Pflege. Tropfschale und Wassertank regelmäßig reinigen.",
             "https://www.sharkninja.de/blog/ninja-luxe-cafe-reinigen.html"),
        Task("[Pflege] Ninja Luxe Café Reinigungs- und Entkalkungsanzeige prüfen", 1, "month",
             "Reinigungsprogramm und Entkalkungsprogramm NUR bei entsprechender Geräteanzeige und mit freigegebenen Mitteln ausführen. Keine starre Entkalkungsfrist, keine Essig-Hausmittel. Wasserhärte-Einstellung prüfen.",
             "https://www.sharkninja.de/blog/ninja-luxe-cafe-reinigen.html"),
    )),
    Rule(r"\bOutIn\s+Fino\b", (
        Task("[Pflege] OutIn Fino Mahlwerk trocken reinigen", 1, "month",
             "Vorsorge-Erinnerung, keine Herstellerfrist: nach längerer Nutzung Bohnenbehälter und innere Mahlscheibe nach Handbuch säubern. Nur trockene Bürste/Luftbläser. NICHT mit Wasser spülen.",
             "https://de.outin.com/pages/outin-fino-faqs"),
    )),
    Rule(r"\bComfee\s+Luftentfeuchter\s+MDDF-20DEN7-WF\b", (
        Task("[Pflege] Comfee Luftfilter reinigen", 2, "week",
             "Netzstecker ziehen. Luftfilter gemäß Handbuch ausbauen, reinigen und vollständig trocknen lassen. Gerät nie ohne Filter betreiben. Bei stärkerer Verschmutzung früher.",
             "https://www.feelcomfee.com/de/produkte/klimatisieren-heizen/mddf-20den7-wf"),
        Task("[Pflege] Comfee Kondensatbehälter reinigen", 2, "week",
             "Wassertank mit mildem Reinigungsmittel und Wasser ausspülen, trocknen und sicher einsetzen. Nicht in die Spülmaschine. Bei Schlauchbetrieb zusätzlich Abfluss und Schlauch kontrollieren.",
             "https://www.feelcomfee.com/de/produkte/klimatisieren-heizen/mddf-20den7-wf"),
    )),
    Rule(r"\bIKEA\s+STARKVIND\b", (
        Task("[Pflege] STARKVIND Vorfilter reinigen", 4, "week",
             "Vorfilter bei gezogenem Netzstecker vorsichtig absaugen. Partikel- und Gasfilter NICHT waschen. IKEA empfiehlt 2–4 Wochen je nach Staubbelastung.",
             "https://www.ikea.com/de/de/customer-service/product-support/air-purifiers/"),
        Task("[Pflege] STARKVIND Partikel- und Gasfilter prüfen", 6, "month",
             "IKEA empfiehlt Filterkontrolle beziehungsweise Filterwechsel etwa alle 6 Monate; bei Anzeige oder stärkerer Belastung früher. Partikel- und Gasfilter möglichst gemeinsam ersetzen und Filteranzeige zurücksetzen.",
             "https://www.ikea.com/de/de/customer-service/product-support/air-purifiers/"),
        Task("[Pflege] STARKVIND Luftqualitätssensor prüfen", 6, "month",
             "Luftqualitätssensor vorsichtig absaugen, ohne Elektronik zu befeuchten. Vorsorge entsprechend Geräteanleitung.",
             "https://www.ikea.com/de/de/customer-service/product-support/air-purifiers/"),
    )),
    Rule(r"\bSwitchBot\s+Luftreiniger\b", (
        Task("[Pflege] SwitchBot Luftreiniger Vorfilter reinigen", 4, "week",
             "Vorfilter etwa alle 2–4 Wochen absaugen. Netzstecker ziehen. Filter nicht mit Wasser auswaschen; Außenflächen nach Bedarf trocken/leicht feucht abwischen.",
             "https://support.switch-bot.com/hc/de/articles/26181828718743-Wechselh%C3%A4ufigkeit-des-Filters-f%C3%BCr-den-SwitchBot-Luftreiniger"),
        Task("[Pflege] SwitchBot Luftreiniger Filter prüfen", 6, "month",
             "Filterzustand und App-/Filterlebensdaueranzeige prüfen. Hersteller empfiehlt Austausch je nach Nutzung nach 6–12 Monaten; Austausch nach Verschmutzung und Anzeige, nicht pauschal sofort.",
             "https://support.switch-bot.com/hc/de/articles/26181828718743-Wechselh%C3%A4ufigkeit-des-Filters-f%C3%BCr-den-SwitchBot-Luftreiniger"),
    )),
    Rule(r"\bECOFLOW\s+RIVER\s+2\s+MAX\b", (
        Task("[Pflege] EcoFlow RIVER 2 Max Lagerakku prüfen", 3, "month",
             "Nur bei LANGFRISTIGER LAGERUNG: Ladestand und Zustand kontrollieren. Nach dem zum Modell passenden RIVER-2-Max-Handbuch den Lade-/Entladezyklus durchführen und wieder ca. 60 % für die Lagerung bereitstellen. Nicht bei regulärem Gebrauch künstlich zyklisieren.",
             "https://rs.ecoflow.com/wp-content/uploads/2023/11/ECOFLOW_RIVER_2_Max-User_Manual_EU_V1.0.pdf"),
    )),
    Rule(r"\bSeverin\b.*toaster\b", (
        Task("[Pflege] Severin Toaster Krümelschublade reinigen", 4, "week",
             "Vorsorge bei regelmäßiger Nutzung: Stecker ziehen, abkühlen lassen, Krümelschublade entleeren und wieder einsetzen. Gehäuse nur trocken/leicht feucht reinigen; kein Eintauchen in Wasser.",
             "https://severin.com/wp-content/uploads/2023/04/2509.pdf"),
    )),
    Rule(r"\bKlarstein\s+Bolero\s+Smart\b", (
        Task("[Pflege] Deckenventilator Sichtprüfung", 3, "month",
             "Vorsorgevorschlag, keine gesicherte Herstellerfrist: bei abgeschaltetem Gerät sichtbare Staubablagerungen und ungewöhnliche Geräusche/Vibration prüfen. Elektroanschlüsse und Arbeiten in Höhe nur durch Fachkundige.",
             ""),
    )),
    Rule(r"^Server$", (
        Task("[Pflege] Server SMART, Backup und Kühlung kontrollieren", 1, "month",
             "Betriebliche Vorsorge: SMART-/ZFS-/RAID-Warnungen, Temperaturen, Lüfter und Backup-Protokolle kontrollieren. Kein Herstellerintervall.",
             ""),
        Task("[Pflege] Server Backup-Wiederherstellung testen", 3, "month",
             "Betriebliche Vorsorge: Stichproben-Restore auf separatem Testziel durchführen; Luftwege von außen auf Staub prüfen. Hardware nur nach sachgerechter Abschaltung öffnen.",
             ""),
    )),
)

# These are general technical category labels. No inventory details are stored.
TECH_CATEGORIES = (
    ("3D-Druck", "3D-Druck"),
    ("IT & Netzwerk", "IT & Netzwerk"),
    ("Kabel & Verbindungen", "Kabel & Adapter"),
    ("Energie & Batterien", "Energie & Batterien"),
    ("Elektronik & Licht", "Elektronik & Licht"),
)


def all_items(client):
    out = []
    for offset in range(0, 10000, 200):
        page = client.call("list_items", {"limit": 200, "offset": offset})
        rows = page.get("items")
        if not isinstance(rows, list):
            raise ValueError("Unexpected Ferret item list")
        out.extend(rows)
        if len(out) >= int(page.get("total", 0)):
            return out
    raise ValueError("Inventory exceeds safety page limit")


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get("children") or [])


def create_structure(client, available, items, *, apply, summary):
    # Missing optional tools must never block maintenance creation.
    if not {"save_location", "update_item"} <= available:
        summary["location_structure_unavailable"] = 1
    else:
        tree = client.call("list_locations")
        props = tree.get("properties") or []
        if len(props) != 1:
            raise ValueError("Expected one Ferret property; cannot choose location")
        prop = props[0]
        room = next((x for x in prop.get("locations", []) if x.get("name") == "Arbeitszimmer"), None)
        if room:
            children = room.get("children") or []
            bucket = next((x for x in children if x.get("name") == "Noch einzuordnen"), None)
            candidates = [
                x for x in items
                if x.get("locationId") == room["id"]
                and "Homebox-Lagerort: Arbeitszimmer / Noch einzuordnen" in (x.get("notes") or "")
                and "Standort prüfen" in (x.get("tags") or [])
            ]
            summary["would_move_to_review_location"] = len(candidates)
            if apply and candidates:
                if bucket is None:
                    bucket = client.call("save_location", {
                        "name": "Noch einzuordnen", "propertyId": prop["id"],
                        "parentId": room["id"],
                    })
                    summary["locations_created"] += 1
                for item in candidates:
                    client.call("update_item", {"id": item["id"], "locationId": bucket["id"]})
                    summary["moved_to_review_location"] += 1

    if not {"save_category", "update_item"} <= available:
        summary["technical_categories_unavailable"] = 1
        return
    categories = client.call("list_categories").get("categories") or []
    known = {x["name"]: x["id"] for x in flatten(categories)}
    parent = known.get("Electronics")
    if not parent:
        raise ValueError("Electronics parent category not found")
    for _tag, name in TECH_CATEGORIES:
        if name not in known:
            summary["would_create_categories"] += 1
            if apply:
                created = client.call("save_category", {"name": name, "parentId": parent})
                known[name] = created["id"]
                summary["categories_created"] += 1
    for item in items:
        # Preserve specific existing categories: Computers, Cameras, etc.
        if item.get("categoryId") != parent:
            continue
        for tag, category in TECH_CATEGORIES:
            if tag in (item.get("tags") or []) and category in known:
                summary["would_refine_categories"] += 1
                if apply:
                    client.call("update_item", {"id": item["id"], "categoryId": known[category]})
                    summary["categories_refined"] += 1
                break


def prepare_tasks(client, items, *, apply, available, summary):
    if "list_maintenance" not in available:
        raise ValueError("Ferret MCP does not expose list_maintenance")
    candidates = []
    for item in items:
        for rule in RULES:
            if re.search(rule.pattern, item.get("name") or "", flags=re.I):
                candidates.extend((item, task) for task in rule.tasks)
    summary["matched_devices"] = len({x[0]["id"] for x in candidates})
    summary["candidate_maintenance"] = len(candidates)
    missing = []
    # Query per-item to avoid accidental duplicate tasks with identical titles
    # on separate devices and to include completed one-offs.
    cached = {}
    for item, task in candidates:
        if item["id"] not in cached:
            result = client.call("list_maintenance", {"status": "all", "itemId": item["id"]})
            existing = result.get("tasks") or []
            if not isinstance(existing, list):
                raise ValueError("Unexpected Ferret maintenance task list")
            cached[item["id"]] = {str(t.get("title") or "").casefold() for t in existing}
        if task.title.casefold() in cached[item["id"]]:
            summary["already_scheduled"] += 1
        else:
            missing.append((item, task))
    summary["would_create_maintenance"] = len(missing)
    if apply and missing and "save_maintenance" not in available:
        # Never claim a reminder exists when it was only put in item notes.
        raise ValueError("Ferret MCP lacks save_maintenance; no schedule was written. Enable/upgrade the Ferret MCP write capability.")
    if not apply:
        return
    for item, task in missing:
        notes = task.steps + ("\nQuelle: " + task.source if task.source else "")
        response = client.call("save_maintenance", {
            "itemId": item["id"], "title": task.title, "notes": notes,
            "intervalCount": task.count, "intervalUnit": task.unit,
        })
        if not response.get("id"):
            raise ValueError("Ferret did not confirm created maintenance task")
        summary["scheduled_maintenance"] += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Curate Ferret maintenance and optional structure. Dry-run by default.")
    parser.add_argument("--apply", action="store_true", help="Apply confirmed changes to Ferret")
    parser.add_argument("--structure", action="store_true",
                        help="Also create technical categories and an exact Noch einzuordnen sub-room if supported")
    parser.add_argument("--structure-only", action="store_true", help="Skip scheduled maintenance creation")
    args = parser.parse_args(argv)
    token = os.environ.get("FERRET_MCP_TOKEN")
    url = os.environ.get("FERRET_MCP_URL")
    if not token or not url:
        print("Missing FERRET_MCP_TOKEN or FERRET_MCP_URL", file=sys.stderr)
        return 1
    try:
        summary = Counter()
        with FerretMCP(url, token) as client:
            available = client.available_tools()
            summary["maintenance_write_available"] = int("save_maintenance" in available)
            summary["category_write_available"] = int("save_category" in available)
            summary["location_write_available"] = int("save_location" in available)
            items = all_items(client)
            summary["inventory_count"] = len(items)
            if not args.structure_only:
                # Perform all preflight reads before any optional structure write.
                prepare_tasks(client, items, apply=False, available=available, summary=summary)
                if args.apply and summary["would_create_maintenance"] and "save_maintenance" not in available:
                    raise ValueError("No save_maintenance write tool exposed by Ferret MCP. Maintenance notes already exist, but scheduled reminders cannot be created.")
            if args.structure or args.structure_only:
                create_structure(client, available, items, apply=False, summary=summary)
            if args.apply:
                if not args.structure_only:
                    prepare_tasks(client, items, apply=True, available=available, summary=CounterProxy(summary))
                if args.structure or args.structure_only:
                    create_structure(client, available, items, apply=True, summary=CounterProxy(summary))
        print(("APPLY" if args.apply else "DRY RUN") + " - " + json.dumps(dict(summary), ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        # Never log raw payloads, URLs, error messages, or HTTP responses.
        # They could contain secret headers or private inventory information.
        kind = "Ferret tool or write permission unavailable" if isinstance(error, ValueError) else type(error).__name__
        print("Ferret care setup failed: " + kind, file=sys.stderr)
        return 1


class CounterProxy:
    """Suppress would_* counters when the apply pass repeats preflight scans."""
    def __init__(self, counter):
        self.counter = counter

    def __getitem__(self, key):
        return self.counter[key]

    def __setitem__(self, key, val):
        if not key.startswith("would_") and key not in (
            "matched_devices", "candidate_maintenance", "already_scheduled",
            "location_structure_unavailable", "technical_categories_unavailable",
        ):
            self.counter[key] = val


if __name__ == "__main__":
    sys.exit(main())
