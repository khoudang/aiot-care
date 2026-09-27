/* ================= ADMIN ================= */
  (function(){
    const $=id=>document.getElementById(id);
    const usersBody=$('users-body'),loginBody=$('login-body'),auditBody=$('audit-body');
    let loginAll=[],auditAll=[],loginExp=false,auditExp=false;const LIMIT=10;
    async function fj(url,opt={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt});const d=await r.json().catch(()=>({}));if(!r.ok||d.ok===false)throw new Error(d.message||'Lỗi máy chủ.');return d;}
    function fmtSql(v){if(!v)return'--';const d=new Date(String(v).replace(' ','T'));return isNaN(d)?v:d.toLocaleString('vi-VN');}
    function renderUsers(us){
      if(!us||!us.length){usersBody.innerHTML='<tr><td colspan="6"><div class="empty">Chưa có tài khoản nào.</div></td></tr>';return;}
      usersBody.innerHTML=us.map(u=>{
        const rb=u.role==='admin'?'<span class="pill admin"><i class="fas fa-crown"></i> admin</span>':'<span class="pill member"><i class="fas fa-user"></i> member</span>';
        const sus=Number(u.is_suspended)===1;
        const sb=sus?'<span class="pill off"><i class="fas fa-lock"></i> Đã khóa</span>':'<span class="pill on"><i class="fas fa-lock-open"></i> Hoạt động</span>';
        const un=String(u.username).replace(/'/g,"\\'");
        return `<tr class="${sus?'dim':''}"><td>${u.id}</td><td>${u.username}</td><td>${rb}</td><td>${sb}</td><td>${fmtSql(u.created_at)}</td>
          <td><div class="act-group">
            <button class="btn sm" onclick="editUser(${u.id},'${un}')"><i class="fas fa-pen"></i></button>
            <button class="btn sm ${sus?'ok':''}" onclick="toggleSuspend(${u.id})"><i class="fas fa-user-lock"></i> ${sus?'Mở':'Khóa'}</button>
            <button class="btn sm danger" onclick="delUser(${u.id},'${un}')"><i class="fas fa-trash"></i></button>
          </div></td></tr>`;}).join('');
    }
    const loginRow=l=>`<tr><td>${l.id}</td><td>${l.username||('user #'+(l.user_id??''))}</td><td>${l.ip_address||'--'}</td><td>${fmtSql(l.timestamp)}</td></tr>`;
    function paintLogin(){const more=$('login-more');
      if(!loginAll.length){loginBody.innerHTML='<tr><td colspan="4"><div class="empty">Chưa có dữ liệu.</div></td></tr>';more.style.display='none';return;}
      loginBody.innerHTML=(loginExp?loginAll:loginAll.slice(0,LIMIT)).map(loginRow).join('');
      if(loginAll.length>LIMIT){more.style.display='';more.innerHTML=loginExp?'<i class="fas fa-chevron-up"></i> Thu gọn':`<i class="fas fa-chevron-down"></i> Xem thêm (${loginAll.length-LIMIT})`;}else more.style.display='none';}
    function renderLogin(ls){loginAll=ls||[];paintLogin();}
    function isWarn(a){const t=String(a||'').toLowerCase();return t.includes('cảnh báo')||t.includes('gas')||t.includes('cháy')||t.includes('té ngã')||t.includes('khẩn')||t.includes('sức khỏe');}
    const auditRow=l=>{const w=isWarn(l.action);const a=w?`<span class="warn-txt"><i class="fas fa-triangle-exclamation"></i> ${l.action}</span>`:l.action;return `<tr class="${w?'warn-row':''}"><td>${l.id}</td><td>${l.username||(l.user_id?('user #'+l.user_id):'hệ thống')}</td><td>${a}</td><td>${fmtSql(l.timestamp)}</td></tr>`;};
    function paintAudit(){const more=$('audit-more');
      if(!auditAll.length){auditBody.innerHTML='<tr><td colspan="4"><div class="empty">Chưa có dữ liệu.</div></td></tr>';more.style.display='none';return;}
      auditBody.innerHTML=(auditExp?auditAll:auditAll.slice(0,LIMIT)).map(auditRow).join('');
      if(auditAll.length>LIMIT){more.style.display='';more.innerHTML=auditExp?'<i class="fas fa-chevron-up"></i> Thu gọn':`<i class="fas fa-chevron-down"></i> Xem thêm (${auditAll.length-LIMIT})`;}else more.style.display='none';}
    function renderAudit(ls){auditAll=ls||[];paintAudit();}
    async function loadUsers(){usersBody.innerHTML='<tr><td colspan="6"><div class="empty">Đang tải…</div></td></tr>';renderUsers((await fj('/api/admin/users')).users||[]);}
    async function loadLogs(){const d=await fj('/api/admin/logs');renderLogin(d.login_logs||[]);renderAudit(d.audit_logs||[]);}
    async function loadConfig(){const c=(await fj('/api/admin/configs')).configs||{};$('cfg-code').value=c.admin_register_code||'';$('cfg-token').value=c.telegram_bot_token||'';$('cfg-chat').value=c.telegram_chat_id||'';}
    window.editUser=async(id,cur)=>{const u=prompt('Username mới:',cur);if(u===null)return;const un=u.trim();if(!un){alert('Không được để trống.');return;}const p=prompt('Mật khẩu mới (trống nếu giữ nguyên):','');if(p===null)return;try{const d=await fj(`/api/admin/users/${id}/edit`,{method:'POST',body:JSON.stringify({username:un,password:p.trim()})});renderUsers(d.users||[]);loadLogs();alert(d.message||'Đã cập nhật.');}catch(e){alert(e.message);}};
    window.toggleSuspend=async id=>{try{const d=await fj(`/api/admin/users/${id}/suspend`,{method:'POST'});renderUsers(d.users||[]);loadLogs();alert(d.message||'Đã cập nhật.');}catch(e){alert(e.message);}};
    window.delUser=async(id,n)=>{if(!confirm(`Xóa vĩnh viễn tài khoản "${n}"?`))return;try{const d=await fj(`/api/admin/users/${id}`,{method:'DELETE'});renderUsers(d.users||[]);loadLogs();alert(d.message||'Đã xóa.');}catch(e){alert(e.message);}};
    $('reload-users').addEventListener('click',()=>loadUsers().catch(e=>alert(e.message)));
    $('reload-logs').addEventListener('click',()=>loadLogs().catch(e=>alert(e.message)));
    $('reload-audit').addEventListener('click',()=>loadLogs().catch(e=>alert(e.message)));
    $('login-more').addEventListener('click',()=>{loginExp=!loginExp;paintLogin();});
    $('audit-more').addEventListener('click',()=>{auditExp=!auditExp;paintAudit();});
    $('clear-login').addEventListener('click',async()=>{if(!confirm('Xóa toàn bộ lịch sử đăng nhập?'))return;try{const d=await fj('/api/admin/logs',{method:'DELETE',body:JSON.stringify({target:'login'})});loginExp=false;renderLogin(d.login_logs||[]);renderAudit(d.audit_logs||[]);}catch(e){alert(e.message);}});
    $('clear-audit').addEventListener('click',async()=>{if(!confirm('Xóa toàn bộ lịch sử hoạt động & cảnh báo?'))return;try{const d=await fj('/api/admin/logs',{method:'DELETE',body:JSON.stringify({target:'audit'})});auditExp=false;renderAudit(d.audit_logs||[]);renderLogin(d.login_logs||[]);}catch(e){alert(e.message);}});
    $('reload-config').addEventListener('click',()=>loadConfig().catch(e=>alert(e.message)));
    $('config-form').addEventListener('submit',async e=>{e.preventDefault();try{const d=await fj('/api/admin/configs',{method:'POST',body:JSON.stringify({admin_register_code:$('cfg-code').value.trim(),telegram_bot_token:$('cfg-token').value.trim(),telegram_chat_id:$('cfg-chat').value.trim()})});alert(d.message||'Đã lưu.');loadLogs();}catch(err){alert(err.message);}});
    Promise.all([loadUsers(),loadLogs(),loadConfig()]).catch(()=>{usersBody.innerHTML='<tr><td colspan="6"><div class="empty">Không tải được dữ liệu — kiểm tra kết nối máy chủ.</div></td></tr>';});
  })();
