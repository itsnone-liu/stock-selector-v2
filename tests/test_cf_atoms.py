import csv,json,struct
from pathlib import Path
from stock_selector.cf.atoms import INSUFFICIENT,replay_l1,replay_l4,replay_margin


def write_csv(p,fields,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def test_margin_requires_both_exchanges_and_emits_state(tmp_path):
    s=[]
    for i in range(25):s.append({'信用交易日期':f'202601{i+1:02d}','融资余额':1000+i*20,'融资买入额':10})
    write_csv(tmp_path/'sse_margin/summary_x.csv',list(s[0]),s)
    for i in range(25):write_csv(tmp_path/f'szse_margin/202601{i+1:02d}.csv',['融资余额','融资买入额'],[{'融资余额':1+i*.01,'融资买入额':.1}])
    rows=replay_margin(tmp_path)
    assert rows[-1]['state']=='LEVERAGE_BUILDING'
    assert rows[-1]['source_id']=='sse_szse_official_margin_v1'


def test_margin_overlapping_sse_segments_are_deduplicated(tmp_path):
    row={'信用交易日期':'20260101','融资余额':1000,'融资买入额':10}
    write_csv(tmp_path/'sse_margin/summary_a.csv',list(row),[row])
    write_csv(tmp_path/'sse_margin/summary_b.csv',list(row),[row])
    write_csv(tmp_path/'szse_margin/20260101.csv',['融资余额','融资买入额'],[{'融资余额':1,'融资买入额':.1}])
    from stock_selector.cf.atoms import load_margin
    assert load_margin(tmp_path)['20260101']['balance']==100001000


def test_margin_live_overlay_ignores_one_sided_date(tmp_path):
    import gzip
    from stock_selector.cf.atoms import overlay_live_margin
    live=tmp_path/'live';live.mkdir()
    with gzip.open(live/'margin_sse.jsonl.gz','wt') as f:f.write(json.dumps({'date':'20260102','rzye':100,'rzmre':1})+'\n')
    base={'20260101':{'balance':10,'buy':1,'sources':['sse_official','szse_official']}}
    assert '20260102' not in overlay_live_margin(base,live)


def day(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b''.join(struct.pack('<IIIIIfII',d,int(c*100),int(c*100),int(c*100),int(c*100),a,1,0) for d,c,a in rows))


def test_l4_replay_uses_only_tdx_breadth(tmp_path):
    rows=[(20260101+i,100+i,1000.0) for i in range(65)]
    day(tmp_path/'vipdoc/sh/lday/sh880005.day',rows);day(tmp_path/'vipdoc/sh/lday/sh880006.day',[(d,60,1000) for d,_,_ in rows])
    out=replay_l4(tmp_path)
    assert out[-1]['state']!='INSUFFICIENT_SUPPORT'
    assert out[-1]['source_id']=='tdx_880005_880006_v1'


def test_l1_g9_fails_closed_on_mechanical_jump(tmp_path):
    fields=['统计日期','基金代码','基金简称','基金份额']
    names=['沪深300ETF','上证50ETF','中证500ETF']
    write_csv(tmp_path/'sse_etf_scale/20260101.csv',fields,[{'统计日期':'2026-01-01','基金代码':f'51030{i}','基金简称':n,'基金份额':100} for i,n in enumerate(names)])
    write_csv(tmp_path/'sse_etf_scale/20260102.csv',fields,[{'统计日期':'2026-01-02','基金代码':f'51030{i}','基金简称':n,'基金份额':300 if i==0 else 101} for i,n in enumerate(names)])
    cfg={'families':{'A':{'name_pattern':['沪深300']},'B':{'name_pattern':['上证50']},'C':{'name_pattern':['中证500']}},'exclusion_words_v1':[]}
    up=tmp_path/'u.json';up.write_text(json.dumps(cfg,ensure_ascii=False))
    out=replay_l1(tmp_path,up)
    assert out[-1]['state']==INSUFFICIENT
    assert out[-1]['reason']=='G9_adjustment_unverified'
