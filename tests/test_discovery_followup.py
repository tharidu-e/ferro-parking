"""Small regression fixtures for the live-batch failure patterns, not batch replays."""
import csv
import json

import pytest

from ferro_parking import discover, fill, validation
from ferro_parking.sources import generic


class London:
    def classify(self, rows):
        return [(row, 'London') for row in rows]


def source(**changes):
    return {'name':'Terminal Long Stay', 'address':'Airport Road', 'postcode':'TW6 1EW',
            'lat':'51.5', 'lon':'0', 'url':'https://example.org/long-stay',
            'tariff':'Not published', 'hours':'', 'max_stay':'', 'official':True, **changes}


def sheet(**changes):
    return {'Place ID':'PP-1','Location Name':'Terminal Long Stay','Postcode':'TW6 1EW',
            'Latitude':'51.5','Longitude':'0','Source URLs (primary first)':'https://example.org/long-stay',
            'Tariff Detail':'Not published', **changes}


def test_generic_preserves_both_place_id_spellings(tmp_path):
    path=tmp_path/'source.json'
    path.write_text(json.dumps([{'name':'A','place_id':'PP-1'},{'name':'B','Place ID':'PP-2'}]))
    assert [row['place_id'] for row in generic(path)] == ['PP-1','PP-2']


def test_place_id_precedes_other_stages():
    target=sheet(**{'Place ID':'PP-2','Postcode':'OTHER'})
    assert discover.dedupe(source(place_id='PP-2'),[sheet(),target]) == ([target],'Place ID')


def test_url_matches_any_listed_source_before_postcode():
    target=sheet(**{'Place ID':'PP-2','Postcode':'OTHER','Source URLs (primary first)':'https://example.org/else ; https://example.org/long-stay'})
    assert discover.dedupe(source(),[sheet(**{'Source URLs (primary first)':''}),target]) == ([target],'Source URL')


@pytest.mark.parametrize('postcode,method',[('TW6 1EW','postcode+name'),('', 'pin within 50 m+name')])
def test_shared_location_resolved_by_name(postcode,method):
    target=sheet(**{'Source URLs (primary first)':'','Postcode':postcode})
    other=sheet(**{'Place ID':'PP-2','Location Name':'Terminal Short Stay','Source URLs (primary first)':'','Postcode':postcode})
    assert discover.dedupe(source(url='',postcode=postcode),[other,target]) == ([target],method)


def test_same_name_shared_postcode_stays_ambiguous():
    hits,_=discover.dedupe(source(url=''),[sheet(),sheet(**{'Place ID':'PP-2'})])
    assert len(hits)==2


def test_unparseable_tariff_keeps_match_and_flags_failed_field(tmp_path):
    result=discover.run([source(tariff='Call for prices')],[sheet()],tmp_path,London())
    assert result['matched']==1
    assert result['exceptions']==0
    with (tmp_path/'matches.csv').open() as stream:
        row=next(csv.DictReader(stream))
    assert json.loads(row['flags'])['tariff_unparsed'] is True


def test_no_identity_column_is_not_an_unresolved_identity():
    row={fill.CAN_PARK:'Yes','Verification Result':'Needs on-site check'}
    assert not any(f['rule']=='identity' for f in validation.validate_rows([row]))


@pytest.mark.parametrize('field,flag',[('hours','hours_unparsed'),('max_stay','max_stay_unparsed')])
def test_time_parse_failure_keeps_match(field,flag,tmp_path):
    result=discover.run([source(**{field:'See the sign'})],[sheet()],tmp_path,London())
    assert (result['matched'],result['exceptions'])==(1,0)
    with (tmp_path/'matches.csv').open() as stream:
        assert json.loads(next(csv.DictReader(stream))['flags'])[flag] is True


