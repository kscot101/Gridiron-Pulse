from pathlib import Path
import json, os, re
from datetime import datetime
from playwright.sync_api import sync_playwright
root=Path.cwd();base='http://127.0.0.1:8765/Gridiron-Pulse/'
data=json.loads((root/'data/projection-trial.json').read_text());board=json.loads((root/'data/homepage-scoreboard.json').read_text())
# Deterministic rendering at the supplied snapshot's time. Public checks use wall time.
stamp=max(data['generatedAt'],board['fetchedAt'])
when=int(datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()*1000)+60000
report={'snapshotTime':stamp,'mode':'Saved statistical inputs; external APIs blocked','pageErrors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.getenv('CHROMIUM_PATH') or None)
    context=browser.new_context(viewport={'width':390,'height':844},timezone_id='America/New_York')
    context.add_init_script('''{const T=%d, Real=Date;window.Date=class extends Real{constructor(...v){super(...(v.length?v:[T]));}static now(){return T;}};}'''%when)
    def route(rt):
        url=rt.request.url
        if not url.startswith(base):return rt.abort()
        rel=url[len(base):].split('?')[0].split('#')[0] or 'index.html'
        if rel=='data/homepage-snapshot.json':return rt.fulfill(status=503,body='Outage fixture')
        path=(root/rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():return rt.fulfill(status=404,body='Missing')
        return rt.fulfill(path=str(path))
    context.route('**/*',route)
    page=context.new_page();page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
    page.goto(base,wait_until='domcontentloaded')
    page.locator('#gp-saved-picks .ds-pick').first.wait_for(timeout=20000)
    page.wait_for_function("[...document.querySelectorAll('#gp-saved-picks .gp-pick-reason')].some(e=>e.textContent.includes('Averaged'))")
    reason=page.locator('#gp-saved-picks .gp-pick-reason').first.inner_text()
    for selector in ['#gp-saved-spotlight','#gp-saved-picks']:
        txt=page.locator(selector).inner_text()
        assert not re.search(r'v2\.?1|WORKLOAD TRIAL|Tracked v2|verified pregame captures',txt,re.I),txt
        assert 'Why this player' in txt
    rows=page.locator('#gp-saved-picks [data-saved-record]').evaluate_all("ns=>ns.map(n=>({id:n.dataset.savedRecord,stats:[...n.querySelectorAll('[data-saved-metric]')].map(m=>({key:m.dataset.savedMetric,text:m.textContent}))}))")
    for row in rows:
        record=next(r for r in data['forecasts'] if r['id']==row['id'])
        for m in row['stats']:assert float(m['text'].replace(',',''))==record['predictions'][m['key']]
    page.locator('#gp-saved-picks .gp-pick-details summary').first.click()
    assert 'Saved' in page.locator('#gp-saved-picks .gp-pick-details').first.inner_text()
    assert not re.search(r'v2\.?1|WORKLOAD TRIAL',page.locator('#gp-saved-picks .gp-pick-details').first.inner_text(),re.I)
    page.locator('#gp-saved-picks .gp-pick-details summary').first.click()
    page.locator('[data-edge="qb"]').click();page.wait_for_function("[...document.querySelectorAll('#gp-saved-picks .ds-pick>small')].every(x=>x.textContent.includes('/ QB'))")
    page.locator('[data-edge="all"]').click()
    page.locator('#gp-saved-picks').scroll_into_view_if_needed();page.screenshot(path='pick-copy-mobile.png')
    for width in [320,390,768,1440]:
        page.set_viewport_size({'width':width,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2'),width
    page.locator('#gp-saved-picks').scroll_into_view_if_needed();page.screenshot(path='pick-copy-desktop.png')
    # Exercise the normal renderer separately using an unchanged real record.
    sample=next(r for r in reversed(data['forecasts']) if r['position']=='WR' and r['model']=='v2.1-tracked-1')
    rendered=page.evaluate('''r=>{const p={name:r.playerName,athleteId:r.athleteId,player_id:r.player_id,position:r.position,team:r.team,opponent:r.opponent,gameId:r.gameId};const h=document.createElement('section');h.innerHTML=playerProjectionMarkup(p);return {text:h.textContent,metrics:[...h.querySelectorAll('[data-metric]')].map(n=>({k:n.dataset.metric,v:n.textContent})),reason:h.querySelectorAll('.gp-pick-reason').length};}''',sample)
    assert rendered['reason']==1
    assert not re.search(r'v2\.?1|WORKLOAD TRIAL',rendered['text'],re.I)
    assert len(rendered['metrics'])==len(sample['predictions'])
    for m in rendered['metrics']:assert float(m['v'].replace(',',''))==sample['predictions'][m['k']]
    page.locator('#gp-trial-switch').check()
    assert 'Use recent-usage estimates' in page.locator('.gp-exact-switch').inner_text()
    assert not report['pageErrors'],report['pageErrors']
    report.update(passed=True,exactForecastValues=True,normalAndBackupCards=True,plainLabels=True,detailsRetained=True,positionFilters=True,mobileOverflow=False,exampleReason=reason)
    (root/'pick-copy-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));browser.close()
