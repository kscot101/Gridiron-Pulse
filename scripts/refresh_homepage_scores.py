#!/usr/bin/env python3
"""Read public scoreboards server-side; never generate picks or model grades."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
OUT=Path('data/homepage-scoreboard.json')


def get(url):
    request=Request(url,headers={'Accept':'application/json','User-Agent':'GridironPulse-Scores/1','Cache-Control':'no-cache'})
    with urlopen(request,timeout=35) as response:
        data=json.load(response)
    if not isinstance(data,dict) or not isinstance(data.get('events'),list):
        raise RuntimeError('Scoreboard returned an invalid response')
    return data


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (ValueError,TypeError):
        return None


def main():
    current=get(BASE)
    checked=datetime.now(timezone.utc)
    season=current.get('season') or {}
    week=(current.get('week') or {}).get('number')
    if not season.get('year') or not season.get('type') or not isinstance(week,int) or not current['events']:
        raise RuntimeError('Current season/week could not be verified')
    for event in current['events']:
        kickoff=stamp(event.get('date'))
        state=((event.get('status') or {}).get('type') or {}).get('state')
        if not kickoff or (state=='pre' and (checked-kickoff).total_seconds()>21600):
            raise RuntimeError('Scoreboard contains an expired scheduled game; retaining previous file')
    previous=None
    previous_error=None
    if week>1:
        try:
            url=BASE+'?'+urlencode({'dates':season['year'],'seasontype':season['type'],'week':week-1})
            previous=get(url)
            if str((previous.get('season') or {}).get('year'))!=str(season['year']) or str((previous.get('week') or {}).get('number'))!=str(week-1):
                raise RuntimeError('Previous-week response did not match requested season/week')
        except Exception as error:
            previous=None
            previous_error=str(error)
    payload={'ok':True,'fetchedAt':checked.isoformat(),'source':'ESPN public scoreboard','scoreboard':current,'previousScoreboard':previous,'previousError':previous_error,'note':'Timestamped score snapshot, not model predictions or locked-pick grades.'}
    OUT.parent.mkdir(exist_ok=True)
    temp=OUT.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(OUT)
    print(json.dumps({'fetchedAt':payload['fetchedAt'],'season':season,'week':week,'currentGames':len(current['events']),'previousGames':len((previous or {}).get('events',[])),'previousError':previous_error}),flush=True)


if __name__=='__main__':
    main()
