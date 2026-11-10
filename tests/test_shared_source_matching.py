"""Regression cases supplied by the PR #3 live replay review."""
import csv
import json

from ferro_parking import discover


class London:
    def classify(self, rows):
        return [(row, 'London') for row in rows]


def row(pid, name, **extra):
    return {'Place ID':pid, 'Location Name':name, 'Source URLs (primary first)':'https://example.org/shared', **extra}


def test_shared_source_url_ranks_baynard_address_against_car_park_name():
    target=row('PP-1','Baynard House Car Park (City of London Corporation)')
    others=[row('PP-2','London Wall Car Park'),row('PP-3','Tower Hill Car Park'),row('PP-4','Minories Car Park')]
    hits,method=discover.dedupe({'name':'Baynard House, Queen Victoria Street','url':'https://example.org/shared'},[target,*others])
    assert hits==[target]
    assert method=='Source URL+name'


def test_heathrow_terminal_two_is_distinct_from_three_four_five():
    rows=[row(f'PP-{terminal}',f'Heathrow Terminal {terminal} Terminal Parking (formerly Short Stay)') for terminal in (2,3,4,5)]
    hits,method=discover.dedupe({'name':'Heathrow Terminal 2 Terminal Parking formerly Short Stay','url':'https://example.org/shared'},rows)
    assert hits==[rows[0]]
    assert method=='Source URL+name'


def test_ambiguous_url_falls_through_to_unique_postcode():
    target=row('PP-1','Same name',Postcode='TW6 1EW')
    other=row('PP-2','Same name',Postcode='E16 2PB')
    hits,method=discover.dedupe({'name':'Same name','url':'https://example.org/shared','postcode':'TW6 1EW'},[target,other])
    assert hits==[target]
    assert method=='postcode'


def test_true_shared_name_tie_remains_ambiguous():
    rows=[row('PP-1','Same name'),row('PP-2','Same name')]
    hits,_=discover.dedupe({'name':'Same name','url':'https://example.org/shared'},rows)
    assert hits==rows


def test_source_name_unicode_dash_does_not_discard_the_match(tmp_path):
    name='Hackney Central Station '+chr(0x2013)+' Amhurst Road'
    summary=discover.run([{'name':name,'url':'https://example.org/shared'}],[row('PP-1',name)],tmp_path,London())
    assert (summary['matched'],summary['exceptions'])==(1,0)
    with (tmp_path/'matches.csv').open() as stream:
        match=next(csv.DictReader(stream))
    assert match['name']=='Hackney Central Station - Amhurst Road'


def test_drafted_text_normalises_both_dashes(tmp_path):
    name='Station'+chr(0x2014)+'Road'
    summary=discover.run([{'name':name,'address':'A'+chr(0x2013)+'B'}],[],tmp_path,London())
    assert (summary['new'],summary['exceptions'])==(1,0)
    with (tmp_path/'candidates.csv').open() as stream:
        candidate=next(csv.DictReader(stream))
    assert candidate['Location Name']=='Station-Road'
    assert candidate['Street Address']=='A-B'


def test_near_equal_names_are_not_a_clear_winner():
    rows=[row('PP-1','Baynard House North Car Park'),row('PP-2','Baynard House South Car Park')]
    hits,_=discover.dedupe({'name':'Baynard House Car Park','url':'https://example.org/shared'},rows)
    assert len(hits)==2


def test_conflicting_terminal_number_cannot_win_a_fuzzy_match():
    rows=[row('PP-3','Heathrow Terminal 3 Short Stay Parking'),row('PP-4','Heathrow Terminal 4 Long Stay Parking')]
    hits,_=discover.dedupe({'name':'Heathrow Terminal 2 Short Stay Parking','url':'https://example.org/shared'},rows)
    assert len(hits)==2


def test_ambiguous_postcode_can_fall_through_to_a_precise_pin():
    rows=[row('PP-1','Same name',Postcode='TW6 1EW',Latitude='51.5',Longitude='0'),
          row('PP-2','Same name',Postcode='TW6 1EW',Latitude='51.6',Longitude='0')]
    hits,method=discover.dedupe({'name':'Same name','postcode':'TW6 1EW','lat':'51.5','lon':'0'},rows)
    assert hits==[rows[0]]
    assert method=='pin within 50 m'


def test_replay_preserves_official_evidence_and_includes_city(tmp_path):
    import importlib.util
    from pathlib import Path
    path=Path(__file__).parents[1]/'scripts'/'replay_discovery_batches.py'
    spec=importlib.util.spec_from_file_location('replay_shared_sources',path)
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    sheet_file=tmp_path/'sheet.csv'
    discover.write_table(sheet_file,[row('PP-1','City parking')],[])
    exceptions=tmp_path/'exceptions.csv'
    discover.write_table(exceptions,[{'source':json.dumps({'name':'City parking','url':'https://example.org/shared','official':True,'hours':'24/7'})}],[])
    out=tmp_path/'replay';out.mkdir()
    comparison=replay.replay(sheet_file,{'col':exceptions},out,London())
    with (out/'col'/'matches.csv').open() as stream:
        match=next(csv.DictReader(stream))
    assert json.loads(match['improvements'])[discover.HOURS]=='24/7'
    assert 'hours_unverified' not in json.loads(match['flags'])
    assert comparison[0]['previous_review']=={'listed':5,'matched':0,'exceptions':5}
    assert comparison[0]['after']=={'listed':1,'matched':1,'exceptions':0}


def test_replay_writes_source_and_sheet_names_for_spot_checks(tmp_path):
    import importlib.util
    from pathlib import Path
    path=Path(__file__).parents[1]/'scripts'/'replay_discovery_batches.py'
    spec=importlib.util.spec_from_file_location('replay_audit_names',path)
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    sheet_file=tmp_path/'sheet.csv'
    discover.write_table(sheet_file,[row('PP-1','Baynard House Car Park (City of London Corporation)')],[])
    exceptions=tmp_path/'exceptions.csv'
    discover.write_table(exceptions,[{'source':json.dumps({'name':'Baynard House, Queen Victoria Street','url':'https://example.org/shared'})}],[])
    out=tmp_path/'replay';out.mkdir()
    replay.replay(sheet_file,{'col':exceptions},out,London())
    with (out/'col'/'spot_checks.csv').open() as stream:
        check=next(csv.DictReader(stream))
    assert check['Place ID']=='PP-1'
    assert check['source_name']=='Baynard House, Queen Victoria Street'
    assert check['sheet_name']=='Baynard House Car Park (City of London Corporation)'
