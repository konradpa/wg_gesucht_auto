"""Local ImmoScout search settings and Berlin district eligibility."""

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import unicodedata

import yaml


DATA = Path(__file__).resolve().parent.parent / "data" / "berlin"


def normalize_name(value):
    value = str(value).casefold().replace("ß", "ss")
    for umlaut, replacement in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        value = value.replace(umlaut, replacement)
    value = unicodedata.normalize("NFKD", value)
    return re.sub(r"[^a-z0-9]", "", value)


def ring_contains(x, y, ring):
    """Ray casting in GeoJSON longitude/latitude order, including boundaries."""
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a[:2]
        bx, by = b[:2]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def geometry_contains(x, y, geometry):
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    elif geometry["type"] != "MultiPolygon":
        raise ValueError("Expected district Polygon or MultiPolygon")
    return any(ring_contains(x, y, polygon[0]) and
               not any(ring_contains(x, y, hole) for hole in polygon[1:])
               for polygon in polygons)


def load_features(filename):
    boundaries = json.loads((DATA / filename).read_text())
    features = []
    for feature in boundaries["features"]:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        points = [point for polygon in polygons for ring in polygon for point in ring]
        bbox = (min(p[0] for p in points), min(p[1] for p in points),
                max(p[0] for p in points), max(p[1] for p in points))
        features.append((feature["properties"]["name"], geometry, bbox))
    return features


@lru_cache(maxsize=1)
def berlin_data():
    neighborhoods = json.loads((DATA / "neighborhoods.json").read_text())
    return load_features("districts.geojson"), {normalize_name(k): v for k, v in neighborhoods.items()}


@lru_cache(maxsize=1)
def berlin_neighborhoods():
    return load_features("neighborhoods.geojson")


def resolve_berlin_ortsteil(listing):
    if str(listing.get("city", "")).casefold() != "berlin":
        return None, "unknown"
    latitude, longitude = listing.get("latitude"), listing.get("longitude")
    if latitude is not None or longitude is not None:
        try:
            x, y = float(longitude), float(latitude)
            if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
                return None, "unknown"
        except (TypeError, ValueError):
            return None, "unknown"
        for name, geometry, (west, south, east, north) in berlin_neighborhoods():
            if west <= x <= east and south <= y <= north and geometry_contains(x, y, geometry):
                return name, "coordinates"
        return None, "unknown"
    quarter = re.sub(r"\s*\([^)]*\)\s*$", "", listing.get("district", "")).strip()
    key = normalize_name(quarter)
    for name, _, _ in berlin_neighborhoods():
        if normalize_name(name) == key:
            return name, "neighborhood_name"
    return None, "unknown"


def resolve_berlin_district(listing):
    """Prefer coordinates; fall back to the exact official neighborhood name.

    Present but invalid/outside coordinates do not fall back to potentially
    conflicting location text. No address is sent to a geocoding service.
    """
    if str(listing.get("city", "")).casefold() != "berlin":
        return None, "unknown"
    features, neighborhoods = berlin_data()
    latitude, longitude = listing.get("latitude"), listing.get("longitude")
    if latitude is not None or longitude is not None:
        try:
            x, y = float(longitude), float(latitude)
            if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
                return None, "unknown"
        except (TypeError, ValueError):
            return None, "unknown"
        for name, geometry, (west, south, east, north) in features:
            if west <= x <= east and south <= y <= north and geometry_contains(x, y, geometry):
                return name, "coordinates"
        return None, "unknown"
    quarter = re.sub(r"\s*\([^)]*\)\s*$", "", listing.get("district", "")).strip()
    key = normalize_name(quarter)
    if key in neighborhoods:
        return neighborhoods[key], "neighborhood"
    for name, _, _ in features:
        if normalize_name(name) == key:
            return name, "district_name"
    return None, "unknown"


