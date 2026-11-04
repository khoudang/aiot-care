/* ================= AIoT Care Station — client (BLE, không MQTT) ================= */
  const socket = (typeof io !== 'undefined') ? io() : null;
  // Remove the retired history panel even from a cached dashboard template.



  function updateGreeting(){
    const heading=document.getElementById('dynamic-greeting');
    if(!heading)return;
    const hour=Number(new Intl.DateTimeFormat('en-GB',{hour:'numeric',hourCycle:'h23',timeZone:'Asia/Ho_Chi_Minh'}).format(new Date()));
    const period=hour<11?'sáng':hour<14?'trưa':hour<18?'chiều':'tối';
    heading.textContent=`Chào buổi ${period}, ${document.body.dataset.username||'Người dùng'}.`;
    const date=document.getElementById('overview-date');
    if(date)date.textContent=new Intl.DateTimeFormat('vi-VN',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'Asia/Ho_Chi_Minh'}).format(new Date());
  }
  updateGreeting();
  setInterval(updateGreeting,60000);

  /* Align the sidebar divider to the overview header in the desktop shell. */
  (function alignBrandDivider(){
    const header=document.querySelector('#overview .overview-heading');
    const brand=document.getElementById('sidebar-top-brand');
    const viewport=document.querySelector('.main-wrap');
    if(!header||!brand||!viewport)return;
    const desktop=window.matchMedia('(min-width:1024px)');
    function align(){
      if(!desktop.matches){brand.style.removeProperty('--brand-divider-height');return;}
      if(!header.getClientRects().length)return;
      const height=header.getBoundingClientRect().bottom+viewport.scrollTop-brand.getBoundingClientRect().top;
      if(height>0)brand.style.setProperty('--brand-divider-height',height+'px');
    }
    if(typeof ResizeObserver!=='undefined'){
      const observer=new ResizeObserver(align);observer.observe(header);
    }
    window.addEventListener('resize',align);
    document.fonts?.ready.then(align);
    align();
  })();

  (function(){
    const b=document.body;
    const username=document.getElementById('side-username'),role=document.getElementById('side-role');
    if(username)username.textContent=b.dataset.username||'Người dùng';
    if(role)role.textContent=(b.dataset.role==='admin'?'Quản trị viên':'Thành viên');
  })();

  /* ---- Drawer / navigation ---- */
  const sidebar=document.getElementById('sidebar'), scrim=document.getElementById('scrim');
  function openDrawer(){sidebar.classList.add('open');scrim.classList.add('show')}
  function closeDrawer(){sidebar.classList.remove('open');scrim.classList.remove('show')}
  document.getElementById('burger').addEventListener('click',openDrawer);
  document.getElementById('drawer-close')?.addEventListener('click',closeDrawer);
  scrim.addEventListener('click',closeDrawer);

  /* Account settings share the main content navigation. */
  const preferencePrefix='aiot-account-'+document.body.dataset.username+'-';
  const dark=document.getElementById('dark-mode-toggle');
  // Upgrade the old sidebar markup too when Flask still has a cached template.
  const themeLabel=dark.closest('label');
  const themeNav=document.querySelector('#sidebar .nav');
  if(themeLabel&&themeNav){
    themeLabel.classList.add('sidebar-theme');
    dark.setAttribute('role','switch');
    if(!themeLabel.querySelector('.fa-moon')){
      const moon=document.createElement('i');moon.className='fas fa-moon';moon.setAttribute('aria-hidden','true');themeLabel.prepend(moon);
    }
    if(!themeLabel.closest('.theme-nav-item')){
      const item=document.createElement('li');item.className='theme-nav-item';item.append(themeLabel);themeNav.append(item);
    }
  }
  try{dark.checked=localStorage.getItem(preferencePrefix+'dark')==='true';}catch(_){}
  document.body.classList.toggle('dark-mode',dark.checked);
  try{localStorage.setItem('aiot-theme-dark',String(dark.checked));}catch(_){}
  dark.addEventListener('change',()=>{document.body.classList.toggle('dark-mode',dark.checked);try{localStorage.setItem(preferencePrefix+'dark',String(dark.checked));localStorage.setItem('aiot-theme-dark',String(dark.checked));}catch(_){}});
  const personalDark=document.getElementById('personal-dark-toggle');
  personalDark.checked=dark.checked;
  personalDark.addEventListener('change',()=>{dark.checked=personalDark.checked;dark.dispatchEvent(new Event('change'));});
  dark.addEventListener('change',()=>{personalDark.checked=dark.checked;});
  function renderAccountAvatar(src){document.querySelectorAll('[data-account-avatar]').forEach(el=>{const img=el.querySelector('img'),initial=el.querySelector('span');img.hidden=!src;initial.hidden=!!src;if(src)img.src=src;else img.removeAttribute('src');});}
  try{const saved=localStorage.getItem(preferencePrefix+'avatar');if(saved&&/^data:image\/(png|jpeg|webp);base64,/.test(saved))renderAccountAvatar(saved);}catch(_){}
  const rooms=document.querySelectorAll('.room');
  const titles={
    personal:['Cá nhân',''],
    overview:['Tổng quan','Theo dõi và điều khiển ba phòng.'],
    patient:['Phòng người bệnh','Camera bám người, cảm biến và thiết bị chăm sóc'],
    living:['Phòng khách','Cảm biến hiện diện, ánh sáng và thiết bị'],
    kitchen:['Phòng bếp','Giám sát gas – khói – lửa và thông gió khẩn cấp'],
    gestures:['Tùy chỉnh cử chỉ','Ánh xạ cử chỉ để điều khiển thiết bị'],
    'admin-users':['Quản lý tài khoản','Tài khoản truy cập hệ thống'],
    'admin-logs':['Nhật ký & cảnh báo','Lịch sử đăng nhập, hoạt động và cảnh báo'],
    'admin-settings':['Cấu hình hệ thống','Tài khoản, Telegram và kết nối ESP'],
  };
  function goTo(room,{historyMode='push'}={}){
    if(!Array.from(rooms).some(r=>r.id===room))return;
    const url=new URL(window.location.href);
    if(url.searchParams.get('tab')!==room){
      url.searchParams.set('tab',room);
      if(historyMode==='replace')window.history.replaceState(null,'',url);
      else window.history.pushState(null,'',url);
    }
    document.querySelectorAll('[data-room]').forEach(i=>i.classList.toggle('active',i.dataset.room===room));
    document.querySelectorAll('#botnav button').forEach(i=>{
      const selected=i.dataset.room===room||(i.hasAttribute('data-personal-tab')&&['gestures','admin-settings','admin-users','admin-logs'].includes(room));
      i.classList.toggle('active',selected);if(selected)i.setAttribute('aria-current','page');else i.removeAttribute('aria-current');
    });
    rooms.forEach(r=>r.classList.toggle('active',r.id===room));
    const t=titles[room];if(t){const title=document.getElementById('pt-title'),sub=document.getElementById('pt-sub');if(title)title.textContent=t[0];if(sub)sub.textContent=t[1]||'';}
    closeDrawer();
    if(room==='kitchen'&&typeof loadKitchenAlerts==='function')loadKitchenAlerts();
    document.querySelector('.main-wrap')?.scrollTo({top:0,behavior:'smooth'});
  }
  document.querySelectorAll('[data-room]').forEach(i=>i.addEventListener('click',()=>goTo(i.dataset.room)));
  document.querySelectorAll('[data-goto]').forEach(el=>el.addEventListener('click',()=>goTo(el.dataset.goto)));
  function restoreCurrentTab(){
    const selected=new URL(window.location.href).searchParams.get('tab');
    const allowed=Array.from(rooms).some(room=>room.id===selected);
    goTo(allowed?selected:'overview',{historyMode:'replace'});
  }
  window.addEventListener('popstate',restoreCurrentTab);
  // Wait for the rest of this script to initialize telemetry and control state.
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',restoreCurrentTab,{once:true});
  else queueMicrotask(restoreCurrentTab);

  function touch(){
    const stamp=document.getElementById('last-update');
    if(stamp)stamp.textContent=new Intl.DateTimeFormat('vi-VN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZone:'Asia/Ho_Chi_Minh'}).format(new Date());
  }

  /* ---- sparklines ---- */
  const sparks={};
  const sensorSeries={patient:{temp:'sp-pt-temp',hum:'sp-pt-humi'},living:{temp:'sp-lv-temp',hum:'sp-lv-humi',lux:'sp-lv-lux'},kitchen:{gas:'sp-kt-gas'}};
  if(!document.getElementById('sp-kt-gas')){
    const card=document.getElementById('kt-gas-card');
    if(card){const canvas=document.createElement('canvas');canvas.id='sp-kt-gas';canvas.className='spark';card.append(canvas);}
  }
  function drawSpark(id){
    const c=document.getElementById(id),series=sparks[id];
    if(!c||!series||!c.clientWidth||!c.clientHeight)return;
    const ratio=window.devicePixelRatio||1;
    const w=c.width=Math.round(c.clientWidth*ratio),h=c.height=Math.round(c.clientHeight*ratio);
    const ctx=c.getContext('2d');ctx.clearRect(0,0,w,h);
    const valid=series.data.filter(v=>typeof v==='number'&&Number.isFinite(v));
    const caption=c.nextElementSibling;
    if(!valid.length){if(caption?.classList.contains('sensor-chart-caption'))caption.textContent='Ch\u01b0a c\u00f3 l\u1ecbch s\u1eed';return;}
    const min=Math.min(...valid),max=Math.max(...valid),range=max-min||1;
    ctx.lineWidth=1.6*ratio;ctx.strokeStyle=series.color||'#4c9be8';ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();
    let connected=false;
    series.data.forEach((value,i)=>{
      if(typeof value!=='number'||!Number.isFinite(value)){connected=false;return;}
      const x=5*ratio+(i/Math.max(1,series.data.length-1))*(w-10*ratio);
      const y=max===min?h/2:h-6*ratio-(value-min)/range*(h-12*ratio);
      if(connected)ctx.lineTo(x,y);else ctx.moveTo(x,y);
      connected=true;
      if(valid.length===1){ctx.arc(x,y,2*ratio,0,Math.PI*2);ctx.fill();}
    });ctx.stroke();
    const labels=series.labels||[];
    const time=labels.length?labels[0]+' \u2013 '+labels[labels.length-1]:'';
    const text=(time?time+' \u00b7 ':'')+min+' \u2013 '+max;
    c.setAttribute('role','img');c.setAttribute('aria-label','L\u1ecbch s\u1eed c\u1ea3m bi\u1ebfn: '+text);c.title=text;
    if(caption?.classList.contains('sensor-chart-caption'))caption.textContent=text;
  }
  function spark(id,val,color){
    if(typeof val!=='number'||!Number.isFinite(val))return;
    if(!sparks[id])sparks[id]={data:[],labels:[]};
    const series=sparks[id];series.color=color;series.data.push(val);series.labels.push(new Date().toLocaleTimeString('vi-VN'));
    if(series.data.length>30){series.data.shift();series.labels.shift();}drawSpark(id);
  }
  function renderSensorHistories(histories){
    if(!histories||typeof histories!=='object')return;
    for(const [room,fields] of Object.entries(sensorSeries))for(const [key,id] of Object.entries(fields)){
      if(!Array.isArray(histories[room]?.[key]))continue;
      sparks[id]={data:histories[room][key].slice(-30),labels:(histories[room].labels||[]).slice(-30),color:'#4c9be8'};drawSpark(id);
    }
  }
  document.querySelectorAll('.detail-room canvas.spark').forEach(canvas=>{
    const caption=document.createElement('small');caption.className='sensor-chart-caption';caption.textContent='Ch\u01b0a c\u00f3 l\u1ecbch s\u1eed';canvas.after(caption);
    if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>drawSpark(canvas.id)).observe(canvas);
  });
  fetch('/api/history',{cache:'no-store'}).then(response=>response.ok?response.json():null).then(renderSensorHistories).catch(()=>{});

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
  const cameraStats=document.querySelector('.cam-overlay-stats');
  if(cameraStats&&videoFeed)videoFeed.parentElement.after(cameraStats);
  let camActive=false,camMode='auto';
  function setCameraUI(active,mode){
    const wasActive=camActive;
    camActive=active;if(mode)camMode=mode;
    videoFeed.style.display=active?'block':'none';
    videoPh.style.display=active?'none':'block';
    document.querySelectorAll('#cam-seg button').forEach(b=>b.classList.toggle('on',b.dataset.mode===camMode));
    if(active){const want='/video_feed';if(!wasActive||!videoFeed.getAttribute('src'))videoFeed.src=want+'?'+Date.now();}
    if(!active){videoFeed.removeAttribute('src');videoFeed.parentElement.style.aspectRatio='';document.getElementById('oc-gesture').textContent='Cử chỉ: camera tắt';}
  }
  document.querySelectorAll('#cam-seg button').forEach(b=>b.addEventListener('click',()=>{
    const m=b.dataset.mode;camMode=m;
    document.querySelectorAll('#cam-seg button').forEach(x=>x.classList.toggle('on',x===b));
    if(socket&&socket.connected){
      if(m==='on'){
        // Open a fresh stream immediately; backend confirmation owns actual state.
        camActive=false;
        setCameraUI(true,m);
      }else if(m==='off')setCameraUI(false,m);
      socket.emit('set_camera_mode',{mode:m});
    }else{
      setCameraUI(false,m);
      showSys('Mất kết nối. Chưa gửi lệnh camera.','light');
    }
  }));
  videoFeed.addEventListener('load',()=>{if(camActive&&videoFeed.naturalWidth&&videoFeed.naturalHeight)videoFeed.parentElement.style.aspectRatio=videoFeed.naturalWidth+' / '+videoFeed.naturalHeight;});
  videoFeed.addEventListener('error',()=>{videoFeed.style.display='none';videoPh.style.display='block';videoFeed.parentElement.style.aspectRatio='';camActive=false;});

  /* ---- device control ---- */
  const pendingControls=new Map();
  const roomPrefix={patient:'pt',living:'lv',kitchen:'kt'};
  let controlSequence=0;
  const controlSession=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,8);
  function emitSet(room,device,payload){
    if(!socket||!socket.connected){showSys('Mất kết nối. Chưa gửi lệnh điều khiển.','light');return;}
    const key=room+':'+device,previous=pendingControls.get(key);
    if(previous)clearTimeout(previous.timer);
    const status=document.getElementById(`${roomPrefix[room]}-${device}-status`);
    const target={...payload,request_id:controlSession+'-'+(++controlSequence),acknowledged:false};
    if(status)status.textContent='Đang chờ thiết bị…';
    target.timer=setTimeout(()=>{if(pendingControls.get(key)!==target)return;pendingControls.delete(key);if(status)status.textContent='Chưa xác nhận';socket.emit('request_initial_state');},10000);
    pendingControls.set(key,target);
    socket.emit('set_device',Object.assign({room,device,request_id:target.request_id},payload));
  }
  function confirmedData(room,data){
    const result={...data};
    for(const [key,target] of pendingControls){
      if(!key.startsWith(room+':'))continue;
      const device=key.split(':')[1],speed=device==='fan'?'fan_speed':device==='exhaust'?'exhaust_speed':null;
      const matches=speed?data[speed]!=null&&Math.abs(+data[speed]-(target.value||0))<=1:data[device]!=null&&!!data[device]===target.state;
      if(matches&&target.acknowledged){clearTimeout(target.timer);pendingControls.delete(key);}
      else{delete result[device];if(speed)delete result[speed];}
    }
    return result;
  }
  function clearPendingControls(){for(const target of pendingControls.values())clearTimeout(target.timer);pendingControls.clear();}

  function bindToggle(id,tileId,onTxt,offTxt,cb){
    const el=document.getElementById(id),tile=document.getElementById(tileId);
    if(!el||!tile)return;
    el.addEventListener('change',()=>{tile.classList.toggle('on',el.checked);const st=document.getElementById(id.replace('-toggle','-status'));if(st)st.textContent=el.checked?onTxt:offTxt;cb&&cb(el.checked);});
  }
  function bindRange(id,valId,cb){
    const el=document.getElementById(id),v=document.getElementById(valId);
    if(!el||!v)return;
    let timer=null,editingTimer=null,lastSentAt=0,lastSentValue=null,pendingValue=0;
    const send=value=>{cb&&cb(value);lastSentAt=performance.now();lastSentValue=value;};
    el.addEventListener('input',()=>{
      clearTimeout(editingTimer);clearTimeout(el._userEditTimeout);el.dataset.userEditing='1';el.dataset.desiredValue=el.value;v.textContent=el.value;pendingValue=+el.value;
      const wait=Math.max(0,120-(performance.now()-lastSentAt));
      if(wait===0){if(timer){clearTimeout(timer);timer=null;}send(pendingValue);}
      else if(!timer)timer=setTimeout(()=>{timer=null;send(pendingValue);},wait);
    });
    el.addEventListener('change',()=>{
      if(timer){clearTimeout(timer);timer=null;}
      pendingValue=+el.value;v.textContent=el.value;
      if(pendingValue!==lastSentValue)send(pendingValue);
      editingTimer=setTimeout(()=>{delete el.dataset.userEditing;delete el.dataset.desiredValue;},2200);
      el._userEditTimeout=editingTimer;
    });
  }
  bindToggle('pt-buzzer-toggle','pt-buzzer-tile','Đang kêu','Im lặng',on=>emitSet('patient','buzzer',{state:on}));
  bindToggle('pt-light-toggle','pt-light-tile','Đang bật','Đang tắt',on=>emitSet('patient','light',{state:on}));
  bindToggle('pt-fan-toggle','pt-fan-tile','Đang chạy','Đang tắt',on=>{const r=document.getElementById('pt-fan-range');if(!on){r.value=0;document.getElementById('pt-fan-val').textContent=0;}emitSet('patient','fan',{state:on,value:on?(+r.value||100):0});});
  bindRange('pt-fan-range','pt-fan-val',v=>{const t=document.getElementById('pt-fan-toggle');t.checked=v>0;document.getElementById('pt-fan-tile').classList.toggle('on',v>0);document.getElementById('pt-fan-status').textContent=v>0?'Đang chạy':'Đang tắt';emitSet('patient','fan',{state:v>0,value:v});});
  bindToggle('lv-light-toggle','lv-light-tile','Đang bật','Đang tắt',on=>emitSet('living','light',{state:on}));
  bindToggle('lv-fan-toggle','lv-fan-tile','Đang chạy','Đang tắt',on=>{const r=document.getElementById('lv-fan-range');if(!on){r.value=0;document.getElementById('lv-fan-val').textContent=0;}emitSet('living','fan',{state:on,value:on?(+r.value||100):0});});
  bindRange('lv-fan-range','lv-fan-val',v=>{const t=document.getElementById('lv-fan-toggle');t.checked=v>0;document.getElementById('lv-fan-tile').classList.toggle('on',v>0);document.getElementById('lv-fan-status').textContent=v>0?('Tốc độ '+v+'%'):'Đang tắt';emitSet('living','fan',{state:v>0,value:v});});
  bindToggle('lv-auto-toggle','lv-auto-tile','Bật đèn khi có người buổi tối','Đã tắt tự động',on=>emitSet('living','auto',{state:on}));
  bindToggle('kt-window-toggle','kt-window-tile','Đang mở','Đang đóng',on=>emitSet('kitchen','window',{state:on}));
  bindToggle('kt-exhaust-toggle','kt-exhaust-tile','Đang hút','Đang tắt',on=>{const r=document.getElementById('kt-exhaust-range'),v=on?(+r.value||100):0;r.value=v;document.getElementById('kt-exhaust-val').textContent=v;emitSet('kitchen','exhaust',{state:on,value:v});});
  bindRange('kt-exhaust-range','kt-exhaust-val',v=>{const on=v>0,t=document.getElementById('kt-exhaust-toggle');t.checked=on;document.getElementById('kt-exhaust-tile').classList.toggle('on',on);document.getElementById('kt-exhaust-status').textContent=on?'Đang hút':'Đang tắt';emitSet('kitchen','exhaust',{state:on,value:v});});
  bindToggle('kt-buzzer-toggle','kt-buzzer-tile','Đang kêu','Im lặng',on=>emitSet('kitchen','buzzer',{state:on}));
  bindToggle('kt-light-toggle','kt-light-tile','Đang bật','Đang tắt',on=>emitSet('kitchen','light',{state:on}));

  /* ---- apply data ---- */
  function badge(el,cls,txt){el.className='rb '+cls;el.textContent=txt;el.dataset.domainClass=cls;el.dataset.domainText=txt;delete el.dataset.telemetryWarning;}
  function syncOverviewWarning(){
    const overview=document.getElementById('overview'),line=document.getElementById('emg');
    const safety=overview.dataset.alertLevel&&overview.dataset.alertLevel!=='normal';
    const fall=document.querySelector('.ovr[data-goto="patient"].needs-attention');
    const warning=!!(safety||fall);
    overview.classList.remove('has-warning');
    line.classList.toggle('show',warning);
    if(fall&&!safety)document.getElementById('emg-desc').textContent='Phòng người bệnh: phát hiện té ngã. Cần kiểm tra ngay.';
  }
  function markRoomAttention(room,message,level){
    const card=document.querySelector('.ovr[data-goto="'+room+'"]'),marker=document.getElementById('attn-'+room);
    if(!card||!marker)return;
    const active=!!message;
    card.classList.toggle('needs-attention',active);
    if(active){card.dataset.attention=level||'warn';marker.hidden=false;marker.lastChild.textContent=' '+message;}
    else{delete card.dataset.attention;marker.hidden=true;}
    syncOverviewWarning();
  }
  function setToggle(id,tileId,on,onTxt,offTxt){const el=document.getElementById(id);if(el)el.checked=!!on;document.getElementById(tileId)?.classList.toggle('on',!!on);const st=document.getElementById(id.replace('-toggle','-status'));if(st)st.textContent=on?onTxt:offTxt;}

  function applyPatient(d){
    d=confirmedData('patient',d);
    if(d.light!=null)setToggle('pt-light-toggle','pt-light-tile',d.light,'Đang bật','Đang tắt');
    if(d.temp!=null){document.getElementById('pt-temp').textContent=d.temp;document.getElementById('ov-patient-temp').textContent=d.temp;spark('sp-pt-temp',d.temp,'#4c9be8');}
    if(d.hum!=null){document.getElementById('pt-humi').textContent=d.hum;document.getElementById('ov-patient-humi').textContent=d.hum;spark('sp-pt-humi',d.hum,'#3ba55d');}
    // Node phòng bệnh không có cảm biến gas; nếu firmware cũ từng gửi thì bỏ qua an toàn.
    if(d.gas!=null){const gasVal=document.getElementById('pt-gas'),gasCard=document.getElementById('pt-gas-card');if(gasVal){gasVal.textContent=Math.round(d.gas);spark('sp-pt-gas',d.gas,'#d6982c');}if(gasCard)gasCard.classList.toggle('alarm',d.gas>=2500);}
    if(d.motion!=null)document.getElementById('oc-pir').innerHTML='<i class="fas fa-person-walking"></i> PIR: '+(d.motion?'có chuyển động':'yên tĩnh');
    if(d.buzzer!=null){document.getElementById('pt-buzzer-toggle').checked=!!d.buzzer;document.getElementById('pt-buzzer-tile').classList.toggle('alarm',!!d.buzzer);document.getElementById('pt-buzzer-status').textContent=d.buzzer?'Đang kêu':'Im lặng';}
    if(d.fan_speed!=null){const r=document.getElementById('pt-fan-range'),v=document.getElementById('pt-fan-val');if(r.dataset.userEditing&&Math.abs(+d.fan_speed-(+r.dataset.desiredValue))<=1){clearTimeout(r._userEditTimeout);delete r.dataset.userEditing;delete r.dataset.desiredValue;}if(!r.dataset.userEditing){r.value=d.fan_speed;v.textContent=d.fan_speed;}const on=d.fan_speed>0;document.getElementById('pt-fan-toggle').checked=on;document.getElementById('pt-fan-tile').classList.toggle('on',on);document.getElementById('pt-fan-status').textContent=on?'Đang chạy':'Đang tắt';}
    touch();
  }
  function applyLiving(d){
    d=confirmedData('living',d);
    if(d.temp!=null){document.getElementById('lv-temp').textContent=d.temp;document.getElementById('ov-living-temp').textContent=d.temp;spark('sp-lv-temp',d.temp,'#4c9be8');}
    if(d.hum!=null){document.getElementById('lv-humi').textContent=d.hum;spark('sp-lv-humi',d.hum,'#3ba55d');}
    if(d.lux!=null){document.getElementById('lv-lux').textContent=Math.round(d.lux);spark('sp-lv-lux',d.lux,'#e0a52e');}
    if(d.motion!=null){const t=d.motion?'Có người':'Không có người';document.getElementById('lv-motion-status').textContent=t;document.getElementById('lv-motion-tile').classList.toggle('on',!!d.motion);document.getElementById('ov-living-motion').textContent=nodeState&&nodeState.living?t:'--';}
    if(d.light!=null){setToggle('lv-light-toggle','lv-light-tile',d.light,'Đang bật','Đang tắt');document.getElementById('ov-living-light').textContent=nodeState&&nodeState.living?(d.light?'Bật':'Tắt'):'--';}
    if(d.fan_speed!=null){const r=document.getElementById('lv-fan-range'),v=document.getElementById('lv-fan-val');if(r.dataset.userEditing&&Math.abs(+d.fan_speed-(+r.dataset.desiredValue))<=1){clearTimeout(r._userEditTimeout);delete r.dataset.userEditing;delete r.dataset.desiredValue;}if(!r.dataset.userEditing){r.value=d.fan_speed;v.textContent=d.fan_speed;}const on=d.fan_speed>0;document.getElementById('lv-fan-toggle').checked=on;document.getElementById('lv-fan-tile').classList.toggle('on',on);document.getElementById('lv-fan-status').textContent=on?('Tốc độ '+d.fan_speed+'%'):'Đang tắt';}
    if(d.auto!=null){document.getElementById('lv-auto-toggle').checked=!!d.auto;document.getElementById('lv-auto-tile').classList.toggle('on',!!d.auto);}
    touch();
  }
  function applyKitchen(d){
    d=confirmedData('kitchen',d);
    const kitchenConnected=!!(nodeState&&nodeState.kitchen);
    if(d.gas!=null&&(kitchenConnected||d.gas>=1500)){const g=Math.round(d.gas);document.getElementById('kt-gas').textContent=g;document.getElementById('ov-kitchen-gas').textContent=g;setGauge(d.gas);
      const st=document.getElementById('kt-gas-state'),card=document.getElementById('kt-gas-card');
      if(d.gas>=2500){st.className='badge bad';st.innerHTML='<i class="fas fa-triangle-exclamation"></i> Nguy hiểm';card.classList.add('alarm');}
      else if(d.gas>=1500){st.className='badge warn';st.innerHTML='<i class="fas fa-circle-exclamation"></i> Tăng cao';card.classList.remove('alarm');}
      else{st.className='badge ok';st.innerHTML='<i class="fas fa-circle-check"></i> An toàn';card.classList.remove('alarm');}
    }
    if(d.smoke!=null&&(kitchenConnected||d.smoke)){document.getElementById('kt-smoke-status').textContent=d.smoke?'PHÁT HIỆN KHÓI':'Không phát hiện';document.getElementById('kt-smoke-tile').classList.toggle('alarm',!!d.smoke);document.getElementById('ov-kitchen-smoke').textContent=d.smoke?'Có':'Không';}
    if(d.flame!=null&&(kitchenConnected||d.flame)){document.getElementById('kt-flame-status').textContent=d.flame?'PHÁT HIỆN LỬA':'Không phát hiện';document.getElementById('kt-flame-tile').classList.toggle('alarm',!!d.flame);document.getElementById('ov-kitchen-flame').textContent=d.flame?'Có':'Không';}
    if(d.window!=null)setToggle('kt-window-toggle','kt-window-tile',d.window,'Đang mở','Đang đóng');
    if(d.exhaust_speed!=null){const r=document.getElementById('kt-exhaust-range'),v=document.getElementById('kt-exhaust-val');if(r.dataset.userEditing&&Math.abs(+d.exhaust_speed-(+r.dataset.desiredValue))<=1){clearTimeout(r._userEditTimeout);delete r.dataset.userEditing;delete r.dataset.desiredValue;}if(!r.dataset.userEditing){r.value=d.exhaust_speed;v.textContent=d.exhaust_speed;}}
    if(d.exhaust!=null)setToggle('kt-exhaust-toggle','kt-exhaust-tile',d.exhaust,'Đang hút','Đang tắt');
    if(d.light!=null)setToggle('kt-light-toggle','kt-light-tile',d.light,'Đang bật','Đang tắt');
    if(d.buzzer!=null)setToggle('kt-buzzer-toggle','kt-buzzer-tile',d.buzzer,'Đang kêu','Im lặng');
    const danger=d.flame||d.smoke||(d.gas!=null&&d.gas>=2500),warn=(d.gas!=null&&d.gas>=1500);
    badge(document.getElementById('ov-kitchen-badge'),danger?'bad':(warn?'warn':(kitchenConnected?'ok':'')),danger?'Nguy hiểm':(warn?'Cảnh báo':(kitchenConnected?'An toàn':'Chưa kết nối')));
    if(danger||warn||kitchenConnected)markRoomAttention('kitchen',danger?'Cần kiểm tra phòng bếp':warn?'Kiểm tra khí gas':'',danger?'danger':'warn');
    touch();
  }
  function applyAI(a){
    const modeLabel=document.getElementById('ai-observe-mode');
    if(modeLabel && a.observe_only!=null)modeLabel.hidden=!a.observe_only;
    if(a.gesture!=null){
      const elG=document.getElementById('oc-gesture');
      const handLabels={not_detected:'Chưa thấy bàn tay',unrecognized:'Thấy tay, chưa rõ cử chỉ',unavailable:'Nhận diện tay chưa sẵn sàng',disabled:'Nhận diện tay đang tắt',waiting:'Đang chờ nhận diện tay',stale:'Đang chờ kết quả tay mới'};
      const gestureText=a.gesture&&a.gesture!=='—'?a.gesture:(handLabels[a.hand_status]||'—');
      const gTxt='Cử chỉ: '+gestureText;
      if(elG&&elG.textContent!==gTxt)elG.textContent=gTxt;
      document.querySelectorAll('#gesture-table tr[data-g]').forEach(r=>r.classList.toggle('live',r.dataset.g===a.gesture));
    }
    if(a.fps!=null){
      const el=document.getElementById('ai-fps');
      const txt=String(a.fps);
      if(el&&el.textContent!==txt)el.textContent=txt;
    }
    if(a.video_fps!=null){
      const elV=document.getElementById('ai-video-fps');
      const vTxt=String(a.video_fps);
      if(elV&&elV.textContent!==vTxt)elV.textContent=vTxt;
    }
    const latVal=a.work_ms!=null?a.work_ms:a.latency;
    if(latVal!=null){
      const elL=document.getElementById('ai-latency');
      const lTxt=String(latVal);
      if(elL&&elL.textContent!==lTxt)elL.textContent=lTxt;
    }
    const ageVal=a.overlay_age_ms;
    if(ageVal!=null){
      const elA=document.getElementById('ai-age');
      const aTxt=String(ageVal);
      if(elA&&elA.textContent!==aTxt)elA.textContent=aTxt;
    }
    const fallSignal=a.observe_only?a.fall_suspected:a.fall;
    if(a.ai_available===false){
      const fall=document.getElementById('oc-fall');
      fall.textContent='AI chưa sẵn sàng';fall.classList.remove('alarm');
      document.getElementById('ov-patient-fall').textContent='Chưa có nhận diện AI';
      return;
    }
    if(fallSignal!=null){
      if(fallSignal)markRoomAttention('patient',a.observe_only?'Nghi té ngã (chỉ quan sát)':'Cảnh báo té ngã','danger');
      else markRoomAttention('patient','','');
      const oc=document.getElementById('oc-fall');
      const fallText=a.observe_only?'NGHI TÉ NGÃ (quan sát)':'TÉ NGÃ';
      const expectedText=fallSignal?fallText:'Té ngã: chưa phát hiện';
      if(oc&&oc.textContent!==expectedText){
        oc.textContent=expectedText;
        oc.classList.toggle('alarm',!!fallSignal);
      }
      const ovFall=document.getElementById('ov-patient-fall');
      const expectedOv=fallSignal?fallText:'Chưa phát hiện';
      if(ovFall&&ovFall.textContent!==expectedOv)ovFall.textContent=expectedOv;
      badge(document.getElementById('ov-patient-badge'),fallSignal?'bad':'ok',fallSignal?'Nghi té ngã':(a.observe_only?'Quan sát':'Bình thường'));
    }

  }

  /* ---- lịch sử cảnh báo bếp (Yêu cầu 4) ---- */
  function fmtT(v){if(!v)return'--';const d=new Date(String(v).replace(' ','T'));return isNaN(d)?v:d.toLocaleString('vi-VN');}
  let _lastKitchenFetch = 0;
  async function loadKitchenAlerts(){
    const list=document.getElementById('kt-alert-list');if(!list)return;
    const now=Date.now();
    if(now - _lastKitchenFetch < 1000)return;
    _lastKitchenFetch = now;
    try{
      const r=await fetch('/api/kitchen_alerts');const d=await r.json();const a=(d&&d.alerts)||[];
      if(!a.length){list.innerHTML='<div class="empty">Chưa có cảnh báo nào.</div>';return;}
      list.innerHTML=a.map(x=>`<div class="alert-item"><i class="fas fa-triangle-exclamation ai-ic"></i><div class="ai-body"><div class="ai-act">${x.action}</div><div class="ai-time">${fmtT(x.timestamp)}</div></div></div>`).join('');
    }catch(e){}
  }
  const ktReload=document.getElementById('kt-alerts-reload');
  if(ktReload)ktReload.addEventListener('click',loadKitchenAlerts);

  /* ---- fall confirmation ---- */
  let fallConfirmation=null;
  function renderFallConfirmation(){
    const button=document.getElementById('patient-confirm-safe');
    const message=document.getElementById('patient-confirm-message');
    if(!button||!message)return;
    const status=fallConfirmation,connected=!!socket&&socket.connected;
    button.disabled=!connected||!status||!status.can_confirm;
    let text='Đang tải trạng thái cảnh báo té ngã…';
    if(!connected)text='Mất kết nối realtime; chưa thể gửi xác nhận.';
    else if(status){
      if(!status.required)text='Không có cảnh báo té ngã cần xác nhận.';
      else if(status.blocked_by_kitchen)text='Còn cảnh báo phòng bếp; hãy kiểm tra và xác nhận tại phòng bếp.';
      else if(status.active)text='AI còn báo dấu hiệu té ngã. Kiểm tra người bệnh trước khi xác nhận.';
      else if(status.pending)text='Đã gửi xác nhận; đang chờ node phòng bệnh phản hồi. Còi vẫn được khóa an toàn.';
      else if(!status.node_online)text='Node phòng bệnh chưa kết nối; chờ kết nối lại để xác nhận.';
      else text='Cảnh báo té ngã đang chờ xác nhận. Chỉ bấm sau khi đã kiểm tra người bệnh an toàn.';
    }
    message.textContent=text;
  }
  function applyFallConfirmation(status){fallConfirmation=status||null;renderFallConfirmation();}
  const patientConfirmButton=document.getElementById('patient-confirm-safe');
  if(patientConfirmButton)patientConfirmButton.addEventListener('click',()=>{
    if(patientConfirmButton.disabled||!socket||!socket.connected)return;
    patientConfirmButton.disabled=true;
    document.getElementById('patient-confirm-message').textContent='Đang gửi xác nhận an toàn…';
    socket.emit('confirm_fall_safe',{});
  });
  renderFallConfirmation();

  /* ---- alert state machine ---- */
  const STEPS=['normal','light','emergency','awaiting'];
  function setAlert(level,msg){
    const idx=STEPS.indexOf(level);if(idx<0)return;
    document.getElementById('confirm-btn').disabled=false;
    const chip=document.getElementById('state-chip'),desc=document.getElementById('state-desc');
    const allRoomsConnected=Object.values(nodeState).every(Boolean);
    const displayLevel=level==='normal'&&!allRoomsConnected?'unknown':level;
    const map={normal:['ok','Chưa có cảnh báo','Chưa có cảnh báo nào được ghi nhận.'],unknown:['warn','Chưa đủ dữ liệu','Không thể xác nhận tình trạng an toàn khi một hoặc nhiều phòng chưa kết nối.'],light:['bad','Cảnh báo nhẹ','Khí gas tăng cao hơn mức bình thường'],emergency:['bad','Khẩn cấp','Phát hiện khói/lửa hoặc gas rất cao — đang xử lý'],awaiting:['bad','Chờ xác nhận','Điều kiện đã an toàn — cần xác nhận để khôi phục']};
    document.getElementById('state-card').dataset.level=displayLevel;
    if(level==='normal'){if(nodeState.kitchen)markRoomAttention('kitchen','','');}
    else markRoomAttention('kitchen',level==='light'?'Kiểm tra khí gas':'Cảnh báo an toàn',level==='light'?'warn':'danger');
    const m=map[displayLevel];chip.className='chip '+(displayLevel==='normal'?'ok':(displayLevel==='unknown'?'warn':'bad'));chip.innerHTML='<i class="fas fa-circle"></i> '+m[1];desc.textContent=m[2];
    document.getElementById('overview').dataset.alertLevel=level;
    document.getElementById('emg-desc').textContent=msg||map[level][2];
    syncOverviewWarning();
    document.getElementById('silence-btn').classList.toggle('show',level==='light'||level==='emergency'||level==='awaiting');
    document.getElementById('confirm-btn').classList.toggle('show',level==='awaiting');
    // The persistent overview line displays safety alerts without a duplicate banner.
  }
  document.getElementById('confirm-btn').addEventListener('click',()=>{if(socket)socket.emit('confirm_safe',{});});
  document.getElementById('silence-btn').addEventListener('click',()=>{if(socket)socket.emit('silence_alert',{});});
  document.getElementById('sysbar-x').addEventListener('click',()=>document.getElementById('sysbar').classList.remove('show'));
  function showSys(msg,lvl){const box=document.getElementById('sysbar');document.getElementById('sysbar-text').textContent=msg;box.className='sysbar show'+(lvl==='light'?' light':'');clearTimeout(showSys._t);showSys._t=setTimeout(()=>box.classList.remove('show'),9000);}

  /* ---- node status ---- */
  const nodeState={patient:false,living:false,kitchen:false};
  const telemetryCache={};
  function setNode(room,online){
    const el=document.getElementById('node-'+room);if(!el)return;
    el.classList.toggle('off',!online);
    el.querySelector('.nsub').textContent=online?'Đã kết nối':'Chưa kết nối';
    const roomBadge=document.getElementById('ov-'+room+'-badge');
    if(!online&&roomBadge&&!roomBadge.classList.contains('bad')){roomBadge.className='rb';roomBadge.textContent='Chưa kết nối';}
    if(online&&roomBadge&&roomBadge.textContent==='Chưa kết nối'){roomBadge.className='rb ok';roomBadge.textContent='Đã kết nối';}
    if(room==='kitchen'){document.getElementById('kitchen-dot').classList.toggle('show',!online);document.getElementById('bn-kitchen-dot').classList.toggle('show',!online);}
    document.querySelectorAll('[data-node-label]').forEach(label=>{if(label.dataset.nodeLabel===room){label.textContent=online?'Đã kết nối':'Chưa kết nối';label.classList.toggle('online',online);}});
    nodeState[room]=online;updateNodeChip();
  }
  function applyTelemetry(quality){
    const names={temp:'nhiệt độ',hum:'độ ẩm',motion:'hiện diện',lux:'ánh sáng',gas:'ADC khí',flame:'tín hiệu lửa'};
    Object.entries(quality||{}).forEach(([room,q])=>{
      if(!['patient','living','kitchen'].includes(room)||!q)return;
      telemetryCache[room]=q;
      let status=q.status;
      if(status!=='unavailable'){
        if(nodeState[room]===false)status='offline';
        else if(status==='offline'||q.transport_connected===false)status='awaiting';
      }
      const fresh=status==='fresh';
      const missing=Object.entries(q.fields||{}).filter(([,f])=>f.status!=='fresh').map(([key])=>names[key]||key);
      const labels={fresh:'Đang nhận dữ liệu cảm biến',partial:'Có dữ liệu; thiếu/cũ: '+missing.join(', '),
        stale:'Dữ liệu cảm biến đã cũ — không coi giá trị cuối là hiện tại',
        awaiting:'BLE đã kết nối; đang chờ dữ liệu cảm biến',
        offline:'Chưa có liên kết BLE; giữ giá trị cuối nếu có',
        unavailable:'Không kiểm tra được gateway; chưa xác minh độ mới dữ liệu'};
      const text=labels[status]||labels.unavailable;
      const qualityLabel=document.getElementById('data-quality-'+room);
      if(qualityLabel){qualityLabel.textContent=text;qualityLabel.className='badge '+(fresh?'ok':'warn');}
      const node=document.getElementById('node-'+room);
      if(node){node.classList.toggle('off',!fresh);node.querySelector('.nsub').textContent=
        status==='offline'&&q.transport_state==='connecting'?'Đang kết nối BLE':text;}
      const roomBadge=document.getElementById('ov-'+room+'-badge');
      // A freshness warning must never downgrade a known danger/alarm badge.
      if(roomBadge&&!roomBadge.classList.contains('bad')){
        if(!fresh){
          if(!roomBadge.dataset.telemetryWarning){roomBadge.dataset.telemetryBaseClass=roomBadge.className;roomBadge.dataset.telemetryBaseText=roomBadge.textContent;}
          roomBadge.className='rb warn';roomBadge.textContent=status==='offline'?'Chưa kết nối':'Dữ liệu chưa đủ/mới';roomBadge.dataset.telemetryWarning='1';
        }else if(roomBadge.dataset.telemetryWarning){
          roomBadge.className=roomBadge.dataset.domainClass?'rb '+roomBadge.dataset.domainClass:(roomBadge.dataset.telemetryBaseClass||'rb ok');
          roomBadge.textContent=roomBadge.dataset.domainText||roomBadge.dataset.telemetryBaseText||'Nhận dữ liệu';
          delete roomBadge.dataset.telemetryWarning;delete roomBadge.dataset.telemetryBaseClass;delete roomBadge.dataset.telemetryBaseText;
        }
      }
    });
  }

  function updateNodeChip(){
    const n=Object.values(nodeState).filter(Boolean).length;
    const c=document.getElementById('node-chip');c.innerHTML='<i class="fas fa-diagram-project"></i> '+n+'/'+Object.keys(nodeState).length+' phòng';
    c.title='Số liên kết BLE; xem nhãn từng phòng để biết độ mới dữ liệu';
    c.className='chip nodes'+(n===Object.keys(nodeState).length?' ok':' warn');
    const state=document.getElementById('state-card'),chip=document.getElementById('state-chip'),desc=document.getElementById('state-desc');
    if(state.dataset.level==='normal'||state.dataset.level==='unknown'){
      const complete=n===Object.keys(nodeState).length;
      state.dataset.level=complete?'normal':'unknown';
      chip.className='chip '+(complete?'ok':'warn');
      chip.innerHTML='<i class="fas fa-circle"></i> '+(complete?'Chưa có cảnh báo':'Chưa đủ dữ liệu');
      desc.textContent=complete?'Chưa có cảnh báo nào được ghi nhận.':'Không thể xác nhận tình trạng an toàn khi một hoặc nhiều phòng chưa kết nối.';
    }
  }
  function setConn(ok){
    document.querySelectorAll('.sw input, input[type="range"], #cam-seg button').forEach(el=>el.disabled=!ok);
    const c=document.getElementById('conn-chip'),m=document.getElementById('mt-conn');
    if(c){c.className='chip '+(ok?'ok':'bad');c.innerHTML='<i class="fas fa-circle"></i> '+(ok?'Đã kết nối':'Mất kết nối');}
    if(m)m.className='mt-conn '+(ok?'ok':'bad');
    renderFallConfirmation();
  }

  /* ================= SOCKET ================= */
  async function refreshNodeStatus(){
    try{
      const r=await fetch('/api/state',{cache:'no-store',credentials:'same-origin'});
      if(!r.ok)throw new Error('Gateway state unavailable');
      const s=await r.json();
      touch();
      if(s.nodes)Object.keys(nodeState).forEach(room=>{
        if(s.nodes[room]!=null)setNode(room,!!s.nodes[room]);
      });
      applyTelemetry(s.telemetry);
      applyFallConfirmation(s.fall_confirmation);
    }catch(e){applyTelemetry(Object.fromEntries(Object.keys(nodeState).map(room=>[room,{status:'unavailable'}])));applyFallConfirmation(null);}
  }
  refreshNodeStatus();
  setInterval(refreshNodeStatus,3000);
  if(socket){
    socket.on('command_result',result=>{
      const target=pendingControls.get(result.room+':'+result.device);
      if(target&&target.request_id===result.request_id&&result.status==='applied')target.acknowledged=true;
    });
    socket.on('connect',()=>{setConn(true);socket.emit('request_initial_state');loadKitchenAlerts();});
    socket.on('disconnect',()=>{clearPendingControls();setConn(false);document.getElementById('state-chip').textContent='Mất kết nối realtime';document.getElementById('state-chip').className='chip';document.getElementById('state-desc').textContent='Trạng thái node được cập nhật qua API khi realtime gián đoạn.';document.getElementById('confirm-btn').disabled=true;});
    socket.on('command_error',e=>{clearPendingControls();showSys(e.message||'Không gửi được lệnh.','light');socket.emit('request_initial_state');});
    socket.on('sensor_chart_update',renderSensorHistories);
    socket.on('bootstrap',s=>{
      renderSensorHistories(s.histories);
      if(s.nodes){['patient','living','kitchen'].forEach(r=>setNode(r,!!s.nodes[r]));}
      if(s.rooms){applyPatient(s.rooms.patient||{});applyLiving(s.rooms.living||{});applyKitchen(s.rooms.kitchen||{});}
      if(s.ai)applyAI(s.ai);
      if(s.camera){setCameraUI(!!s.camera.active,s.camera.mode);}
      if(s.alert)setAlert(s.alert.level);
      applyTelemetry(s.telemetry);
      applyFallConfirmation(s.fall_confirmation);
    });
    socket.on('room_update',m=>{if(m.room==='patient')applyPatient(m.data);else if(m.room==='living')applyLiving(m.data);else if(m.room==='kitchen')applyKitchen(m.data);applyTelemetry(telemetryCache);});
    socket.on('node_status',n=>{['patient','living','kitchen'].forEach(r=>{if(n[r]!=null)setNode(r,n[r]===true||n[r]==='online');});applyTelemetry(telemetryCache);});
    socket.on('camera_sync',c=>{setCameraUI(!!c.active,c.mode);});
    socket.on('ai_status',a=>{applyAI(a);});
    socket.on('fall_confirmation',applyFallConfirmation);
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
      const cnt=document.getElementById('gcard-count-badge');if(cnt)cnt.textContent=(ms&&ms.length)||0;
      if(!ms||!ms.length){list.innerHTML='<div class="empty">Chưa có ánh xạ. Chọn cử chỉ và lưu để bắt đầu.</div>';return;}
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
      const button=document.getElementById('gm-add'),message=document.getElementById('gm-message');
      if(button.disabled)return;
      button.disabled=true;message.textContent='Đang lưu…';
      try{const d=await fj('/api/gesture_mappings',{method:'POST',body:JSON.stringify({gesture_name:gEl.value,target_device:dEl.value,action:aEl.value})});renderList(d.mappings);message.textContent='Đã lưu ánh xạ.';}catch(e){message.textContent=e.message;}finally{button.disabled=false;}
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