def test_failed_field_does_not_hide_other_supported_facts(tmp_path):
    result=discover.run([source(tariff='Long prose',hours='24/7')],[sheet()],tmp_path,London())
    assert result['matched']==1
    with (tmp_path/'matches.csv').open() as stream:
        match=next(csv.DictReader(stream))
    improvements=json.loads(match['improvements'])
    assert improvements[discover.HOURS]=='24/7'
    assert 'Tariff Detail' not in improvements


def test_unparseable_candidate_keeps_raw_source_quote(tmp_path):
    result=discover.run([source(tariff='No parking facilities')],[],tmp_path,London())
    assert (result['new'],result['exceptions'])==(1,0)
    with (tmp_path/'candidates.csv').open() as stream:
        row=next(csv.DictReader(stream))
    assert row['Tariff Detail']=='Not published'
    assert row[fill.CAN_PARK]=='Unknown'
    assert 'No parking facilities' in row['Evidence Detail (what the source shows)']


def test_weak_fuzzy_name_does_not_resolve_ambiguity():
    hits,_=discover.dedupe(source(name='Something else',url=''),[sheet(),sheet(**{'Location Name':'Other place','Place ID':'PP-2'})])
    assert len(hits)==2


def test_duplicate_place_ids_remain_ambiguous():
    assert len(discover.dedupe(source(place_id='PP-1'),[sheet(),sheet()])[0])==2


def test_city_finder_repairs_only_currency_question_marks(tmp_path):
    from ferro_parking.sources import city_of_london
    path=tmp_path/'city.json'
    path.write_text(json.dumps({'features':[{'properties':{'CAR_PARKS':'Example','TARIFFS':'?2.50 per hour. Questions? Contact us.'},'geometry':{'type':'Point','coordinates':[0,51.5]}}]}))
    row=city_of_london(path)[0]
    assert row['tariff']=='£2.50 per hour. Questions? Contact us.'


def test_dead_presumed_no_parking_builder_cannot_produce_a_plan():
    from ferro_parking.policy_fill import presumed_no_parking_fields
    with pytest.raises(RuntimeError,match='Map absence'):
        presumed_no_parking_fields()


def test_all_new_validation_rules_include_place_and_field():
    row={**discover.draft(source()),'Place ID':'PP-1',fill.CAN_PARK:'Conditional',
         'Brand':'','Place Category':'','Price Status':'Not published','Cost Type':'Paid',
         'Tariff Type':'Free period, then hourly','Tariff Detail':'Free for 30 mins, then £1.00 per hour',
         discover.HOURS:'Mo-Fr 09:00-17:00','Hours Basis':'Car park hours','Notes':'Charging hours apply'}
    problems=validation.validate_rows([row])
    assert {'required','price-status','cost-type','charging-hours'} <= {p['rule'] for p in problems}
    for problem in problems:
        assert problem['Place ID']=='PP-1'
        assert set(problem)=={'Place ID','field','value','rule','message'}


@pytest.mark.parametrize('field,value',[('Charges (as published)','GBP 2.50 per hour'),('Tariff Detail','£2.50 per hour'),('Charges (as published)','50p per hour'),('Charges (as published)','2.50/hour')])
def test_published_price_contradicts_not_published_status(field,value):
    problems=validation.validate_rows([{**discover.draft(source()),field:value}])
    assert any(p['rule']=='price-status' for p in problems)


@pytest.mark.parametrize('text',['Free for 30 mins, then £1.00 per hour','Free; then paid','0-1 hrs £0.00; 1-2 hrs £3.00'])
def test_paid_is_inconsistent_with_free_first_period(text):
    problems=validation.validate_rows([{**discover.draft(source()),'Cost Type':'Paid','Tariff Detail':text}])
    assert any(p['rule']=='cost-type' for p in problems)


def test_charging_hours_warning_alone_does_not_fail_cli(tmp_path):
    row=discover.draft(source(hours='24/7'))
    row['Notes']='Enforcement is in operation on site'
    path=tmp_path/'candidates.csv'
    discover.write_table(path,[row],[])
    assert validation.main([str(path)])==0
    with (tmp_path/'validation.csv').open() as stream:
        problems=list(csv.DictReader(stream))
    assert len(problems)==1
    assert problems[0]['rule']=='charging-hours'
    assert problems[0]['message'].startswith('WARNING:')


