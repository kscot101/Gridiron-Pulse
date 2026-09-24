"""Offline guardrails. Mock records are never exported as real predictions."""
import unittest
from copy import deepcopy
from datetime import timedelta
import pandas as pd
import projection_trial as T

class TrialTests(unittest.TestCase):
    def test_missing_and_zero(self):
        for v in [None,'',' ',True,False,'nan','--',[],{},float('inf')]:
            self.assertIsNone(T.number(v))
        self.assertEqual(T.number(0),0)
        self.assertEqual(T.number('0'),0)

    def test_freeze_is_immutable(self):
        now=T.dt('2026-09-24T18:00:00Z')
        r={'id':'g|1|trial','kickoff':'2026-09-25T00:00:00Z','predictions':{'receiving_yards':55}}
        ledger={}; self.assertTrue(T.freeze(ledger,r,now));original=deepcopy(ledger)
        self.assertFalse(T.freeze(ledger,{**r,'predictions':{'receiving_yards':99}},now))
        self.assertEqual(ledger,original)
        self.assertFalse(T.freeze({},r,now+timedelta(days=1)))
        self.assertFalse(T.freeze({},r,T.dt(r['kickoff'])-timedelta(minutes=4)))

    def test_exact_stat_grade_no_generic_hit(self):
        now=T.dt('2026-09-26T00:00:00Z')
        rec={'kickoff':'2026-09-25T00:00:00Z','recordedAt':'2026-09-24T18:00:00Z','predictions':{'passing_yards':280,'passing_tds':1.8}}
        result=T.grade(rec,{'passing_yards':200,'passing_tds':2},True,now,'hash')
        self.assertEqual(result['metrics']['passing_yards']['absoluteError'],80)
        self.assertEqual(result['metrics']['passing_tds']['absoluteError'],0.2)
        self.assertNotIn('HIT',str(result))
        missing=T.grade(rec,{'passing_yards':0},True,now,'hash')
        self.assertEqual(missing['metrics']['passing_yards']['absoluteError'],280)
        self.assertEqual(missing['metrics']['passing_tds']['status'],'NO_DATA')
        self.assertEqual(T.grade(rec,{},False,now,'hash')['status'],'PENDING')

    def test_position_identity_not_stat_category(self):
        s={'header':{'id':'g','season':{'year':2026,'type':2},'week':2,'competitions':[{'date':'2026-09-20T00:00:00Z','status':{'type':{'completed':True}}}]},'boxscore':{'teams':[],'players':[{'team':{'abbreviation':'KC'},'statistics':[{'name':'receiving','labels':['REC','YDS','TD','TGTS'],'athletes':[{'athlete':{'id':'87','displayName':'Test TE'},'stats':['5','70','0','8']},{'athlete':{'id':'unknown'},'stats':['2','20','0','2']}]}]}]}}
        rows=T.parse_summary(s,{('87','KC'):{'id':'gsis87','position':'TE'}})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['position'],'TE')
        self.assertEqual(rows[0]['receiving_tds'],0)
        self.assertIsNone(rows[0]['rushing_yards'])
        self.assertIsNone(rows[0]['scrimmage_yards'])

    def test_future_stats_do_not_change_same_game_forecast(self):
        rows=[]
        for w in range(1,6):
            rows.append({'player_id':'p','team':'A','position':'WR','season':2024,'week':w,'team_attempts':30.,'team_carries':20.,**{k:float(w) for k in T.STATS}})
        d=pd.DataFrame(rows); f=T.features(d,3)
        d.loc[d.week.eq(4),T.STATS]=9999
        d.loc[d.week.eq(4),'team_attempts']=9999
        modified=T.features(d,3)
        cols=[c for c in f if c.startswith('s_') or c.startswith('expected_')]
        a=f[f.week.eq(4)][cols].reset_index(drop=True)
        b=modified[modified.week.eq(4)][cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(a,b)

    def test_freshness(self):
        now=T.dt('2026-09-24T18:00:00Z')
        self.assertFalse(T.fresh('2026-09-24T14:00:00Z',now))
        self.assertFalse(T.fresh('2026-09-24T19:00:00Z',now))
        self.assertTrue(T.fresh('2026-09-24T17:00:00Z',now))

if __name__=='__main__': unittest.main(verbosity=2)
