import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import Point

from ferro_parking import readiness, triage_blanks
from ferro_parking.fill import CAN_PARK, SOURCE_URLS
from ferro_parking.validation import HOURS


def ready(**changes):
    return {CAN_PARK:'Yes','Latitude':'51.5','Longitude':'-0.1','Who Can Park':'Anyone (paid)',
            'Cost Type':'Paid',HOURS:'24/7','Max Stay (mins)':'120','Tariff Detail':'£1.00 per hour',
            'Borough':'Hackney','Postcode':'E8 1AA',**changes}


@pytest.mark.parametrize('column,value',[('Latitude','nan'),('Longitude','inf'),('Latitude','91'),('Longitude','181'),('Latitude',''),('Longitude','no pin'),('Who Can Park','Unknown'),('Cost Type','Not published'),(CAN_PARK,'No'),(CAN_PARK,'')])
def test_showable_requires_answers_and_usable_numeric_pin(column,value):
    assert readiness.bars(ready(**{column:value}))==(False,False)


def test_readiness_time_exception_requires_documented_source():
    row=ready(**{HOURS:'Not published','Max Stay (mins)':'Not published'})
    assert readiness.bars(row)==(True,False)
    row[SOURCE_URLS]='https://example.org/site'
    assert readiness.bars(row)==(True,True)
    row['Tariff Detail']='Not published'
    assert readiness.bars(row)==(True,False)


def test_not_applicable_counts_as_known():
    row=ready(**{HOURS:'Not applicable','Max Stay (mins)':'Not applicable','Tariff Detail':'Not applicable'})
    assert readiness.bars(row)==(True,True)


@pytest.mark.parametrize('column',['Who Can Park','Cost Type','Tariff Detail'])
def test_documentation_does_not_make_unknown_driver_value_known(column):
    row=ready(**{column:'Not published',SOURCE_URLS:'https://example.org/site'})
    assert readiness.bars(row)[1] is False


@pytest.mark.parametrize('postcode,district',[('TW6 1EW','TW6'),('E162PB','E16'),('sw1a 1aa','SW1A'),('','Unknown'),('Not published','Unknown')])
def test_postcode_district(postcode,district):
    assert readiness.postcode_district(postcode)==district


def test_readiness_counts_both_bars_by_borough_and_district():
    result=readiness.counts([ready(),ready(**{HOURS:'Not published'}),ready(**{'Borough':'','Postcode':'TW6 1EW',CAN_PARK:'No'})])
    assert result['total']=={'rows':3,'showable':2,'complete':1}
    assert result['by_borough']['Hackney']=={'rows':2,'showable':2,'complete':1}
    assert result['by_district']['TW6']=={'rows':1,'showable':0,'complete':0}
    assert result['by_borough']['Unknown']['rows']==1


@pytest.mark.parametrize('name,category,kind,url,want',[
    ('Tesco','Supermarket - convenience','Retail','', 'likely venue customers-only'),
    ('Hotel','Hotel','Hotel','', 'likely venue customers-only'),
    ('Gym','Gym / leisure centre','Gym','', 'likely venue customers-only'),
    ('Hospital','Hospital / health centre','Hospital','', 'likely venue customers-only'),
    ('Station car park','','Station Car Park','', 'station'),
    ('Council car park','Council car park','','', 'council'),
    ('APCOA','Private / operator car park','','https://www.apcoa.co.uk/site', 'operator with a URL'),
    ('NCP','','Parking','https://example.org/site', 'operator with a URL'),
    ('Petrol station','Petrol station','','','likely venue customers-only'),
    ('Mystery','','','', 'unknown'),
])
def test_triage_buckets(name,category,kind,url,want):
    row={'Place ID':'PP-1','Location Name':name,'Place Category':category,'Type (as captured)':kind,SOURCE_URLS:url,CAN_PARK:''}
    result=triage_blanks.triage([row])[0]
    assert result['bucket']==want
    assert result['reason']
    assert result['Source URL']==url
    assert result['Place ID']=='PP-1'
    assert CAN_PARK not in result


def test_triage_includes_every_blank_and_leaves_nonblank_rows_out():
    rows=[{CAN_PARK:'', 'Place ID':'PP-1','Verified By':'Tharidu'}, {CAN_PARK:'  ','Place ID':'PP-2'}, {CAN_PARK:'Unknown','Place ID':'PP-3'}]
    assert [r['Place ID'] for r in triage_blanks.triage(rows)]==['PP-1','PP-2']


def test_optional_osm_evidence_is_observation_not_a_parking_answer():
    from ferro_parking import osm_match
    point=Point(-0.1,51.5)
    park={'geom':osm_match.to_m(point),'ll':point,'type':'node','id':12,'tags':{'amenity':'parking','access':'customers'}}
    row={**ready(),CAN_PARK:'','Place ID':'PP-1','Location Name':'Shop'}
    result=triage_blanks.triage([row],parks=[park])[0]
    evidence=json.loads(result['OSM evidence'])
    assert evidence[0]['tags']['access']=='customers'
    assert evidence[0]['distance_m']==0
    assert CAN_PARK not in result


def test_local_commands_never_change_the_input(tmp_path,capsys):
    source=tmp_path/'sheet.csv'
    rows=[{**ready(),CAN_PARK:'','Place ID':'PP-1','Location Name':'Example hotel','Place Category':'Hotel'},ready()]
    headers=list(dict.fromkeys(k for row in rows for k in row))
    with source.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=headers)
        writer.writeheader(); writer.writerows(rows)
    original=source.read_bytes()
    assert triage_blanks.main(['--sheet-csv',str(source),'--out',str(tmp_path/'triage')])==0
    assert readiness.main(['--sheet-csv',str(source)])==0
    assert source.read_bytes()==original
    assert 'showable=1 complete=1' in capsys.readouterr().out
    with (tmp_path/'triage'/'triage_blanks.csv').open() as stream:
        assert len(list(csv.DictReader(stream)))==1
    with pytest.raises(FileExistsError):
        triage_blanks.main(['--sheet-csv',str(source),'--out',str(tmp_path/'triage')])


def test_entrypoint_wires_read_only_commands(tmp_path,monkeypatch):
    import sys
    from ferro_parking import __main__, fill
    source=tmp_path/'sheet.csv'
    source.write_text(CAN_PARK+',Location Name\n,Example hotel\n')
    monkeypatch.setattr(fill.sheets,'get_service',lambda:pytest.fail('Read-only commands must not authenticate'))
    for command,extra in [('readiness',[]),('triage-blanks',['--out',str(tmp_path/'triage')]),
                          ('propose-categories',['--out',str(tmp_path/'categories')]),
                          ('fill-postcodes',['--postcodes-csv',str(Path(__file__).parent/'fixtures'/'postcode_centroids.csv'),'--out',str(tmp_path/'postcodes')])]:
        monkeypatch.setattr(sys,'argv',['ferro_parking',command,'--sheet-csv',str(source),*extra])
        assert __main__.main()==0


def test_optional_pbf_cli_uses_existing_collector(tmp_path):
    source=tmp_path/'sheet.csv'
    source.write_text(CAN_PARK+',Location Name,Latitude,Longitude\n,Example shop,51.5,-0.1\n')
    pbf=Path(__file__).parent/'fixtures'/'discovery_sample.osm'
    assert triage_blanks.main(['--sheet-csv',str(source),'--pbf',str(pbf),'--out',str(tmp_path/'triage')])==0
    with (tmp_path/'triage'/'triage_blanks.csv').open() as stream:
        row=next(csv.DictReader(stream))
    assert json.loads(row['OSM evidence'])[0]['tags']['amenity']=='parking'
