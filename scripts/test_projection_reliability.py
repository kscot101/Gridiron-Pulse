import copy
import unittest
from projection_identity import canonical_id, changed, depth_starter, number, select_qbs
from refresh_projection_feed import stat_total


class ReliabilityTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        for value in (None,'','  ',True,False,{},[],float('nan'),float('inf'),'unavailable'):
            self.assertIsNone(number(value))
        self.assertEqual(number(0),0)
        self.assertEqual(number('0'),0)
        self.assertEqual(number(' 1.9 '),1.9)

    def test_namespaces(self):
        self.assertEqual(canonical_id('00-0026498'),'gsis:00-0026498')
        self.assertEqual(canonical_id('12483'),'espn:12483')
        self.assertFalse(changed('00-0026498','Matthew Stafford','12483','Matthew Stafford'))
        self.assertFalse(changed('00-0026498','Matthew Stafford','gsis:00-0026498','Matthew Stafford'))
        self.assertTrue(changed('00-001','Quarterback A','00-002','Quarterback B'))
        self.assertIsNone(changed('00-001','','123',''))
        self.assertIsNone(changed('00-001','A','123','B',False))

    def test_order_independent_conflict(self):
        a={'name':'Dak Prescott','team':'DAL','position':'QB','role':'STARTER','athleteId':'2577417'}
        b={'name':'Joe Milton III','team':'DAL','position':'QB','role':'STARTER','athleteId':'4362887'}
        self.assertFalse(select_qbs([a,b],[])['DAL']['resolved'])
        self.assertEqual(select_qbs([a,b],[])['DAL']['playerId'],select_qbs([b,a],[])['DAL']['playerId'])
        historical=[{'player_name':'Dak Prescott','position':'QB','player_id':'00-0033077','latest_rate':260}]
        verified={'DAL':{'id':'2577417','name':'Dak Prescott'}}
        for room in ([a,b],[b,a]):
            result=select_qbs(room,historical,verified)['DAL']
            self.assertEqual(result['playerName'],'Dak Prescott')
            self.assertEqual(result['playerId'],'gsis:00-0033077')
            self.assertEqual(result['rate'],260)
            self.assertTrue(result['resolved'])

    def test_unique_starter_and_unverified_rank(self):
        a={'name':'QB A','position':'QB','team':'DET','role':'STARTER','id':'1'}
        b={'name':'QB B','position':'QB','team':'DET','role':'BACKUP','id':'2','depthRank':1}
        self.assertEqual(select_qbs([a,b],[])['DET']['playerName'],'QB A')
        b['role']='STARTER'
        self.assertFalse(select_qbs([a,b],[])['DET']['resolved'])
        a['depthChart']={'sourceCount':1,'rank':1}
        self.assertEqual(select_qbs([a,b],[])['DET']['playerName'],'QB A')

    def test_no_invented_zero_current_stats(self):
        self.assertEqual(stat_total({'actualGames':0},['passingYards']),0)
        self.assertIsNone(stat_total({'actualGames':1},['passingYards']))
        self.assertIsNone(stat_total({},['passingYards']))
        self.assertEqual(stat_total({'actualGames':1,'currentStats':{'passingYards':0}},['passingYards']),0)
        self.assertIsNone(stat_total({'actualGames':1,'currentStats':{'rushingYards':12}},['rushingYards','receivingYards']))

    def test_explicit_depth_rank(self):
        data={'depthchart':[{'positions':{'qb':{'position':{'abbreviation':'QB'},'athletes':[
            {'rank':2,'athlete':{'id':'2','displayName':'Backup'}},
            {'rank':1,'athlete':{'id':'1','displayName':'Starter'}}]}}}]}
        self.assertEqual(depth_starter(data)['id'],'1')
        data['depthchart'][0]['positions']['qb']['athletes'][0]['rank']=1
        self.assertIsNone(depth_starter(data))
        self.assertIsNone(depth_starter({}))


if __name__=='__main__':
    unittest.main(verbosity=2)
