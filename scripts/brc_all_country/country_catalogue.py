#!/usr/bin/env python3
"""Pinned Admin-0 source identities; candidate registration is deliberately disabled."""
import argparse
import hashlib
import json
import math
from pathlib import Path

PARENTS = ('FSOAP', 'FSOAS', 'BRCSOA', 'NPBRCPOA', 'WTC', 'PBRCPOA', 'DBRCPOA')
EMITTED = {'FSOAP': 'CO', 'DBRCPOA': 'BC', 'NPBRCPOA': 'OC', 'PBRCPOA': 'OC'}
COMMIT = '9380cca83db5f9aef52d5e762765100745f84b27'
MAX_ORIGINS = 244


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_ring(ring):
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError('ring must have >=4 vertices and be explicitly closed')
    for point in ring:
        if len(point) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                  or not math.isfinite(x) for x in point):
            raise ValueError('invalid coordinate')
        if not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
            raise ValueError('coordinate out of range')
    if len({tuple(p) for p in ring[:-1]}) < 3:
        raise ValueError('degenerate ring')
    longitude = ring[0][0]
    for x, _ in ring[1:]:
        longitude = x + 360 * math.floor((longitude - x + 180) / 360)
    if abs(longitude-ring[0][0]) > 1e-9:
        raise ValueError('polar winding ring requires polar classifier')


def polygons(geometry):
    if geometry.get('type') == 'Polygon':
        result = [geometry['coordinates']]
    elif geometry.get('type') == 'MultiPolygon':
        result = geometry['coordinates']
    else:
        raise ValueError('unsupported geometry type')
    if not result:
        raise ValueError('empty geometry')
    for polygon in result:
        if not polygon:
            raise ValueError('missing exterior ring')
        for ring in polygon:
            validate_ring(ring)
    return result


def ring_contains(ring, longitude, latitude):
    # Continuous longitudes prevent a 179/-179 edge from spanning the globe.
    points = [tuple(ring[0])]
    for x, y in ring[1:]:
        previous = points[-1][0]
        x += 360 * math.floor((previous - x + 180) / 360)
        points.append((x, y))
    # A ring winding once around a pole requires a distinct polar algorithm.
    # Explicit refusal keeps an unsupported topology from becoming UNS.
    if abs(points[-1][0] - points[0][0]) > 1e-9:
        raise ValueError('polar winding ring requires polar classifier')
    centre = (min(x for x, _ in points) + max(x for x, _ in points)) / 2
    x = longitude + 360 * math.floor((centre - longitude + 180) / 360)
    y = latitude
    if y < min(p[1] for p in points) or y > max(p[1] for p in points):
        return False
    if x < min(p[0] for p in points) or x > max(p[0] for p in points):
        return False
    inside = False
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) <= 1e-12 * max(1, abs(bx-ax), abs(by-ay)) and \
                min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            raise ValueError('boundary point is ambiguous')
        if (ay > y) != (by > y):
            crossing = ax + (y-ay) * (bx-ax) / (by-ay)
            if x < crossing:
                inside = not inside
    return inside


