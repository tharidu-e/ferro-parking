import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from ferro_parking import discover, fill, formats, gaps, london, sources, sync, validation
from ferro_parking.run_paths import new_run_dir, reserve_output

FIX = Path(__file__).parent / 'fixtures'


def test_generic_adapter_fixture_and_json(tmp_path):
    rows = sources.generic(FIX / 'source_locations.csv')
    assert rows[0]['name'] == 'Example car park'
    assert rows[0]['official'] is False
    path = tmp_path / 'locations.json'
    path.write_text(json.dumps(rows))
    assert sources.generic(path) == rows


def test_official_finder_fixture():
    row = sources.city_of_london(FIX / 'official_city_finder.json')[0]
    assert row['official'] is True
    assert row['lat'] == '51.515'
    assert row['tariff'] == '£3.00 per hour'
    assert row['url'] == sources.CITY_URL


def test_official_finder_refuses_truncation(tmp_path):
    path = tmp_path / 'truncated.json'
    path.write_text('{"exceededTransferLimit": true}')
    with pytest.raises(ValueError, match='truncated'):
        sources.city_of_london(path)


@pytest.mark.parametrize('text,expected', [
    ('Free', ('Free (time limit not published)', 'Free')),
    ('£1.5 per hour', ('Hourly rate', '£1.50 per hour')),
    ('0-1 hrs £1.50; 1-2 hrs £3.00', ('Banded by stay length', '0-1 hrs £1.50; 1-2 hrs £3.00')),
    ('', ('Not published', 'Not published')),
])
def test_tariff_parser(text, expected):
    assert formats.parse_tariff(text) == expected


@pytest.mark.parametrize('text', ['£1 per day', 'from £1 per hour', '1-0 hrs £1.00', '0-1 hrs £1.00; 2-3 hrs £2.00', 'Free on Sundays', '£1.00 per hour subject to minimum charge'])
def test_tariff_parser_refuses_guessing(text):
    with pytest.raises(ValueError):
        formats.parse_tariff(text)


@pytest.mark.parametrize('text', ['24/7', 'Mo-Sa 07:00-22:00; Su 10:00-16:00', 'Mo-Su 07:00-sunset', 'Not published'])
def test_hours_supported(text):
    assert formats.parse_hours(text) == text


@pytest.mark.parametrize('text', ['Mo 25:00-26:00', 'daily', '9am to 5pm', 'Mo 12:99-14:00'])
def test_hours_refuses_invalid_or_ambiguous(text):
    with pytest.raises(ValueError):
        formats.parse_hours(text)


@pytest.mark.parametrize('text,want', [('2 hours','120'), ('90 mins','90'), ('No limit','No limit'), ('','Not published')])
def test_stay_parser(text, want):
    assert formats.parse_stay(text) == want


def test_dedupe_priority_and_ambiguity():
    source = {'name':'A', 'address':'1 Road', 'postcode':'W1 1AA', 'lat':'51.5', 'lon':'0'}
    postcode = {'Place ID':'PP-1', 'Postcode':'W11AA'}
    identity = {'Place ID':'PP-2', 'Location Name':'A', 'Street Address':'1 Road', 'Latitude':'51.5', 'Longitude':'0'}
    assert discover.dedupe(source, [identity, postcode]) == ([postcode], 'postcode')
    source['postcode'] = ''
    assert discover.dedupe(source, [identity])[1] == 'name+street'
    source['address'] = ''
    assert discover.dedupe(source, [identity])[1] == 'pin within 50 m'
    source.update(brand='Tesco', lat='51.5007')
    identity['Brand'] = 'Tesco'
    assert discover.dedupe(source, [identity])[1] == 'same brand within 100 m'
    source['postcode'] = 'W1 1AA'
    assert len(discover.dedupe(source, [postcode, dict(postcode)])[0]) == 2


def test_london_bulk_lookup_reverse_fallback_cache_and_limit(tmp_path):
    calls = []
    def request(path, payload):
        calls.append((path, payload))
        if payload is not None:
            return {'status':200, 'result':[
                {'query':pc, 'result':None if pc == 'OLD' else {'region':'London' if pc.startswith('L') else 'South East'}}
                for pc in payload['postcodes']]}
        return {'status':200, 'result':[{'region':'London'}]}
    rows = [{'postcode':f'L{i}'} for i in range(101)] + [{'postcode':'OUT'}, {'postcode':'OLD','lat':'51.5','lon':'0'}, {'postcode':''}]
    pauses = []
    classifier = london.LondonFilter(tmp_path, request=request, pause=pauses.append)
    results = classifier.classify(rows)
    assert len([c for c in calls if c[1] is not None]) == 2
    assert results[-3][1] == 'South East'
    assert results[-2][1] == 'London'
    assert results[-1][1] is None
    assert len(pauses) == 3
    before = len(calls)
    classifier.classify(rows)
    assert len(calls) == before