@pytest.mark.parametrize('context',['Charging hours','Controlled hours','Charges apply 09:00-17:00'])
def test_clear_charging_hours_is_error(context):
    row={**discover.draft(source(hours='Mo-Fr 09:00-17:00')),'Notes':context}
    problems=validation.validate_rows([row])
    assert any(p['rule']=='charging-hours' and not validation.is_warning(p) for p in problems)


def test_unknown_hours_do_not_get_charging_hours_error():
    row={**discover.draft(source()),'Notes':'Charging hours 09:00-17:00'}
    assert not any(p['rule']=='charging-hours' for p in validation.validate_rows([row]))


@pytest.mark.parametrize('can_park',['Yes','Conditional'])
def test_brand_category_required_and_closed_cannot_park(can_park):
    row={**discover.draft(source()),fill.CAN_PARK:can_park,'Location Status':'Closed'}
    problems=validation.validate_rows([row])
    assert {p['field'] for p in problems if p['rule']=='required'}=={'Brand','Place Category'}
    assert any(p['rule']=='closed' and p['field']==fill.CAN_PARK for p in problems)


@pytest.mark.parametrize('field',['Notes','Brand','Location Name','Operator'])
@pytest.mark.parametrize('dash',[chr(0x2013),chr(0x2014)])
def test_unicode_dash_rule_covers_every_written_field(field,dash):
    problems=validation.validate_rows([{**discover.draft(source()),field:'Before'+dash+'after'}])
    assert any(p['rule']=='dashes' and p['field']==field for p in problems)


def test_matching_fixture_cases():
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures'/'discovery_match_cases.json').read_text())
    for case in fixture['cases']:
        hits,method=discover.dedupe(case['source'],case['sheet'])
        assert method==case['method']
        assert [row['Place ID'] for row in hits]==[case['place_id']]


