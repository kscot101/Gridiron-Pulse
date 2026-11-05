import copy,json,unittest
from datetime import datetime,timezone
from pathlib import Path
from build_player_directory import build,rows,ROOT

class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.r=[dict(season='2026',gsis_id='00-0000001',espn_id='123',full_name='Different Name',football_name='Known',last_name='Name',position='WR',team='A',week='1',status='ACT')]
        self.s=[dict(player_id='00-0000001',player_display_name='Known Name',position='WR',team='A',season='2026',season_type='REG',week='1',game_id='g1',receiving_yards='41',receptions='3')]
        self.g=[dict(game_id='g1',game_type='REG',season='2026',week='1',gameday='2026-09-01',home_team='A',away_team='B',home_score='21',away_score='7')]
        self.old=dict(schemaVersion=1,players=[])
    def test_alias_and_ids(self):
        d,g=build(self.r,self.s,self.g,self.old,2026)
        self.assertEqual(g['players'][0]['espnId'],'123')
        self.assertIn('Different Name',g['players'][0]['aliases'])
        self.assertIn('Known Name',d['players'][0]['aliases'])
        self.assertEqual(g['players'][0]['games'][0]['stats']['receivingYards'],41)
    def test_unknown_not_zero(self):
        _,g=build(self.r,self.s,self.g,self.old,2026)
        self.assertIsNone(g['players'][0]['games'][0]['stats']['targets'])
    def test_future_not_results(self):
        self.g[0]['gameday']='2099-01-01'
        old=build(self.r,self.s,[dict(self.g[0],gameday='2026-09-01')],self.old,2026)[1]
        _,g=build(self.r,self.s,self.g,old,2026)
        self.assertEqual(g['latestGameDate'],'2026-09-01')
    def test_conflicting_provider_ids_fail(self):
        self.r.append(dict(self.r[0],espn_id='999'))
        with self.assertRaises(ValueError):build(self.r,self.s,self.g,self.old,2026)
    def test_roster_only_does_not_invent_appearance(self):
        self.r.append(dict(self.r[0],gsis_id='00-0000002',espn_id='456',full_name='Roster Only'))
        d,g=build(self.r,self.s,self.g,self.old,2026)
        self.assertFalse(next(p for p in d['players'] if p['athleteId']=='456')['hasRecordedGames'])
        self.assertEqual(len(g['players']),1)
    def test_original_not_mutated(self):
        before=copy.deepcopy(self.old);build(self.r,self.s,self.g,self.old,2026);self.assertEqual(self.old,before)
    def test_current_real_source_coverage(self):
        d=json.loads((ROOT/'data/player-directory.json').read_text());g=json.loads((ROOT/'data/player-recent-games.json').read_text())
        ids={p['id'] for p in d['players']};log_ids={p['id'] for p in g['players']}
        self.assertTrue(log_ids.issubset(ids))
        self.assertEqual(len(ids),len(d['players']))
        es=[p['athleteId'] for p in d['players'] if p['athleteId']];self.assertEqual(len(es),len(set(es)))
        self.assertGreater(d['coverage']['currentSeasonStatPlayers'],100)
        for p in g['players']:
            games=p['games'];self.assertEqual(len(games),len({x['gameId'] for x in games}))
if __name__=='__main__':unittest.main(verbosity=2)