class CountryCatalogue:
    def __init__(self, document, source_sha256):
        if document.get('type') != 'FeatureCollection':
            raise ValueError('expected FeatureCollection')
        self.features = {}
        for feature in document['features']:
            code = feature['properties'].get('ADM0_A3')
            if not isinstance(code, str) or len(code) != 3 or not code.isascii() or \
                    not code.isupper() or not code.isalpha() or code in ('UNS', 'UNT'):
                raise ValueError('invalid/reserved country ID')
            if code in self.features:
                raise ValueError('duplicate country ID')
            polygons(feature['geometry'])
            self.features[code] = feature
        if not self.features:
            raise ValueError('empty catalogue')
        self.source_sha256 = source_sha256

    @classmethod
    def from_path(cls, path):
        raw = Path(path).read_bytes()
        return cls(json.loads(raw), hashlib.sha256(raw).hexdigest())

    def classify(self, longitude, latitude):
        if not math.isfinite(longitude) or not math.isfinite(latitude) or abs(latitude) > 90:
            raise ValueError('invalid query point')
        longitude = (longitude + 180) % 360 - 180
        matches = []
        for code, feature in sorted(self.features.items()):
            for polygon in polygons(feature['geometry']):
                # Latitude rejection before polar topology evaluation.
                if latitude < min(p[1] for p in polygon[0]) or \
                        latitude > max(p[1] for p in polygon[0]):
                    continue
                if ring_contains(polygon[0], longitude, latitude) and not any(
                        ring_contains(hole, longitude, latitude) for hole in polygon[1:]):
                    matches.append(code)
                    break
        if len(matches) > 1:
            raise ValueError('overlapping country geometries: ' + ','.join(matches))
        return matches[0] if matches else 'UNS'

    def manifest(self):
        entries = []
        for index, (code, feature) in enumerate(sorted(self.features.items())):
            props = feature['properties']
            entries.append({'index': index, 'code': code, 'role': 'source_country',
                            'metadata': {k: props.get(k) for k in
                                         ('NAME', 'ADMIN', 'ISO_A3', 'TYPE', 'SOV_A3', 'SOVEREIGNT')},
                            'geometry_sha256': digest(feature['geometry'])})
        for code, role in [('UNS', 'unassigned_source'), ('UNT', 'initial_background')]:
            entries.append({'index': len(entries), 'code': code, 'role': role})
        if len(entries) > MAX_ORIGINS:
            raise ValueError('catalogue exceeds registered capacity')
        manifest = {'schema': 'brc-country-catalogue-v1', 'source_sha256': self.source_sha256,
                    'source_commit': COMMIT, 'dataset': 'Natural Earth 50m Admin-0 countries',
                    'licence': 'public domain', 'identity_field': 'ADM0_A3',
                    'countries': len(self.features), 'origins': entries,
                    'classification': 'cell centre; boundary/overlap/polar-winding refusal'}
        manifest['catalogue_sha256'] = digest(manifest)
        return manifest


def registration(manifest, shape=(144, 91, 47)):
    origins = manifest['origins']
    stocks = [{'species': parent + '_' + origin['code'], 'parent': parent,
               'origin_index': origin['index'], 'background_vv': 0,
               'additional_optical_contribution': False,
               'emission_proxy': EMITTED.get(parent) if origin['code'] != 'UNT' else None}
              for parent in PARENTS for origin in origins]
    return {'schema': 'brc-country-registration-candidate-v1', 'enable_live': False,
            'catalogue_sha256': manifest['catalogue_sha256'], 'parents': list(PARENTS),
            'origin_count': len(origins), 'stock_count': len(stocks), 'stocks': stocks,
            'initial_physical_restart_destination': 'UNT', 'legacy_nonzero_ROW_restart': 'refuse',
            'grid_shape_estimate': list(shape),
            'one_float64_state_bytes': math.prod(shape) * len(stocks) * 8,
            'live_blockers': ['dynamic transport solver', 'native identifier maps',
                              'chemistry and own-stock losses', 'restart/HISTORY capacity',
                              'native positive FINN geography and parent invariance']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geojson', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    catalogue = CountryCatalogue.from_path(args.geojson)
    if len(catalogue.features) != 242:
        raise ValueError('pinned roster must contain exactly 242 countries')
    manifest = catalogue.manifest()
    args.output.mkdir(exist_ok=True)
    for filename, value in [('catalogue.json', manifest),
                            ('registration_candidate.json', registration(manifest))]:
        with (args.output / filename).open('xb') as stream:
            stream.write(canonical(value))
    print(json.dumps({'countries': 242, 'origins': 244, 'stocks': 1708,
                      'catalogue_sha256': manifest['catalogue_sha256']}))


if __name__ == '__main__':
    main()
