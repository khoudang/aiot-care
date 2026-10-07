/* ================= AIoT Care Station — client (BLE, không MQTT) ================= */
  const socket = (typeof io !== 'undefined') ? io() : null;

  (function(){
    const b=document.body;
    document.getElementById('side-username').textContent=b.dataset.username||'Người dùng';
    document.getElementById('side-role').textContent=(b.dataset.role==='admin'?'Quản trị viên':'Thành viên');
  })();

  /* ---- Drawer / navigation ---- */
  const sidebar=document.getElementById('sidebar'), scrim=document.getElementById('scrim');
  function openDrawer(){sidebar.classList.add('open');scrim.classList.add('show')}
  function closeDrawer(){sidebar.classList.remove('open');scrim.classList.remove('show')}
  document.getElementById('burger').addEventListener('click',openDrawer);
  document.getElementById('drawer-close').addEventListener('click',closeDrawer);
  scrim.addEventListener('click',closeDrawer);

  const rooms=document.querySelectorAll('.room');
  const titles={
    overview:['Tổng quan','Theo dõi và điều khiển ba phòng.'],
    patient:['Phòng người bệnh','Camera bám người, cảm biến và thiết bị chăm sóc'],
    living:['Phòng khách','Cảm biến hiện diện, ánh sáng và thiết bị'],
    kitchen:['Phòng bếp','Giám sát gas – khói – lửa và thông gió khẩn cấp'],
    'admin-users':['Quản lý tài khoản','Tài khoản truy cập hệ thống'],
    'admin-logs':['Nhật ký & cảnh báo','Lịch sử đăng nhập, hoạt động và cảnh báo'],
    'admin-settings':['Cấu hình hệ thống','Tài khoản, Telegram và kết nối ESP'],
  };
  function goTo(room){
    document.querySelectorAll('[data-room]').forEach(i=>i.classList.toggle('active',i.dataset.room===room));
    rooms.forEach(r=>r.classList.toggle('active',r.id===room));
    const t=titles[room];if(t){document.getElementById('pt-title').textContent=t[0];document.getElementById('pt-sub').textContent=t[1]||'';}
    closeDrawer();
    if(room==='kitchen'&&typeof loadKitchenAlerts==='function')loadKitchenAlerts();
    window.scrollTo({top:0,behavior:'smooth'});
  }
  document.querySelectorAll('[data-room]').forEach(i=>i.addEventListener('click',()=>goTo(i.dataset.room)));
  document.querySelectorAll('[data-goto]').forEach(el=>el.addEventListener('click',()=>goTo(el.dataset.goto)));

  function touch(){document.getElementById('last-update').textContent=new Date().toLocaleTimeString('vi-VN');}

  /* ---- sparklines ---- */
  const sparks={};
  function spark(id,val,color){
    const c=document.getElementById(id);if(!c||val==null)return;
    if(!sparks[id])sparks[id]={data:[]};
    const s=sparks[id];s.data.push(+val);if(s.data.length>30)s.data.shift();
    const ctx=c.getContext('2d'),w=c.width=c.clientWidth*2,h=c.height=c.clientHeight*2;
    ctx.clearRect(0,0,w,h);const d=s.data;if(d.length<2)return;
    const mn=Math.min(...d),mx=Math.max(...d),rg=(mx-mn)||1;
    ctx.lineWidth=2.5;ctx.strokeStyle=color;ctx.beginPath();
    d.forEach((v,i)=>{const x=i/(d.length-1)*w,y=h-7-((v-mn)/rg)*(h-14);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
    ctx.stroke();const g=ctx.createLinearGradient(0,0,0,h);g.addColorStop(0,color+'33');g.addColorStop(1,color+'00');
    ctx.lineTo(w,h);ctx.lineTo(0,h);ctx.closePath();ctx.fillStyle=g;ctx.fill();
  }

  /* ---- gauge ---- */
  function setGauge(v){
    const pct=Math.max(0,Math.min(100,v/3000*100));
    let col='var(--ok)';if(v>=2500)col='var(--bad)';else if(v>=1500)col='var(--warn)';
    const cs=getComputedStyle(document.documentElement);
    const hex=cs.getPropertyValue(col.replace('var(','').replace(')','')).trim()||col;
    document.getElementById('kt-gauge').style.background=`conic-gradient(${hex} ${pct*3.6}deg, var(--surface-3) 0deg)`;
  }

  /* ---- camera ---- */
  const videoFeed=document.getElementById('video-feed'),videoPh=document.getElementById('video-ph');
  let camActive=false,camMode='auto';
  function setCameraUI(active,mode){
    camActive=active;if(mode)camMode=mode;
    videoFeed.style.display=active?'block':'none';
    videoPh.style.display=active?'none':'block';
    document.querySelectorAll('#cam-seg button').forEach(b=>b.classList.toggle('on',b.dataset.mode===camMode));
    if(active){const want='/video_feed';if(!videoFeed.src.includes(want)||videoFeed.style.display==='none')videoFeed.src=want+'?'+Date.now();}
    if(!active){videoFeed.parentElement.style.aspectRatio='';document.getElementById('oc-gesture').textContent='Cử chỉ: — (camera tắt)';}
  }
  document.querySelectorAll('#cam-seg button').forEach(b=>b.addEventListener('click',()=>{
    const m=b.dataset.mode;camMode=m;
    document.querySelectorAll('#cam-seg button').forEach(x=>x.classList.toggle('on',x===b));
    if(socket)socket.emit('set_camera_mode',{mode:m});
  }));
  videoFeed.addEventListener('load',()=>{if(camActive&&videoFeed.naturalWidth&&videoFeed.naturalHeight)videoFeed.parentElement.style.aspectRatio=videoFeed.naturalWidth+' / '+videoFeed.naturalHeight;});
  videoFeed.addEventListener('error',()=>{videoFeed.style.display='none';videoPh.style.display='block';videoFeed.parentElement.style.aspectRatio='';});

  /* ---- device control ---- */
  function emitSet(room,device,payload){if(!socket||!socket.connected){showSys('Mất kết nối. Chưa gửi lệnh điều khiển.','light');return;}socket.emit('set_device',Object.assign({room,device},payload));}
  function bindToggle(id,tileId,onTxt,offTxt,cb){
    const el=document.getElementById(id),tile=document.getElementById(tileId);
    el.addEventListener('change',()=>{tile.classList.toggle('on',el.checked);const st=document.getElementById(id.replace('-toggle','-status'));if(st)st.textContent=el.checked?onTxt:offTxt;cb&&cb(el.checked);});
  }
  function bindRange(id,valId,cb){const el=document.getElementById(id),v=document.getElementById(valId);el.addEventListener('input',()=>{v.textContent=el.value;cb&&cb(+el.value);});}
  bindToggle('pt-light-toggle','pt-light-tile','Đang bật','Đang tắt',on=>emitSet('patient','light',{state:on}));
  bindToggle('pt-buzzer-toggle','pt-buzzer-tile','Đang kêu','Im lặng',on=>emitSet('patient','buzzer',{state:on}));
  bindToggle('pt-fan-toggle','pt-fan-tile','Đang chạy','Đang tắt',on=>{const r=document.getElementById('pt-fan-range');if(!on){r.value=0;document.getElementById('pt-fan-val').textContent=0;}emitSet('patient','fan',{state:on,value:on?(+r.value||100):0});});
  bindRange('pt-fan-range','pt-fan-val',v=>{const t=document.getElementById('pt-fan-toggle');t.checked=v>0;document.getElementById('pt-fan-tile').classList.toggle('on',v>0);document.getElementById('pt-fan-status').textContent=v>0?'Đang chạy':'Đang tắt';emitSet('patient','fan',{state:v>0,value:v});});
  bindToggle('lv-light-toggle','lv-light-tile','Đang bật','Đang tắt',on=>emitSet('living','light',{state:on}));
  bindToggle('lv-fan-toggle','lv-fan-tile','Đang chạy','Đang tắt',on=>{const r=document.getElementById('lv-fan-range');if(!on){r.value=0;document.getElementById('lv-fan-val').textContent=0;}emitSet('living','fan',{state:on,value:on?(+r.value||100):0});});
  bindRange('lv-fan-range','lv-fan-val',v=>{const t=document.getElementById('lv-fan-toggle');t.checked=v>0;document.getElementById('lv-fan-tile').classList.toggle('on',v>0);document.getElementById('lv-fan-status').textContent=v>0?('Tốc độ '+v+'%'):'Đang tắt';emitSet('living','fan',{state:v>0,value:v});});
  bindToggle('lv-auto-toggle','lv-auto-tile','Bật đèn khi có người buổi tối','Đã tắt tự động',on=>emitSet('living','auto',{state:on}));
  bindToggle('kt-window-toggle','kt-window-tile','Đang mở','Đang đóng',on=>emitSet('kitchen','window',{state:on}));
  bindToggle('kt-exhaust-toggle','kt-exhaust-tile','Đang hút','Đang tắt',on=>emitSet('kitchen','exhaust',{state:on}));
  bindToggle('kt-light-toggle','kt-light-tile','Đang bật','Đang tắt',on=>emitSet('kitchen','light',{state:on}));
  bindToggle('kt-buzzer-toggle','kt-buzzer-tile','Đang kêu','Im lặng',on=>emitSet('kitchen','buzzer',{state:on}));

  /* ---- apply data ---- */
  function badge(el,cls,txt){el.className='rb '+cls;el.textContent=txt;}
  function setToggle(id,tileId,on,onTxt,offTxt){const el=document.getElementById(id);el.checked=!!on;document.getElementById(tileId).classList.toggle('on',!!on);const st=document.getElementById(id.replace('-toggle','-status'));if(st)st.textContent=on?onTxt:offTxt;}

  function applyPatient(d){
    if(d.temp!=null){document.getElementById('pt-temp').textContent=d.temp;document.getElementById('ov-patient-temp').textContent=d.temp;spark('sp-pt-temp',d.temp,'#4c9be8');}
    if(d.hum!=null){document.getElementById('pt-humi').textContent=d.hum;document.getElementById('ov-patient-humi').textContent=d.hum;spark('sp-pt-humi',d.hum,'#3ba55d');}
    if(d.gas!=null){document.getElementById('pt-gas').textContent=Math.round(d.gas);spark('sp-pt-gas',d.gas,'#d6982c');document.getElementById('pt-gas-card').classList.toggle('alarm',d.gas>=2500);}
    if(d.motion!=null)document.getElementById('oc-pir').innerHTML='<i class="fas fa-person-walking"></i> PIR: '+(d.motion?'có chuyển động':'yên tĩnh');
    if(d.light!=null)setToggle('pt-light-toggle','pt-light-tile',d.light,'Đang bật','Đang tắt');
    if(d.buzzer!=null){document.getElementById('pt-buzzer-toggle').checked=!!d.buzzer;document.getElementById('pt-buzzer-tile').classList.toggle('alarm',!!d.buzzer);document.getElementById('pt-buzzer-status').textContent=d.buzzer?'Đang kêu':'Im lặng';}
    if(d.fan_speed!=null){const r=document.getElementById('pt-fan-range');r.value=d.fan_speed;document.getElementById('pt-fan-val').textContent=d.fan_speed;const on=d.fan_speed>0;document.getElementById('pt-fan-toggle').checked=on;document.getElementById('pt-fan-tile').classList.toggle('on',on);document.getElementById('pt-fan-status').textContent=on?'Đang chạy':'Đang tắt';}
    touch();
  }
  function applyLiving(d){
    if(d.temp!=null){document.getElementById('lv-temp').textContent=d.temp;document.getElementById('ov-living-temp').textContent=d.temp;spark('sp-lv-temp',d.temp,'#4c9be8');}
    if(d.hum!=null){document.getElementById('lv-humi').textContent=d.hum;spark('sp-lv-humi',d.hum,'#3ba55d');}
    if(d.lux!=null){document.getElementById('lv-lux').textContent=Math.round(d.lux);spark('sp-lv-lux',d.lux,'#e0a52e');}
    const presence=(d.presence!=null)?d.presence:d.motion;
    if(presence!=null){const t=presence?'Có người':'Không có người';document.getElementById('lv-motion-status').textContent=t;document.getElementById('lv-motion-tile').classList.toggle('on',!!presence);document.getElementById('ov-living-motion').textContent=t;}
    if(d.light!=null){setToggle('lv-light-toggle','lv-light-tile',d.light,'Đang bật','Đang tắt');document.getElementById('ov-living-light').textContent=d.light?'Bật':'Tắt';}
    if(d.fan_speed!=null){const r=document.getElementById('lv-fan-range');r.value=d.fan_speed;document.getElementById('lv-fan-val').textContent=d.fan_speed;const on=d.fan_speed>0;document.getElementById('lv-fan-toggle').checked=on;document.getElementById('lv-fan-tile').classList.toggle('on',on);document.getElementById('lv-fan-status').textContent=on?('Tốc độ '+d.fan_speed+'%'):'Đang tắt';}
    if(d.auto!=null){document.getElementById('lv-auto-toggle').checked=!!d.auto;document.getElementById('lv-auto-tile').classList.toggle('on',!!d.auto);}
    touch();
  }
  function applyKitchen(d){
    if(d.gas!=null){const g=Math.round(d.gas);document.getElementById('kt-gas').textContent=g;document.getElementById('ov-kitchen-gas').textContent=g;setGauge(d.gas);
      const st=document.getElementById('kt-gas-state'),card=document.getElementById('kt-gas-card');
      if(d.gas>=2500){st.className='badge bad';st.innerHTML='<i class="fas fa-triangle-exclamation"></i> Nguy hiểm';card.classList.add('alarm');}
      else if(d.gas>=1500){st.className='badge warn';st.innerHTML='<i class="fas fa-circle-exclamation"></i> Tăng cao';card.classList.remove('alarm');}
      else{st.className='badge ok';st.innerHTML='<i class="fas fa-circle-check"></i> An toàn';card.classList.remove('alarm');}
    }
    if(d.smoke!=null){document.getElementById('kt-smoke-status').textContent=d.smoke?'PHÁT HIỆN KHÓI':'Không phát hiện';document.getElementById('kt-smoke-tile').classList.toggle('alarm',!!d.smoke);document.getElementById('ov-kitchen-smoke').textContent=d.smoke?'Có':'Không';}
    if(d.flame!=null){document.getElementById('kt-flame-status').textContent=d.flame?'PHÁT HIỆN LỬA':'Không phát hiện';document.getElementById('kt-flame-tile').classList.toggle('alarm',!!d.flame);document.getElementById('ov-kitchen-flame').textContent=d.flame?'Có':'Không';}
    if(d.window!=null)setToggle('kt-window-toggle','kt-window-tile',d.window,'Đang mở','Đang đóng');
    if(d.exhaust!=null)setToggle('kt-exhaust-toggle','kt-exhaust-tile',d.exhaust,'Đang hút','Đang tắt');
    if(d.light!=null)setToggle('kt-light-toggle','kt-light-tile',d.light,'Đang bật','Đang tắt');
    if(d.buzzer!=null)setToggle('kt-buzzer-toggle','kt-buzzer-tile',d.buzzer,'Đang kêu','Im lặng');
    const danger=d.flame||d.smoke||(d.gas!=null&&d.gas>=2500),warn=(d.gas!=null&&d.gas>=1500);
    badge(document.getElementById('ov-kitchen-badge'),danger?'bad':(warn?'warn':'ok'),danger?'Nguy hiểm':(warn?'Cảnh báo':'An toàn'));
    touch();
  }
  function applyAI(a){
    if(a.gesture!=null){document.getElementById('oc-gesture').textContent='Cử chỉ: '+(a.gesture||'—');document.querySelectorAll('#gesture-table tr[data-g]').forEach(r=>r.classList.toggle('live',r.dataset.g===a.gesture));}
    if(a.fps!=null)document.getElementById('ai-fps').textContent=a.fps;
    if(a.latency!=null)document.getElementById('ai-latency').textContent=a.latency;
    if(a.fall!=null){const oc=document.getElementById('oc-fall');oc.innerHTML=a.fall?'<i class="fas fa-person-falling"></i> TÉ NGÃ':'Bình thường';oc.classList.toggle('alarm',!!a.fall);
      document.getElementById('ov-patient-fall').textContent=a.fall?'TÉ NGÃ':'Bình thường';badge(document.getElementById('ov-patient-badge'),a.fall?'bad':'ok',a.fall?'Té ngã':'An toàn');}
  }

  /* ---- lịch sử cảnh báo bếp (Yêu cầu 4) ---- */
  function fmtT(v){if(!v)return'--';const d=new Date(String(v).replace(' ','T'));return isNaN(d)?v:d.toLocaleString('vi-VN');}
  async function loadKitchenAlerts(){
    const list=document.getElementById('kt-alert-list');if(!list)return;
    try{
      const r=await fetch('/api/kitchen_alerts');const d=await r.json();const a=(d&&d.alerts)||[];
      if(!a.length){list.innerHTML='<div class="empty">Chưa có cảnh báo nào.</div>';return;}
      list.innerHTML=a.map(x=>`<div class="alert-item"><i class="fas fa-triangle-exclamation ai-ic"></i><div class="ai-body"><div class="ai-act">${x.action}</div><div class="ai-time">${fmtT(x.timestamp)}</div></div></div>`).join('');
    }catch(e){}
  }
  const ktReload=document.getElementById('kt-alerts-reload');
  if(ktReload)ktReload.addEventListener('click',loadKitchenAlerts);

  /* ---- alert state machine ---- */
  const STEPS=['normal','light','emergency','awaiting'];
  function setAlert(level,msg){
    const idx=STEPS.indexOf(level);if(idx<0)return;
    document.getElementById('confirm-btn').disabled=false;
    const chip=document.getElementById('state-chip'),desc=document.getElementById('state-desc');
    const map={normal:['ok','Bình thường','Hệ thống đang ở trạng thái bình thường'],light:['bad','Cảnh báo nhẹ','Khí gas tăng cao hơn mức bình thường'],emergency:['bad','Khẩn cấp','Phát hiện khói/lửa hoặc gas rất cao — đang xử lý'],awaiting:['bad','Chờ xác nhận','Điều kiện đã an toàn — cần xác nhận để khôi phục']};
    document.getElementById('state-card').dataset.level=level;
    const m=map[level];chip.className='chip '+(level==='normal'?'ok':'bad');chip.innerHTML='<i class="fas fa-circle"></i> '+m[1];desc.textContent=m[2];
    document.getElementById('emg').classList.toggle('show',level==='emergency'||level==='awaiting');
    document.getElementById('confirm-btn').classList.toggle('show',level==='awaiting');
    if(msg)showSys(msg,level==='light'?'light':'');
  }
  document.getElementById('confirm-btn').addEventListener('click',()=>{if(socket)socket.emit('confirm_safe',{});});
  document.getElementById('sysbar-x').addEventListener('click',()=>document.getElementById('sysbar').classList.remove('show'));
  function showSys(msg,lvl){const box=document.getElementById('sysbar');document.getElementById('sysbar-text').textContent=msg;box.className='sysbar show'+(lvl==='light'?' light':'');clearTimeout(showSys._t);showSys._t=setTimeout(()=>box.classList.remove('show'),9000);}

  /* ---- node status ---- */
  const nodeState={patient:false,living:false,kitchen:false};
  function setNode(room,online){
    const el=document.getElementById('node-'+room);if(!el)return;
    el.classList.toggle('off',!online);
    el.querySelector('.nsub').textContent=online?'Đã kết nối':'Chưa kết nối';
    const roomBadge=document.getElementById('ov-'+room+'-badge');
    if(!online&&roomBadge){roomBadge.className='rb';roomBadge.textContent='Chưa kết nối';}
    if(online&&roomBadge&&roomBadge.textContent==='Chưa kết nối'){roomBadge.className='rb ok';roomBadge.textContent='Đã kết nối';}
    if(room==='kitchen'){document.getElementById('kitchen-dot').classList.toggle('show',!online);document.getElementById('bn-kitchen-dot').classList.toggle('show',!online);}
    nodeState[room]=online;updateNodeChip();
  }
  function updateNodeChip(){
    const n=Object.values(nodeState).filter(Boolean).length;
    const c=document.getElementById('node-chip');c.innerHTML='<i class="fas fa-diagram-project"></i> '+n+'/'+Object.keys(nodeState).length+' phòng';
    c.className='chip nodes'+(n===Object.keys(nodeState).length?' ok':(n===0?' bad':''));
  }
  function setConn(ok){
    document.querySelectorAll('.sw input, input[type="range"], #cam-seg button').forEach(el=>el.disabled=!ok);
    const c=document.getElementById('conn-chip'),m=document.getElementById('mt-conn');
    c.className='chip '+(ok?'ok':'bad');c.innerHTML='<i class="fas fa-circle"></i> '+(ok?'Đã kết nối':'Mất kết nối');
    m.className='mt-conn '+(ok?'ok':'bad');
  }

  /* ================= SOCKET ================= */
  if(socket){
    socket.on('connect',()=>{setConn(true);socket.emit('request_initial_state');loadKitchenAlerts();});
    socket.on('disconnect',()=>{setConn(false);Object.keys(nodeState).forEach(room=>setNode(room,false));document.getElementById('state-chip').textContent='Mất kết nối';document.getElementById('state-chip').className='chip';document.getElementById('state-desc').textContent='Dữ liệu có thể đã cũ. Đang kết nối lại…';document.getElementById('confirm-btn').disabled=true;});
    socket.on('command_error',e=>{showSys(e.message||'Không gửi được lệnh.','light');socket.emit('request_initial_state');});
    socket.on('bootstrap',s=>{
      if(s.rooms){applyPatient(s.rooms.patient||{});applyLiving(s.rooms.living||{});applyKitchen(s.rooms.kitchen||{});}
      if(s.nodes){['patient','living','kitchen'].forEach(r=>setNode(r,!!s.nodes[r]));}
      if(s.ai)applyAI(s.ai);
      if(s.camera){setCameraUI(!!s.camera.active,s.camera.mode);}
      if(s.alert)setAlert(s.alert.level);
    });
    socket.on('room_update',m=>{if(m.room==='patient')applyPatient(m.data);else if(m.room==='living')applyLiving(m.data);else if(m.room==='kitchen')applyKitchen(m.data);});
    socket.on('node_status',n=>{['patient','living','kitchen'].forEach(r=>{if(n[r]!=null)setNode(r,n[r]===true||n[r]==='online');});});
    socket.on('camera_sync',c=>{setCameraUI(!!c.active,c.mode);});
    socket.on('ai_status',applyAI);
    socket.on('alert_state',a=>{setAlert(a.level,a.message);if(typeof loadKitchenAlerts==='function')loadKitchenAlerts();});
    socket.on('system_alert',a=>{showSys(a.message||'Có cảnh báo mới.',(a.type==='gas'||a.type==='health')?'light':'');if(typeof loadKitchenAlerts==='function')loadKitchenAlerts();});
  }

  /* ---- panel tùy chỉnh cử chỉ (Yêu cầu 2) ---- */
  (function gesturePanel(){
    const gEl=document.getElementById('gm-gesture'),dEl=document.getElementById('gm-device'),aEl=document.getElementById('gm-action'),list=document.getElementById('gm-list');
    if(!gEl)return;
    const labels={gesture:{},device:{},action:{}};
    async function fj(url,opt={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt});const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw new Error(d.message||'Lỗi máy chủ.');return d;}
    function fillSelect(sel,arr){sel.innerHTML=arr.map(o=>`<option value="${o.key}">${o.label}</option>`).join('');}
    function renderList(ms){
      const cnt=document.getElementById('gcard-count');if(cnt)cnt.textContent=(ms&&ms.length)||0;
      if(!ms||!ms.length){list.innerHTML='<div class="empty">Chưa có ánh xạ nào — thêm ở trên.</div>';return;}
      list.innerHTML=ms.map(m=>{
        const gl=labels.gesture[m.gesture_name]||m.gesture_name,dl=labels.device[m.target_device]||m.target_device,al=labels.action[m.action]||m.action;
        return `<div class="gmap-item"><span class="gi-gesture">${gl}</span><i class="fas fa-arrow-right gi-arrow"></i><span class="gi-target"><b>${dl}</b> · ${al}</span><button class="gi-del" onclick="delGesture('${m.gesture_name}')"><i class="fas fa-xmark"></i></button></div>`;
      }).join('');
    }
    async function load(){
      const d=await fj('/api/gesture_mappings');const o=d.options;
      o.gestures.forEach(x=>labels.gesture[x.key]=x.label);
      o.devices.forEach(x=>labels.device[x.key]=x.label);
      o.actions.forEach(x=>labels.action[x.key]=x.label);
      fillSelect(gEl,o.gestures);fillSelect(dEl,o.devices);fillSelect(aEl,o.actions);
      renderList(d.mappings);
    }
    document.getElementById('gm-add').addEventListener('click',async()=>{
      try{const d=await fj('/api/gesture_mappings',{method:'POST',body:JSON.stringify({gesture_name:gEl.value,target_device:dEl.value,action:aEl.value})});renderList(d.mappings);}catch(e){alert(e.message);}
    });
    window.delGesture=async g=>{if(!confirm('Xóa ánh xạ cử chỉ này?'))return;try{const d=await fj(`/api/gesture_mappings/${g}`,{method:'DELETE'});renderList(d.mappings);}catch(e){alert(e.message);}};
    /* Thu gọn / mở rộng panel cử chỉ + di chuyển khối dữ liệu (mặc định thu gọn để tránh chạm nhầm) */
    (function(){
      const card=document.getElementById('gesture-card'),head=document.getElementById('gcard-head');
      if(!card||!head)return;
      const ptop=document.querySelector('#patient .p-top'),
            data=document.getElementById('patient-data'),
            slotR=document.getElementById('data-slot-right'),
            slotB=document.getElementById('data-slot-bottom');
      function syncData(){
        const collapsed=card.classList.contains('collapsed');
        if(ptop)ptop.classList.toggle('data-right',collapsed);
        if(data&&slotR&&slotB){const dest=collapsed?slotR:slotB;if(data.parentElement!==dest)dest.appendChild(data);}
      }
      function toggle(){const open=!card.classList.toggle('collapsed');head.setAttribute('aria-expanded',open?'true':'false');syncData();}
      head.addEventListener('click',toggle);
      head.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle();}});
      syncData();
    })();
    load().catch(()=>{list.innerHTML='<div class="empty">Không tải được ánh xạ cử chỉ.</div>';});
  })();

document.querySelectorAll('.nav [data-room], [data-goto]').forEach(el=>{
  if(el.tagName==='BUTTON')return;
  el.tabIndex=0;el.setAttribute('role','button');
  el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();el.click();}});
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeDrawer();});
if(!socket){setConn(false);showSys('Không tải được kết nối trực tiếp. Kiểm tra mạng rồi tải lại trang.','light');}
