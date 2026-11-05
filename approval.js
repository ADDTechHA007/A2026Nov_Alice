'use strict';
const escapeApproval=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const approvalContent=document.querySelector('#email-approval-content');
const approvalToken=new URLSearchParams(location.hash.slice(1)).get('token');
async function approvalApi(path,body){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:approvalToken,...body})});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'无法读取审批资料');return data;
}
async function loadEmailApproval(){
  try{
    const d=await approvalApi('/api/email-approval/view',{});
    approvalContent.innerHTML=`<div class="card-title"><h2>${escapeApproval(d.status)}</h2><span class="badge">资料 V${escapeApproval(d.version)}</span></div><p class="helper">指定收件人：${escapeApproval(d.recipient)}<br>有效期至：${escapeApproval(d.expires)}<br>请勿转发此专属链接；持有链接者可代表本次收件人操作。</p><pre class="email-approval-summary">${escapeApproval(d.summary)}</pre><h3>本次邮件附件</h3><p class="helper">资料摘要 approval-summary.txt 及以下文件已随邮件准备，请在邮件中查看附件。</p><ul>${d.attachments.map(a=>`<li>${escapeApproval(a.name)} · ${escapeApproval(a.category)}</li>`).join('')}</ul>${d.actionable?`<form id="email-decision-form"><fieldset><legend>请选择本次审批结果</legend><label class="checkbox"><input type="radio" name="decision" value="approve" required>批准，交接执行并锁定审批资料</label><label class="checkbox"><input type="radio" name="decision" value="return" required>退回补充</label></fieldset><label class="field"><span>审批意见（退回时必填）</span><textarea name="note" rows="4" maxlength="5000" placeholder="填写审批意见或退回原因"></textarea></label><label class="checkbox"><input type="checkbox" name="confirmed" required>我已查看本次资料，确认提交所选结果</label><div class="error" id="decision-error" role="alert"></div><button class="primary" type="submit">确认提交审批结果</button></form>`:`<p class="approval-lock-note">当前链接不能再次审批。${escapeApproval(d.decided)} ${escapeApproval(d.decision_note)}</p>`}`;
  }catch(e){approvalContent.textContent=e.message;}
}
document.addEventListener('change',e=>{
  if(e.target.name==='decision'){
    const note=document.querySelector('[name=note]');note.required=e.target.value==='return';
  }
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='email-decision-form')return;e.preventDefault();
  const form=e.target,values=Object.fromEntries(new FormData(form)),button=form.querySelector('button');
  const error=document.querySelector('#decision-error');error.textContent='';button.disabled=true;
  try{
    const result=await approvalApi('/api/email-approval/decide',{decision:values.decision,note:values.note,confirmed:values.confirmed==='on'});
    await loadEmailApproval();
    const message=document.createElement('p');message.className='approval-lock-note';message.textContent=result.message;approvalContent.prepend(message);
  }catch(err){error.textContent=err.message;button.disabled=false;}
});
loadEmailApproval();
