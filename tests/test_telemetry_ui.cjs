const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'static/js/dashboard.js'), 'utf8');
const start = source.indexOf('  function applyTelemetry(');
const end = source.indexOf('  function updateNodeChip(', start);
assert.ok(start >= 0 && end > start, 'Actual production renderer must exist');
class Element {
  constructor(cls = '') {
    this.className = cls; this.textContent = ''; this.dataset = {};
    this.classList = {
      contains: c => this.className.split(/\s+/).includes(c),
      add: c => this.classList.toggle(c, true),
      remove: c => this.classList.toggle(c, false),
      toggle: (c, yes) => {const set = new Set(this.className.split(/\s+/).filter(Boolean)); yes ? set.add(c) : set.delete(c); this.className = [...set].join(' ');}
    };
    this.sub = {textContent: ''};
  }
  querySelector() { return this.sub; }
}
const nodes = {'data-quality-patient': new Element(), 'node-patient': new Element(), 'ov-patient-badge': new Element('rb bad')};
nodes['ov-patient-badge'].textContent = 'Known alarm';
const ctx = {document: {getElementById: id => nodes[id] || null}, telemetryCache: {}, nodeState:{patient:true}};
vm.createContext(ctx); vm.runInContext(source.slice(start, end), ctx);
ctx.applyTelemetry({patient: {status: 'stale', fields: {temp: {status: 'stale'}}}});
assert.equal(nodes['ov-patient-badge'].textContent, 'Known alarm');
assert.equal(nodes['ov-patient-badge'].className, 'rb bad');
assert.match(nodes['data-quality-patient'].textContent, /đã cũ/);
nodes['ov-patient-badge'].className = 'rb ok';
nodes['ov-patient-badge'].textContent = 'Nhận dữ liệu';
ctx.applyTelemetry({patient: {status: 'stale'}});
assert.equal(nodes['ov-patient-badge'].className, 'rb warn');
ctx.applyTelemetry({patient: {status: 'fresh'}});
assert.equal(nodes['ov-patient-badge'].textContent, 'Nhận dữ liệu');
ctx.applyTelemetry({patient: {status: 'partial', fields: {temp: {status: 'missing'}}}});
assert.match(nodes['data-quality-patient'].textContent, /nhiệt độ/);
ctx.nodeState.patient=false;
ctx.applyTelemetry({patient: {status: 'offline', transport_state: 'connecting'}});
assert.equal(nodes['node-patient'].sub.textContent, 'Đang kết nối BLE');
assert.doesNotMatch(nodes['data-quality-patient'].textContent, /mất nguồn|tắt nguồn/);
console.log('PASS: base freshness renderer checks');
// Exercise real production socket handlers, not hand-written equivalents.
const eventElements = {}, callbacks = {};
const eventCtx = {document: {getElementById: id => eventElements[id] || (eventElements[id] = new Element())},
  nodeState: {patient:true,living:true,kitchen:true}, telemetryCache: {}, setGauge() {}, touch() {},
  socket: {on: (name, fn) => callbacks[name] = fn}};
vm.createContext(eventCtx);
function loadActual(first, next) {
  const a=source.indexOf(first), b=source.indexOf(next,a); assert.ok(a>=0&&b>a);
  vm.runInContext(source.slice(a,b),eventCtx);
}
loadActual('  function badge(', '  function setToggle(');
loadActual('  function applyKitchen(', '  function applyAI(');
loadActual('  function setNode(', '  function setConn(');
for(const event of ['node_status','room_update']){
  const line=source.split('\n').find(l=>l.includes(`socket.on('${event}',`));assert.ok(line);vm.runInContext(line,eventCtx);
}
const cases=[
 ['cached fresh versus disconnect',()=>{
   eventCtx.applyTelemetry({patient:{status:'fresh',transport_connected:true}});
   callbacks.node_status({patient:false});
   assert.ok(eventElements['node-patient'].classList.contains('off'));
   assert.doesNotMatch(eventElements['node-patient'].sub.textContent,/Đang nhận dữ liệu/);
 }],
 ['cached offline versus reconnect',()=>{
   eventCtx.nodeState.patient=false;
   eventCtx.applyTelemetry({patient:{status:'offline',transport_connected:false}});
   callbacks.node_status({patient:true});
   assert.match(eventElements['node-patient'].sub.textContent,/chờ dữ liệu/);
 }],
 ['fresh recovery retains real gas warning',()=>{
   eventCtx.applyTelemetry({kitchen:{status:'stale',transport_connected:true}});
   callbacks.room_update({room:'kitchen',data:{gas:1800}});
   eventCtx.applyTelemetry({kitchen:{status:'fresh',transport_connected:true}});
   assert.equal(eventElements['ov-kitchen-badge'].className,'rb warn');
   assert.match(eventElements['ov-kitchen-badge'].textContent,/Cảnh báo/);
 }]
];
let failures=0;
for(const [name,run] of cases){try{run();console.log('PASS',name);}catch(error){failures++;console.error('FAIL',name,error.message);}}
console.log(`SOCKET_REGRESSIONS=${cases.length} FAILURES=${failures}`);process.exitCode=failures?1:0;
