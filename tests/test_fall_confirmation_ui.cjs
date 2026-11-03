const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/dashboard.js'),'utf8');
const start=source.indexOf('  /* ---- fall confirmation ---- */');
const end=source.indexOf('  /* ---- alert state machine ---- */',start);
assert.ok(start>=0&&end>start,'Patient fall confirmation controls must exist');
const calls=[],elements={};
function el(id){return elements[id]||(elements[id]={disabled:true,textContent:'',dataset:{},handlers:{},addEventListener(event,fn){this.handlers[event]=fn;}});}
const socket={connected:true,emit:(event,data)=>calls.push([event,data])};
const ctx={document:{getElementById:el},socket};vm.createContext(ctx);
vm.runInContext(source.slice(start,end),ctx);
const button=el('patient-confirm-safe'),message=el('patient-confirm-message');
const ready={required:true,active:false,pending:false,blocked_by_kitchen:false,node_online:true,can_confirm:true};
ctx.applyFallConfirmation(ready);
assert.equal(button.disabled,false,'Normal kitchen must not hide/disable pending fall confirmation');
button.handlers.click();assert.equal(calls.length,1);assert.equal(calls[0][0],'confirm_fall_safe');
assert.equal(button.disabled,true,'Prevent repeated clicks while request is in flight');
for(const patch of [{active:true,can_confirm:false},{pending:true,can_confirm:false},{blocked_by_kitchen:true,can_confirm:false},{node_online:false,can_confirm:false},{required:false,can_confirm:false}]){
 ctx.applyFallConfirmation({...ready,...patch});assert.equal(button.disabled,true,JSON.stringify(patch));
 button.handlers.click();assert.equal(calls.length,1,'Disabled button must never emit a confirmation');
}
ctx.applyFallConfirmation({...ready,pending:true,can_confirm:false});assert.match(message.textContent,/chờ node/i);
socket.connected=false;ctx.applyFallConfirmation(ready);assert.equal(button.disabled,true);assert.match(message.textContent,/kết nối/i);
const template=fs.readFileSync(path.join(__dirname,'../templates/index.html'),'utf8');
const patient=template.slice(template.indexOf('id="patient"'),template.indexOf('id="living"'));
assert.match(patient,/id="patient-confirm-safe"/,'Button must be inside patient room');
assert.doesNotMatch(patient,/<button[^>]*id="patient-confirm-safe"[^>]*hidden/);
const css=fs.readFileSync(path.join(__dirname,'../static/css/gateway-diagnostics.css'),'utf8');
assert.match(css,/\.patient-safety-confirm/,'CSS must style .patient-safety-confirm');
assert.match(css,/\.patient-confirm-btn/,'CSS must style .patient-confirm-btn');
assert.match(css,/body\.dark-mode/,'CSS must include dark-mode styling');
console.log('PASS: patient confirmation, safety guards, pending state, disconnect, scoped event, CSS and visible markup');
