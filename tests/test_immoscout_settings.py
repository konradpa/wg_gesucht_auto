import json
from pathlib import Path
import tempfile
import unittest

from src.immoscout_settings import (
    ImmoScoutSettings, geometry_contains, resolve_berlin_district, resolve_berlin_ortsteil,
)
from src.immoscout_web_api import SearchPage


def listing(**overrides):
    return {"id": "test", "city": "Berlin", "district": "Prenzlauer Berg (Prenzlauer Berg)",
            "latitude": None, "longitude": None, "warm_rent": 1000,
            "size": 50, "rooms": 2, "paywall_active": False, **overrides}


class DistrictTests(unittest.TestCase):
    def test_neighborhood_geometry_and_exact_name_fallback(self):
        for lat, lon, name in [(52.541, 13.413, "Prenzlauer Berg"),
                               (52.499, 13.418, "Kreuzberg"),
                               (52.46726, 13.37928, "Tempelhof")]:
            self.assertEqual(resolve_berlin_ortsteil(listing(latitude=lat, longitude=lon)),
                             (name, "coordinates"))
        self.assertEqual(resolve_berlin_ortsteil(listing()), ("Prenzlauer Berg", "neighborhood_name"))
        self.assertEqual(resolve_berlin_ortsteil(listing(district="Koepenick (Koepenick)")),
                         ("Köpenick", "neighborhood_name"))

    def test_invalid_coordinates_do_not_use_neighborhood_text(self):
        for lat, lon in [(53.55, 10), (float("nan"), 13), (52.5, None)]:
            self.assertEqual(resolve_berlin_ortsteil(listing(latitude=lat, longitude=lon)), (None, "unknown"))
        self.assertEqual(resolve_berlin_ortsteil(listing(district="Pankow (Pankow)", city="Hamburg")),
                         (None, "unknown"))

    def test_real_district_polygons_and_coordinate_order(self):
        for lat, lon, expected in [(52.46726, 13.37928, "Tempelhof-Schöneberg"),
                                   (52.5200, 13.4050, "Mitte"),
                                   (52.541, 13.413, "Pankow")]:
            with self.subTest(expected=expected):
                self.assertEqual(resolve_berlin_district(listing(latitude=lat, longitude=lon)),
                                 (expected, "coordinates"))

    def test_missing_coordinates_use_official_neighborhood(self):
        self.assertEqual(resolve_berlin_district(listing()), ("Pankow", "neighborhood"))
        self.assertEqual(resolve_berlin_district(listing(district="Haselhorst (Spandau)")),
                         ("Spandau", "neighborhood"))
        self.assertEqual(resolve_berlin_district(listing(district="Koepenick (Koepenick)")),
                         ("Treptow-Köpenick", "neighborhood"))

    def test_coordinates_take_precedence_over_conflicting_text(self):
        self.assertEqual(resolve_berlin_district(listing(latitude=52.5200, longitude=13.4050))[0], "Mitte")
        for lat, lon in [(53.55, 10), (float("nan"), 13), (52.5, None)]:
            self.assertIsNone(resolve_berlin_district(listing(latitude=lat, longitude=lon))[0])
        self.assertIsNone(resolve_berlin_district(listing(city="Hamburg"))[0])

    def test_polygon_holes_and_multipolygons(self):
        geometry = {"type": "Polygon", "coordinates": [
            [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
            [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
        ]}
        self.assertTrue(geometry_contains(3, 3, geometry))
        self.assertFalse(geometry_contains(1.5, 1.5, geometry))
        self.assertFalse(geometry_contains(5, 3, geometry))
        self.assertTrue(geometry_contains(0, 2, geometry))
        self.assertTrue(geometry_contains(3, 3, {"type": "MultiPolygon", "coordinates": [geometry["coordinates"]]}))


class SettingsTests(unittest.TestCase):
    def test_neighborhoods_only_filter_and_combined_district_filter(self):
        def page():
            return SearchPage([listing(), listing(district="Kreuzberg (Kreuzberg)"),
                               listing(district="Friedrichshain (Friedrichshain)")],
                              1, 20, 2, 3, "next")
        result = page()
        ImmoScoutSettings(ortsteil=["Prenzlauer Berg", "Kreuzberg"]).filter_page(result)
        self.assertEqual([l["berlin_ortsteil"] for l in result.listings], ["Prenzlauer Berg", "Kreuzberg"])
        result = page()
        ImmoScoutSettings(bezirk=["Pankow"], ortsteil=["Prenzlauer Berg", "Kreuzberg"]).filter_page(result)
        self.assertEqual([l["berlin_ortsteil"] for l in result.listings], ["Prenzlauer Berg"])

    def test_neighborhood_filter_excludes_unknown_and_preserves_empty_page_pagination(self):
        page = SearchPage([listing(district="Unknown")], 1, 20, 2, 1, "next")
        counts = ImmoScoutSettings(ortsteil=["Prenzlauer Berg"]).filter_page(page)
        self.assertEqual(page.listings, [])
        self.assertEqual(counts["unknown_location"], 1)
        self.assertEqual(page.next_url, "next")

    def test_invalid_neighborhood_settings_fail_before_search(self):
        for kwargs in [{"ortsteil": "Kreuzberg"}, {"ortsteil": ["Prenzlauer"]},
                       {"ortsteil": ["Charlottenburg-Wilmersdorf"]},
                       {"ortsteil": ["Kreuzberg"], "region": "/de/hamburg/hamburg"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ImmoScoutSettings(**kwargs)

    def test_filters_preserve_empty_page_pagination_and_reject_unknown_rent_location(self):
        page = SearchPage([listing(paywall_active=True), listing(warm_rent=None),
                           listing(warm_rent=1501), listing(district="unknown"),
                           listing(district="Spandau (Spandau)")], 1, 20, 3, 41, "next")
        counts = ImmoScoutSettings(bezirk=["Pankow"]).filter_page(page)
        self.assertEqual(page.listings, [])
        self.assertEqual(page.next_url, "next")
        self.assertEqual(page.total_hits, 41)
        self.assertEqual(counts, {"premium": 1, "warm_rent": 2, "size_rooms": 0,
                                  "district": 1, "unknown_location": 1})

    def test_multiple_districts_normalization_and_inclusive_warm_budget(self):
        page = SearchPage([listing(warm_rent=1500), listing(district="Köpenick (Köpenick)"),
                           listing(district="Mitte (Mitte)")], 1, 20, 1, 3, None)
        ImmoScoutSettings(bezirk=["Pankow", "Treptow-Koepenick"]).filter_page(page)
        self.assertEqual([l["berlin_district"] for l in page.listings], ["Pankow", "Treptow-Köpenick"])

    def test_bad_settings_fail_instead_of_silently_widening_search(self):
        for kwargs in [{"bezirk": ["Prenzlauer Berg"]}, {"bezirk": "Pankow"},
                       {"max_warm_rent": -1}, {"max_warm_rent": float("nan")},
                       {"max_pages": 0}, {"skip_paywalled": "false"},
                       {"region": "/de/hamburg/hamburg", "bezirk": ["Pankow"]}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ImmoScoutSettings(**kwargs)

    def test_yaml_block_is_separate_from_wg_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text('search: {max_price: 650}\nimmoscout:\n  search:\n    max_warm_rent: 1200\n    bezirk: [Pankow]\n')
            settings = ImmoScoutSettings.from_yaml(path)
        self.assertEqual(settings.max_warm_rent, 1200)
        self.assertEqual(settings.bezirk, ["Pankow"])

    def test_misspelled_yaml_settings_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text('immoscout: {search: {max_warm_miete: 500}}')
            with self.assertRaisesRegex(ValueError, "max_warm_miete"):
                ImmoScoutSettings.from_yaml(path)


if __name__ == "__main__":
    unittest.main()
