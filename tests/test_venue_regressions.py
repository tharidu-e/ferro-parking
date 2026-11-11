"""Synthetic offline branch-page fixtures, not claims about real branches."""
import json
from pathlib import Path

import pytest

from ferro_parking.sources.venue import VenueFetcher

CASES = json.loads((Path(__file__).parent / 'fixtures/venue_cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_venue_safety_fixtures(case):
    values, notes, flags, quote = VenueFetcher('puregym.com').values(case['text'])
    if case.get('empty'):
        assert values == {}
        return
    for field, expected in case.get('expected', {}).items():
        assert values.get(field) == expected
    for field in case.get('absent', []):
        assert field not in values
    if case.get('excluded_quote'):
        assert case['excluded_quote'] not in quote
    assert values['Can Park? (Yes/No/Conditional)'] == 'Conditional'
    assert values['Who Can Park'] == 'Customers only'
