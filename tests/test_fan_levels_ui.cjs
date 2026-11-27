const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const root = path.join(__dirname, '..');
const dashboard = fs.readFileSync(path.join(root, 'static/js/dashboard.js'), 'utf8');

test('dashboard loads and initializes the presets after the command handlers', () => {
  const template = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
  const presets = template.indexOf("filename='js/fan-levels.js'");
  const client = template.indexOf("filename='js/dashboard.js'");
  assert.ok(presets >= 0 && presets < client, 'Preset script must load before the dashboard');
  assert.match(dashboard, /initFanLevels\(\(\) => !!socket && socket.connected\)/);
  assert.ok(dashboard.indexOf('initFanLevels(') > dashboard.indexOf('  function setConn('));
  assert.match(template, /fan-levels-v2/);
});

test('the first asynchronous socket connection enables presets in a real DOM', async () => {
  const {JSDOM} = require('jsdom');
  const dom = new JSDOM('<div class="device-card-modern"><input id="pt-fan-range" type="range" min="0" max="100" value="0"><span id="pt-fan-val">0</span></div>', {runScripts:'outside-only'});
  try {
    const context = dom.getInternalVMContext();
    context.socket = {connected:false}; context.renderFallConfirmation = () => {};
    const first = dashboard.indexOf('  function setConn(');
    vm.runInContext(dashboard.slice(first, dashboard.indexOf('  /* ================= SOCKET', first)), context);
    vm.runInContext(fs.readFileSync(path.join(root, 'static/js/fan-levels.js'), 'utf8'), context);
    const startup = dashboard.match(/^setConn\(!!socket && socket.connected\);\s*initFanLevels\(\(\) => !!socket && socket.connected\);/m);
    assert.ok(startup, 'Initial connection state must be applied before constructing presets');
    vm.runInContext(startup[0], context);
    const button = dom.window.document.querySelector('.fan-levels button');
    assert.equal(button.disabled, true);
    context.socket.connected = true; context.setConn(true);
    await Promise.resolve();
    assert.equal(button.disabled, false);
    context.socket.connected = false; context.setConn(false);
    await Promise.resolve();
    assert.equal(button.disabled, true);
  } finally { dom.window.close(); }
});

function fixture() {
  const elements = {}, observers = [], sent = [];
  class Element {
    constructor() {
      this.value = '0'; this.textContent = ''; this.dataset = {};
      this.disabled = false; this.hidden = false; this.children = [];
      this.attributes = {}; this.handlers = {}; this.classes = new Set();
      this.classList = {toggle: (key, on) => on ? this.classes.add(key) : this.classes.delete(key)};
    }
    append(...children) { this.children.push(...children); }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    getAttribute(key) { return this.attributes[key]; }
    addEventListener(name, callback) { (this.handlers[name] ||= []).push(callback); }
    dispatchEvent(event) { for (const callback of this.handlers[event.type] || []) callback(event); }
    click() { if (!this.disabled) this.dispatchEvent({type:'click'}); }
    closest() { return this.card; }
    querySelector(selector) { return this.selectors?.[selector] || null; }
  }
  const get = id => elements[id] ||= new Element();
  for (const prefix of ['pt-fan', 'lv-fan', 'kt-exhaust']) {
    const card = get(prefix + '-tile');
    card.selectors = {'.sw': new Element(), '.device-slider-control': new Element(), '.ha-range-control': new Element()};
    get(prefix + '-range').card = card;
  }
  const socket = {connected: true, emit: (event, payload) => sent.push({event, payload})};
  const context = {
    document: {getElementById: get, createElement: () => new Element(), querySelector: () => null},
    nodeState: {patient:true,living:true,kitchen:true}, touch() {}, spark() {}, setGauge() {},
    socket, showSys() {}, setTimeout: () => 1, clearTimeout() {},
    Date, Math, Map, performance: {now: () => 1000}, Event: class {constructor(type) {this.type = type;}},
    MutationObserver: class {constructor(callback) {observers.push(callback);} observe() {}},
  };
  vm.createContext(context);
  vm.runInContext(dashboard.slice(dashboard.indexOf('  /* ---- device control ---- */'), dashboard.indexOf('  /* ---- apply data ---- */')), context);
  const script = path.join(root, 'static/js/fan-levels.js');
  assert.ok(fs.existsSync(script), 'Three-level fan controls must be implemented');
  vm.runInContext(fs.readFileSync(script, 'utf8'), context);
  context.initFanLevels(() => socket.connected);
  vm.runInContext(dashboard.slice(dashboard.indexOf('  /* ---- apply data ---- */'), dashboard.indexOf('  /* ---- lịch sử cảnh báo bếp')), context);
  const controls = prefix => {
    const children = get(prefix + '-tile').children;
    const group = children.find(child => child.className === 'fan-levels');
    return {buttons: group.children, children};
  };
  return {get, socket, sent, controls, context, sync: () => observers.forEach(callback => callback())};
}

