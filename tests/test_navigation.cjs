const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/dashboard.js'),'utf8');
const start=source.indexOf('  const rooms=document.querySelectorAll');
const end=source.indexOf('  function touch()',start);
function setup(href,ids=['overview','patient','personal']){
  const rooms=ids.map(id=>({id,classList:{toggle(name,value){this[name]=value;}}}));
  const events={};let pushes=0,replaces=0;
  const location={href};
  const context={URL,queueMicrotask,window:{location,addEventListener:(name,fn)=>events[name]=fn,
    history:{pushState(a,b,url){location.href=String(url);pushes++;},replaceState(a,b,url){location.href=String(url);replaces++;}}},
    document:{readyState:'loading',querySelectorAll:selector=>selector==='.room'?rooms:[],getElementById:()=>null,querySelector:()=>null,
      addEventListener:(name,fn)=>events[name]=fn},closeDrawer(){}};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  return {context,rooms,events,location,counts:()=>({pushes,replaces})};
}
const initial=setup('http://localhost/dashboard?tab=patient');
initial.events.DOMContentLoaded();
assert.equal(initial.rooms.find(r=>r.id==='patient').classList.active,true);
assert.equal(initial.counts().pushes,0);
initial.context.goTo('personal');
assert.equal(new URL(initial.location.href).searchParams.get('tab'),'personal');
assert.equal(initial.counts().pushes,1);
const reloaded=setup(initial.location.href);reloaded.events.DOMContentLoaded();
assert.equal(reloaded.rooms.find(r=>r.id==='personal').classList.active,true);
initial.location.href='http://localhost/dashboard?tab=patient';initial.events.popstate();
assert.equal(initial.rooms.find(r=>r.id==='patient').classList.active,true);
const forbidden=setup('http://localhost/dashboard?tab=admin-users');forbidden.events.DOMContentLoaded();
assert.equal(forbidden.rooms[0].classList.active,true);
assert.equal(new URL(forbidden.location.href).searchParams.get('tab'),'overview');
console.log('PASS: reload restores tab, back navigation, inaccessible tab fallback');
