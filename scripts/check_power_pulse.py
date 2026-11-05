#!/usr/bin/env python3
"""Exercise first-visitor rankings with live services and the big mirror blocked."""
import json,mimetypes,time,shutil
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,unquote
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE='https://kscot101.github.io/Gridiron-Pulse/'

def run():
    data=json.loads((ROOT/'data/power-pulse.json').read_text());p=data['rankings'];errors=[];requests=[]
    report={'testedAt':datetime.now(timezone.utc).isoformat(),'mode':'First visitor; all external feeds and full homepage mirror blocked','teams':len(p['teams']),'players':len(p['players']),'passed':False}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--no-sandbox'],executable_path=shutil.which('chromium'))
        context=browser.new_context(viewport={'width':1365,'height':900},timezone_id='America/New_York')
        def route(r):
            url=r.request.url
            if not url.startswith(BASE):return r.abort()
            rel=unquote(urlsplit(url).path.removeprefix(urlsplit(BASE).path)) or 'index.html'
            requests.append(rel)
            if rel=='data/homepage-snapshot.json':return r.abort()
            local=(ROOT/rel).resolve()
            if not local.is_relative_to(ROOT) or not local.is_file():return r.fulfill(status=404,body='Unavailable')
            r.fulfill(path=str(local),content_type=mimetypes.guess_type(str(local))[0] or 'application/octet-stream')
        context.route('**/*',route)
        page=context.new_page();page.on('pageerror',lambda err:errors.append(str(err)))
        start=time.monotonic();page.goto(BASE,wait_until='domcontentloaded')
        page.wait_for_function("document.querySelectorAll('#power-grid .ranking-card').length===16",timeout=10000)
        report['firstVisitLoadMs']=round((time.monotonic()-start)*1000)
        state=page.evaluate("({games:allGames().length,boards:allBoards().length,power:powerRankings(),text:document.getElementById('power-feed-status').textContent})")
        assert state['games']==0 and state['boards']==0
        assert state['power']==p
        report['noLiveDependency']=True;report['status']=state['text']
        page.locator('#power-pulse').scroll_into_view_if_needed()
        expected=sorted(p['teams'],key=lambda t:t['heatScore'],reverse=True)[:16]
        displayed=page.locator('#power-grid .ranking-card .heat > strong').all_text_contents()
        assert [str(round(t['heatScore'])) for t in expected]==displayed
        report['exactTeamScores']=True
        page.locator('[data-power-order="cold"]').click()
        assert page.locator('#power-grid .ranking-card .heat > strong').first.inner_text()==str(min(t['heatScore'] for t in p['teams']))
        page.locator('[data-power-order="hot"]').click();page.locator('[data-power-kind="players"]').click()
        positions=page.locator('[data-power-position]').evaluate_all('(els)=>els.map(e=>e.dataset.powerPosition)')
        for pos in positions:
            page.locator('[data-power-position="'+pos+'"]').click()
            expected=sorted([r for r in p['players'] if r['positionGroup']==pos],key=lambda t:t['heatScore'],reverse=True)[:16]
            assert page.locator('#power-grid .ranking-card').count()==len(expected)
            assert page.locator('#power-grid .ranking-card .heat > strong').all_text_contents()==[str(round(t['heatScore'])) for t in expected]
        report['positionFilters']=positions;report['exactPlayerScores']=True
        page.locator('[data-power-position="QB"]').click()
        name=page.locator('#power-grid .ranking-card [data-profile-kind="player"]').first
        report['profileName']=name.inner_text();name.click()
        page.locator('#detail-overlay.open').wait_for(timeout=10000)
        assert report['profileName'] in page.locator('#detail-overlay').inner_text()
        page.keyboard.press('Escape');report['playerProfile']=True
        page.locator('[data-power-kind="teams"]').click()
        for metric,key in [('offense','offensePulse'),('defense','defensePulse'),('tandem','tandemPulse')]:
            b=page.locator('[data-power-metric="'+metric+'"]')
            if b.is_enabled():
                b.click()
                expected_scores=page.evaluate('(key)=>powerRankings().teams.map(t=>GPPowerPulse.metric(t,key,state.historicalOutlook)).filter(x=>x!==null).sort((a,b)=>b-a).slice(0,16)',key)
                assert page.locator('#power-grid .ranking-card .heat > strong').all_text_contents()[:len(expected_scores)]==[str(int(v+0.5)) for v in expected_scores]
        page.locator('[data-power-metric="overall"]').click()
        report['unitViewsChecked']=True
        context.route(BASE+'data/power-pulse.json*',lambda r:r.abort())
        page.evaluate('()=>GPPowerPulse.load()')
        assert page.locator('#power-grid .ranking-card').count()==16
        report['failedRefreshRetainsRankings']=True
        page.evaluate('()=>{state.snapshot={games:[],playerEdge:[],powerRankings:{teams:[],players:[]}};renderAll();}')
        assert page.locator('#power-grid .ranking-card').count()==16
        report['lateEmptyFeedRetainsRankings']=True
        page.locator('#power-pulse').scroll_into_view_if_needed()
        page.screenshot(path=str(ROOT/'power-pulse-desktop.png'))
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844});page.locator('#power-pulse').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
        report['mobileOverflow']=False
        page.set_viewport_size({'width':390,'height':844});page.locator('#power-pulse').scroll_into_view_if_needed();page.screenshot(path=str(ROOT/'power-pulse-mobile.png'))
        assert not errors,errors
        report['pageErrors']=errors;report['passed']=True
        browser.close()
    (ROOT/'power-pulse-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':run()
