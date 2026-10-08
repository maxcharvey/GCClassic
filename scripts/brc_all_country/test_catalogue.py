#!/usr/bin/env python3
import copy
import json
import sys
import unittest
from pathlib import Path
from country_catalogue import CountryCatalogue, canonical, digest, registration

PINNED = Path(sys.argv.pop(1))


def feature(code, rings, kind='Polygon'):
    return {'type': 'Feature', 'properties': {'ADM0_A3': code},
            'geometry': {'type': kind, 'coordinates': rings}}


def collection(*features):
    return CountryCatalogue({'type': 'FeatureCollection', 'features': list(features)}, 'fixture')


def box(x0, x1, y0, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


class CatalogueTests(unittest.TestCase):
    def test_holes_and_islands(self):
        cat = collection(feature('AAA', [[box(0, 10, 0, 10), box(2, 4, 2, 4)],
                                         [box(20, 21, 20, 21)]], 'MultiPolygon'))
        self.assertEqual(cat.classify(1, 1), 'AAA')
        self.assertEqual(cat.classify(3, 3), 'UNS')
        self.assertEqual(cat.classify(20.5, 20.5), 'AAA')
        self.assertEqual(cat.classify(50, 50), 'UNS')

    def test_dateline_and_longitude_normalization(self):
        cat = collection(feature('AAA', [box(179, -179, -2, 2)]))
        for lon in (179.5, -179.5, 180.5, 539.5):
            self.assertEqual(cat.classify(lon, 0), 'AAA')
        self.assertEqual(cat.classify(0, 0), 'UNS')

    def test_boundaries_and_overlaps_refuse(self):
        a = feature('AAA', [box(0, 10, 0, 10)])
        for point in ((0, 5), (10, 5), (5, 0), (0, 0)):
            with self.assertRaises(ValueError):
                collection(a).classify(*point)
        with self.assertRaises(ValueError):
            collection(a, feature('BBB', [box(5, 15, 5, 15)])).classify(7, 7)

    def test_malformed_and_reserved(self):
        a = feature('AAA', [box(0, 10, 0, 10)])
        bad = copy.deepcopy(a)
        bad['geometry']['coordinates'][0][-1] = [1, 1]
        nan = copy.deepcopy(a)
        nan['geometry']['coordinates'][0][1][0] = float('nan')
        for features in ((a, a), (bad,), (nan,),
                         (feature('UNT', [box(0, 1, 0, 1)]),),
                         (feature('UNS', [box(0, 1, 0, 1)]),)):
            with self.assertRaises(ValueError):
                collection(*features)
        for point in ((float('nan'), 0), (0, 91), (float('inf'), 0)):
            with self.assertRaises(ValueError):
                collection(a).classify(*point)

    def test_polar_winding_explicit_refusal(self):
        ring = [[-180, -80], [-90, -80], [0, -80], [90, -80], [180, -80], [-180, -80]]
        with self.assertRaises(ValueError):
            collection(feature('AAA', [ring]))

    def test_pinned_roster_registration(self):
        cat = CountryCatalogue.from_path(PINNED)
        manifest = cat.manifest()
        self.assertEqual(manifest['countries'], 242)
        self.assertEqual(len(manifest['origins']), 244)
        codes = [x['code'] for x in manifest['origins']]
        self.assertEqual(codes[:242], sorted(cat.features))
        self.assertEqual(codes[-2:], ['UNS', 'UNT'])
        for territory in ('PRI', 'GUM', 'GRL', 'KOS', 'CYN', 'ATC'):
            self.assertIn(territory, codes)
        reverse = {'type': 'FeatureCollection', 'features': list(reversed(list(cat.features.values())))}
        self.assertEqual(canonical(manifest), canonical(CountryCatalogue(reverse, cat.source_sha256).manifest()))
        payload = dict(manifest)
        receipt = payload.pop('catalogue_sha256')
        self.assertEqual(receipt, digest(payload))
        candidate = registration(manifest)
        self.assertFalse(candidate['enable_live'])
        self.assertEqual(candidate['stock_count'], 1708)
        self.assertEqual(len({s['species'] for s in candidate['stocks']}), 1708)
        self.assertTrue(all(not s['additional_optical_contribution'] for s in candidate['stocks']))
        self.assertTrue(all(s['emission_proxy'] is None for s in candidate['stocks']
                            if s['species'].endswith('_UNT')))
        self.assertEqual(candidate['one_float64_state_bytes'], 8415493632)

    def test_pinned_interior_points(self):
        cat = CountryCatalogue.from_path(PINNED)
        # Geographic fixtures, not emission-bearing FINN cells or border qualification.
        points = {'USA': (-100, 40), 'CAN': (-100, 60), 'BRA': (-50, -10),
                  'AUS': (135, -25), 'FRA': (2, 47), 'JPN': (139, 36),
                  'GRL': (-40, 72), 'ZAF': (25, -30), 'IND': (79, 22)}
        for expected, point in points.items():
            self.assertEqual(cat.classify(*point), expected)
        self.assertEqual(cat.classify(-140, 0), 'UNS')


if __name__ == '__main__':
    unittest.main()