def test_replay_uses_exception_source_json_and_reports_measured_counts(tmp_path):
    import importlib.util
    from pathlib import Path
    path=Path(__file__).parents[1]/'scripts'/'replay_discovery_batches.py'
    spec=importlib.util.spec_from_file_location('replay_batches',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sheet_file=tmp_path/'sheet.csv'
    discover.write_table(sheet_file,[sheet()],[])
    exceptions=tmp_path/'exceptions.csv'
    discover.write_table(exceptions,[{'source':json.dumps(source(tariff='No published tariff'))}],[])
    output=tmp_path/'replay'
    output.mkdir()
    result=module.replay(sheet_file,{'heathrow':exceptions},output,London())
    assert result[0]['after']=={'listed':1,'matched':1,'exceptions':0}
    assert result[0]['same_listed_count'] is False
    assert result[0]['before']=={'listed':20,'matched':0,'exceptions':20}


def test_invalid_url_does_not_abort_postcode_matching():
    hits,method=discover.dedupe(source(url='https://[broken'),[sheet()])
    assert method=='postcode'
    assert hits[0]['Place ID']=='PP-1'


def test_unparseable_charging_prose_never_discards_the_matched_place(tmp_path):
    result=discover.run([source(tariff='Charges apply. See PDF for prices.',hours='24/7')],[sheet()],tmp_path,London())
    assert (result['matched'],result['exceptions'])==(1,0)
    with (tmp_path/'matches.csv').open() as stream:
        row=next(csv.DictReader(stream))
    flags=json.loads(row['flags'])
    assert flags['tariff_unparsed'] is True
    assert flags['hours_context_unresolved'] is True
    assert discover.HOURS not in json.loads(row['improvements'])


def test_not_applicable_tariff_is_not_a_published_price():
    row=discover.draft(source(tariff='Not applicable'))
    assert row['Price Status']=='Not applicable'
    assert not any(f['rule']=='consistency' for f in validation.validate_rows([row]))


def test_identity_absent_passes_otherwise_valid_on_site_check_row():
    row={**discover.draft(source()),fill.CAN_PARK:'Yes','Verification Result':'Needs on-site check','Brand':'Example','Place Category':'Other'}
    assert validation.validate_rows([row])==[]
    assert any(p['rule']=='identity' for p in validation.validate_rows([{**row,'Identity resolved':'No'}]))


def test_unique_strong_fuzzy_name_can_win():
    src=source(name='Official Heathrow Terminal Five Long Stay Parking',url='')
    target=sheet(**{'Location Name':'Heathrow Terminal Five Long Stay Parking'})
    other=sheet(**{'Place ID':'PP-2','Location Name':'London Airport Terminal Two Short Stay'})
    hits,method=discover.dedupe(src,[other,target])
    assert hits==[target]
    assert method=='postcode+name'


def test_shared_city_feed_url_does_not_identify_minories(tmp_path):
    """Regression for 2026-11-11_17/discover/exceptions.csv."""
    from ferro_parking.sources import CITY_URL
    minories = source(name='The Minories, Mansell Street', address='', postcode='',
                      lat='51.510314495818264', lon='-0.07308898555678242',
                      url=CITY_URL)
    other = source(name='Baynard House, Queen Victoria Street', address='', postcode='',
                   lat='51.511871776333777', lon='-0.10059747965261778', url=CITY_URL)
    # Two unrelated records carry the feed URL. Neither is Minories.
    unrelated = [sheet(**{'Place ID': f'PP-{index}', 'Location Name': name,
                         'Postcode': '', 'Latitude': '51.6', 'Longitude': '0',
                         'Source URLs (primary first)': CITY_URL})
                 for index, name in enumerate(['London Wall', 'Smithfield'])]
    target = sheet(**{'Place ID': 'PP-000194', 'Location Name': 'Minories Car Park',
                      'Postcode': '', 'Latitude': minories['lat'],
                      'Longitude': minories['lon'], 'Source URLs (primary first)': ''})
    # With no nearby target, the old URL stage returned the saved ambiguity.
    old_hits, old_method = discover.dedupe(minories, unrelated)
    assert len(old_hits) == 2
    assert old_method == 'Source URL'
    result = discover.run([minories, other], unrelated + [target], tmp_path, London())
    assert (result['matched'], result['new'], result['exceptions']) == (1, 1, 0)
    with (tmp_path / 'matches.csv').open() as stream:
        match = next(csv.DictReader(stream))
    assert (match['Place ID'], match['method']) == ('PP-000194', 'pin within 50 m')
    assert json.loads(match['source'])['url'] == CITY_URL


def test_shared_feed_url_does_not_merge_distinct_new_listings(tmp_path):
    rows = [source(name='North Car Park', postcode='', address=''),
            source(name='South Car Park', postcode='', address='', lat='51.6')]
    result = discover.run(rows, [], tmp_path, London())
    assert (result['new'], result['exceptions']) == (2, 0)


def test_single_listing_retains_source_url_match(tmp_path):
    result = discover.run([source(postcode='', lat='', lon='')], [sheet()], tmp_path, London())
    assert result['matched'] == 1
    with (tmp_path / 'matches.csv').open() as stream:
        assert next(csv.DictReader(stream))['method'] == 'Source URL'


def test_barnet_historical_csv_preserves_names_without_parking_claims(tmp_path):
    from ferro_parking.sources import barnet_2014
    path = tmp_path / 'barnet.csv'
    path.write_text('Car Park,Type,Number of Free Parking Spaces \n Church Hill Road Car park ,Free Off Street Parking,68\n')
    row = barnet_2014(path)[0]
    assert row['name'] == 'Church Hill Road Car park'
    assert row['source_period'] == '2014-12'
    assert row['official'] is True
    assert all(row[key] == '' for key in ('lat', 'lon', 'tariff', 'hours', 'max_stay'))
    assert discover.draft(row)[fill.CAN_PARK] == 'Unknown'


@pytest.mark.parametrize('text', ['name,Type\nExample,Free\n', 'Car Park,Type\n,Free\n'])
def test_barnet_rejects_wrong_header_or_blank_name(text, tmp_path):
    from ferro_parking.sources import barnet_2014
    path = tmp_path / 'barnet.csv'
    path.write_text(text)
    with pytest.raises(ValueError, match='Barnet CSV'):
        barnet_2014(path)


def test_hillingdon_point_inventory_is_identity_only(tmp_path):
    from ferro_parking.sources import hillingdon
    path = tmp_path / 'points.geojson'
    path.write_text(json.dumps({'crs': {'properties': {'name': 'EPSG:4326'}},
                               'features': [{'properties': {'CAR_PARK': 'Cedars', 'POSTCODE': 'UB8 1ND',
                                                            'PRICES': 'free', 'MAX_STAY': '4 hours'},
                                             'geometry': {'type': 'Point', 'coordinates': [-0.48, 51.54]}}]}))
    row = hillingdon(path)[0]
    assert (row['name'], row['lat'], row['lon'], row['postcode']) == ('Cedars', '51.54', '-0.48', 'UB8 1ND')
    assert all(row[key] == '' for key in ('tariff', 'hours', 'max_stay'))


@pytest.mark.parametrize('change', [{'error': {'message': 'bad'}}, {'exceededTransferLimit': True},
                                   {'crs': {'properties': {'name': 'EPSG:27700'}}},
                                   {'features': [{'properties': {'CAR_PARK': 'A'},
                                                  'geometry': {'type': 'Polygon'}}]}])
def test_hillingdon_rejects_failed_truncated_or_wrong_geometry(change, tmp_path):
    from ferro_parking.sources import hillingdon
    path = tmp_path / 'points.geojson'
    path.write_text(json.dumps(change))
    with pytest.raises(ValueError):
        hillingdon(path)


def test_bromley_reads_local_search_and_entry_pins(tmp_path):
    from ferro_parking.sources import bromley
    search = tmp_path / 'search.html'
    search.write_text('<a class="list__link" href="/directory-record/152/example"><span class="list__link-text">Example &amp; Park</span></a>')
    (tmp_path / 'bromley_car_park_152.html').write_text('<input id="map_marker_location_59" value="51.42,0.018">')
    row = bromley(search)[0]
    assert (row['name'], row['lat'], row['lon']) == ('Example & Park', '51.42', '0.018')
    assert row['url'] == 'https://www.bromley.gov.uk/directory-record/152/example'
    assert all(row[key] == '' for key in ('tariff', 'hours', 'max_stay'))


@pytest.mark.parametrize('case', ['missing', 'challenge', 'paginated'])
def test_bromley_refuses_incomplete_entry_downloads(tmp_path, case):
    from ferro_parking.sources import bromley
    search = tmp_path / 'search.html'
    text = '<a class="list__link" href="/directory-record/152/example"><span class="list__link-text">Example</span></a>'
    if case == 'paginated':
        text += '<nav class="pagination">Next</nav>'
    search.write_text(text)
    if case == 'challenge':
        (tmp_path / 'bromley_car_park_152.html').write_text('Pardon Our Interruption')
    with pytest.raises((ValueError, FileNotFoundError)):
        bromley(search)


def test_hounslow_excludes_street_bays_and_payment_trial_lists(tmp_path):
    from ferro_parking.sources import hounslow
    path = tmp_path / 'hounslow.html'
    path.write_text(''.join(f'<h4>Car parks</h4><ul><li>Park {i}</li></ul><h4>30 minutes free</h4><ul><li>Street bay</li></ul>' for i in range(5)) + '<h5>Car parks</h5><ul><li>Repeated trial site</li></ul>')
    rows = hounslow(path)
    assert [r['name'] for r in rows] == [f'Park {i}' for i in range(5)]
    assert all(r['lat'] == r['lon'] == r['tariff'] == '' for r in rows)


def test_hounslow_refuses_partial_or_challenge_page(tmp_path):
    from ferro_parking.sources import hounslow
    path = tmp_path / 'hounslow.html'
    path.write_text('<h4>Car parks</h4><ul><li>A</li></ul>')
    with pytest.raises(ValueError, match='all five'):
        hounslow(path)


def test_havering_imports_only_car_park_links_without_map_centres(tmp_path):
    from ferro_parking.sources import havering
    path = tmp_path / 'havering.html'
    path.write_text('<li><a href="https://www.havering.gov.uk/car-parks-1/rex-close-car-park">Rex Close Car Park</a></li><li><a href="/parking">Parking</a></li><iframe src="https://www.google.com/maps/embed?pb=!2d0.1!3d51.5"></iframe>')
    rows = havering(path)
    assert len(rows) == 1
    assert rows[0]['name'] == 'Rex Close Car Park'
    assert rows[0]['lat'] == rows[0]['lon'] == ''


def test_bexley_excludes_on_street_sections_and_keeps_postcode(tmp_path):
    from ferro_parking.sources import bexley
    path = tmp_path / 'bexley.html'
    path.write_text('<h4 class="field--name-field-item-title">Felixstowe Road car park</h4><li>postcode SE2 9RH</li><h3>On-street parking bays</h3><h4 class="field--name-field-item-title">Abbey Wood</h4>')
    rows = bexley(path)
    assert len(rows) == 1
    assert rows[0]['postcode'] == 'SE2 9RH'
    assert rows[0]['name'] == 'Felixstowe Road car park'


def test_bexley_refuses_missing_section_boundary(tmp_path):
    from ferro_parking.sources import bexley
    path = tmp_path / 'bexley.html'
    path.write_text('Pardon Our Interruption')
    with pytest.raises(ValueError):
        bexley(path)


def test_croydon_uses_all_map_markers_despite_paginated_visible_list(tmp_path):
    from ferro_parking.sources import croydon
    path = tmp_path / 'croydon.html'
    markers = [{'title': f'Park {i}', 'type': 'point', 'lat': 51.37, 'lon': -0.1,
                'popup': {'value': f'<a href="/parking/find-council-car-parks-croydon/park-{i}">Park {i}</a>'}}
               for i in range(2)]
    data = {'leaflet': {'leaflet-map-view-localgov-directory-channel-embed-map': {'features': markers}}}
    path.write_text('<nav class="pager">Next page</nav><script type="application/json" data-drupal-selector="drupal-settings-json">' + json.dumps(data) + '</script>')
    rows = croydon(path)
    assert [r['name'] for r in rows] == ['Park 0', 'Park 1']
    assert all(r['lat'] == '51.37' and r['tariff'] == '' for r in rows)


def test_croydon_refuses_missing_map(tmp_path):
    from ferro_parking.sources import croydon
    path = tmp_path / 'croydon.html'
    path.write_text('No map')
    with pytest.raises(ValueError):
        croydon(path)


def test_barnet_current_list_excludes_other_lists_and_retains_closure_quote(tmp_path):
    from ferro_parking.sources import barnet, BARNET_URL
    path = tmp_path / 'current.html'
    path.write_text('<h2>Barnet car parks</h2><ul><li><a>Brunswick Road</a> - Brunswick Park Road, London, N11 1JJ | Open all day</li><li>Watling Avenue- River approach, HA8 0AZ | Car Park Closed.</li></ul><h2>Pay By Phone</h2><ul><li>Not another site</li></ul>')
    rows = barnet(path)
    assert [r['name'] for r in rows] == ['Brunswick Road', 'Watling Avenue']
    assert rows[0]['postcode'] == 'N11 1JJ'
    assert rows[0]['url'] == BARNET_URL
    assert 'Closed' in rows[1]['identity_quote']
    assert all(r['lat'] == r['lon'] == r['tariff'] == r['hours'] == '' for r in rows)


@pytest.mark.parametrize('text', ['<title>Pardon Our Interruption</title>', 'Car Park,Type\nOld site,Free\n'])
def test_barnet_current_adapter_refuses_challenge_or_historical_csv(tmp_path, text):
    from ferro_parking.sources import barnet
    path = tmp_path / 'current.html'
    path.write_text(text)
    with pytest.raises(ValueError, match='Barnet current page'):
        barnet(path)


def test_greenwich_joins_marker_names_and_pins_by_id(tmp_path):
    from urllib.parse import quote_plus
    from ferro_parking.sources import greenwich
    path = tmp_path / 'greenwich.html'
    anchor = '<a href="https://www.royalgreenwich.gov.uk/directory_record/17/example">Example Park</a>'
    path.write_text(f'<input id="map_marker_info_17" value="{quote_plus(anchor)}"><input id="17" class="mapMarkers" value="51.48,0.02">')
    row = greenwich(path)[0]
    assert (row['name'], row['lat'], row['lon']) == ('Example Park', '51.48', '0.02')
    assert row['tariff'] == row['hours'] == row['max_stay'] == ''
    path.write_text(f'<input id="map_marker_info_17" value="{quote_plus(anchor)}">')
    with pytest.raises(ValueError, match='missing map'):
        greenwich(path)


def test_redbridge_keeps_distinct_eastwood_codes_and_excludes_street_parking(tmp_path):
    from ferro_parking.sources import redbridge
    path = tmp_path / 'redbridge.html'
    path.write_text('<h2>Council car parks</h2><h3>Area</h3><h3>Eastwood Close</h3><p>E18 1BY RingGo Location Number: 7105</p><h3>Eastwood Close</h3><p>E18 1BY RingGo Location Number: 7116</p><h2>On-street parking</h2><h3>A bay</h3><p>RingGo Location Number: 123</p>')
    rows = redbridge(path)
    assert [r['location_code'] for r in rows] == ['7105', '7116']
    assert all(r['postcode'] == 'E18 1BY' and r['tariff'] == r['lat'] == '' for r in rows)


def test_waltham_forest_splits_grouped_sites_and_excludes_street_bays(tmp_path):
    from ferro_parking.sources import waltham_forest
    path = tmp_path / 'forest.html'
    path.write_text('<h2>Council car park charges</h2><h3>Bedford Road E17</h3><p>£1</p><h3>Brandon Road E17, Hall Lane E4</h3><p>£2</p><h3>Town Hall Car Park E17 and Willow House Car Park E17</h3><h2>On-street pay and display charges</h2><h3>Street E17</h3>')
    rows = waltham_forest(path)
    assert len(rows) == 5
    assert rows[-1]['name'] == 'Willow House Car Park E17'
    assert all(r['tariff'] == r['lat'] == '' for r in rows)


def test_newham_requires_linked_areas_and_reads_exact_site_page(tmp_path):
    from ferro_parking.sources import newham
    index = tmp_path / 'index.html'
    index.write_text('<a href="/directory/2/car-parks-in-newham/category/2">Area</a>')
    (tmp_path / 'newham-2.html').write_text('<a href="/directory-record/42/example">Example</a>')
    (tmp_path / 'newham-site-42.html').write_text('<h1>Example - Car parks in Newham</h1><dt>Address</dt><dd>Example Road, E6 1HZ</dd><dt>Charges</dt><dd>Free</dd>')
    row = newham(index)[0]
    assert (row['name'], row['postcode']) == ('Example', 'E6 1HZ')
    assert row['tariff'] == row['lat'] == ''


def test_richmond_reads_all_areas_and_excludes_tariffs_and_contact_sections(tmp_path):
    from ferro_parking.sources import richmond_upon_thames
    path = tmp_path / 'index.html'
    path.write_text('<a href="/services/parking/car_parks/ham_area_car_parks">Ham</a>')
    (tmp_path / 'richmond-upon-thames-ham_area_car_parks.html').write_text('<h2>Ham Street</h2><p>Postcode: TW10 7RS Map: Ham Street car park Tariffs: Free</p><h2>Contact us</h2><p>Town Hall</p>')
    row = richmond_upon_thames(path)[0]
    assert (row['name'], row['postcode'], row['tariff']) == ('Ham Street', 'TW10 7RS', '')


def test_ealing_keeps_free_inventory_site_and_closed_marker_without_parking_answers(tmp_path):
    from ferro_parking.sources import ealing
    path = tmp_path / 'layout.txt'
    path.write_text('FEES AND CHARGES FOR OFF-STREET CAR PARKS\nWE03 Singapore Road - Surface\nEmission based Rates - Table 2a\nDean Gardens Car Park *      37217      Hourly rate 4\nArden Road Car Park          37218      Hourly rate 4\nVersion 34_A Updated: 12/12/2024\n')
    rows = ealing(path)
    assert [r['name'] for r in rows] == ['Dean Gardens Car Park', 'Arden Road Car Park', 'Singapore Road Car Park']
    assert rows[0]['source_closed'] is True
    assert all(r['source_period'] == '12/12/2024' and r['tariff'] == r['lat'] == '' for r in rows)


def test_merton_selects_identity_table_instead_of_season_ticket_repetitions(tmp_path):
    from ferro_parking.sources import merton
    path = tmp_path / 'merton.html'
    path.write_text('<table><tr><th>Car park</th><th>Period</th></tr><tr><td>Repeated season site</td><td>Month</td></tr></table><table><tr><th>Car park (by area)</th><th>Hours</th><th>Charges</th></tr><tr><td>Kenley Road, Morden</td><td>Always</td><td>Free</td></tr></table>')
    rows = merton(path)
    assert len(rows) == 1
    assert rows[0]['name'] == 'Kenley Road, Morden'
    assert rows[0]['tariff'] == rows[0]['hours'] == ''


def test_harrow_requires_site_fields_and_keeps_free_period_out_of_answers(tmp_path):
    from ferro_parking.sources import harrow
    path = tmp_path / 'harrow.html'
    path.write_text('<h2>Council car parks</h2><p>Introduction</p><h2>Greenhill Way</h2><p>Car park type: PayByPhone Post Code: HA1 1LD Tariff: 1st hour free</p><h2>Parking Operations</h2><p>Contact us</p>')
    rows = harrow(path)
    assert len(rows) == 1
    assert (rows[0]['name'], rows[0]['postcode']) == ('Greenhill Way', 'HA1 1LD')
    assert rows[0]['tariff'] == rows[0]['max_stay'] == ''


def test_southwark_counts_heading_once_and_excludes_season_ticket_section(tmp_path):
    from ferro_parking.sources import southwark
    path = tmp_path / 'southwark.html'
    path.write_text('<p>We run 1 car parks</p><h3><span class="accordion-pane__heading">Choumert Grove car park</span><button hidden>Choumert Grove car park</button></h3><p>London SE15 4RB</p><h3><span class="accordion-pane__heading">Car park season tickets</span></h3><p>Monthly</p>')
    rows = southwark(path)
    assert len(rows) == 1
    assert rows[0]['postcode'] == 'SE15 4RB'


def test_kingston_reads_second_page_before_counting_complete_inventory(tmp_path):
    from ferro_parking.sources import kingston_upon_thames
    path = tmp_path / 'kingston.html'
    path.write_text('<a href="?page=1">Next</a><a href="/parking/car-parks/ashdown" class="teaser-link"><h2>Ashdown</h2></a>')
    (tmp_path / 'kingston-page-2.html').write_text('<a href="/parking/car-parks/rose" class="teaser-link"><h2>Rose</h2></a>')
    assert [r['name'] for r in kingston_upon_thames(path)] == ['Ashdown', 'Rose']
