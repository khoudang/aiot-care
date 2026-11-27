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
const eventCtx = {document: {getElementById: id => eventElements[id] || (eventElements[id] = new Element()), querySelectorAll: () => [], querySelector: () => null},
  nodeState: {patient:true,living:true,kitchen:true}, telemetryCache: {}, pendingControls: new Map(), clearTimeout, setGauge() {}, touch() {},
  socket: {on: (name, fn) => callbacks[name] = fn}};
vm.createContext(eventCtx);
function loadActual(first, next) {
  const a=source.indexOf(first), b=source.indexOf(next,a); assert.ok(a>=0&&b>a);
  vm.runInContext(source.slice(a,b),eventCtx);
}
loadActual('  function badge(', '  function setToggle(');
loadActual('  function confirmedData(', '  function clearPendingControls(');
loadActual('  function applyKitchen(', '  function applyAI(');
loadActual('  function setNode(', '  function setConn(');
for(const event of ['node_status','room_update','telemetry_update']){
  const line=source.split('\n').find(l=>l.includes(`socket.on('${event}',`));assert.ok(line);vm.runInContext(line,eventCtx);
}
const cases=[
 ['MP-2 uses AO only; no DO widgets remain',()=>{
   const html=fs.readFileSync(path.join(__dirname,'../templates/index.html'),'utf8');
   assert.doesNotMatch(html,/id="(?:kt-smoke-tile|kt-smoke-status|ov-kitchen-smoke)"/);
   assert.match(html,/id="kt-gas"/);
   assert.match(html,/id="kt-flame-status"/);
 }],
 ['legacy DO telemetry is ignored by the AO-only dashboard',()=>{
   eventCtx.nodeState.kitchen=true;
   eventCtx.applyKitchen({gas:500,smoke:true,mp2_do_enabled:true,mp2_do_alarm:true,flame:false});
   assert.equal(eventElements['kt-smoke-status'],undefined);
   assert.equal(eventElements['ov-kitchen-smoke'],undefined);
   assert.equal(eventElements['kt-gas'].textContent,500);
 }],
 ['AO gas warning and flame display still render',()=>{
   eventCtx.applyKitchen({gas:1800,flame:true});
   assert.match(eventElements['kt-gas-state'].innerHTML,/Tăng cao/);
   assert.ok(eventElements['kt-flame-tile'].classList.contains('alarm'));
 }],

 ['cached fresh versus disconnect',()=>{
   eventCtx.applyTelemetry({patient:{status:'fresh',transport_connected:true}});
   callbacks.node_status({patient:false});
   assert.ok(eventElements['node-patient'].classList.contains('off'));
   assert.doesNotMatch(eventElements['node-patient'].sub.textContent,/Đang nhận dữ liệu/);
 }],
 ['backend freshness event replaces cached state',()=>{
   eventCtx.nodeState.patient=true;
   callbacks.telemetry_update({patient:{status:'awaiting',transport_connected:true,fields:{temp:{status:'missing'}}}});
   assert.match(eventElements['node-patient'].sub.textContent,/chờ dữ liệu/);
   assert.match(eventElements['data-quality-patient'].textContent,/chờ dữ liệu/);
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


async function testKitchenAlertRendererUsesTextNodes() {
  const start = source.indexOf('  let _lastKitchenFetch = 0;');
  const end = source.indexOf('  const ktReload', start);
  assert.ok(start >= 0 && end > start, 'Actual production kitchen alert renderer must exist');

  class FakeNode {
    constructor(tag) { this.tagName = tag; this.children = []; this.className = ''; this._text = ''; this.attributes = {}; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = [...nodes]; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
  }

  let now = 10000;
  class FakeDate extends Date { static now() { return now; } }
  const list = new FakeNode('div');
  const malicious = '<img src=x onerror=alert(1)>';
  let alerts = [{action: malicious, timestamp: '2026-11-23 10:00:00'}];
  const ctx = {
    document: {
      getElementById: id => id === 'kt-alert-list' ? list : null,
      createElement: tag => new FakeNode(tag)
    },
    Date: FakeDate,
    fetch: async () => ({json: async () => ({alerts})}),
    fmtT: value => value || '--'
  };
  vm.createContext(ctx);
  vm.runInContext(source.slice(start, end), ctx);
  await ctx.loadKitchenAlerts();

  assert.equal(list.children.length, 1);
  const action = list.children[0].children[1].children[0];
  assert.equal(action.textContent, malicious, 'Untrusted action must be rendered as literal text');
  assert.equal(list.children[0].children[1].children.length, 2);

  now += 1500;
  alerts = [];
  await ctx.loadKitchenAlerts();
  assert.equal(list.children.length, 1);
  assert.equal(list.children[0].className, 'empty');
  assert.equal(list.children[0].textContent, 'Chưa có cảnh báo nào.');
  console.log('PASS: kitchen alert renderer uses safe text nodes');
}

testKitchenAlertRendererUsesTextNodes().catch(error => {
  console.error('FAIL: kitchen alert renderer', error);
  process.exitCode = 1;
});

const templateSource = fs.readFileSync(path.join(__dirname, '..', 'templates/index.html'), 'utf8');
assert.match(templateSource, /Cảm biến khí MP-2/);
assert.doesNotMatch(templateSource, /Ngõ cảnh báo DO|MP-2 DO/);
assert.doesNotMatch(templateSource, /Gas \(MQ-2\)/);
console.log('PASS: MP-2 dashboard terminology');
