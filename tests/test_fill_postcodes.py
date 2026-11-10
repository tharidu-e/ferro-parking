import csv
from pathlib import Path

import pytest

from ferro_parking import fill_postcodes as fp
from ferro_parking.discover import write_table
from ferro_parking.fill import PROTECTED_COLUMNS

FIX=Path(__file__).parent/'fixtures'/'postcode_centroids.csv'


def sheet(**extra):
    return {'Place ID':'PP-1','Location Name':'Example','Postcode':'','Latitude':'51.5001','Longitude':'-0.1','Geo Precision':'Building',**extra}


def test_nearby_centroid_proposal_and_real_distance():
    proposed,skipped=fp.postcode_proposals([sheet()],fp.load_directory(FIX))
    assert skipped==[]
    row=proposed[0]
    assert row['proposed_postcode']=='AA1 1AA'
    assert float(row['distance_m'])==pytest.approx(11.1,abs=0.1)
    assert row['method']=='nearest centroid'
    assert not any(key.startswith('proposed_') and key!='proposed_postcode' for key in row)
    assert {'Latitude','Longitude','Postcode','Geo Source','Geo Precision'} <= PROTECTED_COLUMNS


def test_distant_pin_is_skipped():
    proposed,skipped=fp.postcode_proposals([sheet(Latitude='52.0')],fp.load_directory(FIX),250)
    assert not proposed
    assert skipped[0]['reason']=='nearest postcode is too far'
    assert skipped[0]['proposed_postcode']==''


def test_postcode_centroid_pin_is_skipped_even_at_zero_distance():
    proposed,skipped=fp.postcode_proposals([sheet(**{'Latitude':'51.5','Geo Precision':'Postcode centroid'})],fp.load_directory(FIX))
    assert not proposed
    assert 'circular' in skipped[0]['reason']


@pytest.mark.parametrize('extra',[{'Postcode':'AA1 1AA'},{'Postcode':'Unknown'},{'Latitude':''},{'Longitude':'nan'},{'Latitude':'91'}])
def test_existing_postcode_or_missing_usable_pin_is_omitted(extra):
    assert fp.postcode_proposals([sheet(**extra)],fp.load_directory(FIX))==([],[])


def test_empty_directory_has_explicit_skip_reason():
    proposed,skipped=fp.postcode_proposals([sheet()],fp.PostcodeDirectory([]))
    assert proposed==[]
    assert skipped[0]['reason']=='no postcode directory loaded'


def test_equidistant_postcodes_are_not_guessed():
    directory=fp.PostcodeDirectory([{'postcode':'AA1 1AA','lat':51.5,'lon':-0.1},{'postcode':'AA1 1AB','lat':51.5,'lon':-0.1}])
    proposed,skipped=fp.postcode_proposals([sheet()],directory)
    assert proposed==[]
    assert 'ambiguous' in skipped[0]['reason']


def test_spatial_seed_cannot_override_the_true_haversine_nearest():
    directory=fp.PostcodeDirectory([{'postcode':'AA1 1AA','lat':80.0,'lon':0.01},{'postcode':'BB1 1BB','lat':80.002,'lon':0.0}])
    code,distance=directory.nearest(80.0,0.0)
    assert code=='AA1 1AA'
    assert 190<distance<200


@pytest.mark.parametrize('headers',['Postcode,latitude,longitude','pcds,lat,lon','POSTCODE,LAT,LON'])
def test_directory_column_aliases(tmp_path,headers):
    path=tmp_path/'directory.csv'
    path.write_text(headers+'\naa11aa,51.5,-0.1\n')
    assert fp.load_directory(path).nearest(51.5,-0.1)==('AA1 1AA',0.0)


@pytest.mark.parametrize('text',['postcode,lat\nAA11AA,51.5\n','postcode,lat,lon\nINVALID,51.5,-0.1\n','postcode,lat,lon\nAA11AA,nan,-0.1\n'])
def test_invalid_directory_fails_closed(tmp_path,text):
    path=tmp_path/'directory.csv';path.write_text(text)
    with pytest.raises(ValueError):
        fp.load_directory(path)


@pytest.mark.parametrize('limit',[-1,float('nan'),float('inf')])
def test_distance_limit_must_be_finite_nonnegative(limit):
    with pytest.raises(ValueError):
        fp.postcode_proposals([sheet()],fp.load_directory(FIX),limit)


def test_cli_preserves_input_and_exclusive_output_and_never_authenticates(tmp_path,monkeypatch,capsys):
    from ferro_parking import fill
    monkeypatch.setattr(fill.sheets,'get_service',lambda:pytest.fail('No Google authentication'))
    source=tmp_path/'sheet.csv'
    write_table(source,[sheet(**{'Location Name':'Example'+chr(0x2014)+'Place','Geo Source':'Official'+chr(0x2013)+'source'})],[])
    original=source.read_bytes();directory_original=FIX.read_bytes()
    out=tmp_path/'postcodes'
    args=['--sheet-csv',str(source),'--postcodes-csv',str(FIX),'--out',str(out)]
    assert fp.main(args)==0
    assert source.read_bytes()==original and FIX.read_bytes()==directory_original
    assert 'proposed=1 skipped=0' in capsys.readouterr().out
    for path in out.glob('*.csv'):
        assert chr(0x2013) not in path.read_text() and chr(0x2014) not in path.read_text()
    with pytest.raises(FileExistsError):
        fp.main(args)
