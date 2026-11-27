const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../static/js/dashboard.js'),'utf8');
function fixture(){
  const elements=new Map(),events={},sent=[],cleared=[];
  const socket={connected:true,on:(name,fn)=>events[name]=fn,emit:(...args)=>sent.push(args)};
  const context={socket,document:{getElementById:id=>{if(!elements.has(id))elements.set(id,{textContent:''});return elements.get(id);}},setTimeout:()=>1,clearTimeout:timer=>cleared.push(timer),showSys(){},console};
  vm.createContext(context);
  const controls=source.slice(source.indexOf('  const pendingControls=new Map();'),source.indexOf('  function bindToggle('));
  const result=source.slice(source.indexOf("    socket.on('command_result'"),source.indexOf("    socket.on('connect'"));
  const error=source.split('\n').find(line=>line.includes("socket.on('command_error'"));
  vm.runInContext(controls+'\n'+result+'\n'+error+'\nthis.pending=pendingControls;',context);
  function send(room,device){context.emitSet(room,device,{state:true});return sent.filter(e=>e[0]==='set_device').at(-1)[1];}
  return {context,events,sent,cleared,send};
}
test('an unrelated room or device error cannot discard a pending command',()=>{
  const f=fixture();f.send('living','light');
  f.events.command_error({room:'kitchen',device:'window',request_id:'other',message:'full'});
  assert.equal(f.context.pending.size,1);
  f.events.command_error({room:'living',device:'fan',request_id:'other',message:'full'});
  assert.equal(f.context.pending.size,1);
  assert.equal('light' in f.context.confirmedData('living',{light:false}),false);
});
test('an obsolete request error cannot clear a newer target',()=>{
  const f=fixture(),old=f.send('living','light'),latest=f.send('living','light');
  f.events.command_error({...old,message:'timeout'});
  assert.equal(f.context.pending.get('living:light').request_id,latest.request_id);
});
test('a correlated error clears exactly its target, not the other room',()=>{
  const f=fixture(),first=f.send('living','light');f.send('patient','fan');
  f.events.command_error({...first,message:'rejected'});
  assert.equal(f.context.pending.has('living:light'),false);
  assert.equal(f.context.pending.has('patient:fan'),true);
});
test('an unscoped legacy error preserves correlation until normal timeout',()=>{
  const f=fixture();f.send('living','light');
  f.events.command_error({room:'living',message:'unknown old error'});
  assert.equal(f.context.pending.size,1);
});
test('superseded/rejected results are terminal only for matching requests',()=>{
  const f=fixture(),old=f.send('living','light'),latest=f.send('living','light');
  f.events.command_result({...old,status:'superseded'});
  assert.equal(f.context.pending.get('living:light').request_id,latest.request_id);
  f.events.command_result({...latest,status:'superseded'});
  assert.equal(f.context.pending.size,0);
  const next=f.send('living','light');
  f.events.command_result({...next,status:'rejected'});
  assert.equal(f.context.pending.size,0);
});
