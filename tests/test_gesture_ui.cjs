const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/dashboard.js'),'utf8');
const a=source.indexOf('  function applyAI('),b=source.indexOf('  /* ---- lịch sử',a);
assert.ok(a>=0&&b>a);
const el={textContent:''};
const ctx={document:{getElementById:id=>id==='oc-gesture'?el:null,querySelectorAll:()=>[]}};
vm.createContext(ctx);vm.runInContext(source.slice(a,b),ctx);
for(const [status,text] of [['not_detected','Chưa thấy bàn tay'],['unrecognized','Thấy tay, chưa rõ cử chỉ'],['unavailable','Nhận diện tay chưa sẵn sàng'],['stale','Đang chờ kết quả tay mới']]){
 ctx.applyAI({gesture:'—',hand_status:status});assert.ok(el.textContent.includes(text),status+': '+el.textContent);
}
ctx.applyAI({gesture:'Bàn tay mở (5 ngón)',hand_status:'detected'});
assert.match(el.textContent,/Bàn tay mở/);
console.log('PASS: 4 hand diagnostics and recognized gesture rendering');
