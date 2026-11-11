"""Small read-only source adapters. Generic imports require evidence review."""
import csv
import io
from html import unescape
import json
import re
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
    return [{**{key: str(row.get(key) or '') for key in keys}, 'official': False,
             'place_id': str(row.get('place_id') or row.get('Place ID') or '').strip()} for row in data]


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
                     'url': CITY_URL, 'tariff': re.sub(r'\?(?=\d)', '£', properties.get('TARIFFS', '') or ''),
                     'hours': '', 'max_stay': '', 'brand': '', 'official': True})
    return rows


BARNET_URL = 'https://open.barnet.gov.uk/download/23lk2/kjx/car-parks.csv'


def barnet(location=None):
    """Council's December 2014 inventory; no coordinates or current tariffs.

    Preserve names for review. Do not infer current parking terms from the
    historical Type column or manufacture pins to pass the London filter.
    """
    reader = csv.DictReader(io.StringIO(read_input(location or BARNET_URL)))
    if not reader.fieldnames or 'Car Park' not in reader.fieldnames:
        raise ValueError('Barnet CSV requires the Car Park header')
    rows = []
    for item in reader:
        name = (item.get('Car Park') or '').strip()
        if not name:
            raise ValueError('Barnet CSV contains a missing car park name')
        rows.append({'name': name, 'address': '', 'postcode': '', 'lat': '', 'lon': '',
                     'url': BARNET_URL, 'tariff': '', 'hours': '', 'max_stay': '',
                     'brand': '', 'official': True, 'source_period': '2014-12'})
    return rows


HILLINGDON_URL = ('https://services1.arcgis.com/vBu1s2ZA7rxzmHBD/ArcGIS/rest/services/'
                  'Car_Park__CPZ_and_Railways_WFL1/FeatureServer/3/query'
                  '?where=1%3D1&outFields=*&outSR=4326&f=geojson')


def hillingdon(location=None):
    """Council car park point inventory, imported for identity review only."""
    data = json.loads(read_input(location or HILLINGDON_URL))
    if data.get('error') or data.get('exceededTransferLimit'):
        raise ValueError('Official finder returned an error or a truncated result')
    crs = data.get('crs', {}).get('properties', {}).get('name', '')
    if crs and not crs.endswith((':4326', ':CRS84')):
        raise ValueError('Official finder coordinates must be WGS84')
    rows = []
    for feature in data['features']:
        props, geometry = feature['properties'], feature['geometry']
        if geometry['type'] != 'Point':
            raise ValueError('Official finder geometry must be a WGS84 point')
        name = str(props['CAR_PARK'] or '').strip()
        if not name:
            raise ValueError('Official finder contains a missing car park name')
        lon, lat = geometry['coordinates'][:2]
        rows.append({'name': name, 'lat': str(lat), 'lon': str(lon),
                     'address': '', 'postcode': str(props.get('POSTCODE') or '').strip(),
                     'url': HILLINGDON_URL, 'tariff': '', 'hours': '', 'max_stay': '',
                     'brand': '', 'official': True})
    return rows


def bromley(location=None):
    """Read a saved complete directory search and its adjacent entry pages.

    Save entries as bromley_car_park_<record ID>.html alongside the search.
    Fail on missing pages, rather than treating a partial download as coverage.
    """
    if not location or str(location).startswith(('http://', 'https://')):
        raise ValueError('Bromley requires a local directory search file and entry pages')
    raw = read_input(location)
    links = re.findall(r'<a class="list__link" href="(/directory-record/(\d+)/[^"<>]+)">'
                       r'<span class="list__link-text">([^<>]+)</span></a>', raw)
    if not links:
        raise ValueError('Bromley search contains no car park entries')
    if re.search(r'<nav[^>]+(?:class="pagination|aria-label="Pagination)', raw):
        raise ValueError('Bromley search is paginated; a complete list is required')
    rows = []
    for url, record_id, name in dict.fromkeys(links):
        page = Path(location).parent / f'bromley_car_park_{record_id}.html'
        entry = read_input(page)
        pin = re.search(r'id="map_marker_location_\d+" value="(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)"', entry)
        if not pin:
            raise ValueError(f'Bromley entry {record_id} has no exact map pin')
        rows.append({'name': unescape(name).strip(), 'lat': pin[1], 'lon': pin[2],
                     'address': '', 'postcode': '', 'url': 'https://www.bromley.gov.uk' + url,
                     'tariff': '', 'hours': '', 'max_stay': '', 'brand': '', 'official': True})
    return rows


