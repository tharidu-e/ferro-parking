import csv
import json
from pathlib import Path

import pytest

from ferro_parking import propose_categories as pc
from ferro_parking.discover import write_table
from ferro_parking.validation import dropdowns


@pytest.mark.parametrize('typ,want',[
    ('Hotel','Hotel'), ('Hotel / Private Car Park (operator - APCOA)','Hotel'),
    ('Gym (PureGym)','Gym / leisure centre'), ('Leisure Centre (Better/GLL)','Gym / leisure centre'),
    ('Supermarket (Co-op)','Supermarket - convenience'), ('Supermarket (Iceland)','Supermarket - convenience'),
    ('Retail / Supermarket','Supermarket - large format'), ('Supermarket','Supermarket - large format'),
    ('Retail - Trade/DIY','Retail warehouse / DIY / trade'), ('Retail / Trade & DIY','Retail warehouse / DIY / trade'),
    ('Retail - DIY','Retail warehouse / DIY / trade'), ('DIY / Home Improvement Store','Retail warehouse / DIY / trade'),
    ('DIY / Home store','Retail warehouse / DIY / trade'), ('Retail Warehouse','Retail warehouse / DIY / trade'),
    ('Retail - Warehouse club (members)','Retail warehouse / DIY / trade'), ('Garden Centre','Retail warehouse / DIY / trade'),
    ('Retail (Dobbies)','Retail warehouse / DIY / trade'), ('Retail / Shopping Centre','Shopping centre'), ('Retail Park','Shopping centre'),
    ('Other Retail (Example)','Other'), ('Retail Store (Next)','Other'), ('Retail / Discount store','Other'),
    ('Retail - Clothing/Homeware','Other'), ('Retail - Furniture/Home','Other'),
    ("Restaurant (Nando's)",'Fast food / drive-thru'), ('Restaurant (KFC)','Fast food / drive-thru'),
    ("Restaurant (McDonald's)",'Fast food / drive-thru'), ('Restaurant (Burger King)','Fast food / drive-thru'),
    ('Fast Food / Drive-thru','Fast food / drive-thru'), ('Pub-restaurant','Restaurant / pub / cafe'),
    ('Restaurant (Independent)','Restaurant / pub / cafe'), ('Station Car Park (National Rail)','Station'),
    ('Station (National Rail - Southeastern)','Station'), ('Fuel station (Esso)','Petrol station'), ('Petrol Station (Shell)','Petrol station'),
    ('Private Car Park (operator - NCP)','Private / operator car park'),
    ('Public Car Park (Council)','Council car park'), ('Council car-park','Council car park'),
    ('Hospital','Hospital / health centre'), ('Health Centre (private outpatients)','Hospital / health centre'),
    ('Hospital / Private Car Park (operator - Saba)','Hospital / health centre'),
    ('University','School / college'), ('College (FE)','School / college'),
    ('Cinema','Other'), ('Stadium / Arena','Other'), ('Place of Worship','Other'), ('Airport','Other'),
    ('EV charging (InstaVolt)','Other'), ('EV Charging (Tesla Supercharger)','Other'), ('Car wash (IMO)','Other'),
    ('Cemetery (Council)','Other'), ('Crematorium','Other'), ('Park / Attraction','Other'), ('Park Car Park','Other'),
])
def test_explicit_type_groups_only_use_real_dropdown_values(typ,want):
    value,reason,confidence=pc.category_proposal({'Type (as captured)':typ})
    assert value==want
    assert value in dropdowns()['Place Category']
    assert confidence=='high'
    assert reason


def test_name_station_cannot_override_supermarket_and_small_brand_refines_type():
    value,_,_=pc.category_proposal({'Location Name':'M&S Waterloo Station','Type (as captured)':'Retail / Supermarket','Brand':'M&S Simply Food'})
    assert value=='Supermarket - convenience'
    assert pc.category_proposal({'Location Name':'Station House','Type (as captured)':'Retail Store (Example)'})[0]=='Other'
    assert pc.category_proposal({'Location Name':'Station House','Type (as captured)':''})[0]==''


def test_park_car_park_requires_council_wording():
    assert pc.category_proposal({'Type (as captured)':'Park Car Park','Location Name':'Council park'})[0]=='Council park / open space'
    assert pc.category_proposal({'Type (as captured)':'Park Car Park','Location Name':'Private attraction'})[0]=='Other'


