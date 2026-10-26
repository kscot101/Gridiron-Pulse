import unittest
from datetime import datetime, timezone
from build_defense_profiles import aggregate, build, num, fantasy, PLAYER_FIELDS, METRICS

class DefenseTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertIsNone(num(''));self.assertIsNone(num(None));self.assertEqual(num('0'),0)
        a=aggregate([{'values':{'passYards':0}},{'values':{'passYards':None}}],['passYards'])['passYards']
        self.assertEqual(a,{'value':0,'n':1,'expected':2})
    def test_ratio_is_volume_weighted(self):
        a=aggregate([{'values':{'completions':1,'attempts':1}},{'values':{'completions':1,'attempts':9}}],['completionPct'])
        self.assertEqual(a['completionPct']['value'],20)
    def fixture(self):
        game={'game_id':'g1','season':'2026','game_type':'REG','week':'1','gameday':'2026-09-10','gametime':'20:00','home_team':'KC','away_team':'LV','home_score':'21','away_score':'14','espn':'1'}
        fields=['completions','attempts','passing_yards','passing_tds','passing_interceptions','sack_yards_lost','rushing_yards','rushing_tds','carries','receptions','receiving_yards','passing_20','rushing_10','fumbles_lost_total','def_sacks','def_interceptions','def_qb_hits']
        rows=[dict.fromkeys(fields,'0') for _ in range(2)]
        for r,t,o in zip(rows,['KC','LV'],['LV','KC']):r.update(season='2026',season_type='REG',game_id='g1',team=t,opponent_team=o)
        rows[1].update(passing_yards='210',sack_yards_lost='-10',rushing_yards='90',passing_interceptions='1',fumbles_lost_total='2',attempts='30',completions='20',receptions='20',receiving_yards='210')
        return rows,[game]
    def test_opponent_direction_and_net(self):
        teams,games=self.fixture();d,p=build(teams,[],games,2026,now=datetime(2026,10,1,tzinfo=timezone.utc))
        v=d['teams']['KC']['games'][0]['values'];self.assertEqual(v['passYards'],210);self.assertEqual(v['netPassYards'],200);self.assertEqual(v['rushYards'],90);self.assertEqual(v['takeaways'],3)
        self.assertIsNone(v['TE_fantasy'])
    def test_postseason_future_and_unfinished_excluded(self):
        teams,games=self.fixture()
        for changes in [{'game_type':'POST'},{'gameday':'2027-01-01'},{'home_score':''}]:
            g=dict(games[0],**changes);d,p=build(teams,[],[g],2026,now=datetime(2026,10,1,tzinfo=timezone.utc));self.assertEqual(d['teams']['KC']['completedGames'],0)
    def test_duplicate_conflict_fails(self):
        teams,games=self.fixture();teams.append(dict(teams[0],passing_yards='999'))
        with self.assertRaises(ValueError):build(teams,[],games,2026)
    def test_scoring_explicit(self):
        fields=['passing_yards','passing_tds','passing_interceptions','rushing_yards','rushing_tds','receiving_yards','receiving_tds','receptions','sack_fumbles_lost','rushing_fumbles_lost','receiving_fumbles_lost','passing_2pt_conversions','rushing_2pt_conversions','receiving_2pt_conversions']
        r=dict.fromkeys(fields,'0');r.update(passing_yards='250',passing_tds='2',passing_interceptions='1',rushing_yards='20')
        self.assertEqual(fantasy(r),18);r['passing_yards']='';self.assertIsNone(fantasy(r))
    def test_last_three_use_final_three_not_last_three_nonmissing(self):
        from build_defense_profiles import windows
        games=[{'id':str(i),'date':str(i),'values':{'passYards':v}} for i,v in enumerate([100,200,None,300])]
        s=windows(games,['passYards'])['last3']['passYards'];self.assertEqual(s,{'value':250,'n':2,'expected':3})
    def test_real_data_reconciles(self):
        import csv
        from pathlib import Path
        root=Path('.defense-inputs')
        if not root.exists():self.skipTest('No downloaded inputs')
        def read(n):
            with (root/(n+'.csv')).open() as f:return list(csv.DictReader(f))
        d,p=build(read('teams'),read('players'),read('games'),2026)
        self.assertEqual(len(d['teams']),32);self.assertGreater(len(p['players']),100)
        for t in d['teams'].values():
            self.assertEqual(len({g['id'] for g in t['games']}),len(t['games']))
            self.assertEqual(t['averages']['season']['points']['n'],t['completedGames'])
            for g in t['games']:
                v=g['values']
                if v['passYards'] is not None:self.assertGreaterEqual(v['passYards'],v['netPassYards'])
if __name__=='__main__':unittest.main(verbosity=2)
