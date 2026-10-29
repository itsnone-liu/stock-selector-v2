import importlib.util
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

p=Path(__file__).resolve().parents[1]/'scripts/cfis/is2b_macro_context.py'
s=importlib.util.spec_from_file_location('macro',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
TZ=timezone(timedelta(hours=8))

def raw(day='2024-01-01',value=5):
    return {'refRates':[{'effectiveDate':day,'type':'SOFR','percentRate':value}]}

def test_assumption_lag_not_observation_date():
    r=m.parse(raw(),'sofr')
    assert m.point(r,datetime(2024,1,7,tzinfo=TZ)) is None
    assert m.point(r,datetime(2024,1,8,tzinfo=TZ))['value']==5
    assert m.point(r,datetime(2024,1,16,tzinfo=TZ)) is None

def test_invalid_duplicate_type_nan():
    for r in [dict(refRates=[]),dict(refRates=raw()['refRates']*2),raw(value=float('nan'))]:
        with pytest.raises(ValueError):m.parse(r,'sofr')
    with pytest.raises(ValueError):m.parse(raw(),'effr')

def test_future_not_used_and_spread_alignment():
    rates={'sofr':m.parse(raw(),'sofr'),'effr':m.parse({'refRates':[{'effectiveDate':'2024-01-02','type':'EFFR','percentRate':4}]},'effr')}
    f=[{'week':'2024-W02','assessment_at':'2024-01-09T00:00:00+08:00','current_known':'True'}]
    r=m.build(f,rates)[0]
    assert r['sofr_minus_effr_pp']==''
    assert r['vintage_status']=='LATEST_VINTAGE_NOT_PIT'
    later=m.parse(raw('2024-02-01',9),'sofr')
    assert m.build(f,{**rates,'sofr':rates['sofr']+later})==[r]
