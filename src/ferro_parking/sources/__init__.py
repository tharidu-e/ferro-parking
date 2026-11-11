"""Small read-only source adapters. Generic imports require evidence review."""
import csv
import io
from html import unescape
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote_plus
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


BARNET_CSV_URL = 'https://open.barnet.gov.uk/download/23lk2/kjx/car-parks.csv'
BARNET_URL = 'https://www.barnet.gov.uk/parking/car-parks-and-street-parking-locations'


def barnet_2014(location):
    """Council's December 2014 inventory; no coordinates or current tariffs.

    Preserve names for review. Do not infer current parking terms from the
    historical Type column or manufacture pins to pass the London filter.
    """
    reader = csv.DictReader(io.StringIO(read_input(location)))
    if not reader.fieldnames or 'Car Park' not in reader.fieldnames:
        raise ValueError('Barnet CSV requires the Car Park header')
    rows = []
    for item in reader:
        name = (item.get('Car Park') or '').strip()
        if not name:
            raise ValueError('Barnet CSV contains a missing car park name')
        rows.append({'name': name, 'address': '', 'postcode': '', 'lat': '', 'lon': '',
                     'url': BARNET_CSV_URL, 'tariff': '', 'hours': '', 'max_stay': '',
                     'brand': '', 'official': True, 'source_period': '2014-12'})
    return rows