def test_normalised_dashes_case_and_whitespace():
    typ='  PRIVATE CAR PARK (operator '+chr(0x2013)+' NCP)  '
    assert pc.category_proposal({'Type (as captured)':typ})[0]=='Private / operator car park'


@pytest.mark.parametrize('typ',['','  ','Undocumented object','Parking area'])
def test_unknown_or_ambiguous_type_is_unclassified(typ):
    proposed,unclassified,conflicts=pc.proposals([{'Type (as captured)':typ,'Location Name':'Example Station'}])
    assert proposed==conflicts==[]
    assert unclassified[0]['proposed_place_category']==''


def test_single_valued_discovery_fallback_has_medium_confidence():
    value,_,confidence=pc.category_proposal({'Type (as captured)':'Railway station entrance'})
    assert (value,confidence)==('Station','medium')


def test_current_matching_category_is_omitted_differences_and_invalid_values_are_conflicts():
    rows=[{'Place ID':'PP-1','Type (as captured)':'Hotel','Place Category':'Hotel'},
          {'Place ID':'PP-2','Type (as captured)':'Hotel','Place Category':'Other'},
          {'Place ID':'PP-3','Type (as captured)':'Park Car Park','Place Category':'Park / open space'}]
    proposed,unclassified,conflicts=pc.proposals(rows)
    assert proposed==unclassified==[]
    assert [r['Place ID'] for r in conflicts]==['PP-2','PP-3']
    for row in conflicts:
        assert row['current_place_category']==row['Place Category']
        assert row['current_place_category'] in row['reason']
        assert row['proposed_place_category'] in row['reason']


def test_fallback_ignores_existing_category_and_does_not_use_other_or_car_park():
    assert pc.category_proposal({'Type (as captured)':'Parking area','Place Category':'Hotel'})[0]==''
    assert pc.category_proposal({'Type (as captured)':'Mystery','Place Category':'Other'})[0]==''


def test_cli_preserves_input_uses_exclusive_outputs_and_strips_all_written_dashes(tmp_path,monkeypatch):
    from ferro_parking import fill
    monkeypatch.setattr(fill.sheets,'get_service',lambda:pytest.fail('No Google authentication'))
    source=tmp_path/'sheet.csv'
    rows=[{'Place ID':'PP-1','Location Name':'Example'+chr(0x2014)+'Hotel','Brand':'A'+chr(0x2013)+'B','Type (as captured)':'Hotel','Place Category':''},
          {'Place ID':'PP-2','Location Name':'','Brand':'','Type (as captured)':'','Place Category':''}]
    write_table(source,rows,[])
    before=source.read_bytes()
    out=tmp_path/'proposal'
    assert pc.main(['--sheet-csv',str(source),'--out',str(out)])==0
    assert source.read_bytes()==before
    for file in out.glob('*.csv'):
        text=file.read_text()
        assert chr(0x2013) not in text and chr(0x2014) not in text
    with (out/'propose_categories.csv').open() as stream:
        row=next(csv.DictReader(stream))
    assert 'proposed_brand' not in row
    assert row['Brand']=='A-B'
    with pytest.raises(FileExistsError):
        pc.main(['--sheet-csv',str(source),'--out',str(out)])


def test_osm_is_only_an_observation_and_cannot_map_missing_type(tmp_path):
    source=tmp_path/'sheet.csv'
    write_table(source,[{'Place ID':'PP-1','Location Name':'Station','Latitude':'51.5','Longitude':'-0.1','Type (as captured)':''}],[])
    out=tmp_path/'proposal'
    pbf=Path(__file__).parent/'fixtures'/'discovery_sample.osm'
    assert pc.main(['--sheet-csv',str(source),'--out',str(out),'--pbf',str(pbf)])==0
    with (out/'unclassified.csv').open() as stream:
        row=next(csv.DictReader(stream))
    assert row['proposed_place_category']==''
    assert json.loads(row['OSM evidence'])[0]['tags']['amenity']=='parking'


def test_whitespace_only_is_blank_but_filled_whitespace_is_not_an_exact_dropdown():
    proposed,unclassified,conflicts=pc.proposals([
        {'Type (as captured)':'Hotel','Place Category':'  '},
        {'Type (as captured)':'Hotel','Place Category':' Hotel '},
    ])
    assert len(proposed)==1 and unclassified==[]
    assert len(conflicts)==1
    assert conflicts[0]['current_place_category']==' Hotel '
    assert 'outside dropdown' in conflicts[0]['reason']
