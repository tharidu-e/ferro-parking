"""Cached, rate-limited postcodes.io bulk lookup with coordinate fallback."""
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


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
