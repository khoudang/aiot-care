/* Run with NODE_PATH=<scratch>/admin-dom-tests/node_modules node --test this-file. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function fixture({failLogs=false}={}){
  const dom=new JSDOM(fs.readFileSync(path.join(root,'templates/index.html'),'utf8'),{runScripts:'outside-only',url:'http://isolated.test/dashboard'});
  const w=dom.window;
  let users=[{id:1,username:'fixture-admin',role:'admin',is_suspended:0},{id:2,username:'member\'"<img src=x onerror=alert(1)>',role:'member',is_suspended:0}];
  const requests=[];let failure='';
  w.alert=w.prompt=w.confirm=()=>{throw Error('Native account dialogs are unavailable');};
  w.fetch=async(url,opt={})=>{
    requests.push([url,opt]);
    if(failLogs&&url.startsWith('/api/admin/logs'))return {ok:false,json:async()=>({ok:false,message:'Logs unavailable'})};
    if(url.startsWith('/api/admin/users') && opt.method){
      if(failure)return {ok:false,json:async()=>({ok:false,message:failure})};
      if(url==='/api/admin/users')users.push({id:3,username:JSON.parse(opt.body).username,role:'member',is_suspended:0});
      else if(url.endsWith('/suspend'))users=users.map(u=>u.id===2?{...u,is_suspended:1-u.is_suspended}:u);
      else if(opt.method==='DELETE')users=users.filter(u=>u.id!==2);
      else if(url.endsWith('/edit'))users=users.map(u=>u.id===2?{...u,username:JSON.parse(opt.body).username}:u);
      return {ok:true,json:async()=>({ok:true,message:'Đã cập nhật.',users})};
    }
    return {ok:true,json:async()=>({ok:true,users,configs:{},nodes:[],locations:[],login_logs:[],audit_logs:[]})};
  };
  w.eval(fs.readFileSync(path.join(root,'static/js/admin.js'),'utf8'));
  await tick();
  return {w,requests,fail:message=>failure=message,close:()=>w.close()};
}
test('log load failure must not erase working user management',async()=>{
  const f=await fixture({failLogs:true});
  try{assert.ok(f.w.document.querySelector('[data-user-action="suspend"][data-user-id="2"]'),'log failure erased account controls');}
  finally{f.close();}
});
function submit(w,id){w.document.getElementById(id).dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));}
test('create, lock, unlock and explicitly confirm delete without native dialogs',async()=>{
  const f=await fixture();const {w}=f;const $=id=>w.document.getElementById(id);
  try{
    assert.ok($('user-create-form'),'missing account creation form');
    $('new-username').value='created-member';$('new-password').value='fixture-password';
    submit(w,'user-create-form');await tick();
    assert.match($('users-body').textContent,/created-member/);
    assert.equal($('new-password').value,'');
    assert.equal($('users-body').querySelector('img'),null,'username must not become HTML');
    $('users-body').querySelector('[data-user-action="suspend"][data-user-id="2"]').click();await tick();
    assert.match($('users-body').textContent,/Đã khóa/);
    $('users-body').querySelector('[data-user-action="suspend"][data-user-id="2"]').click();await tick();
    assert.doesNotMatch($('users-body').textContent,/Đã khóa/);
    $('users-body').querySelector('[data-user-action="delete"][data-user-id="2"]').click();await tick();
    assert.equal(f.requests.filter(([u,o])=>o.method==='DELETE').length,0);
    assert.equal($('user-delete-panel').hidden,false);
    $('user-delete-cancel').click();
    assert.equal($('user-delete-panel').hidden,true);
    $('users-body').querySelector('[data-user-action="delete"][data-user-id="2"]').click();
    $('user-delete-confirm').click();await tick();
    assert.equal($('users-body').querySelector('[data-user-id="2"]'),null);
    assert.match($('users-message').textContent,/Đã cập nhật/);
  }finally{f.close();}
});
test('lock denial remains inline and preserves table; edit uses in-page form',async()=>{
  const f=await fixture();const {w}=f;const $=id=>w.document.getElementById(id);
  try{
    assert.ok($('users-message'),'missing inline feedback');
    f.fail('Admin không thể tự khóa/mở khóa chính mình.');
    $('users-body').querySelector('[data-user-action="suspend"][data-user-id="1"]').click();await tick();
    assert.match($('users-message').textContent,/không thể tự khóa/);
    assert.ok($('users-body').querySelector('[data-user-id="2"]'));
    f.fail('');
    $('users-body').querySelector('[data-user-action="edit"][data-user-id="2"]').click();
    assert.equal($('user-edit-panel').hidden,false);
    $('edit-username').value='renamed-member';
    submit(w,'user-edit-form');await tick();
    assert.match($('users-body').textContent,/renamed-member/);
    assert.equal($('user-edit-panel').hidden,true);
  }finally{f.close();}
});
