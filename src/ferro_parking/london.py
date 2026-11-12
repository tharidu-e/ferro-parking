"""London membership: borough polygons from the extract, or a postcodes.io lookup.

BoroughFilter is the one to use. It tests whether a point falls inside a
Greater London borough polygon read from the OpenStreetMap extract, which is
what the execution checklist asks for: postcode classification alone is not a
boundary test. It needs no network, so a source list downloaded once can be
imported offline, and it names the borough as well as answering yes or no.

LondonFilter remains for a source that gives postcodes and no coordinates. It
calls postcodes.io, so it cannot run without network access.
"""
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

LONDON = "London"
BOROUGH_CACHE = Path("data/cache/boroughs.geojson")


class LondonFilter:
    def __init__(self, cache='data/cache/postcodes', request=None, pause=time.sleep):
        self.cache = Path(cache)
        self.request = request or self._http
        self.pause = pause
        self.last_request = 0.0

    def _http(self, path, payload):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request('https://api.postcodes.io' + path, data=body,
                          headers={'Content-Type': 'application/json', 'User-Agent': 'FerroParking/0.1'})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def _get(self, path, payload=None):
        key = hashlib.sha256(json.dumps([path, payload], sort_keys=True).encode()).hexdigest()
        file = self.cache / (key + '.json')
        if file.exists():
            return json.loads(file.read_text())
        self.pause(max(0, 1.0 - (time.monotonic() - self.last_request)))
        data = self.request(path, payload)
        self.last_request = time.monotonic()
        if data.get('status') != 200:
            raise ValueError('postcodes.io lookup failed')
        self.cache.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data))
        return data

    def classify(self, rows):
        postcodes = sorted({r.get('postcode', '').replace(' ', '').upper() for r in rows} - {''})
        results = {}
        for offset in range(0, len(postcodes), 100):
            data = self._get('/postcodes', {'postcodes': postcodes[offset:offset+100]})
            for result in data['result']:
                results[result['query'].replace(' ', '').upper()] = result['result']
        output = []
        for row in rows:
            postcode = row.get('postcode', '').replace(' ', '').upper()
            result = results.get(postcode)
            if result is None:
                try:
                    coords = row
                    if not row.get("lat") or not row.get("lon"):
                        if not postcode:
                            raise ValueError("No postcode or coordinates")
                        from urllib.parse import quote
                        terminated = self._get("/terminated_postcodes/" + quote(postcode))["result"]
                        coords = {"lat": terminated["latitude"], "lon": terminated["longitude"]}
                    lat, lon = float(coords["lat"]), float(coords["lon"])
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError('Invalid coordinates')
                    data = self._get(f'/postcodes?lon={lon}&lat={lat}&limit=1')
                    found = data.get('result') or []
                    result = found[0] if found else None
                except (ValueError, KeyError, TypeError):
                    result = None
            output.append((row, result.get('region') if result else None))
        return output


class BoroughFilter:
    """London membership by borough polygon, with no network request.

    Parsing the extract takes minutes, so the polygons are cached as GeoJSON on
    first use and every later run loads the cache. Delete the cache to rebuild
    it from a newer extract.
    """

    def __init__(self, pbf=None, cache=BOROUGH_CACHE):
        self.cache = Path(cache)
        self.boroughs = self._load(pbf)
        if not self.boroughs:
            raise ValueError(
                "no borough polygon available: pass the OpenStreetMap extract "
                "once with --boroughs-from so the cache can be built")
        from shapely.ops import unary_union
        self.london = unary_union([b["geom_ll"] for b in self.boroughs])

    def _load(self, pbf):
        from shapely.geometry import mapping, shape
        if self.cache.exists():
            data = json.loads(self.cache.read_text(encoding="utf-8"))
            return [{"name": f["properties"]["name"], "geom_ll": shape(f["geometry"])}
                    for f in data["features"]]
        if not pbf:
            return []
        from . import osm_places
        handler = osm_places.collect(pbf)
        boroughs = [{"name": b["name"], "geom_ll": b["geom_ll"]} for b in handler.boroughs]
        if boroughs:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {"name": b["name"]},
                              "geometry": mapping(b["geom_ll"])} for b in boroughs]},
            ), encoding="utf-8")
        return boroughs

    def borough_of(self, point_ll):
        for borough in self.boroughs:
            if borough["geom_ll"].intersects(point_ll):
                return borough["name"]
        return ""

    def classify(self, rows):
        """[(row, "London" or None)]. A row inside London also gets its borough.

        A row with no usable coordinate is unresolved rather than London. The
        answer has to come from geometry, and there is none to test."""
        from shapely.geometry import Point
        output = []
        for row in rows:
            try:
                point = Point(float(row["lon"]), float(row["lat"]))
            except (KeyError, TypeError, ValueError):
                output.append((row, None))
                continue
            if not self.london.contains(point):
                output.append((row, None))
                continue
            name = self.borough_of(point)
            if name:
                row["borough"] = name
            output.append((row, LONDON))
        return output
