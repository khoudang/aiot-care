// Remove fields retained in templates cached by a running server.
const registrationCodeField=document.getElementById('cfg-code');
if(registrationCodeField)registrationCodeField.closest('.fld').remove();
const configDescription=document.querySelector('#config-form')?.previousElementSibling?.querySelector('p');
if(configDescription)configDescription.textContent='Telegram Bot';
/* ================= ADMIN ================= */
  (function(){
    const $=id=>document.getElementById(id);
    const settings=$('admin-settings');
    if(settings&&!settings.querySelector('.settings-scroll')){
      const scroll=document.createElement('div');scroll.className='settings-scroll';
      Array.from(settings.children).filter(el=>!el.classList.contains('detail-heading')).forEach(el=>scroll.append(el));
      settings.append(scroll);
    }
    // A running server may still render the previous dashboard template.
    const logsHeading=document.querySelector('#admin-logs>.detail-heading');
    if(logsHeading&&!$('logs-from')){
      const filter=document.createElement('div');filter.className='logs-filter';
      filter.innerHTML='<label for="logs-from">Từ ngày</label><input type="date" id="logs-from"><label for="logs-to">Đến ngày</label><input type="date" id="logs-to"><span id="logs-filter-message" role="status" aria-live="polite"></span>';
      logsHeading.append(filter);
    }
    const logsFilter=logsHeading?.querySelector('.logs-filter');
    if(logsFilter&&!$('logs-apply')){
      const apply=document.createElement('button');apply.id='logs-apply';apply.type='button';apply.className='btn';
      apply.innerHTML='<i class="fas fa-filter" aria-hidden="true"></i> Lọc';
      logsFilter.insertBefore(apply,$('logs-filter-message'));
      apply.addEventListener('click',()=>loadLogs().catch(()=>{}));
    }
    for(const id of ['logs-from','logs-to']){
      const input=$(id);
      if(!input)continue;
      const field=document.createElement('div');
      field.className='logs-date-field';
      input.before(field);
      const display=document.createElement('span');
      display.className='logs-date-display';
      display.setAttribute('aria-hidden','true');
      field.append(input,display);
      function syncDate(){
        display.textContent=input.value?input.value.split('-').reverse().join('/'):'dd/mm/yyyy';
        display.classList.toggle('is-empty',!input.value);
      }
      input.addEventListener('input',syncDate);
      input.addEventListener('change',syncDate);
      syncDate();
    }
    const usersBody=$('users-body'),loginBody=$('login-body'),auditBody=$('audit-body');
    let loginAll=[],auditAll=[];let logRequest=0;
    async function fj(url,opt={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt});const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw new Error(d.message||'Lỗi máy chủ.');return d;}
    function fmtSql(v){if(!v)return'--';const d=new Date(String(v).replace(' ','T'));return isNaN(d)?v:d.toLocaleString('vi-VN');}
    let accountUsers=[];
    const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    function renderUsers(us){
      accountUsers=us||[];
      if(!us||!us.length){usersBody.innerHTML='<tr><td colspan="6"><div class="empty">Chưa có tài khoản nào.</div></td></tr>';return;}
      usersBody.innerHTML=us.map(u=>{
        const rb=u.role==='admin'?'<span class="pill admin"><i class="fas fa-crown"></i> admin</span>':'<span class="pill member"><i class="fas fa-user"></i> member</span>';
        const sus=Number(u.is_suspended)===1;
        const sb=sus?'<span class="pill off"><i class="fas fa-lock"></i> Đã khóa</span>':'<span class="pill on"><i class="fas fa-lock-open"></i> Hoạt động</span>';
        return `<tr class="${sus?'dim':''}"><td>${Number(u.id)}</td><td>${escapeHtml(u.username)}</td><td>${rb}</td><td>${sb}</td><td>${escapeHtml(fmtSql(u.created_at))}</td>
          <td><div class="act-group">
            <button type="button" class="btn sm" data-user-action="edit" data-user-id="${Number(u.id)}" aria-label="Sửa tài khoản ${escapeHtml(u.username)}"><i class="fas fa-pen"></i></button>
            <button type="button" class="btn sm ${sus?'ok':''}" data-user-action="suspend" data-user-id="${Number(u.id)}">${sus?'Mở khóa':'Khóa'}</button>
            <button type="button" class="btn sm danger" data-user-action="delete" data-user-id="${Number(u.id)}" aria-label="Xóa tài khoản ${escapeHtml(u.username)}"><i class="fas fa-trash"></i></button>
          </div></td></tr>`;}).join('');
    }
    const loginRow=l=>`<tr><td>${l.username||('user #'+(l.user_id??''))}</td><td>${l.ip_address||'--'}</td><td>${fmtSql(l.timestamp)}</td></tr>`;
    function paintLogin(){loginBody.innerHTML=loginAll.length?loginAll.map(loginRow).join(''):'<tr><td colspan="3"><div class="empty">Chưa có dữ liệu.</div></td></tr>';}
    function renderLogin(ls){loginAll=ls||[];paintLogin();}
    function isWarn(a){const t=String(a||'').toLowerCase();return t.includes('cảnh báo')||t.includes('gas')||t.includes('cháy')||t.includes('té ngã')||t.includes('khẩn')||t.includes('sức khỏe');}
    const auditRow=l=>{const w=isWarn(l.action);const a=w?`<span class="warn-txt"><i class="fas fa-triangle-exclamation"></i> ${l.action}</span>`:l.action;return `<tr class="${w?'warn-row':''}"><td>${l.username||(l.user_id?('user #'+l.user_id):'hệ thống')}</td><td>${a}</td><td>${fmtSql(l.timestamp)}</td></tr>`;};
    function paintAudit(){if(!auditBody)return;auditBody.innerHTML=auditAll.length?auditAll.map(auditRow).join(''):'<tr><td colspan="3"><div class="empty">Chưa có dữ liệu.</div></td></tr>';}
    function renderAudit(ls){auditAll=ls||[];paintAudit();}
    async function loadUsers(){usersBody.innerHTML='<tr><td colspan="6"><div class="empty">Đang tải…</div></td></tr>';renderUsers((await fj('/api/admin/users')).users||[]);}
    async function loadLogs(){
      const from=$('logs-from')?.value||'',to=$('logs-to')?.value||'';
      const message=$('logs-filter-message');
      if(from&&to&&from>to){if(message)message.textContent='Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.';return;}
      const token=++logRequest;
      if(message)message.textContent='Đang tải…';
      try{
        const d=await fj('/api/admin/logs?'+new URLSearchParams({from,to}));
        if(token!==logRequest)return;
        renderLogin(d.login_logs||[]);renderAudit(d.audit_logs||[]);
        if(message)message.textContent='';
        document.querySelectorAll('#admin-logs .table-wrap').forEach(el=>el.scrollTop=0);
      }catch(error){if(token===logRequest&&message)message.textContent=error.message;throw error;}
    }
    ['logs-from','logs-to'].forEach(id=>$(id)?.addEventListener('change',()=>loadLogs().catch(()=>{})));
    const sampleField=document.createElement('div');
    sampleField.className='fld';
    sampleField.innerHTML='<label for="cfg-sample-interval">Kho&#7843;ng l&#7845;y m&#7851;u bi&#7875;u &#273;&#7891; (gi&#226;y)</label><input id="cfg-sample-interval" type="number" min="5" max="3600" value="60" required>';
    $('config-form').querySelector('.settings-actions').before(sampleField);
    async function loadConfig(){const c=(await fj('/api/admin/configs')).configs||{};$('cfg-token').value=c.telegram_bot_token||'';$('cfg-chat').value=c.telegram_chat_id||'';$('cfg-sample-interval').value=c.sensor_sample_interval||60;}
    const bleNames={patient:'Phòng người bệnh',living:'Phòng khách',kitchen:'Phòng bếp'};
    const bleStatus=state=>{
      if(state==='ready'||state===true)return 'Sẵn sàng';
      if(state==='connecting')return 'Đang kết nối';
      if(state==='subscribing')return 'Đang đăng ký';
      if(state==='stale')return 'Mất tín hiệu';
      return 'Chưa kết nối';
    };
    let scannedBleDevices=[];
    function fillBleChoices(select){
      select.textContent='';
      const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent=scannedBleDevices.length?'Chọn thiết bị BLE đã quét…':'Chưa có kết quả quét';select.append(placeholder);
      for(const device of scannedBleDevices){const option=document.createElement('option');option.value=device.mac;option.textContent=`${device.name||'Thiết bị BLE'} · ${device.mac}`;select.append(option);}
      select.disabled=!scannedBleDevices.length;
    }
    function paintBleNodes(nodes){
      const list=$('ble-list');list.textContent='';
      for(const node of nodes){
        const row=document.createElement('div');row.className='ble-row';row.dataset.room=node.room;
        const label=document.createElement('label');label.textContent=bleNames[node.room]||node.room;
        const status=document.createElement('span');status.className='ble-state';status.textContent=bleStatus(node.state||node.online);
        const input=document.createElement('input');input.value=node.mac;input.setAttribute('aria-label',`MAC BLE ${label.textContent}`);input.spellcheck=false;
        const picker=document.createElement('div');picker.className='ble-picker';
        const select=document.createElement('select');select.className='ble-device-select';select.setAttribute('aria-label',`Thiết bị BLE ${label.textContent}`);fillBleChoices(select);
        select.addEventListener('change',()=>{if(select.value){input.value=select.value;select.value='';}});
        picker.append(input,select);
        const save=document.createElement('button');save.type='button';save.className='btn sm';save.textContent='Lưu';
        save.addEventListener('click',async()=>{save.disabled=true;try{const d=await fj(`/api/admin/ble-nodes/${node.room}`,{method:'POST',body:JSON.stringify({mac:input.value.trim()})});const current=(d.nodes||[]).find(item=>item.room===node.room);if(current){input.value=current.mac;status.textContent=bleStatus(current.state||current.online);}$('ble-message').textContent=d.message||'Đã lưu.';}catch(err){$('ble-message').textContent=err.message;}finally{save.disabled=false;}});
        row.append(label,status,picker,save);list.append(row);
      }
    }
    async function loadBleNodes(){paintBleNodes((await fj('/api/admin/ble-nodes')).nodes||[]);}
    $('ble-scan').addEventListener('click',async()=>{const btn=$('ble-scan');btn.disabled=true;$('ble-message').textContent='Đang quét BLE…';try{const devices=(await fj('/api/admin/ble-scan')).devices||[];scannedBleDevices=devices;document.querySelectorAll('.ble-device-select').forEach(fillBleChoices);$('ble-message').textContent=devices.length?`Tìm thấy ${devices.length} thiết bị. Mở danh sách thiết bị ở phòng tương ứng, chọn MAC rồi nhấn Lưu.`:'Không tìm thấy thiết bị đang phát BLE.';}catch(err){$('ble-message').textContent=err.message;}finally{btn.disabled=false;}});
    if(typeof socket!=='undefined'&&socket)socket.on('node_status',statuses=>{document.querySelectorAll('.ble-row').forEach(row=>{row.querySelector('.ble-state').textContent=bleStatus(statuses[row.dataset.room]);});});
    if(typeof socket!=='undefined'&&socket)socket.on('node_state',states=>{document.querySelectorAll('.ble-row').forEach(row=>{row.querySelector('.ble-state').textContent=bleStatus(states[row.dataset.room]);});});
    let accountBusy=false,editId=null,deleteId=null;
    const usersMessage=$('users-message');
    const accountDialogs=new Map();
    for(const id of ['user-edit-panel','user-delete-panel']){
      const panel=$(id);
      const dialog=document.createElement('dialog');
      dialog.className='account-dialog';
      dialog.setAttribute('aria-labelledby',panel.getAttribute('aria-labelledby'));
      const feedback=document.createElement('p');
      feedback.className='account-dialog-feedback';
      feedback.setAttribute('role','status');
      panel.before(dialog);
      dialog.append(panel,feedback);
      panel.hidden=false;
      dialog.addEventListener('cancel',event=>{
        event.preventDefault();
        if(!accountBusy)$(id.replace('-panel','-cancel')).click();
      });
      accountDialogs.set(id,{dialog,feedback});
    }
    function showAccountDialog(id,open){
      const {dialog,feedback}=accountDialogs.get(id);
      if(open){usersMessage.textContent='';feedback.textContent='';dialog.showModal();}
      else if(dialog.open)dialog.close();
    }
    function accountMessage(text){
      const active=Array.from(accountDialogs.values()).find(({dialog})=>dialog.open);
      (active?.feedback||usersMessage).textContent=text;
    }
    async function mutateAccount(url,options,onSuccess){
      if(accountBusy)return;
      accountBusy=true;accountMessage('Đang xử lý…');
      const buttons=Array.from($('admin-users').querySelectorAll('button'));
      buttons.forEach(button=>button.disabled=true);
      try{
        const data=await fj(url,options);
        renderUsers(data.users||[]);
        onSuccess?.();accountMessage(data.message||'Đã cập nhật.');
        loadLogs().catch(()=>{});
      }catch(error){accountMessage(error.message);}
      finally{accountBusy=false;buttons.forEach(button=>button.disabled=false);}
    }
    $('user-create-form').addEventListener('submit',event=>{
      event.preventDefault();
      mutateAccount('/api/admin/users',{method:'POST',body:JSON.stringify({username:$('new-username').value.trim(),password:$('new-password').value.trim()})},()=>{$('user-create-form').reset();});
    });
    usersBody.addEventListener('click',event=>{
      const button=event.target.closest('[data-user-action]');
      if(!button||accountBusy)return;
      const id=Number(button.dataset.userId),user=accountUsers.find(item=>Number(item.id)===id);
      if(!user)return;
      if(button.dataset.userAction==='suspend'){
        mutateAccount(`/api/admin/users/${id}/suspend`,{method:'POST'});
      }else if(button.dataset.userAction==='edit'){
        editId=id;showAccountDialog('user-delete-panel',false);deleteId=null;
        $('edit-username').value=user.username;$('edit-password').value='';
        showAccountDialog('user-edit-panel',true);$('edit-username').focus();
      }else if(button.dataset.userAction==='delete'){
        deleteId=id;showAccountDialog('user-edit-panel',false);editId=null;$('edit-password').value='';
        $('user-delete-description').textContent=`Xóa vĩnh viễn tài khoản "${user.username}" và nhật ký của tài khoản? Không thể hoàn tác.`;
        showAccountDialog('user-delete-panel',true);$('user-delete-cancel').focus();
      }
    });
    $('user-edit-cancel').addEventListener('click',()=>{showAccountDialog('user-edit-panel',false);editId=null;$('edit-password').value='';});
    $('user-delete-cancel').addEventListener('click',()=>{showAccountDialog('user-delete-panel',false);deleteId=null;});
    $('user-edit-form').addEventListener('submit',event=>{
      event.preventDefault();if(editId===null)return;
      mutateAccount(`/api/admin/users/${editId}/edit`,{method:'POST',body:JSON.stringify({username:$('edit-username').value.trim(),password:$('edit-password').value.trim()})},()=>{showAccountDialog('user-edit-panel',false);editId=null;$('edit-password').value='';});
    });
    $('user-delete-confirm').addEventListener('click',()=>{
      if(deleteId===null)return;
      mutateAccount(`/api/admin/users/${deleteId}`,{method:'DELETE'},()=>{showAccountDialog('user-delete-panel',false);deleteId=null;});
    });
    $('reload-logs').addEventListener('click',()=>loadLogs().catch(e=>alert(e.message)));
    $('clear-login').addEventListener('click',async()=>{if(!confirm('Xóa toàn bộ lịch sử đăng nhập?'))return;try{const d=await fj('/api/admin/logs',{method:'DELETE',body:JSON.stringify({target:'login'})});await loadLogs();}catch(e){alert(e.message);}});
    $('config-form').addEventListener('submit',async e=>{e.preventDefault();try{const d=await fj('/api/admin/configs',{method:'POST',body:JSON.stringify({telegram_bot_token:$('cfg-token').value.trim(),telegram_chat_id:$('cfg-chat').value.trim(),sensor_sample_interval:Number($('cfg-sample-interval').value)})});alert(d.message||'Đã lưu.');loadLogs();}catch(err){alert(err.message);}});
    const weatherForm=$('weather-config-form'),weatherSelect=$('cfg-weather-city'),weatherMessage=$('weather-config-message');
    if(weatherForm){
      const weatherSave=$('weather-save');
      weatherSave.disabled=true;
      fj('/api/admin/weather-location').then(data=>{
        for(const item of data.locations){const option=document.createElement('option');option.value=item.key;option.textContent=item.name;weatherSelect.append(option);}
        weatherSelect.value=data.city||'';weatherSave.disabled=false;
      }).catch(err=>{weatherMessage.textContent=err.message;});
      weatherForm.addEventListener('submit',async event=>{
        event.preventDefault();weatherSave.disabled=true;weatherMessage.textContent='Đang lưu…';
        try{await fj('/api/admin/weather-location',{method:'POST',body:JSON.stringify({city:weatherSelect.value})});weatherMessage.textContent='Đã lưu địa điểm thời tiết cho hệ thống.';window.dispatchEvent(new Event('weather-location-changed'));}
        catch(err){weatherMessage.textContent=err.message;}
        finally{weatherSave.disabled=false;}
      });
    }
    loadBleNodes().catch(err=>{$('ble-message').textContent=err.message;});
    loadUsers().catch(error=>{accountMessage(error.message);usersBody.innerHTML='<tr><td colspan="6"><div class="empty">Không tải được danh sách tài khoản.</div></td></tr>';});
    loadLogs().catch(()=>{});
    loadConfig().catch(()=>{});
  })();
