"""Round-1 authoritative artifact adapters.

This module only projects frozen artifacts. It intentionally fails closed for any
frozen output that has not been materialized at per-asof granularity; it never
re-implements or silently substitutes a research policy.
"""
from __future__ import annotations
import gzip, json
from pathlib import Path
from typing import Any
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.cd_shadow_runtime import assert_asof
from scripts.cd_shadow_daily import ShadowInvalid

class RealArtifactAdapters:
    def __init__(self, root: Path):
        self.root=Path(root); self.data=self.root/'data'/'cd'; self.docs=self.root/'docs'/'cd'
        self.l1=self._load_gz(self.data/'sector_axes'/'l1_market_axes.json.gz')['rows']
        self.l2=self._load_gz(self.data/'sector_axes'/'l2_state_table.json.gz')['states']
        self.pool=self._load_gz(self.data/'l3_candidate_pool_v2.json.gz')['pools']
        self.eps=self._load_gz(self.data/'l4_episodes.json.gz')['episodes']
        self.shadow_authority=self.data/'shadow_authority'
    @staticmethod
    def _load_gz(path: Path):
        if not path.exists(): raise ShadowInvalid(f'missing authoritative artifact: {path}')
        return json.loads(gzip.decompress(path.read_bytes()))
    def load_market_state(self, asof):
        rows=[r for r in self.l1 if r.get('date')==asof]
        if not rows: raise ShadowInvalid(f'L1 has no exact asof date: {asof}')
        r=rows[0]; return {'data_asof':asof,'regime_daily':r.get('regime'),'axes':r,'authority':'data/cd/sector_axes/l1_market_axes.json.gz'}
    def load_sector_states(self, asof):
        rows=[r for r in self.l2 if r.get('date')==asof]
        return {'data_asof':asof,'states':rows,'authority':'data/cd/sector_axes/l2_state_table.json.gz'}
    def load_candidate_pool(self, asof):
        x=self.pool.get(asof)
        if x is None: raise ShadowInvalid(f'L3 has no exact asof date: {asof}')
        return {'data_asof':asof,'candidates':x.get('U_list',[]),'candidate_source':{k:x.get(k,[]) for k in ('L','M','S')},'authority':'data/cd/l3_candidate_pool_v2.json.gz'}
    def load_episode_state(self, asof):
        # Episodes are stateful: only episodes started by or before asof and not ended before it.
        rows=[e for e in self.eps if e['start']<=asof and e['end']>=asof]
        return {'data_asof':asof,'episodes':rows,'authority':'data/cd/l4_episodes.json.gz'}
    def load_lifecycle_state(self, asof):
        # Lifecycle is not present as a frozen per-day cache; do not invent one.
        path=self.shadow_authority/'lifecycle'/f'{asof}.json.gz'
        if not path.exists(): raise ShadowInvalid(f'missing authoritative per-asof lifecycle artifact: {path}')
        return {'data_asof':asof,'lifecycle':self._load_gz(path),'authority':str(path.relative_to(self.root))}
    def _required_day_artifact(self, name, asof):
        path=self.shadow_authority/name/f'{asof}.json.gz'
        if not path.exists(): raise ShadowInvalid(f'missing authoritative per-asof {name}: {path}')
        return self._load_gz(path), path
    def derive_primary_zone(self, asof):
        x,p=self._required_day_artifact('primary_zone',asof); return {'data_asof':asof,'entries':x,'authority':str(p.relative_to(self.root))}
    def derive_frozen_decisions(self, asof):
        x,p=self._required_day_artifact('decisions',asof); return {'data_asof':asof,**x,'authority':str(p.relative_to(self.root)),'orders_allowed':False,'capital_allowed':False}
    def stages(self, asof):
        from scripts.cd_shadow_runtime import RuntimeAdapters
        return RuntimeAdapters(self.load_market_state,self.load_sector_states,self.load_candidate_pool,self.load_episode_state,self.load_lifecycle_state,self.derive_primary_zone,self.derive_frozen_decisions).stages(asof)