def test_discover_outputs_and_finished_rows(tmp_path):
    rows = [dict(name=name, address='', postcode=pc, lat='', lon='', url='', tariff='', hours='', max_stay='', brand='', official=True)
            for name, pc in [('New','N'), ('Matched','M'), ('Ambiguous','A'), ('Outside','O'), ('Bad tariff','B')]]
    rows[-1]['tariff'] = 'call for prices'
    sheet = [{'Place ID':'PP-1','Postcode':'M','Tariff Detail':'Not published','Verification Result':'Confirmed'},
             {'Place ID':'PP-2','Postcode':'A'}, {'Place ID':'PP-3','Postcode':'A'}]
    class Filter:
        def classify(self, data):
            return [(row, 'South East' if row['postcode']=='O' else 'London') for row in data]
    summary = discover.run(rows, sheet, tmp_path, Filter())
    assert (summary['listed'],summary['new'],summary['matched'],summary['exceptions']) == (5,1,1,3)
    with (tmp_path/'matches.csv').open() as stream:
        assert json.loads(next(csv.DictReader(stream))['improvements']) == {}
    assert validation.main([str(tmp_path/'candidates.csv')]) == 0


def clean_candidate():
    return discover.draft({'name':'Example','official':True,'postcode':'EC1A 1AA'})


@pytest.mark.parametrize('change,rule', [
    ({'Who Can Park':'anyone'},'dropdown'),
    ({'Tariff Type':'Hourly rate','Tariff Detail':'£1 per day'},'template'),
    ({'Max Stay (mins)':'1.5'},'minutes'),
    ({discover.HOURS:'Tomorrow'},'hours'),
    ({'Verification Result':'Confirmed'},'confirmed'),
    ({fill.CAN_PARK:'Yes','Verification Result':'Needs on-site check'},'identity'),
    ({'Location Status':'Closed'},'closed'),
    ({'Operator':''},'blank'),
    ({'Notes':chr(0x2014)},'dashes'),
])
def test_validation_rules(change, rule):
    assert rule in {failure['rule'] for failure in validation.validate_rows([{**clean_candidate(), **change}])}


def test_validation_duplicate_and_protected_plan(tmp_path):
    assert 'duplicate' in {f['rule'] for f in validation.validate_rows([clean_candidate(), clean_candidate()])}
    plan = [{'place_id':'PP-1','new':{'Geo Precision':'Building'}}]
    assert 'protected' in {f['rule'] for f in validation.validate_rows(plan, plan=True)}
    path = tmp_path/'plan.json'
    path.write_text(json.dumps(plan))
    assert validation.main([str(path)]) == 1
    with (tmp_path/'validation.csv').open() as stream:
        assert next(csv.DictReader(stream))['Place ID'] == 'PP-1'


@pytest.mark.parametrize('column', ['Confidence (1-5)', 'Latitude', 'Geo Precision', 'Geo Source', 'Geo Future', 'Place ID', 'Hours (as captured)', 'Charges (as published)', 'Enforcement Details', 'Unknown header'])
def test_writer_refuses_loaded_plan_before_auth(column, tmp_path, monkeypatch):
    path = tmp_path/'plan.json'
    path.write_text(json.dumps([{'new':{column:'x'}}]))
    monkeypatch.setattr(fill.sheets, 'get_service', lambda: pytest.fail('Must refuse before authentication'))
    with pytest.raises((ValueError, AssertionError)):
        fill.write_main([str(path)])


def test_wipe_requires_confirmation_before_auth(tmp_path, monkeypatch, capsys):
    path = tmp_path/'plan.json'
    path.write_text(json.dumps([{'new':{'Who Can Park':''}}]))
    monkeypatch.setattr(fill.sheets, 'get_service', lambda: pytest.fail('Must refuse before authentication'))
    with pytest.raises(SystemExit, match='confirm-wipe'):
        fill.write_main([str(path),'--apply'])
    assert 'Rows in plan: 1' in capsys.readouterr().out


def test_append_only_runs(tmp_path):
    first = new_run_dir('discover', tmp_path, '2026-11-09')
    (first/'plan.json').write_text('keep')
    second = new_run_dir('discover', tmp_path, '2026-11-09')
    assert second.parent.name == '2026-11-09_2'
    assert (first/'plan.json').read_text() == 'keep'
    with pytest.raises(FileExistsError):
        reserve_output(first)


def test_sync_identity_and_ambiguous_abort():
    clean = [{'Place ID':'PP-1', 'Location Name':'A', 'Postcode':'W1 1AA'}]
    orig = [{'sheet':'A', 'Address / Postcode':'1 Road W1 1AA', fill.CAN_PARK:'Conditional'}]
    assert sync.captured_can_park_by_place_id(clean, orig) == {'PP-1':'Conditional'}
    with pytest.raises(ValueError, match='alignment'):
        sync.join_tabs(clean, orig + orig)
    with pytest.raises(ValueError, match='alignment'):
        sync.join_tabs(clean, [])