HOUNSLOW_URL = 'https://www.hounslow.gov.uk/car-parks-spaces/parking-street'


def hounslow(location=None):
    """Read only the council's Car parks lists, excluding on-street bays."""
    raw = read_input(location or HOUNSLOW_URL)
    groups = re.findall(r'<h4>Car parks</h4>\s*<ul>(.*?)</ul>', raw, re.S)
    if len(groups) != 5:
        raise ValueError('Hounslow page must contain all five area car park lists')
    rows = []
    for group in groups:
        names = re.findall(r'<li>([^<>]+)</li>', group)
        if not names:
            raise ValueError('Hounslow area has no readable car park names')
        for name in names:
            rows.append({'name': unescape(name).strip(), 'address': '', 'postcode': '',
                         'lat': '', 'lon': '', 'url': HOUNSLOW_URL, 'tariff': '',
                         'hours': '', 'max_stay': '', 'brand': '', 'official': True})
    return rows


HAVERING_URL = 'https://www.havering.gov.uk/car-parks-1'
BEXLEY_URL = ('https://www.bexley.gov.uk/services/parking-transport-and-streets/'
              'parking-bexley/car-parks-and-street-parking')


def havering(location=None):
    """Council's car park links; embedded map view centres are not site pins."""
    raw = read_input(location or HAVERING_URL)
    links = re.findall(r'<li><a href="(https://www\.havering\.gov\.uk/car-parks-1/[^"<>]+)">([^<>]+)</a></li>', raw)
    if not links:
        raise ValueError('Havering page contains no council car park links')
    return [{'name': unescape(name).strip(), 'url': url, 'address': '', 'postcode': '',
             'lat': '', 'lon': '', 'tariff': '', 'hours': '', 'max_stay': '',
             'brand': '', 'official': True} for url, name in dict.fromkeys(links)]


def bexley(location=None):
    """Council car park headings and postcodes, without parking-term claims."""
    raw = read_input(location or BEXLEY_URL)
    if '<h3>On-street parking bays</h3>' not in raw:
        raise ValueError('Bexley page has no boundary between car parks and street bays')
    raw = raw.split('<h3>On-street parking bays</h3>', 1)[0]
    sections = re.split(r'<h4[^>]*class="[^"]*field--name-field-item-title[^"]*"[^>]*>', raw)
    if len(sections) < 2:
        raise ValueError('Bexley page contains no car park sections')
    rows = []
    for section in sections[1:]:
        name = re.match(r'([^<>]+)</h4>', section)
        postcode = re.search(r'postcode\s+([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})', section, re.I)
        if not name or not postcode:
            raise ValueError('Bexley car park section has no name or postcode')
        rows.append({'name': unescape(name[1]).strip(), 'postcode': postcode[1].upper(),
                     'url': BEXLEY_URL, 'address': '', 'lat': '', 'lon': '', 'tariff': '',
                     'hours': '', 'max_stay': '', 'brand': '', 'official': True})
    return rows


CROYDON_URL = 'https://www.croydon.gov.uk/parking/find-council-car-parks-croydon'


def croydon(location=None):
    """Read all markers embedded in the council directory, across list pages."""
    raw = read_input(location or CROYDON_URL)
    settings = re.search(r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>', raw, re.S)
    if not settings:
        raise ValueError('Croydon page contains no directory map settings')
    data = json.loads(settings[1])
    features = data.get('leaflet', {}).get('leaflet-map-view-localgov-directory-channel-embed-map', {}).get('features')
    if not features:
        raise ValueError('Croydon directory map contains no sites')
    rows = []
    for feature in features:
        popup = feature.get('popup', {}).get('value', '')
        url = re.search(r'href="(/parking/find-council-car-parks-croydon/[^"<>]+)"', popup)
        if feature.get('type') != 'point' or not url or not feature.get('title'):
            raise ValueError('Croydon marker lacks an exact site name, URL or point')
        rows.append({'name': unescape(feature['title']).strip(),
                     'lat': str(feature['lat']), 'lon': str(feature['lon']),
                     'url': 'https://www.croydon.gov.uk' + url[1],
                     'address': '', 'postcode': '', 'tariff': '', 'hours': '',
                     'max_stay': '', 'brand': '', 'official': True})
    return rows


ADAPTERS = {'generic': generic, 'city-of-london': city_of_london,
            'barnet': barnet, 'hillingdon': hillingdon, 'bromley': bromley,
            'hounslow': hounslow, 'havering': havering, 'bexley': bexley,
            'croydon': croydon}