def barnet(location=None):
    """Current council list only; the old CSV is a separate cross-check."""
    raw = read_input(location or BARNET_URL)
    headings = list(re.finditer(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>', raw, re.S | re.I))
    section = None
    for index, heading in enumerate(headings):
        title = unescape(re.sub(r'<[^>]*>', '', heading[1])).strip()
        if title.casefold() == 'barnet car parks':
            end = headings[index + 1].start() if index + 1 < len(headings) else len(raw)
            section = raw[heading.end():end]
            break
    listing = re.search(r'<ul\b[^>]*>(.*?)</ul>', section or '', re.S | re.I)
    if not listing:
        raise ValueError('Barnet current page has no Barnet car parks list; CSV and interruption pages are not current inventories')
    rows = []
    for item in re.findall(r'<li\b[^>]*>(.*?)</li>', listing[1], re.S | re.I):
        text = ' '.join(unescape(re.sub(r'<[^>]*>', ' ', item)).split())
        text = text.translate({0x2013: '-', 0x2014: '-'})
        parts = re.split(r'\s*-\s*', text, maxsplit=1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError('Barnet current listing lacks a site name and address')
        name, address = parts
        postcode = re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', address)
        rows.append({'name': name, 'address': address.split('|', 1)[0].strip(),
                     'postcode': postcode[0] if postcode else '', 'lat': '', 'lon': '',
                     'url': BARNET_URL, 'tariff': '', 'hours': '', 'max_stay': '',
                     'brand': '', 'official': True, 'identity_quote': text})
    if not rows:
        raise ValueError('Barnet current list is empty')
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


GREENWICH_URL = 'https://www.royalgreenwich.gov.uk/directory/19/car_parks'


def greenwich(location=None):
    """Match official directory map marker names and pins by record ID."""
    raw = read_input(location or GREENWICH_URL)
    info = dict(re.findall(r'id="map_marker_info_(\d+)" value="([^"<>]+)"', raw))
    pins = {record_id: (lat, lon) for record_id, lat, lon in re.findall(
        r'id="(\d+)" class="mapMarkers" value="(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"', raw)}
    if not info or info.keys() != pins.keys():
        raise ValueError('Greenwich inventory has missing map names or pins')
    rows = []
    for record_id, encoded in info.items():
        anchor = unquote_plus(unescape(encoded))
        site = re.fullmatch(r'<a href="(https://www\.royalgreenwich\.gov\.uk/directory_record/'
                            + record_id + r'/[^"<>]+)">([^<>]+)</a>', anchor)
        if not site:
            raise ValueError('Greenwich marker lacks its exact official site URL or name')
        lat, lon = pins[record_id]
        rows.append({'name': unescape(site[2]).strip(), 'lat': lat, 'lon': lon,
                     'url': site[1], 'postcode': '', 'address': '', 'tariff': '',
                     'hours': '', 'max_stay': '', 'brand': '', 'official': True})
    return rows


def _plain_text(markup):
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', markup)).split()).translate({0x2013: '-', 0x2014: '-'})


def _heading_sections(raw, level):
    headings = list(re.finditer(rf'<h{level}\b[^>]*>(.*?)</h{level}>', raw, re.S | re.I))
    return [(_plain_text(h[1]), raw[h.end():headings[i + 1].start() if i + 1 < len(headings) else len(raw)])
            for i, h in enumerate(headings)]


def _inventory_identity(name, url, detail=''):
    postcode = re.search(r'\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b', detail)
    return {'name': name, 'url': url, 'address': '', 'postcode': postcode[0] if postcode else '',
            'lat': '', 'lon': '', 'tariff': '', 'hours': '', 'max_stay': '', 'brand': '',
            'official': True, 'identity_quote': detail}


REDBRIDGE_URL = 'https://www.redbridge.gov.uk/parking/car-parks-and-on-street-parking/'


def redbridge(location=None):
    """The council inventory distinguishes the two Eastwood sites by RingGo code."""
    raw = read_input(location or REDBRIDGE_URL)
    sections = [body for title, body in _heading_sections(raw, 2) if title == 'Council car parks']
    if len(sections) != 1:
        raise ValueError('Redbridge page has no unique council car park inventory')
    rows = []
    for name, body in _heading_sections(sections[0], 3):
        text = _plain_text(body)
        code = re.search(r'RingGo Location Number:\s*(\d+)', text)
        if not code:
            continue  # Area headings have no site code.
        row = _inventory_identity(name, REDBRIDGE_URL, text)
        row['location_code'] = code[1]
        rows.append(row)
    if not rows or len({r['location_code'] for r in rows}) != len(rows):
        raise ValueError('Redbridge inventory is empty or repeats a site code')
    return rows


WALTHAM_FOREST_URL = ('https://www.walthamforest.gov.uk/parking-roads-and-travel/'
                      'car-parks-and-street-parking/council-car-parks')


def waltham_forest(location=None):
    """Expand grouped council tariff headings into distinct site identities."""
    raw = read_input(location or WALTHAM_FOREST_URL)
    sections = [body for title, body in _heading_sections(raw, 2) if title == 'Council car park charges']
    if len(sections) != 1:
        raise ValueError('Waltham Forest page has no council car park section')
    rows = []
    for title, body in _heading_sections(sections[0], 3):
        for name in re.split(r',\s*|\s+and\s+', title):
            if not re.search(r'\bE\d{1,2}$', name):
                raise ValueError('Waltham Forest heading lacks a site name and district')
            rows.append(_inventory_identity(name, WALTHAM_FOREST_URL, title))
    if not rows:
        raise ValueError('Waltham Forest inventory is empty')
    return rows


NEWHAM_URL = 'https://www.newham.gov.uk/directory/2/car-parks-in-newham'


def newham(location=None):
    """Read every linked area and saved exact site page; never count the index."""
    if not location or str(location).startswith(('http://', 'https://')):
        raise ValueError('Newham requires the local index, area pages and site pages')
    root = Path(location).parent
    areas = dict.fromkeys(re.findall(r'href="/directory/2/car-parks-in-newham/category/(\d+)"', read_input(location)))
    if not areas:
        raise ValueError('Newham index has no area lists')
    sites = {}
    for area in areas:
        page = read_input(root / f'newham-{area}.html')
        links = re.findall(r'href="(/directory-record/(\d+)/[^"<>]+)"', page)
        if not links:
            raise ValueError('Newham area page has no car park entries')
        sites.update((record_id, url) for url, record_id in links)
    rows = []
    for record_id, url in sites.items():
        page = read_input(root / f'newham-site-{record_id}.html')
        heading = re.search(r'<h1\b[^>]*>(.*?)</h1>', page, re.S)
        if not heading or not _plain_text(heading[1]).endswith(' - Car parks in Newham'):
            raise ValueError('Newham site page has no exact inventory title')
        name = _plain_text(heading[1]).removesuffix(' - Car parks in Newham')
        fields = {_plain_text(key): _plain_text(value) for key, value in re.findall(
            r'<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>', page, re.S)}
        address = fields.get('Address', '')
        row = _inventory_identity(name, 'https://www.newham.gov.uk' + url, address)
        row['address'] = address
        rows.append(row)
    return rows


RICHMOND_URL = 'https://www.richmond.gov.uk/car_parks'


def richmond_upon_thames(location=None):
    """Read every council area page linked by the saved complete index."""
    if not location or str(location).startswith(('http://', 'https://')):
        raise ValueError('Richmond requires a local index and all linked area pages')
    links = dict.fromkeys(re.findall(r'href="(/services/parking/car_parks/([a-z_]+_area_car_parks))"', read_input(location)))
    if not links:
        raise ValueError('Richmond index has no area inventory links')
    rows = []
    for url, slug in links:
        page = read_input(Path(location).parent / f'richmond-upon-thames-{slug}.html')
        area = []
        for title, body in _heading_sections(page, 2):
            detail = _plain_text(body)
            if 'Postcode:' in detail and 'Map:' in detail:
                area.append(_inventory_identity(title, 'https://www.richmond.gov.uk' + url, detail))
        if not area:
            raise ValueError('Richmond area page has no readable site inventory')
        rows.extend(area)
    return rows


EALING_URL = 'https://www.ealing.gov.uk/download/downloads/id/5404/car_park_charges_spaces_and_opening_times.pdf'


def ealing(location=None):
    """Read the dated official PDF, or its pdftotext -layout output, as identity only."""
    if not location or str(location).startswith(('http://', 'https://')):
        raise ValueError('Ealing requires a local PDF or layout-preserved text file')
    if Path(location).suffix.lower() == '.pdf':
        try:
            raw = subprocess.run(['pdftotext', '-layout', str(location), '-'],
                                 check=True, capture_output=True, text=True).stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise ValueError('Ealing PDF needs pdftotext -layout; a saved text extract is also accepted') from exc
    else:
        raw = read_input(location)
    marker = 'Emission based Rates - Table 2a'
    if 'FEES AND CHARGES FOR OFF-STREET CAR PARKS' not in raw or marker not in raw:
        raise ValueError('Ealing input is not the official off-street inventory layout')
    table = raw.split(marker, 1)[1].split('Version ', 1)[0]
    rows = []
    for line in table.splitlines():
        match = re.match(r'^\s*(\S.*?)\s{2,}(\d{5})(?:\s|$)', line)
        if not match:
            continue
        name = match[1].strip().removesuffix('*').strip()
        row = _inventory_identity(name, EALING_URL, line.strip())
        row['location_code'] = match[2]
        row['source_closed'] = match[1].strip().endswith('*')
        rows.append(row)
    # This disabled-only site is in the main inventory but has no paid tariff code.
    if re.search(r'\bWE03\s+Singapore Road', raw):
        row = _inventory_identity('Singapore Road Car Park', EALING_URL, 'WE03 Singapore Road - Surface')
        row['location_code'] = 'WE03'
        row['source_closed'] = False
        rows.append(row)
    if not rows or len({r['location_code'] for r in rows}) != len(rows):
        raise ValueError('Ealing inventory is empty or repeats a site code')
    updated = re.search(r'Updated:\s*(\d{2}/\d{2}/\d{4})', raw)
    for row in rows:
        row['source_period'] = updated[1] if updated else 'Not stated'
    return rows


MERTON_URL = 'https://www.merton.gov.uk/streets-parking-transport/parking/charges'


def merton(location=None):
    """Use the site-by-area table, not repeated season-ticket or tariff bands."""
    raw = read_input(location or MERTON_URL)
    inventories = []
    for table in re.findall(r'<table\b[^>]*>.*?</table>', raw, re.S):
        table_rows = re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.S)
        cells = [[_plain_text(cell) for cell in re.findall(r'<t[hd]\b[^>]*>(.*?)</t[hd]>', row, re.S)] for row in table_rows]
        if cells and cells[0] and cells[0][0] == 'Car park (by area)':
            inventories.append(cells[1:])
    if len(inventories) != 1 or not inventories[0]:
        raise ValueError('Merton page has no unique site-by-area inventory')
    rows = []
    for cells in inventories[0]:
        if len(cells) != 3 or not cells[0]:
            raise ValueError('Merton inventory contains an incomplete site row')
        rows.append(_inventory_identity(cells[0], MERTON_URL, cells[0]))
    return rows


HARROW_URL = 'https://www.harrow.gov.uk/parking-permits/council-car-parks-street-parking'


def harrow(location=None):
    """Read the named car park sections, leaving the published terms for research."""
    rows = []
    for title, body in _heading_sections(read_input(location or HARROW_URL), 2):
        detail = _plain_text(body)
        if 'Car park type:' in detail and 'Post Code:' in detail:
            rows.append(_inventory_identity(title, HARROW_URL, detail))
    if not rows:
        raise ValueError('Harrow page has no named car park sections')
    return rows


def _accordion_sections(raw):
    headings = list(re.finditer(r'<h3\b[^>]*>(.*?)</h3>', raw, re.S))
    for index, heading in enumerate(headings):
        label = re.search(r'<span class="accordion-pane__heading">(.*?)</span>', heading[1], re.S)
        if label:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(raw)
            yield _plain_text(label[1]), raw[heading.end():end]


SOUTHWARK_URL = 'https://www.southwark.gov.uk/parking-streets-and-transport/parking/places-park/car-parks'


def southwark(location=None):
    """The named pay-to-park inventory only; park facilities have separate scope."""
    raw = read_input(location or SOUTHWARK_URL)
    rows = [_inventory_identity(name, SOUTHWARK_URL, _plain_text(body))
            for name, body in _accordion_sections(raw) if name.lower().endswith('car park')]
    count = re.search(r'We run (\d+) car parks', _plain_text(raw))
    if not rows or not count or len(rows) != int(count[1]):
        raise ValueError('Southwark named list does not match its published count')
    return rows


KINGSTON_URL = 'https://www.kingston.gov.uk/parking/car-parks'


def kingston_upon_thames(location=None):
    """Read every saved page of the council's paginated car park directory."""
    if not location or str(location).startswith(('http://', 'https://')):
        raise ValueError('Kingston requires a saved index and all directory pages')
    raw = read_input(location)
    page_count = max([0] + [int(n) for n in re.findall(r'href="\?page=(\d+)"', raw)]) + 1
    rows = []
    for page in range(page_count):
        text = raw if page == 0 else read_input(Path(location).parent / f'kingston-page-{page + 1}.html')
        if any(int(n) >= page_count for n in re.findall(r'href="\?page=(\d+)"', text)):
            raise ValueError('Kingston directory has more pages than the saved index')
        links = re.findall(r'<a href="(/parking/car-parks/[^"<>]+)"[^>]*class="teaser-link"[^>]*>.*?<h2>(.*?)</h2>.*?</a>', text, re.S)
        if not links:
            raise ValueError('Kingston directory page has no readable car park entries')
        rows.extend(_inventory_identity(_plain_text(name), 'https://www.kingston.gov.uk' + url)
                    for url, name in links)
    if len({r['url'] for r in rows}) != len(rows):
        raise ValueError('Kingston pages repeat a site; check the saved pagination')
    return rows


HARINGEY_URL = 'https://www.haringey.gov.uk/parking/car-parks'


def haringey(location=None):
    """Keep Stoneleigh A, B and C distinct using the council's RingGo codes."""
    raw = read_input(location or HARINGEY_URL)
    rows = []
    for title, body in _heading_sections(raw, 4):
        detail = _plain_text(body)
        codes = re.findall(r'(?:car park ([A-C]) )?location number (\d+)', detail, re.I)
        for letter, code in codes:
            name = title + (' car park ' + letter.upper() if letter else '')
            row = _inventory_identity(name, HARINGEY_URL, detail)
            row['location_code'] = code
            rows.append(row)
    if not rows or len({r['location_code'] for r in rows}) != len(rows):
        raise ValueError('Haringey inventory is empty or repeats a site code')
    return rows


HACKNEY_URL = 'https://www.hackney.gov.uk/parking-streets-and-transport/where-park/council-car-parks'


def hackney(location=None):
    """Read exact council site headings and retain named closure notices as holds."""
    sections = [body for title, body in _heading_sections(read_input(location or HACKNEY_URL), 2)
                if title == 'Car parks and prices']
    if len(sections) != 1:
        raise ValueError('Hackney page has no council car park inventory')
    raw = sections[0]
    rows = [_inventory_identity(name, HACKNEY_URL, _plain_text(body))
            for name, body in _accordion_sections(raw)]
    for paragraph in re.findall(r'<p\b[^>]*>(.*?)</p>', raw, re.S):
        notice = re.fullmatch(r'(.+? car park) is currently closed\.', _plain_text(paragraph), re.I)
        if notice:
            row = _inventory_identity(notice[1], HACKNEY_URL, _plain_text(paragraph))
            row['source_closed'] = True
            rows.append(row)
    if not rows or len({r['name'].casefold() for r in rows}) != len(rows):
        raise ValueError('Hackney inventory is empty or repeats a site name')
    return rows


BRENT_SITE_PREFIX = '/parking-roads-and-travel/parking/where-you-can-park/car-parks/'


def brent(location=None):
    """Read the complete public search response used by the council directory."""
    if not location:
        raise ValueError('Brent requires a saved council directory search response')
    data = json.loads(read_input(location))
    results = data.get('results', [])
    if not results or data.get('totalCount') != len(results):
        raise ValueError('Brent council search is empty, failed or truncated')
    rows = []
    for result in results:
        doc = result['document']
        geometry = doc.get('brentItemGeoLocation') or {}
        url, name = doc.get('brentItemUrl') or '', doc.get('brentItemTitle') or ''
        if geometry.get('type') != 'Point' or not url.startswith(BRENT_SITE_PREFIX) or not name:
            raise ValueError('Brent site lacks an exact name, car park URL or point')
        lon, lat = geometry['coordinates'][:2]
        row = _inventory_identity(_plain_text(name), 'https://brent.gov.uk' + url)
        row.update({'lat': str(lat), 'lon': str(lon), 'address': doc.get('brentItemAddress') or '',
                    'postcode': doc.get('brentItemPostcode') or ''})
        rows.append(row)
    if len({r['url'] for r in rows}) != len(rows):
        raise ValueError('Brent council search repeats a car park URL')
    return rows


ADAPTERS = {'generic': generic, 'city-of-london': city_of_london,
            'barnet': barnet, 'hillingdon': hillingdon, 'bromley': bromley,
            'hounslow': hounslow, 'havering': havering, 'bexley': bexley,
            'croydon': croydon, 'greenwich': greenwich, 'redbridge': redbridge,
            'waltham-forest': waltham_forest, 'newham': newham, 'richmond-upon-thames': richmond_upon_thames, 'ealing': ealing, 'merton': merton, 'harrow': harrow, 'southwark': southwark, 'kingston-upon-thames': kingston_upon_thames, 'haringey': haringey, 'hackney': hackney, 'brent': brent}
