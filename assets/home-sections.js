(function () {
  'use strict';
  function init() {
    var ids=['top','my-pulse','season-outlook','availability','games','player-edge','live','power-pulse','model-record','results'];
    var sections=ids.map(function(id){return document.getElementById(id);});
    var rail=document.getElementById('home-section-links');
    var drawer=document.getElementById('home-sections-drawer');
    var drawerNav=document.getElementById('home-drawer-links');
    var toggle=document.getElementById('home-sections-toggle');
    var close=document.getElementById('home-sections-close');
    var scrim=document.getElementById('home-sections-scrim');
    if (!rail || sections.some(function(section){return !section;})) return;
    drawerNav.innerHTML=rail.innerHTML;
    var current='top', queued=false;
    function activate(id) {
      if (!ids.includes(id)) return;
      current=id;
      document.querySelectorAll('.home-section-link').forEach(function(button) {
        if (button.dataset.homeSection===id) button.setAttribute('aria-current','location');
        else button.removeAttribute('aria-current');
      });
    }
    function update() {
      queued=false;
      var marker=Math.min(220,window.innerHeight*.35), visible='top';
      sections.forEach(function(section) {
        if (section.getBoundingClientRect().top<=marker) visible=section.id;
      });
      if (window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-8) visible='results';
      if (visible!==current) activate(visible);
    }
    function schedule() {
      if (!queued) {queued=true;requestAnimationFrame(update);}
    }
    function setDrawer(open) {
      drawer.classList.toggle('is-open',open);
      drawer.setAttribute('aria-hidden',String(!open));
      drawer.inert=!open;
      scrim.hidden=!open;
      toggle.setAttribute('aria-expanded',String(open));
      document.body.classList.toggle('sections-drawer-open',open);
      if (open) close.focus();
      else toggle.focus({preventScroll:true});
    }
    toggle.addEventListener('click',function(){setDrawer(true);});
    close.addEventListener('click',function(){setDrawer(false);});
    scrim.addEventListener('click',function(){setDrawer(false);});
    drawer.addEventListener('keydown',function(event) {
      if (event.key==='Escape') {event.preventDefault();setDrawer(false);return;}
      if (event.key!=='Tab') return;
      var focusable=Array.from(drawer.querySelectorAll('button')).filter(function(b){return b.offsetParent!==null;});
      var first=focusable[0],last=focusable[focusable.length-1];
      if (event.shiftKey && document.activeElement===first) {event.preventDefault();last.focus();}
      else if (!event.shiftKey && document.activeElement===last) {event.preventDefault();first.focus();}
    });
    document.querySelectorAll('.home-section-rail,.home-sections-drawer').forEach(function(nav) {
      nav.addEventListener('click',function(event) {
        var button=event.target.closest('[data-scroll]');
        if (!button) return;
        activate(button.dataset.scroll);
        if (nav===drawer) setDrawer(false);
      });
    });
    window.addEventListener('scroll',schedule,{passive:true});
    window.addEventListener('resize',function(){if(window.innerWidth>1180 && drawer.classList.contains('is-open')) setDrawer(false);schedule();},{passive:true});
    update();
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();
