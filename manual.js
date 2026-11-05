'use strict';
const manualEsc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
fetch('/api/state').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(d=>{
  if(d.mode==='public-demo'){
    const note=document.createElement('aside');note.className='trial-notice';
    note.innerHTML='<b>本页正在在线试用环境中打开</b><p>下方为本机版通用手册。在线试用请直接打开本站首页，无须启动本机服务；无需登录，选择“审核”可操作全部环节。你与同事共用测试数据，对方操作后请手动刷新，先保存自己的输入。仅用演示资料；'+(d.ephemeral_storage?'重启或重新部署可能清空测试记录，试用结束前请导出。':'测试记录保存在服务器。')+'邮件仍须手动发送；新审批链接使用本站地址。本机实际 Invoice 不包含在试用站中。</p>';
    document.querySelector('.manual-header').after(note);
    document.querySelectorAll('a[href^="http://127.0.0.1:8766/"]').forEach(a=>{
      const link=new URL(a.href);a.href=link.pathname+link.search+link.hash;
      if(link.searchParams.has('invoice')){a.href='/';a.textContent='返回试用订单列表（本机实际订单未上传）';}
    });
  }
  document.querySelector('#manual-flows').innerHTML=d.production_types.map(type=>`<article><h3>${manualEsc(type)}</h3><p>导入 Invoice → 销售补充制作类型 → ${d.flows[type].map(([name,owner])=>manualEsc(name)+(owner?'（'+manualEsc(owner)+'）':'')).join(' → ')}</p></article>`).join('');
}).catch(()=>{document.querySelector('#manual-flows').textContent='暂时无法读取流程，请返回工作台并检查本地服务。';});
