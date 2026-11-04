const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../static/js/dashboard.js'),'utf8');
const section=src.slice(src.indexOf('  /* ---- device control ---- */'),src.indexOf('  /* ---- apply data ---- */'));
const elements={},sent=[],messages=[];
function el(id){return elements[id]||(elements[id]={checked:false,value:50,textContent:'',dataset:{},handlers:{},classList:{toggle(){}},addEventListener(t,f){this.handlers[t]=f;}});}
const socket={connected:true,emit:(e,p)=>sent.push([e,p])};
const ctx={document:{getElementById:el},socket,showSys:m=>messages.push(m),setTimeout:()=>1,clearTimeout(){},Date,Math,Map,performance:{now:()=>0}};vm.createContext(ctx);vm.runInContext(section,ctx);
const toggle=el('kt-buzzer-toggle');
assert.equal(typeof toggle.handlers.change,'function','Kitchen buzzer must have a change handler (regression: visible toggle sent nothing)');
toggle.checked=true;toggle.handlers.change();
assert.equal(sent.length,1);assert.equal(sent[0][0],'set_device');assert.equal(sent[0][1].room,'kitchen');assert.equal(sent[0][1].device,'buzzer');assert.equal(sent[0][1].state,true);assert.equal(typeof sent[0][1].request_id,'string');
assert.match(el('kt-buzzer-status').textContent,/chờ thiết bị/);
let data=ctx.confirmedData('kitchen',{buzzer:true});assert.equal(data.buzzer,undefined,'Telemetry without matching BLE ACK must not confirm');
vm.runInContext("pendingControls.get('kitchen:buzzer').acknowledged=true",ctx);
data=ctx.confirmedData('kitchen',{buzzer:true});assert.equal(data.buzzer,true);
toggle.checked=false;toggle.handlers.change();assert.equal(sent[1][1].state,false);
socket.connected=false;toggle.checked=true;toggle.handlers.change();assert.equal(sent.length,2);assert.match(messages.at(-1),/Mất kết nối/);
console.log('PASS kitchen buzzer on/off, request correlation, ACK+telemetry, disconnected no command');
