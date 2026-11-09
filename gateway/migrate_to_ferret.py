"""One-shot, resumable Homebox -> Ferret migration. Photos only, never receipts.

Run in the isolated Docker maintenance profile. Dry run is the default.
Everything is read from Homebox. Ferret writes require --apply and a write API key.
No files, tokens or inventory records are written to the container filesystem.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import sys
from urllib.parse import urlsplit, urlunsplit

import httpx

MAX_IMAGE_BYTES = 16 * 1024 * 1024
SOURCE_LIMIT = 10_000
SOURCE_MARKER = "Homebox-Objekt-ID: "
LEGACY_ASSET_MARKER = re.compile(r"(?m)^(?:Homebox-ID|Original Homebox-ID|Homebox-Inventarnummer):\s*(\d{3}-\d{3,})\s*$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
IMAGE_MAGIC = {
    "jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
    "gif": lambda b: b[:4] in (b"GIF87a", b"GIF89a"),
}
TAG_MAP = {
    "Important": "Wichtig",
    "IOT": "Smart Home",
    "Servers": "Server",
    "General": None,
    "Electronics": "Elektronik",
    "Appliances": "Haushalt & Wohnen",
}


def endpoint(url: str, *, require_https=False) -> str:
    parts = urlsplit(url.strip())
    if ((require_https and parts.scheme != "https") or
            parts.scheme not in ("http", "https") or not parts.hostname or
            parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("Invalid configured API URL")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + "/", "", ""))


def ferret_api_from_mcp(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("FERRET_MCP_URL must be an HTTPS MCP URL")
    if not parts.path.endswith("/mcp"):
        raise ValueError("FERRET_MCP_URL must end in /mcp")
    prefix = parts.path[:-4]
    return endpoint(urlunsplit((parts.scheme, parts.netloc, prefix + "/api/v1", "", "")), require_https=True)


def connection_settings(env: dict[str, str]):
    required = ("HOMEBOX_URL", "HOMEBOX_TOKEN", "FERRET_MCP_URL", "FERRET_MCP_TOKEN")
    missing = [x for x in required if not env.get(x)]
    if missing:
        raise ValueError("Missing environment settings: " + ", ".join(missing))
    hb = endpoint(env["HOMEBOX_URL"]) + "api/v1/"
    ferret = (endpoint(env["FERRET_API_URL"], require_https=True) if env.get("FERRET_API_URL")
              else ferret_api_from_mcp(env["FERRET_MCP_URL"]))
    key = env["FERRET_MCP_TOKEN"].strip()
    if not key or any(x.isspace() for x in key) or key.lower().startswith("bearer "):
        raise ValueError("FERRET_MCP_TOKEN must be the raw API key, without Bearer")
    return hb, ferret, env["HOMEBOX_TOKEN"], key


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def homebox_items(hb: httpx.Client):
    """Paged Homebox item discovery; never silently truncate."""
    found = []
    seen = set()
    for page in range(1, SOURCE_LIMIT // 200 + 2):
        payload = request(hb, "GET", "entities", params={"page": page, "pageSize": 200})
        if isinstance(payload, dict):
            rows = payload.get("items") or payload.get("entities") or []
            total = payload.get("total")
        elif isinstance(payload, list):
            rows, total = payload, None
        else:
            raise ValueError("Unexpected Homebox list response")
        if not rows:
            if total is not None and len(found) < int(total):
                raise ValueError("Homebox pagination ended before total was reached")
            break
        for row in rows:
            item_id = row.get("id")
            if not item_id or item_id in seen:
                raise ValueError("Homebox pagination returned a duplicate or missing ID")
            seen.add(item_id)
            found.append(row)
        if len(found) > SOURCE_LIMIT:
            raise ValueError("Homebox source has more items than migration limit")
        if total is not None and len(found) >= int(total):
            break
        if total is None and len(rows) < 200:
            break
    if not found:
        raise ValueError("Homebox returned no items; refusing empty migration")
    return [request(hb, "GET", f"entities/{entry['id']}") for entry in found]


def ferret_items(f: httpx.Client):
    result = []
    for offset in range(0, SOURCE_LIMIT + 1, 200):
        page = request(f, "GET", "items", params={"limit": 200, "offset": offset})
        data = page.get("data")
        if not isinstance(data, list):
            raise ValueError("Unexpected Ferret item list response")
        result.extend(data)
        if len(result) >= page.get("total", 0):
            break
    return result


def source_identity(item: dict) -> tuple[str, str]:
    obj_id = str(item.get("id") or "")
    asset_id = str(item.get("assetId") or "")
    if not obj_id or not asset_id:
        raise ValueError("Homebox item missing stable id or assetId")
    return obj_id, asset_id


def existing_index(items: list[dict]):
    by_uuid, by_asset, by_name = {}, {}, {}
    for item in items:
        notes = item.get("notes") or ""
        obj_match = re.search(r"(?m)^Homebox-Objekt-ID:\s*([a-zA-Z0-9-]{8,})\s*$", notes)
        if obj_match:
            by_uuid.setdefault(obj_match.group(1), []).append(item)
        id_match = LEGACY_ASSET_MARKER.search(notes)
        if id_match:
            by_asset.setdefault(id_match.group(1), []).append(item)
        by_name.setdefault((item.get("name") or "").casefold(), []).append(item)
    return by_uuid, by_asset, by_name


def match_existing(source: dict, indexes):
    by_uuid, by_asset, by_name = indexes
    uuid, asset = source_identity(source)
    matches = by_uuid.get(uuid, []) or by_asset.get(asset, [])
    if len(matches) > 1:
        raise ValueError(f"Ambiguous Ferret migration marker for {asset}")
    if len(matches) == 1:
        return matches[0], False
    if by_name.get((source.get("name") or "").casefold()):
        # A same-named item with no source marker must not be silently overwritten,
        # nor should it be duplicated. Human review is required.
        raise ValueError(f"Existing Ferret item with same name but no migration ID: {asset}")
    return None, True


def infer_category(item: dict) -> str:
    tags = {str(t.get("name") or "").lower() for t in item.get("tags") or [] if isinstance(t, dict)}
    title = (item.get("name") or "").lower()
    if "3d-druck" in tags:
        return "3D-Druck"
    if "foto & video" in tags:
        return "Cameras"
    if "sport & freizeit" in tags:
        return "Sports & outdoors"
    if "werkzeug & mechanik" in tags:
        return "Power tools" if re.search(r"(bohrmaschine|akkuschrauber|schleifer|stichsäge|fräse|dremel)", title) else "Hand tools"
    if "kabel & verbindungen" in tags:
        return "Kabel & Adapter"
    if "energie & batterien" in tags:
        return "Energie & Batterien"
    if "elektronik & licht" in tags:
        return "Elektronik & Licht"
    if "it & netzwerk" in tags or "servers" in tags:
        return "Computers" if re.search(r"(laptop|pc\b|computer|server|nas|ssd|ram|speicher|mainboard|grafikkarte)", title) else "IT & Netzwerk"
    if "haushalt & wohnen" in tags or "appliances" in tags:
        return "Furniture" if re.search(r"(stuhl|tisch|sofa|regal|möbel)", title) else "Appliances"
    if "iot" in tags:
        return "Smart Home"
    return "Electronics" if re.search(r"(sensor|kabel|adapter|platine|modul|router|wifi|usb|lan)", title) else "Tools"


def flatten_categories(nodes):
    out = []
    for node in nodes:
        out.append(node)
        out.extend(flatten_categories(node.get("children") or []))
    return out


def ensure_categories(f: httpx.Client, apply: bool):
    tree = request(f, "GET", "categories").get("data") or []
    categories = {c["name"]: c["id"] for c in flatten_categories(tree)}
    # A small, purpose-built taxonomy. Leave Ferret's starter categories intact.
    additions = [
        ("3D-Druck", "Electronics"),
        ("IT & Netzwerk", "Electronics"),
        ("Elektronik & Licht", "Electronics"),
        ("Energie & Batterien", "Electronics"),
        ("Kabel & Adapter", "Electronics"),
        ("Smart Home", "Electronics"),
    ]
    for name, parent in additions:
        if name not in categories and apply:
            created = request(f, "POST", "categories", json={"name": name, "parentId": categories[parent]})
            categories[name] = created["id"]
    return categories


def get_location_tree(hb: httpx.Client):
    raw = request(hb, "GET", "entities/tree")
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("entities") or raw.get("data") or []
    if not isinstance(raw, list):
        raise ValueError("Unexpected Homebox location tree")
    return raw


def homebox_locations(raw: list[dict]):
    """Source location node ids and hierarchical names."""
    locs = {}
    def walk(nodes, prefix=()):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            is_location = node.get("type") == "location" or (node.get("entityType") or {}).get("isLocation") is True
            if not is_location and node.get("children") is None:
                continue
            path = prefix + (str(node.get("name") or "").strip(),)
            if is_location and node.get("id"):
                locs[node["id"]] = path
                walk(node.get("children") or [], path)
            elif node.get("children"):
                walk(node["children"], prefix)
    walk(raw)
    return locs


def ferret_locations(f: httpx.Client, apply: bool, paths: dict[str, tuple[str, ...]]):
    raw = request(f, "GET", "locations/tree")
    props = raw.get("properties") or []
    if len(props) != 1:
        raise ValueError("Expected exactly one Ferret property. Choose property manually before migration.")
    prop = props[0]
    known = {}
    def index(nodes, prefix=()):
        for n in nodes:
            key = prefix + (n["name"],)
            known[key] = n["id"]
            index(n.get("children") or [], key)
    index(prop.get("locations") or [])
    for path in sorted(set(paths.values()), key=lambda p: (len(p), p)):
        if not path or path in known:
            continue
        parent_id = known.get(path[:-1])
        if len(path) > 1 and not parent_id:
            raise ValueError("Missing parent Ferret location: " + "/".join(path))
        if apply:
            created = request(f, "POST", "locations",
                              json={"propertyId": prop["id"], "name": path[-1], "parentId": parent_id})
            known[path] = created["id"]
    return known


def item_location(hb: httpx.Client, item: dict, source_locs: dict[str, tuple[str, ...]]):
    """Walk item ancestry to the nearest real room; do not invent a position."""
    seen = set()
    parent = item.get("parent") or {}
    for _ in range(25):
        parent_id = parent.get("id") if isinstance(parent, dict) else None
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        if parent_id in source_locs:
            return source_locs[parent_id]
        parent = request(hb, "GET", f"entities/{parent_id}").get("parent") or {}
    return ()


def tags_for(item: dict, placed: bool):
    original = [t.get("name") for t in item.get("tags") or [] if isinstance(t, dict) and t.get("name")]
    result = [TAG_MAP.get(tag, tag) for tag in original]
    result = [t for t in result if t]
    result.append("Homebox-Migration")
    if not placed or any(x == "Noch einzuordnen" for x in placed):
        result.append("Standort prüfen")
    fields = field_values(item)
    if fields.get("Erfassung") == "Sammelbestand":
        result.append("Sammelbestand")
    if fields.get("Bestandsgenauigkeit") in ("unbekannt", "ungefähr"):
        result.append("Bestand prüfen")
    if (item.get("warrantyExpires") or "").startswith("0001-"):
        result.append("Garantie prüfen")
    return list(dict.fromkeys(t[:40] for t in result if t))[:30]


def field_values(item):
    out = {}
    for field in item.get("fields") or []:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        typ = field.get("type")
        value = field.get("numberValue") if typ == "number" else (
            field.get("booleanValue") if typ == "boolean" else field.get("textValue"))
        if value is not None:
            out[field["name"]] = value
    return out


def price_cents(value):
    try:
        cents = int((Decimal(str(value)) * 100).quantize(Decimal("1")))
        return cents if cents >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def item_payload(item: dict, category_id: str | None, location_id: str | None,
                 place: tuple[str, ...]):
    obj_id, asset_id = source_identity(item)
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError(f"Homebox item {asset_id} has no name")
    qty = item.get("quantity")
    if not isinstance(qty, int) or qty < 0:
        qty = 1
    notes = [f"Homebox-ID: {asset_id}", f"{SOURCE_MARKER}{obj_id}",
             "Homebox-Lagerort: " + (" / ".join(place) if place else "ungeklärt")]
    if item.get("notes"):
        notes.append("Original-Notizen:\n" + str(item["notes"]))
    if item.get("purchaseFrom"):
        notes.append("Bezugsquelle: " + str(item["purchaseFrom"]))
    fields = field_values(item)
    if fields:
        notes.append("Homebox-Zusatzfelder:\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()))
    if item.get("warrantyExpires"):
        notes.append("Garantie in Homebox (ungeprüft): " + str(item["warrantyExpires"]))
    if item.get("lifetimeWarranty"):
        notes.append("Homebox: lebenslange Garantie angegeben")
    if item.get("purchasePrice") is not None and qty != 1:
        notes.append(f"Homebox-Gesamtkaufpreis: {item['purchasePrice']} EUR, NICHT als Stückpreis übernommen")
    data = {
        "name": name[:200],
        "quantity": qty,
        "notes": "\n\n".join(notes)[:9950],
        "categoryId": category_id,
        "locationId": location_id,
        "tags": tags_for(item, place),
    }
    for source, dest, limit in [
        ("manufacturer", "brand", 120), ("modelNumber", "model", 120),
        ("serialNumber", "serialNumber", 120),
    ]:
        if item.get(source):
            data[dest] = str(item[source])[:limit]
    if item.get("purchaseDate"):
        try:
            d = date.fromisoformat(str(item["purchaseDate"])[:10])
            if d.year >= 1900:
                data["purchaseDate"] = d.isoformat()
        except ValueError:
            pass
    if qty == 1:
        cents = price_cents(item.get("purchasePrice"))
        if cents is not None:
            data["purchasePriceCents"] = cents
    return data


def extension_for(raw: bytes):
    for extension, check in IMAGE_MAGIC.items():
        if check(raw):
            return extension
    return None


def source_photos(item):
    # Source type and title both matter. Some older uploads classify a scanned
    # invoice as a photo; when the name gives that away, do not transfer it.
    excluded = re.compile(r"(?:rechnung|invoice|receipt|quittung|kassenbon|\bbeleg\b|\bbill\b|manual|warranty|\.pdf$)", re.I)
    return [
        a for a in item.get("attachments") or []
        if isinstance(a, dict)
        and str(a.get("type") or "").lower() == "photo"
        and a.get("id")
        and not excluded.search(str(a.get("title") or (a.get("document") or {}).get("title") or ""))
    ]


def photo_filename(source_id: str, ext: str):
    if not SAFE_ID.fullmatch(source_id):
        raise ValueError("Unsafe Homebox attachment ID")
    return f"homebox-{source_id}.{ext}"


def read_photo(hb: httpx.Client, item: dict, attachment: dict):
    entity_id = item["id"]
    file_id = str(attachment["id"])
    if not SAFE_ID.fullmatch(file_id):
        raise ValueError("Unsafe Homebox attachment ID")
    path = f"entities/{entity_id}/attachments/{file_id}"
    data = bytearray()
    with hb.stream("GET", path) as response:
        response.raise_for_status()
        value = response.headers.get("content-length")
        if value:
            try:
                if int(value) > MAX_IMAGE_BYTES:
                    raise ValueError("Photo exceeds 16 MiB")
            except ValueError:
                if value.isdecimal():
                    raise
                raise ValueError("Invalid Homebox Content-Length") from None
        for chunk in response.iter_bytes():
            if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                raise ValueError("Photo exceeds 16 MiB")
            data.extend(chunk)
    ext = extension_for(data)
    if ext is None:
        raise ValueError("Photo has an unsupported file signature")
    return bytes(data), photo_filename(file_id, ext)


def migrate(hb: httpx.Client, ferret: httpx.Client, *, apply=False, limit=0, photos=True):
    request(ferret, "GET", "me")  # Confirm API-key auth before reading 195 records.
    items = homebox_items(hb)
    dest = ferret_items(ferret)
    indexes = existing_index(dest)
    source_tree = homebox_locations(get_location_tree(hb))
    categories = ensure_categories(ferret, apply)
    locations = ferret_locations(ferret, apply, source_tree)
    counts = Counter(source=len(items), existing_destination=len(dest))
    errors = []
    for item in items[:limit or None]:
        try:
            obj_id, asset_id = source_identity(item)
            existing, create = match_existing(item, indexes)
            place = item_location(hb, item, source_tree)
            category = categories.get(infer_category(item))
            body = item_payload(item, category, locations.get(place), place)
            if create:
                if not apply:
                    counts["would_create"] += 1
                    counts["would_upload_photos"] += len(source_photos(item)) if photos else 0
                    continue
                row = request(ferret, "POST", "items", json=body)
                counts["created"] += 1
                existing = row
                indexes[0][obj_id] = [row]
                indexes[1][asset_id] = [row]
            else:
                counts["already_imported"] += 1
            if not photos:
                continue
            attached = request(ferret, "GET", f"items/{existing['id']}/attachments")
            filenames = {f.get("filename") for f in attached.get("data") or []}
            for image in source_photos(item):
                if any(str(f).startswith("homebox-" + str(image["id"]) + ".") for f in filenames if f):
                    counts["already_uploaded_photos"] += 1
                    continue
                try:
                    raw, filename = read_photo(hb, item, image)
                    result = request(ferret, "POST", f"items/{existing['id']}/attachments",
                                     files={"file": (filename, raw, "image/" + ("jpeg" if filename.endswith(".jpg") else filename.rsplit(".", 1)[-1]))},
                                     data={"kind": "photo", "analyze": "false",
                                           "main": "true" if not filenames else "false"})
                    if not result or not result.get("id"):
                        raise ValueError("Ferret photo upload returned no attachment id")
                    filenames.add(filename)
                    counts["uploaded_photos"] += 1
                except (httpx.HTTPError, ValueError, KeyError) as ex:
                    counts["photo_errors"] += 1
                    errors.append(f"{asset_id}: photo {image['id']}: {type(ex).__name__}")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as ex:
            counts["item_errors"] += 1
            errors.append(f"{item.get('assetId') or 'unknown'}: {type(ex).__name__}: {str(ex)[:90]}")
    return counts, errors


def main(argv=None, *, env=None):
    parser = argparse.ArgumentParser(description="Homebox to Ferret: items and photos, NO receipts or documents.")
    parser.add_argument("--apply", action="store_true", help="Write to Ferret. Without this flag: dry-run only.")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N items (0: all)")
    parser.add_argument("--items-only", action="store_true", help="Skip photos; never import documents")
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    try:
        hb_url, f_url, hb_token, f_token = connection_settings(dict(env or os.environ))
        with httpx.Client(base_url=hb_url, headers={"Authorization": hb_token},
                          timeout=45, follow_redirects=False) as hb, \
             httpx.Client(base_url=f_url, headers={"Authorization": f"Bearer {f_token}"},
                          timeout=90, follow_redirects=False) as f:
            counts, errors = migrate(hb, f, apply=args.apply, limit=args.limit,
                                     photos=not args.items_only)
        print(("APPLY" if args.apply else "DRY RUN") + " - " + json.dumps(dict(counts), ensure_ascii=False, sort_keys=True))
        if errors:
            for error in errors[:30]:
                print("ERROR", error, file=sys.stderr)
            if len(errors) > 30:
                print(f"... and {len(errors)-30} more errors", file=sys.stderr)
            return 2
        return 0
    except (ValueError, httpx.HTTPError, KeyError) as error:
        # Never emit HTTP error bodies, response headers, secrets or file bytes.
        print("Migration failed: " + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
