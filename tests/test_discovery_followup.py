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
