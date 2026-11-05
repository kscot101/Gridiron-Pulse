"""Real published inputs, external APIs disabled; assertions use stored actuals."""
import json, os, re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
root=Path.cwd();base='https://kscot101.github.io/Gridiron-Pulse/'
directory=json.loads((root/'data/player-directory.json').read_text());logs=json.loads((root/'data/player-recent-games.json').read_text());ledger=json.loads((root/'data/projection-trial.json').read_text());board=json.loads((root/'data/homepage-scoreboard.json').read_text())
stamp=max(ledger['generatedAt'],board['fetchedAt']);when=int(datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()*1000)+60000
report={'testedAt':datetime.now().astimezone().isoformat(),'mode':'Published local statistics; external feeds and full game-log download blocked','pageErrors':[],'coverage':directory['coverage']}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.getenv('CHROMIUM_PATH') or None)
    context=browser.new_context(viewport={'width':1440,'height':1000},timezone_id='America/New_York')
    context.add_init_script('{const T=%d,R=Date;window.Date=class extends R{constructor(...v){super(...(v.length?v:[T]));}static now(){return T;}};}'%when)
    def route(rt):
        u=rt.request.url
        if not u.startswith(base):return rt.abort()
        rel=u[len(base):].split('?')[0].split('#')[0] or 'index.html'
        if rel in ['data/homepage-snapshot.json','data/player-recent-games.json']:return rt.fulfill(status=503,body='Unavailable external-feed test')
        f=(root/rel).resolve()
        if not f.is_relative_to(root) or not f.is_file():return rt.fulfill(status=404,body='Missing')
        return rt.fulfill(path=str(f))
    context.route('**/*',route)
    page=context.new_page();page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
    page.goto(base,wait_until='domcontentloaded')
    page.wait_for_function("window.GPPlayerDirectory && GPPlayerDirectory.status === 'ready'")
    counts=page.evaluate('''()=>{const ps=allPlayers();return {all:ps.length,unique:new Set(ps.map(p=>p.player_id||p.athleteId||p.id)).size,missing:GPPlayerDirectory.all().filter(p=>!ps.some(x=>x.player_id&&x.player_id===p.player_id||x.athleteId&&x.athleteId===p.athleteId)).map(p=>p.name)}}''')
    assert counts['all']==counts['unique'],counts
    assert not counts['missing'],counts
    report['searchablePlayers']=counts['all']
    cases=['Foyesade Oluokun','D.J. Moore','T J Watt','Rob Beal Jr.','Jaylahn Tuimoloau']
    checked=[]
    for query in cases:
        page.locator('#open-search').click()
        page.locator('#search-input').fill(query)
        first=page.locator('[data-search-open="player"]').first
        first.wait_for(timeout=10000)
        key=first.get_attribute('data-search-key');name=first.locator('strong').inner_text()
        person=next(x for x in directory['players'] if (x['athleteId'] or x['id'])==key)
        expected=next(x for x in logs['players'] if x['id']==person['player_id'])
        first.click()
        recent=page.locator('#detail-body .gp-recent-root')
        recent.locator('tbody tr').first.wait_for(timeout=15000)
        rows=recent.locator('tbody tr');assert rows.count()==min(5,len(expected['games'])),(query,rows.count())
        assert expected['games'][0]['opponent'] in rows.first.inner_text(),query
        assert 'Actual results, not projections.' in recent.inner_text()
        assert 'Expected ' not in recent.inner_text()
        assert page.locator('#detail-body .gp-recent-root').count()==1
        assert page.locator('#detail-body .gp-h2h-root').count()==1
        headings=recent.locator('thead th').all_text_contents()
        cells=rows.first.locator('td').all_text_contents()
        stat=expected['games'][0]['stats']
        labels={'Pass Yds':'passingYards','Rec Yds':'receivingYards','Rush Yds':'rushingYards','Solo':'soloTackles','Sacks':'sacks'}
        for heading,field in labels.items():
            if heading in headings and stat.get(field) is not None:
                value=cells[headings.index(heading)-1].replace(',','');assert float(value)==stat[field],(query,field,value,stat[field])
        checked.append({'query':query,'name':name,'id':key,'latestGame':expected['games'][0]['date'],'rows':rows.count()})
        page.keyboard.press('Escape')
    report['searchToLogs']=checked
    report['publishedProfileCoverage']=page.evaluate('''()=>GPPlayerDirectory.all().filter(p=>p.hasRecordedGames).length''')
    synthetic=page.evaluate('''()=>{const d=GPPlayerDirectory,original=d.all();d.ingest({ok:true,schemaVersion:1,players:[{id:'00-0000001',player_id:'00-0000001',athleteId:'100',name:'Same Name',position:'WR',teams:['A'],aliases:[]},{id:'00-0000002',player_id:'00-0000002',athleteId:'101',name:'Same Name',position:'WR',teams:['B'],aliases:[]}]});const result={ambiguous:d.resolve({name:'Same Name',position:'WR'})===null,exact:d.resolve({athleteId:'101'}).id==='00-0000002',conflict:d.resolve({player_id:'00-0000001',athleteId:'101'})===null,unknown:d.resolve({athleteId:'999',name:'Same Name'})===null};d.ingest({ok:true,schemaVersion:1,players:original});return result;}''')
    assert all(synthetic.values()),synthetic;report['identityGuards']=synthetic
    page.wait_for_function('window.GPExactTracker && GPExactTracker.data')
    example=next(r for r in reversed(ledger['forecasts']) if r['position']=='WR')
    normal=page.evaluate('''r=>{let el=document.createElement('div');el.innerHTML=GPExactTracker.strip(r);return [...el.querySelectorAll('[data-metric]')].map(n=>({key:n.dataset.metric,value:n.textContent,label:n.previousElementSibling&&n.previousElementSibling.textContent}));}''',example)
    assert len(normal)==len(example['predictions'])
    for item in normal:
        assert item['label'].startswith('Expected '),item
        assert float(item['value'].replace(',',''))==example['predictions'][item['key']]
    page.locator('#gp-saved-picks [data-saved-record]').first.wait_for(timeout=15000)
    saved=page.locator('#gp-saved-picks [data-saved-record]').evaluate_all('''ns=>ns.map(n=>({id:n.dataset.savedRecord,values:[...n.querySelectorAll('[data-saved-metric]')].map(m=>({key:m.dataset.savedMetric,value:m.textContent,label:m.previousElementSibling&&m.previousElementSibling.textContent}))}))''')
    for card in saved:
        rec=next(r for r in ledger['forecasts'] if r['id']==card['id'])
        for item in card['values']:
            assert item['label'].startswith('Expected ')
            assert float(item['value'].replace(',',''))==rec['predictions'][item['key']]
    report.update(normalLabels=True,backupLabels=True,forecastValuesUnchanged=True)
    absent=next(x for x in directory['players'] if not x['hasRecordedGames'])
    page.evaluate('''p=>GPPlayerStats.open(p)''',absent)
    page.wait_for_function("document.querySelector('#detail-body .gp-recent-root')?.getAttribute('aria-busy') === 'false'")
    assert 'does not mean the player did not play' in page.locator('#detail-body .gp-recent-root').inner_text()
    page.keyboard.press('Escape')
    for width in [320,390,768,1440]:
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),width
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#gp-saved-picks').scroll_into_view_if_needed();page.screenshot(path='player-directory-picks-mobile.png')
    page.locator('#open-search').click();page.locator('#search-input').fill('Foyesade Oluokun');page.locator('[data-search-open="player"]').first.click()
    page.locator('#detail-body .gp-recent-root tbody tr').first.wait_for()
    page.locator('#detail-body .gp-recent-root').scroll_into_view_if_needed();page.screenshot(path='player-directory-logs-mobile.png')
    assert not report['pageErrors'],report['pageErrors']
    report.update(passed=True,mobileOverflow=False)
    (root/'player-directory-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    browser.close()