test('all three rooms send correlated 50/75/100 percent commands through existing handlers', () => {
  const f = fixture();
  for (const [prefix, room, device] of [['pt-fan','patient','fan'], ['lv-fan','living','fan'], ['kt-exhaust','kitchen','exhaust']]) {
    const {buttons} = f.controls(prefix);
    assert.deepEqual(buttons.map(button => button.getAttribute('aria-label')), ['Tắt', 'Nhẹ 50%', 'Vừa 75%', 'Mạnh 100%']);
    for (const [i, percent] of [[1,50],[2,75],[3,100],[0,0]]) {
      const before = f.sent.length;
      buttons[i].click();
      assert.equal(f.sent.length, before + 1, 'One click must send exactly one command');
      const {event, payload} = f.sent.at(-1);
      assert.equal(event, 'set_device');
      assert.equal(payload.room, room); assert.equal(payload.device, device);
      assert.equal(payload.value, percent); assert.equal(payload.state, percent > 0);
      assert.equal(typeof payload.request_id, 'string');
      assert.match(f.get(prefix + '-status').textContent, /chờ thiết bị/);
    }
  }
  assert.equal(new Set(f.sent.map(item => item.payload.request_id)).size, 12);
});

test('ACK and telemetry retain ownership; automatic intermediate PWM is not rounded to a preset', () => {
  const f = fixture(), controls = f.controls('lv-fan'), range = f.get('lv-fan-range');
  controls.buttons[2].click();
  f.context.applyLiving({fan_speed:50}); f.sync();
  assert.equal(Number(range.value), 75, 'Unacknowledged telemetry must not confirm a different speed');
  vm.runInContext("pendingControls.get('living:fan').acknowledged=true", f.context);
  f.context.applyLiving({fan_speed:75}); f.sync();
  assert.equal(controls.buttons[2].getAttribute('aria-pressed'), 'true');
  assert.equal(vm.runInContext('pendingControls.size', f.context), 0);
  f.context.applyLiving({fan_speed:70}); f.sync();
  assert.equal(Number(range.value), 70);
  assert.ok(controls.buttons.every(button => button.getAttribute('aria-pressed') === 'false'));
  assert.equal(f.sent.length, 1, 'Rendering telemetry must not send commands');
});

test('offline or disabled controls cannot alter the selected speed or send a command', () => {
  const f = fixture(), range = f.get('lv-fan-range'), controls = f.controls('lv-fan');
  f.socket.connected = false;
  controls.buttons[1].click();
  assert.equal(Number(range.value), 0, 'Disconnect guard must work even before MutationObserver fires');
  f.sync();
  assert.ok(controls.buttons.every(button => button.disabled));
  f.socket.connected = true; range.disabled = true; f.sync();
  controls.buttons[3].click(); controls.buttons[0].click();
  assert.equal(f.sent.length, 0);
  range.disabled = false; f.sync();
  assert.ok(controls.buttons.every(button => !button.disabled));
  controls.buttons[2].click();
  assert.equal(f.sent.at(-1).payload.value, 75);
});

test('Off is a fourth selectable preset and no plus/minus controls remain', () => {
  const f = fixture();
  for (const prefix of ['pt-fan', 'lv-fan', 'kt-exhaust']) {
    const controls = f.controls(prefix);
    assert.equal(controls.buttons.length, 4);
    assert.ok(!controls.children.some(child => child.className === 'fan-step-controls'));
    controls.buttons[3].click(); controls.buttons[0].click();
    assert.deepEqual(f.sent.splice(0).map(item => item.payload.value), [100,0]);
    assert.equal(Number(f.get(prefix + '-range').value), 0);
    assert.equal(controls.buttons[0].getAttribute('aria-pressed'), 'true');
    assert.equal(f.get(prefix + '-toggle').checked, false);
  }
});