def test_gaps_uses_40m_and_brand_150m_and_access_filters():
    def park(oid, x, **tags):
        point = Point(x, 0)
        return {'id':oid, 'type':'node','geom':point,'ll':Point(0,51.5), 'tags':{'amenity':'parking','access':'public',**tags}}
    parks = [park(1,20),park(2,140,name='Tesco'),park(3,160,name='Tesco'),park(4,200,parking='street_side'),park(5,200,access='private')]
    boroughs = [{'name':'Hackney','geom':box(-100,-100,500,100)}]
    rows = [{'Place ID':'PP-1','Latitude':'0','Longitude':'0','Location Name':'Tesco', 'Brand':'Tesco'}]
    assert [p['OSM Link'].rsplit('/',1)[1] for p in gaps.find_gaps(parks,boroughs,rows)] == ['3']
    with pytest.raises(ValueError, match='boundaries'):
        gaps.find_gaps(parks, [], rows)


def test_london_terminated_postcode_without_coordinates(tmp_path):
    paths = []
    def request(path, payload):
        paths.append(path)
        if payload:
            result = [{'query':'OLD','result':None}]
        elif path.startswith('/terminated_postcodes/'):
            result = {'latitude':51.5,'longitude':0}
        else:
            result = [{'region':'London'}]
        return {'status':200,'result':result}
    output = london.LondonFilter(tmp_path, request=request, pause=lambda _:None).classify([{'postcode':'OLD'}])
    assert output[0][1] == 'London'
    assert paths[1] == '/terminated_postcodes/OLD'


def test_generic_claims_are_sent_for_review():
    with pytest.raises(ValueError, match='evidence review'):
        discover.draft({'name':'Test', 'tariff':'Free', 'official':False})


def test_write_allowlist_accepts_research():
    fill.validate_write_columns([{'new':{'Who Can Park':'Unknown','Tariff Detail':'Not published'}}])


def test_clear_command_requires_extra_confirmation(monkeypatch):
    from ferro_parking import clear_unverified
    monkeypatch.setattr(fill.sheets, 'get_service', lambda: pytest.fail('Must refuse before authentication'))
    with pytest.raises(SystemExit):
        clear_unverified.main(['--apply'])


def test_clear_excludes_personal_verifier():
    from ferro_parking import clear_unverified
    assert clear_unverified.eligible_rows([{'Verified By':'Tharidu','Verification Result':''}]) == []


def test_page_fill_does_not_default_geo_precision():
    from datetime import date
    from ferro_parking import page_fill
    values = page_fill.build_row_values({'Place ID':'PP-1'}, {fill.CAN_PARK:'Unknown'}, date(2026,11,9), {})
    assert 'Geo Precision' not in values


def test_validation_checks_every_configured_dropdown():
    for column in validation.dropdowns():
        problems = validation.validate_rows([{**clean_candidate(), column:'INVALID'}])
        assert any(problem['field']==column and problem['rule']=='dropdown' for problem in problems)


def test_no_limit_requires_explicit_source_and_strong_tier():
    row = {**clean_candidate(), 'Max Stay (mins)':'No limit'}
    assert any(f['rule']=='evidence' for f in validation.validate_rows([row]))


def test_brand_dedupe_works_without_explicit_brand_column():
    source = {'name':'Tesco Express A','lat':'51.5007','lon':'0'}
    sheet = [{'Location Name':'Tesco Extra B','Latitude':'51.5','Longitude':'0'}]
    assert discover.dedupe(source,sheet)[1] == 'same brand within 100 m'


def test_validation_refuses_protected_fields_in_candidate():
    assert any(f['rule']=='protected' for f in validation.validate_rows([{**clean_candidate(),'Latitude':'51.5'}]))


def test_validation_duplicate_plan_identity_metadata():
    row = {'place_id':'PP-1','name':'A','postcode':'EC1A 1AA','new':{'Who Can Park':'Unknown'}}
    assert any(f['rule']=='duplicate' for f in validation.validate_rows([row,{**row,'place_id':'PP-2'}],plan=True))


def test_gaps_excludes_neighbouring_council_boundaries():
    with pytest.raises(ValueError, match='boundaries'):
        gaps.find_gaps([], [{'name':'Surrey district','geom':box(-100,-100,500,100)}], [])


def test_discovery_routes_inconsistent_draft_to_exceptions(tmp_path):
    source = {'name':'Free period only','official':True,'tariff':'Free for up to 2 hrs'}
    class Filter:
        def classify(self, rows):
            return [(row,'London') for row in rows]
    result = discover.run([source], [], tmp_path, Filter())
    assert result['new'] == 0
    assert result['exceptions'] == 1
