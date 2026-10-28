from pathlib import Path
p=Path('assets/saved-picks.js');s=p.read_text()
anchor='  function card(r){'
helper='''  function filtered(rows){
    var selected=root.state&&root.state.edge;
    if(selected==='qb')return rows.filter(function(r){return r.position==='QB';});
    if(selected==='stars')return rows.filter(function(r){return r.position!=='QB';});
    if(selected!=='favorites')return rows;
    var favorites=root.state&&root.state.favorites||{};
    return rows.filter(function(r){
      var comp=list(r.scheduleGame.competitions)[0]||{};
      var side=list(comp.competitors).find(function(c){return tm((c.team||{}).abbreviation)===tm(r.team);});
      var tid=String(side&&side.team&&side.team.id||'');
      return list(favorites.players).some(function(p){return String(p.athleteId||p.key)===String(r.athleteId);})||list(favorites.teams).some(function(t){return tm(t.abbreviation||t.team||t.key)===tm(r.team)||(tid&&String(t.key||t.id||t.teamId)===tid);});
    });
  }
'''
if 'function filtered(rows)' not in s:s=s.replace(anchor,helper+anchor)
s=s.replace("var show=rows.length>0&&edge&&!edge.querySelector('[data-record-id]');","var shown=filtered(rows);\n    var show=rows.length>0&&edge&&!edge.querySelector('[data-record-id]');")
s=s.replace("<strong>'+rows.length+' player matchups", "<strong>'+shown.length+' player matchups")
s=s.replace("(expanded?rows:rows.slice(0,6)).map(card).join('')", "(shown.length?(expanded?shown:shown.slice(0,6)).map(card).join(''):'<p class=\"ds-note\">No saved picks match this filter.</p>')")
s=s.replace("(rows.length>6?'<button", "(shown.length>6?'<button")
s=s.replace("'Show all '+rows.length+' picks'", "'Show all '+shown.length+' picks'")
s=s.replace("if(e.target.closest('.ds-expand'))", "if(e.target.closest('[data-edge]')){expanded=false;requestAnimationFrame(paint);}if(e.target.closest('.ds-expand'))")
s=s.replace("if(result[0].status==='fulfilled'&&Array.isArray(result[0].value.forecasts))saved=result[0].value;", "if(result[0].status==='fulfilled'&&Array.isArray(result[0].value.forecasts)&&(!saved||at(result[0].value.generatedAt)>=at(saved.generatedAt)))saved=result[0].value;")
s=s.replace("if(result[1].status==='fulfilled'&&result[1].value.ok===true)schedule=result[1].value;", "if(result[1].status==='fulfilled'&&result[1].value.ok===true&&(!schedule||at(result[1].value.fetchedAt)>=at(schedule.fetchedAt)))schedule=result[1].value;")
p.write_text(s)