@dataclass
class ImmoScoutSettings:
    region: str = "/de/berlin/berlin"
    bezirk: tuple = ()
    ortsteil: tuple = ()
    max_warm_rent: float = 1500
    min_size: float = 0
    min_rooms: float = 0
    max_pages: int = 5
    skip_paywalled: bool = True

    def __post_init__(self):
        if not isinstance(self.region, str):
            raise ValueError("immoscout.search.region must be a geographical path")
        for key in ("max_warm_rent", "min_size", "min_rooms"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"immoscout.search.{key} must be a finite non-negative number")
        if isinstance(self.max_pages, bool) or not isinstance(self.max_pages, int) or self.max_pages < 1:
            raise ValueError("immoscout.search.max_pages must be an integer >= 1")
        if not isinstance(self.skip_paywalled, bool):
            raise ValueError("immoscout.search.skip_paywalled must be true or false")
        if not isinstance(self.bezirk, (list, tuple)) or not all(isinstance(x, str) for x in self.bezirk):
            raise ValueError("immoscout.search.bezirk must be a list of district names")
        if self.bezirk:
            if self.region.rstrip("/") != "/de/berlin/berlin":
                raise ValueError("The district filter currently supports Berlin only")
            names = {normalize_name(name) for name, _, _ in berlin_data()[0]}
            unknown = [name for name in self.bezirk if normalize_name(name) not in names]
            if unknown:
                raise ValueError("Unknown Berlin district: " + ", ".join(unknown))
        if not isinstance(self.ortsteil, (list, tuple)) or not all(isinstance(x, str) for x in self.ortsteil):
            raise ValueError("immoscout.search.ortsteil must be a list of neighborhood names")
        if self.ortsteil:
            if self.region.rstrip("/") != "/de/berlin/berlin":
                raise ValueError("The neighborhood filter currently supports Berlin only")
            names = {normalize_name(name) for name, _, _ in berlin_neighborhoods()}
            unknown = [name for name in self.ortsteil if normalize_name(name) not in names]
            if unknown:
                raise ValueError("Unknown Berlin neighborhood: " + ", ".join(unknown))

    @classmethod
    def from_yaml(cls, path):
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict) or not isinstance(config.get("immoscout", {}), dict):
            raise ValueError("immoscout must be a mapping")
        block = config.get("immoscout", {}).get("search", {})
        if not isinstance(block, dict):
            raise ValueError("immoscout.search must be a mapping")
        unknown = set(block) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError("Unknown immoscout.search settings: " + ", ".join(sorted(unknown)))
        return cls(**block)

    def filter_page(self, page):
        counts = {"premium": 0, "warm_rent": 0, "size_rooms": 0, "district": 0, "unknown_location": 0}
        selected = {normalize_name(name) for name in self.bezirk}
        selected_neighborhoods = {normalize_name(name) for name in self.ortsteil}
        if selected_neighborhoods:
            counts["neighborhood"] = 0
        result = []
        for listing in page.listings:
            if self.skip_paywalled and listing["paywall_active"]:
                counts["premium"] += 1
                continue
            rent = listing.get("warm_rent")
            if not isinstance(rent, (int, float)) or not math.isfinite(rent) or rent > self.max_warm_rent:
                counts["warm_rent"] += 1
                continue
            if any(minimum > 0 and (not isinstance(listing.get(key), (int, float)) or
                                   not math.isfinite(listing[key]) or listing[key] < minimum)
                   for key, minimum in (("size", self.min_size), ("rooms", self.min_rooms))):
                counts["size_rooms"] += 1
                continue
            district, source = resolve_berlin_district(listing)
            listing = {**listing, "berlin_district": district, "district_source": source}
            neighborhood, neighborhood_source = resolve_berlin_ortsteil(listing)
            listing.update(berlin_ortsteil=neighborhood, ortsteil_source=neighborhood_source)
            if selected and (district is None or normalize_name(district) not in selected):
                counts["unknown_location" if district is None else "district"] += 1
                continue
            if selected_neighborhoods and (neighborhood is None or normalize_name(neighborhood) not in selected_neighborhoods):
                counts["unknown_location" if neighborhood is None else "neighborhood"] += 1
                continue
            result.append(listing)
        page.listings = result
        page.skipped_paywalled += counts["premium"]
        return counts
