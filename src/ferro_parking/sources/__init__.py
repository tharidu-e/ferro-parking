"""Small read-only source adapters. Generic imports require evidence review."""
import csv
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen


def read_input(location):
    if str(location).startswith(('https://', 'http://')):
        with urlopen(Request(str(location), headers={'User-Agent': 'FerroParking/0.1'}), timeout=30) as response:
            return response.read().decode('utf-8-sig')
    return Path(location).read_text(encoding='utf-8-sig')


def generic(location):
    raw = read_input(location)
    data = json.loads(raw) if raw.lstrip().startswith(('[', '{')) else list(csv.DictReader(io.StringIO(raw)))
    if not isinstance(data, list):
        raise ValueError('Generic JSON must be an array of location objects')
    keys = ('name', 'address', 'postcode', 'lat', 'lon', 'url', 'tariff', 'hours', 'max_stay', 'brand')
    return [{**{key: str(row.get(key) or '') for key in keys}, 'official': False} for row in data]


# Official City of London public car park finder, ArcGIS layer 2.
CITY_LAYER = 'https://www.mapping.cityoflondon.gov.uk/arcgis/rest/services/COMPASS_Driving_and_Cycling/MapServer/2'
CITY_URL = CITY_LAYER + '/query?where=1%3D1&outFields=*&outSR=4326&f=geojson'


def city_of_london(location=None):
    data = json.loads(read_input(location or CITY_URL))
    if data.get('error') or data.get('exceededTransferLimit'):
        raise ValueError('Official finder returned an error or a truncated result')
    rows = []
    for feature in data['features']:
        properties = feature['properties']
        geometry = feature['geometry']
        if geometry['type'] != 'Point':
            raise ValueError('Official finder geometry must be a WGS84 point')
        lon, lat = geometry['coordinates'][:2]
        rows.append({'name': properties['CAR_PARKS'], 'lat': str(lat), 'lon': str(lon),
                     'address': properties.get('LOCATION', '') or '', 'postcode': '',
                     'url': CITY_URL, 'tariff': properties.get('TARIFFS', '') or '',
                     'hours': '', 'max_stay': '', 'brand': '', 'official': True})
    return rows


ADAPTERS = {'generic': generic, 'city-of-london': city_of_london}
