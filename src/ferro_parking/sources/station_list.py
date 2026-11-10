"""Exact station lookup from the public list used by National Rail's finder.

The official finder maps its station-list names to slugs with the same
normalizer below. Never derive a URL from the supplied parking row name.
The complete list is fetched once, cached, and reused without network access.
"""
from functools import lru_cache
import json
import re
from pathlib import Path

LIST_URL = 'https://nreservices.nationalrail.co.uk/live-info'
LIST_PAGE = 'https://www.nationalrail.co.uk/stations/'
CACHE = Path('data/cache/nationalrail_station_list.json')
QUERY = {'query': 'query StationList { StationList { stations { crs name } } }'}


def official_slug(name):
    # National Rail's public finder function, applied only to official names.
    value = re.sub(r'\([^)]*\)|[^\w\s-]', '', name, flags=re.ASCII)
    return re.sub(r'\s+', '-', value.strip().lower())


@lru_cache(maxsize=4)
def parse(text):
    from .station import station_slug
    stations = json.loads(text)['data']['StationList']['stations']
    if not stations:
        raise ValueError('National Rail station list is empty')
    choices = {}
    for station in stations:
        name = station['name']
        key = station_slug(name)
        choices.setdefault(key, set()).add(
            'https://www.nationalrail.co.uk/stations/' + official_slug(name) + '/')
    return {key: next(iter(urls)) for key, urls in choices.items() if len(urls) == 1}


def load(conn=None, path=CACHE):
    path = Path(path)
    if path.is_file():
        return parse(path.read_text(encoding='utf-8'))
    if conn is None:
        return None
    from .fetch import fetch
    status, text, _ = fetch(LIST_URL, conn, payload=QUERY)
    if status != 200:
        raise ValueError(f'National Rail station list unavailable: HTTP {status}')
    lookup = parse(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text)
    return lookup
