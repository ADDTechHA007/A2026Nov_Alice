'use strict';

const $ = (q, root = document) => root.querySelector(q);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${({
  bag:'<path d="M5 8h14l1 13H4L5 8Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert:'<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  mail:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
  file:'<path d="M14 2H5v20h14V7l-5-5Z"/><path d="M14 2v6h5M8 13h8M8 17h6"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
  download:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  refresh:'<path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  ship:'<path d="M4 17 2 12l10-4 10 4-2 5M6 10V5h12v5M12 5V2M2 21c2 0 3-2 5-2s3 2 5 2 3-2 5-2 3 2 5 2"/>',
  history:'<path d="M3 12a9 9 0 1 0 3-7L3 8m0-5v5h5m4-1v5l3 2"/>',
  user:'<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
})[name] || ''}</svg>`;
const fmtTime = t => new Date(t).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const fmtSize = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(0)} KB` : `${(n/1048576).toFixed(1)} MB`;
const fmtQty = n => Number(n).toLocaleString('zh-CN');
let data = null, selectedOrder = null, selectedItem = null, section = 'info', filter = 'all', search = '', role = localStorage.getItem('ecobag-demo-role') || '审核';
const entryParams = new URLSearchParams(location.search);
let entryApplied = false;
let importFile = null, importPreview = null;
let toastTimer;
const modal = $('#modal');

function toast(message, error = false) {
  const el = $('#toast');
  el.textContent = message;
  el.className = 'visible' + (error ? ' error-toast' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.className = '', 5000);
}
async function api(path, body) {
  const response = await fetch(path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body, actor:role})} : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作失败，请重试。');
  return result;
}
function currentOrder() {return data?.orders.find(o => o.id === selectedOrder);}
function currentItem() {return currentOrder()?.items.find(i => i.id === selectedItem);}
function items() {return data.orders.flatMap(o => o.items);}
function reviewerTestAccess() {return role==='审核' && data?.test_reviewer_full_access===true;}
function canActAs(...roles) {return reviewerTestAccess() || roles.includes(role);}
function isMine(i) {return i.owner===role || reviewerTestAccess() && i.status!=='已完成';}
function isMissing(i) {return i.status === '制作类型待补充' || i.status === '待补资料' && i.missing.length > 0;}
function badge(status) {
  const color = status === '已完成' ? 'green' : status === '老板审批' || status === '财务审核' ? 'amber' : status === '待补资料' ? 'red' : 'blue';
  return `<span class="badge ${color}">${esc(status)}</span>`;
}
function matches(i) {
  return filter === 'all' || filter === 'mine' && isMine(i) || filter === 'missing' && isMissing(i) || filter === 'boss' && i.status === '老板审批';
}
function visibleOrders() {
  const q = search.trim().toLowerCase();
  return data.orders.filter(o => o.items.some(matches) && (!q || `${o.invoice} ${o.customer} ${o.sales} ${o.items.map(i => i.name).join(' ')}`.toLowerCase().includes(q)));
}
async function load() {
  data = await api('/api/state');
  if (!data.roles.includes(role)) role = '审核';
  if (!entryApplied && entryParams.get('invoice')) {
    const entry = data.orders.find(o=>o.invoice===entryParams.get('invoice'));
    if(entry){selectedOrder=entry.id;selectedItem=entry.items[0]?.id;section=entryParams.get('tab')==='sources'?'sources':'info';}
    entryApplied=true;
  }
  render();
}
function render() {
  const visible = visibleOrders();
  if (!visible.some(o => o.id === selectedOrder)) {
    selectedOrder = visible[0]?.id;
    selectedItem = visible[0]?.items.find(matches)?.id;
  }
  const order = currentOrder();
  if (order && !order.items.some(i => i.id === selectedItem)) selectedItem = order.items.find(matches)?.id || order.items[0].id;
  const counts = {all:items().filter(i=>i.status!=='已完成').length, mine:items().filter(i=>isMine(i)).length, missing:items().filter(isMissing).length, boss:items().filter(i=>i.status==='老板审批').length};
  const navs = [['all','grid','全部订单'],['mine','clock','我的待办'],['missing','alert','待补资料'],['boss','shield','等待老板']];
  $('#app').innerHTML = `<div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark">${icon('bag')}</div><div><b>EcoBag</b><small>ORDER WORKSPACE</small></div></div>
      <div class="nav-title">订单协作</div>
      <nav aria-label="工作台导航">${navs.map(([f,ic,label])=>`<button class="nav-btn ${filter===f?'active':''}" data-filter="${f}" title="${label}">${icon(ic)}<span>${label}</span><span class="count">${counts[f]}</span></button>`).join('')}</nav>
      <a class="manual-link" href="/manual.html" target="_blank">${icon('file')}<span>工作台手册</span></a>
      <a class="export-link" href="/api/backup" download>${icon('download')}<span>导出订单与附件</span></a>
      <div class="sidebar-note"><b>一张订单，一个档案</b><br>资料产生时归档<br>交接发生时留痕<br><br><small>${data.mode==='public-demo'?'在线协作测试 · 共用测试数据':'本地原型 · 数据保存在本机'}</small></div>
    </aside>
    <main class="main">
      <header class="header"><div><div class="eyebrow">OPERATIONS / 订单协作</div><h1>订单审核工作台</h1></div>
        <div class="header-actions"><label class="role-control">${icon('user')} 演示角色 <select id="role" aria-label="演示角色">${data.roles.map(r=>`<option ${r===role?'selected':''}>${r}</option>`).join('')}</select></label>
          <a class="manual-top" href="/manual.html" target="_blank">工作台手册</a><button class="icon-only" data-action="refresh" title="刷新资料" aria-label="刷新资料">${icon('refresh')}</button><button class="primary" data-action="import-invoice" ${!canActAs('销售','财务')?'disabled':''}>${icon('upload')} 导入 Invoice</button><button class="small" data-action="new-order" ${!canActAs('销售')?'disabled':''}>手动录入</button></div></header>
      <p class="intro">把资料、邮件和审批放在一起，让每一笔订单的下一步都清楚。</p>
      ${data.mode==='public-demo'?`<div class="trial-notice" role="note"><b>在线试用 · 无需登录 · 请选择“审核”操作全部环节</b><p>你与同事共用测试订单；持有网址的人均可查看、修改和导出。仅用演示资料。对方操作后，点右上角“刷新资料”查看更新，先保存自己的输入。${data.ephemeral_storage?'服务重启或重新部署后测试记录可能清空，结束前请“导出订单与附件”。':''}</p></div>`:''}
      <div class="notice"><span class="dot"></span><span>${data.test_reviewer_full_access?'测试模式：审核角色可操作全部环节，操作仍记录为“审核”；资料校验和流程顺序仍生效。':'先导入 Invoice，再由销售逐项补充制作类型。'}支持 QuickBooks PDF / XLS / CSV 文件导入，QuickBooks / Yahoo 尚未连接；邮件只生成草稿。</span></div>
      <div class="stats">
        ${[['all','处理中产品',counts.all,'按产品分别推进','grid'],['mine','我的待办',counts.mine,`当前角色：${role}`,'clock'],['missing','资料尚未齐全',counts.missing,'缺项交给对应负责人','alert'],['boss','等待老板审批',counts.boss,'资料已审，可集中批准','shield']].map(([f,label,n,hint,ic])=>`<button class="stat ${filter===f?'active':''}" data-filter="${f}"><span class="stat-label">${label}<span class="stat-icon">${icon(ic)}</span></span><strong>${n.toString().padStart(2,'0')}</strong><small>${esc(hint)}</small></button>`).join('')}
      </div>
      <div class="workspace"><aside class="order-panel"><div class="panel-header"><h3>订单档案</h3><span class="badge">${visible.length} 笔</span></div>
        <div class="search">${icon('search')}<input id="search" placeholder="搜索 Invoice、客户或产品" aria-label="搜索订单" value="${esc(search)}"></div>
        <div class="filter-hint">${esc(navs.find(n=>n[0]===filter)[2])} · 点击订单查看完整档案</div>
        <div class="order-list">${visible.length ? visible.map(orderCard).join('') : '<div class="list-empty">当前没有符合条件的订单。<br>可切换“全部订单”或清空搜索。</div>'}</div>
      </aside><section class="detail" aria-label="订单详情">${order ? orderDetail(order) : '<div class="empty">'+icon('check')+'当前队列已处理完毕。<br>切换角色或查看全部订单。</div>'}</section></div>
    </main></div>`;
}
function orderCard(o) {
  const complete = o.items.filter(i=>i.status==='已完成').length;
  const text = complete===o.items.length?'全部完成':complete?'部分完成':'处理中';
  return `<button class="order-card ${o.id===selectedOrder?'selected':''}" data-order="${o.id}"><div class="order-top"><b>${esc(o.invoice)}</b><span class="badge ${complete===o.items.length?'green':''}">${text}</span></div><div class="order-client">${esc(o.customer)}</div><div class="mini-progress">${o.items.map(i=>`<span class="${i.status==='已完成'?'done':i.stage>0?'moving':''}"></span>`).join('')}</div><div class="order-foot"><span>${o.items.length} 个产品 · ${complete} 已完成</span><span>${o.due?esc(o.due.slice(5))+' 交货':'交货日期待确认'}</span></div></button>`;
}
function orderDetail(o) {
  const i = currentItem();
  return `<div class="detail-head"><div class="order-title-row"><h2>${esc(o.invoice)} <span class="badge">Invoice 档案</span></h2><small>${esc(o.customer)}</small></div>
    <div class="detail-meta"><span>销售：${esc(o.sales)}</span><span>要求交货：${esc(o.due||'待确认')}</span><span>产品数：${o.items.length}</span>${o.source?'<span>实际资料导入 · '+esc(o.source.invoice_date)+'</span>':''}</div>
    ${o.source?invoiceSummary(o):''}
    <div class="product-tabs" aria-label="产品明细">${o.items.map(p=>`<button class="product-tab ${routeTone(p.route)} ${p.id===selectedItem?'active':''}" data-item="${p.id}"><b>${esc(p.name)}</b><small><span>${routeBadge(p.route)} · ${fmtQty(p.qty)} 个</span><span>${esc(p.status)}</span></small></button>`).join('')}</div></div>
    <div class="detail-body"><div class="item-heading"><div><h3>${esc(i.name)}</h3><small>${esc(i.code)} · ${routeBadge(i.route)} · 资料 V${i.version}</small></div>${badge(i.status)}</div>
    <div class="route" aria-label="产品流程">${i.flow.map(([name],n)=>`<div class="step ${n<i.stage?'done':n===i.stage?'current':''}"><div class="step-dot"></div>${name}</div>`).join('')}</div>
    <div class="section-tabs" role="tablist">${[['info','资料与进度','file'],...(o.source?[['sources','Invoice 与来源','file']]:[]),['mail','邮件档案','mail'],['shipping','海运批次','ship'],['history','操作历史','history']].map(([tab,label,ic])=>`<button role="tab" aria-selected="${section===tab}" class="${section===tab?'active':''}" data-section="${tab}">${icon(ic)}${label}${tab==='mail'&&i.messages.length?' · '+i.messages.length:''}</button>`).join('')}</div>
    ${section==='info'?infoPanel(i):section==='sources'&&o.source?sourcesPanel(o):section==='mail'?mailPanel(i):section==='shipping'?shippingPanel(i):historyPanel(o,i)}
    </div>`;
}
function field(label, name, value, type='text', disabled=false, wide=false, extra='') {
  return `<label class="field ${wide?'wide':''}"><span>${esc(label)}</span>${type==='textarea'?`<textarea name="${name}" rows="3" ${disabled?'disabled':''}>${esc(value)}</textarea>`:`<input type="${type}" name="${name}" value="${esc(value)}" ${disabled?'disabled':''} ${extra}>`}</label>`;
}
function salesMoney(value) {return value===null||value===undefined?'待确认':'$'+Number(value).toLocaleString('en-CA',{minimumFractionDigits:2,maximumFractionDigits:2});}
function invoiceSummary(o) {
  const s=o.source;
  return `<div class="invoice-summary"><div><small>导入 Invoice 未税销售额</small><strong>${salesMoney(s.subtotal)}</strong></div><div><small>${esc(s.tax_label)}</small><strong>${salesMoney(s.tax_amount)}</strong></div><div><small>含税总额（导入时）</small><strong>${salesMoney(s.total)}</strong></div><div><small>付款到期日</small><strong>${esc(s.payment_due||'待确认')}</strong></div></div><div class="invoice-summary-note">${esc(s.currency_note)} · 制作类型由销售逐项确认 · <button class="text-button" data-section="sources">查看原始 Invoice 与截图</button></div>`;
}
function sourcesPanel(o) {
  const s=o.source;
  const imgs=o.source_documents.filter(d=>d.mime.startsWith('image/'));
  return `<div class="card-title"><h3>原始 Invoice 与核对资料</h3><span class="badge green">${s.lines.length} 项产品 · 行金额已核对</span></div><p class="helper">当前规则：制作类型由销售选择。以下资料保留导入时点原文，后续规则调整和确认见“操作历史”。</p>
    <div class="source-contact-grid"><div class="source-contact"><small>客户与联系方式</small><h3>${esc(o.customer)}</h3><p>${esc(s.contact)}<br>${esc(s.customer_email)}</p><small>发票日期：${esc(s.invoice_date||'待确认')}</small>${s.source_format==='pdf'?`<p class="preserve-lines">Bill to：\n${esc(s.bill_to)}</p>`:''}</div><div class="source-contact"><small>Ship to · 来源文件收货地址</small><p class="preserve-lines">${esc(s.ship_to)}</p>${s.source_format==='pdf'?`<p>原发货日期：${esc(s.shipping_date||s.pdf_extracted?.shipping_date_raw||'未显示')}<br>Ship via：${esc(s.ship_via||'未显示')}<br>Tracking：${esc(s.tracking_no||'未显示')}<br>REP：${esc(s.rep||'未显示')}<br>PO：${esc(s.po||'未显示')}</p><small>仅保留原发票字段，不自动生成运输批次或确认发货。</small>`:''}</div></div>
    <div class="source-table-wrap"><table class="source-table"><thead><tr><th>产品 / 原始 SKU</th><th>原数量</th><th>销售单价</th><th>未税金额</th><th>税码</th></tr></thead><tbody>${s.lines.map(i=>`<tr><td><b>${esc(i.name)}</b><small>${esc(i.product_service)}</small></td><td>${fmtQty(i.qty)}</td><td>${salesMoney(i.sales_rate)}</td><td>${salesMoney(i.sales_amount)}</td><td>${esc(i.tax_code)}</td></tr>`).join('')}</tbody></table></div>
    <div class="source-reconciliation"><h3>金额核对</h3>${s.reconciliation.map(t=>`<p>${icon('check')}${esc(t)}</p>`).join('')}<small>${s.snapshot_balance_due?'来源时点应收余额：'+salesMoney(s.snapshot_balance_due)+'；':''}当前付款状态仍需财务核实。${s.source_format==='pdf'?'合计和税额保留 PDF 原值，已与明细核对。':'税率人工填写时，合计仅为按该税率计算的结果。'}</small></div>
    <div class="source-pending"><h3>导入时未确认的事项</h3><ul>${s.pending.map(p=>`<li>${esc(p)}</li>`).join('')}</ul><p>履行方式依据：${esc(s.route_basis)}</p><p class="preserve-lines">来源可见付款条款：${esc(s.terms_visible||'未显示')}${s.terms_visible&&!s.terms_complete?'（原文未完整显示）':''}</p></div>
    <div class="card-title" style="margin-top:22px"><h3>订单共用来源文件 · ${o.source_documents.length}</h3><small>所有产品共用，不重复上传</small></div>
    ${o.source_documents.map(d=>`<div class="doc">${icon('file')}<div class="doc-info"><a href="/api/order-document/${d.id}" download>${esc(d.name)}</a><small>${esc(d.category)} · ${fmtSize(d.size)} · 导入时保留原文件</small></div>${d.mime.startsWith('image/')?`<button class="small" data-source-image="${d.id}">预览</button>`:''}</div>`).join('')}
    <div class="source-images">${imgs.map(d=>`<button class="source-image-card" data-source-image="${d.id}"><img src="/api/order-image/${d.id}" alt="${esc(d.category)}" loading="lazy"><span>${esc(d.category)} · 点击放大</span></button>`).join('')}</div>
    <p class="helper">产品及售价来源：${esc(s.provenance?.lines)}。客户与日期来源：${esc(s.provenance?.customer_and_dates)}。导入不代表库存、付款、审批或出库完成。</p>`;
}
function routeTone(route) {return ({'国内定制':'route-custom','本地直发':'route-stock','本地加工':'route-processing'})[route]||'route-unclassified';}
function routeLabel(route) {return route==='本地直发'?'本地库存直发':route==='本地加工'?'本地库存加工':route;}
function routeBadge(route) {return `<span class="badge route-badge ${routeTone(route)}">${esc(routeLabel(route))}</span>`;}
function productionPanel(i) {
  const canChange=!i.approval_locked&&canActAs('销售')&&['制作类型待补充','待补资料','财务审核','老板审批','库存预留'].includes(i.status)&&!i.messages.some(m=>JSON.parse(m.snapshot).kind!=='approval')&&!i.shipments.length;
  const o=currentOrder();
  return `<div class="production-panel"><div class="card-title"><h3>${i.route==='制作类型待补充'?'制作类型待补充':'已确认的制作类型'}</h3>${routeBadge(i.route)}</div><p>每个产品单独选择。请按实际履行安排填写；尚未确认时保留“制作类型待补充”，不要猜选。<a href="/manual.html#types" target="_blank" rel="noopener">查看填写手册</a></p>
    <div class="production-guide" aria-label="制作类型填写说明">
      <article data-production-route="国内定制" class="${i.route==='国内定制'?'is-selected':''}"><h4>国内定制</h4><p>需要向国内工厂采购、定制或生产。</p><small>备注可填：工厂名称、规格/图稿版本、预计生产及海运安排、待确认事项。</small></article>
      <article data-production-route="本地直发" class="${i.route==='本地直发'?'is-selected':''}"><h4>本地库存直发</h4><p>使用本地库存，无须印刷或加工，直接发货。</p><small>备注可填：仓库、库存是否已核实、提货或配送方式、预计发货时间。</small></article>
      <article data-production-route="本地加工" class="${i.route==='本地加工'?'is-selected':''}"><h4>本地库存加工</h4><p>使用本地库存，还需要本地印刷或其他加工。</p><small>备注可填：加工商、加工内容、图稿版本、库存状态、预计加工及发货时间。</small></article>
    </div><form id="production-form"><div class="form-grid">${field('销售负责人（整张订单共用）','sales',o.sales==='待确认'?'':o.sales,'text',!canChange||o.sales_locked,false,'required maxlength="100"')}<label class="field"><span>制作类型（逐项填写）</span><select name="route" class="${routeTone(i.route)}" required ${canChange?'':'disabled'}><option value="">请选择制作类型</option>${data.production_types.map(t=>`<option class="${routeTone(t)}" value="${t}" ${i.route===t?'selected':''}>${t==='本地直发'?'本地库存直发':t==='本地加工'?'本地库存加工':t}</option>`).join('')}</select></label>
    <label class="field wide"><span>制作备注（按产品保存，可选）</span><textarea name="production_notes" rows="4" maxlength="5000" aria-describedby="production-notes-help" placeholder="示例：本地白色袋需单面黑色 Logo 印刷；加工商待确认；库存待仓库核实；希望 11 月 20 日前发货。" ${canChange?'':'disabled'}>${esc(i.production_notes||'')}</textarea><small id="production-notes-help">写明已确认的安排、特殊要求和待确认的问题。未知事项写“待确认”；报价、图稿及凭证请另行上传附件。备注不能代替库存确认或审批。</small></label>
    ${i.route!=='制作类型待补充'?field('更改类型原因（更改已选类型时必填）','note','','text',!canChange,true,'maxlength="5000" placeholder="例如：客户新增印刷要求，由库存直发改为本地加工"'):''}</div><div class="production-footer"><small>${i.approval_locked?'老板已批准：制作类型、制作备注及审批信息已锁定。':i.route==='制作类型待补充'?'选择前由销售负责，不能推进或生成业务邮件。':'更改类型将回到新流程起点，旧审核和审批保留；进入执行后不可直接更改。仅修改备注不改变当前节点；实际规格变更请在下方执行资料中登记。'}</small><button class="primary small" type="submit" ${canChange?'':'disabled'}>保存制作类型</button></div></form></div>`;
}
function infoPanel(i) {
  const sharedDocs=currentOrder().source_documents||[];
  const notesEditable = canActAs('销售','跟单')&&i.status!=='已完成';
  const editable = notesEditable&&!i.approval_locked;
  const cats = i.route==='国内定制'?['图稿/规格','工厂报价']:i.route==='本地加工'?['图稿/规格','加工说明']:[];
  const gaps = i.missing;
  const optionalGaps=i.optional_missing||[];
  const uploadable = canActAs('销售','跟单','财务','仓库','物流')&&i.status!=='已完成';
  const check = (label, ok) => `<div class="check-row ${ok?'':'missing'}">${icon(ok?'check':'alert')}<span>${esc(label)}${ok?'已登记':'待补充'}</span></div>`;
  return `${productionPanel(i)}${i.invoice_line?`<div class="sales-reference"><div><small>原始 Product / Service</small><strong>${esc(i.invoice_line.product_service)}</strong></div><div><small>Invoice 销售单价</small><strong>${salesMoney(i.invoice_line.sales_rate)}</strong></div><div><small>Invoice 销售金额（未税）</small><strong>${salesMoney(i.invoice_line.sales_amount)}</strong></div><p>售价来自原始 Invoice。采购 / 库存成本另行登记；原始资料见“Invoice 与来源”。</p></div>`:''}<div class="info-grid"><form id="item-form"><div class="card-title"><h3>产品与执行资料</h3>${notesEditable?'<button type="submit" class="small">'+(i.approval_locked?'保存执行备注':'保存修改')+'</button>':'<small>当前角色查看资料</small>'}</div>
    ${i.approval_locked?'<p class="approval-lock-note">老板已批准 · 前置信息已锁定。后续可补充执行备注、工厂确认、付款及运输凭证。</p>':''}<div class="form-grid">${field('产品名称','name',i.name,'text',!editable,true)}${field('订购数量','qty',i.qty,'number',!editable,false,'min="1" step="1" required')}${field('要求交货（未知可留空）','due',i.due,'date',!editable)}
    ${field('工厂 / 加工商 / 仓库','supplier',i.supplier,'text',!editable,true)}${field('收件邮箱','recipient',i.recipient,'email',!editable,true)}
    ${field('采购 / 加工单价','unit_cost',i.unit_cost,'number',!editable,false,'min="0" step="0.0001" required')}
    <label class="field"><span>币种</span><select name="currency" ${!editable?'disabled':''}>${['CAD','USD','CNY'].map(c=>`<option ${c===i.currency?'selected':''}>${c}</option>`).join('')}</select></label>
    ${field('规格 / 加工要求','spec',i.spec,'textarea',!editable,true)}${field('执行备注','notes',i.notes,'textarea',!notesEditable,true)}</div>
    <p class="helper">采购 / 加工金额：${i.unit_cost>0?esc(i.currency)+' '+Number(i.qty*i.unit_cost).toLocaleString('zh-CN',{maximumFractionDigits:2}):'待登记'}。${i.approval_locked?'审批信息已锁定，执行备注单独留痕。':'审批前关键资料变更后，重新提交审核；原记录保留。'}</p></form>
    <aside class="check-panel"><div class="card-title"><h3>审核资料清单</h3><span class="badge ${gaps.length?'amber':'green'}">${gaps.length?'必填缺 '+gaps.length+' 项':optionalGaps.length?'必填已齐 · 可选未附 '+optionalGaps.length+' 项':i.route==='本地直发'?'规格已登记':'资料已齐'}</span></div><p class="helper" id="execution-save-status" role="status">清单按已保存资料检查。${editable?'填写后可点“保存修改”；提交审核也会先保存当前填写内容。':''}</p>
    <div class="checks">${check('制作类型',i.route!=='制作类型待补充')}${check('产品规格',!!i.spec)}${!['本地直发','制作类型待补充'].includes(i.route)?check('工厂 / 加工商',!!i.supplier)+check('收件邮箱',!!i.recipient)+check('采购 / 加工单价',i.unit_cost>0):''}${cats.map(c=>['图稿/规格','工厂报价'].includes(c)?`<div class="check-row"><span>${esc(c)}（可选）· ${i.documents.some(d=>d.category===c)?'已上传':'未附，提交时提醒'}</span></div>`:check(c,i.documents.some(d=>d.category===c))).join('')}</div>
    <div class="doc-list"><div class="card-title"><h3>归档附件 · ${i.documents.length+sharedDocs.length}</h3><button class="small" data-action="upload" ${uploadable?'':'disabled'}>${icon('plus')} 添加</button></div>
    ${cats.length?`<p class="helper">图稿/规格、工厂报价为可选附件，未附可在提交提醒中确认继续。本地加工的加工说明仍为必填附件。上传时请选择对应类别。</p>`:''}
    ${i.documents.map(d=>`<div class="doc">${icon('file')}<div class="doc-info"><a href="/api/document/${d.id}" download>${esc(d.name)}</a><small>${esc(d.category)} · ${fmtSize(d.size)} · ${esc(d.actor)}</small></div></div>`).join('')}
    ${sharedDocs.map(d=>`<div class="doc">${icon('file')}<div class="doc-info"><a href="/api/order-document/${d.id}" download>${esc(d.name)}</a><small>订单共用 · ${esc(d.category)} · ${fmtSize(d.size)}</small></div>${d.mime.startsWith('image/')?`<button class="small" data-source-image="${d.id}">预览</button>`:''}</div>`).join('')}
    ${!i.documents.length&&!sharedDocs.length?'<div class="empty">尚未上传资料<br>添加文件后，审核人员可直接下载。</div>':''}
    </div></aside></div>${actionPanel(i)}`;
}
function actionLabel(i) {
  return ({'待补资料':'资料齐全，提交审核','财务审核':'审核通过，交老板审批','老板审批':'批准，交接执行','待下单':'已手动发送，等待工厂确认','等工厂确认':'确认工厂已接单','生产中':'生产完成，交接物流','待海运':'进入海运跟踪','海运中':'全部到货，完成产品','库存预留':'库存已预留，准备发货','待发货':'确认已发货，完成产品','待送加工':'确认已送加工','加工中':'加工验收完成，准备发货'})[i.status]||'完成节点';
}
function actionPanel(i) {
  if(i.route==='制作类型待补充')return '<div class="action-box"><h3>当前负责人：销售</h3><p class="helper">请在上方补充销售负责人和制作类型。保存后，本地直发交仓库预留库存；国内定制和本地加工进入待补资料。</p></div>';
  if(i.status==='已完成') return `<div class="completed">${icon('check')} 此产品已完成。邮件、附件和审批历史已保留。</div>`;
  const allowed = canActAs(i.owner);
  return `<div class="action-box"><h3><span>当前交接：${esc(i.status)}</span><span class="badge">负责人：${esc(i.owner)}</span></h3>
    <textarea id="action-note" placeholder="填写交接说明、审核意见或需要补充的问题…" aria-label="操作说明"></textarea>
    <div class="action-buttons"><button class="small ghost" data-action="comment">${icon('plus')} 留下备注</button><div>
    ${i.status==='老板审批'?`<button class="small" data-action="reissue-boss-approval" ${allowed?'':'disabled'}>重新准备老板审批邮件</button>`:''}
    ${['财务审核','老板审批'].includes(i.status)?`<button class="small danger" data-action="return" ${allowed?'':'disabled'}>退回补充</button>`:''}
    <button class="primary small" data-action="next" ${allowed?'':'disabled'}>${actionLabel(i)} ${icon('arrow')}</button></div></div>
    ${!allowed?`<p class="helper">当前等待${esc(i.owner)}处理。可在右上角切换演示角色体验对应操作。</p>`:''}</div>`;
}
function mailPanel(i) {
  const allowed = i.route!=='制作类型待补充' && canActAs('销售','跟单','物流') && (i.route==='本地直发'||i.stage>=3) && i.status!=='已完成';
  return `<div class="card-title"><h3>从工作台生成业务邮件</h3><button class="primary small" data-action="compose" ${allowed?'':'disabled'}>${icon('mail')} 生成邮件草稿</button></div>
    <p class="helper" style="margin:0 0 17px">正文、选中的附件和产品版本一起留档。下载 .eml 后手动发送；本版不接收邮箱回复，可将回复文件作为附件归档。${i.route!=='本地直发'&&i.stage<3?'下单邮件需先通过老板审批。':''}</p>
    ${i.messages.length?i.messages.map(m=>{const s=JSON.parse(m.snapshot);return `<article class="mail-card"><div class="topline"><span class="badge amber">${s.kind==='approval'?'审批邮件 · 草稿归档':'草稿归档 · 未自动发送'}</span><small>${fmtTime(m.created)} · ${esc(m.actor)}</small></div><h3>${esc(m.subject)}</h3>${s.email_approval_id?`<p class="helper">邮件审批结果：${esc(({'approved':'已批准','returned':'已退回','superseded':'已被新申请替代'})[(i.email_approvals||[]).find(a=>a.id===s.email_approval_id)?.status]||'等待处理或已失效，点击刷新资料更新')}</p>`:''}<small>收件人：${esc(m.recipient)} · 产品 V${s.version} · 附件 ${s.documents.length+(s.generated_attachments?.length||0)} 个</small><pre>${esc(m.body)}</pre>${s.documents.map(d=>`<div class="doc">${icon('file')}<a href="/api/${d.source==='order'?'order-document':'document'}/${d.id}" download>${esc(d.name)}</a></div>`).join('')}<div style="margin-top:12px"><a class="badge green" href="/api/message/${m.id}" download>${icon('download')} 下载原始邮件 .eml</a></div></article>`;}).join(''):'<div class="empty">'+icon('mail')+'还没有邮件档案。<br>完成审批后，从这里生成第一封下单邮件。</div>'}`;
}
function shippingPanel(i) {
  if(i.route!=='国内定制')return `<div class="empty">${icon('ship')}此产品采用${esc(i.route)}，无需登记海运。<br>本地发货凭证在“资料与进度”中归档。</div>`;
  const shipped=i.shipments.reduce((s,b)=>s+b.qty,0),arrived=i.shipments.filter(b=>b.status==='已到货').reduce((s,b)=>s+b.qty,0);
  const allowed=canActAs('物流')&&['待海运','海运中'].includes(i.status);
  return `<div class="card-title"><h3>同一产品，可分批装运</h3><button class="small primary" data-action="new-shipment" ${allowed&&shipped<i.qty?'':'disabled'}>${icon('plus')} 登记海运批次</button></div>
    <div class="shipping-summary"><div><small>尚未装运</small><strong>${fmtQty(i.qty-shipped)}</strong></div><div><small>海运中</small><strong>${fmtQty(shipped-arrived)}</strong></div><div><small>已到货</small><strong>${fmtQty(arrived)}</strong></div></div>
    ${i.shipments.length?i.shipments.map(b=>`<article class="shipment-card"><div class="topline"><h3>${fmtQty(b.qty)} 个 · ${esc(b.vessel)}</h3>${badge(b.status)}</div><div class="shipment-fields">${[['航次',b.voyage],['提单号',b.bl],['开船日期',b.etd],['预计到港',b.eta]].map(([k,v])=>`<div><small>${k}</small><b>${esc(v)}</b></div>`).join('')}</div>${b.status==='海运中'?`<button style="margin-top:15px" class="small" data-arrive="${b.id}" ${allowed?'':'disabled'}>确认该批次已到货</button>`:''}</article>`).join(''):'<div class="empty">'+icon('ship')+'尚未登记海运批次。</div>'}<p class="helper">本版按产品登记海运批次；全部数量到货后，才能完成该产品。跨订单合并装柜留待后续扩展。</p>`;
}
function historyPanel(o,i) {
  const events=o.events.filter(e=>!e.item_id||e.item_id===i.id);
  return `<div class="card-title"><h3>此产品的操作历史</h3><small>${events.length} 条记录 · 不覆盖旧记录</small></div><div class="timeline">${events.map(e=>`<article class="event"><div class="event-title"><b>${esc(e.action)} <span class="badge">${esc(e.actor)}</span></b><small>${fmtTime(e.created)}</small></div><p>${esc(e.detail)}</p>${e.snapshot!=='{}'?`<details><summary>查看当时的数据及依据</summary><pre>${esc(JSON.stringify(JSON.parse(e.snapshot),null,2))}</pre></details>`:''}</article>`).join('')}</div>`;
}
function showModal(title, content, footer = '') {
  modal.innerHTML=`<div class="modal-head"><h2>${esc(title)}</h2><button class="small ghost" data-action="close" aria-label="关闭弹窗">${icon('close')}</button></div>${content}${footer}`;
  if(!modal.open) modal.showModal();
}
function footer(text, form) {return `<div class="modal-footer"><button data-action="close">取消</button><button class="primary" type="submit" form="${form}">${text}</button></div>`;}
function lineRow() {return `<div class="new-line"><input name="line-name" placeholder="产品名称" aria-label="产品名称" required maxlength="200"><input name="line-qty" type="number" min="1" step="1" value="100" aria-label="产品数量" required><span class="badge amber">制作类型待补充</span><button type="button" data-action="remove-line" aria-label="删除产品">${icon('close')}</button></div>`;}
function newOrder() {
  showModal('手动录入 Invoice',`<form id="new-order-form" class="modal-body"><p>没有产品导出文件时可手动录入。建立后，每项产品仍须由销售补充制作类型；本次操作不写入 QuickBooks。</p><div class="form-grid">${field('QuickBooks Invoice 编号','invoice','','text',false,false,'required maxlength="100" placeholder="例如 10028"')}${field('客户名称','customer','','text',false,false,'required maxlength="200"')}${field('销售负责人（可稍后填写）','sales','','text',false,false,'maxlength="100"')}${field('要求交货日期（可留空）','due','','date')}</div><div class="line-labels"><span>产品</span><span>数量</span><span>制作类型</span></div><div id="new-lines">${lineRow()}</div><button type="button" class="small" data-action="add-line">${icon('plus')} 添加产品</button><div class="error" id="modal-error"></div></form>`,footer('建立档案','new-order-form'));
}
function importModal() {
  importFile=null;importPreview=null;
  showModal('第一步 · 导入 Invoice',`<form id="import-form" class="modal-body">
    <p>上传 QuickBooks 原始 Invoice PDF，自动提取抬头、日期和产品，核对后确认；也保留产品明细 XLS / UTF-8 CSV 导入。制作类型由销售逐项填写。</p>
    <div class="form-grid"><label class="field wide"><span>Invoice 文件（PDF / XLS / CSV，最大10MB）</span><input id="invoice-file" type="file" accept=".pdf,.xls,.csv" required></label>
      <label class="field wide" id="pdf-date-control" hidden><span>PDF 日期格式（按 QuickBooks 实际设置选择）</span><select name="pdf_date_order"><option value="">未确认，先读取查看</option><option value="dmy">日/月/年：05/11/2026 = 2026年11月5日</option><option value="mdy">月/日/年：05/11/2026 = 2026年5月11日</option></select></label>
      <div class="wide"><button type="button" data-action="preview-import">读取并预览产品</button></div></div>
    <div id="import-preview"></div><div class="form-grid" style="margin-top:18px">
      ${field('Invoice 编号','invoice','','text',false,false,'required maxlength="100"')}${field('客户名称（请核对）','customer','','text',false,false,'required maxlength="200"')}
      ${field('发票日期（可留空）','invoice_date','','date')}${field('付款到期日（不是交货日）','payment_due','','date')}
      <label class="field"><span>销售币种</span><select name="currency"><option value="">待确认</option><option>CAD</option><option>USD</option><option>CNY</option></select></label>
      ${field('统一销售税率 %（未知留空）','tax_rate','','number',false,false,'min="0" max="100" step="0.01" placeholder="例如 13"')}
      <label class="field wide"><span>其他来源附件（可选，最多5个；总文件量20MB）</span><input name="attachments" type="file" multiple></label></div>
    <p class="helper">PDF 仅支持可复制文字的 QuickBooks 同版式发票，扫描件和截图不自动识别。PDF 税额、总额保留原值并核对；币种未显示时留待确认。不会用销售价代替成本，也不会自动确认库存、付款或发货。</p>
    <label class="checkbox" id="pdf-review-control" hidden><input name="confirm_pdf_review" type="checkbox" disabled required>我已核对 PDF 原件、抬头、日期、数量和所有提示，确认按数量栏导入。</label>
    <div class="error" id="modal-error"></div></form>`,footer('确认导入，交销售补充','import-form'));
}
function showImportPreview() {
  const p=importPreview,x=p.extracted;
  $('#import-preview').innerHTML=`<div class="import-result"><h3>${p.lines.length} 项产品 · 未税合计 ${salesMoney(p.subtotal)}</h3>${p.lines.map(l=>`<p>${esc(l.name)} · ${fmtQty(l.qty)} 个 · ${salesMoney(l.sales_rate)} / 个</p>`).join('')}${x?`<p>PDF 税额 ${salesMoney(x.tax_amount)} · 总额 ${salesMoney(x.total)}</p><details open><summary>识别到的发票资料（请核对）</summary><p>编号：${esc(x.invoice)}<br>发票原日期：${esc(x.invoice_date_raw)}<br>销售 REP：${esc(x.rep||'未显示')}</p><p class="preserve-lines">Bill to：\n${esc(x.bill_to)}\n\nShip to：\n${esc(x.ship_to)}\n\n付款条款：\n${esc(x.terms||'未显示')}</p><p>Ship date：${esc(x.shipping_date_raw||'未显示')} · Ship via：${esc(x.ship_via||'未显示')}<br>Tracking：${esc(x.tracking_no||'未显示')} · PO：${esc(x.po||'未显示')}</p></details><div class="pdf-import-warnings"><b>导入前核对</b><ul>${p.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:''}<span class="badge amber">全部产品：制作类型待补充</span></div>`;
  for(const name of ['invoice','customer','invoice_date','payment_due','currency','tax_rate']){
    const input=$(`#import-form [name=${name}]`),value=x?.[name]||'';
    if(!input.value||input.value===input.dataset.autoValue){input.value=value;input.dataset.autoValue=value;}
  }
  $('#pdf-review-control').hidden=!x;
  const review=$('#import-form [name=confirm_pdf_review]');review.disabled=!x;review.checked=false;
}
async function readFilePayload(file) {
  if(!file?.size||file.size>10*1024*1024)throw new Error('请选择一个不超过10MB的文件。');
  const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败。'));reader.readAsDataURL(file);});
  return {name:file.name,data};
}
function uploadModal() {
  showModal('归档产品资料',`<form id="upload-form" class="modal-body"><p>文件将保存在当前产品下。附件作为新记录保留，不覆盖旧文件。老板批准前更新规格、报价或加工说明会要求重新审核；批准后这些类别锁定，只能补充执行凭证。</p><div class="form-grid"><label class="field wide"><span>资料类别</span><select name="category">${data.categories.filter(c=>!currentItem().approval_locked||!['图稿/规格','工厂报价','加工说明'].includes(c)).map(c=>`<option>${esc(c)}</option>`).join('')}</select></label><label class="field wide"><span>选择文件 · 单个最大 10MB</span><input type="file" name="file" required></label></div><div class="error" id="modal-error"></div></form>`,footer('保存并归档','upload-form'));
}
function composeModal() {
  const i=currentItem(),o=currentOrder();
  const subject=`[${i.code}] ${i.route==='国内定制'?'工厂采购下单':i.route==='本地加工'?'本地加工委托':'本地出库安排'} · ${i.name}`;
  const body=`您好，\n\n请按以下资料安排${i.route==='国内定制'?'生产':i.route==='本地加工'?'加工':'出库'}，并回复确认。\n\n订单编号：${o.invoice}\n产品明细：${i.code}\n产品名称：${i.name}\n数量：${i.qty} 个\n规格 / 加工要求：${i.spec||'请补充'}\n要求交货日期：${i.due||'待确认'}\n${i.route==='本地直发'?'':`采购 / 加工单价：${i.unit_cost} ${i.currency}\n金额：${(i.qty*i.unit_cost).toFixed(2)} ${i.currency}\n`}\n补充说明：${i.notes||'无'}\n\n请确认数量、规格、价格及交期。回复时请保留主题中的产品明细编号。\n谢谢！\n${o.sales}`;
  showModal('生成并归档邮件草稿',`<form id="mail-form" class="modal-body" data-version="${i.version}"><p>草稿根据当前产品 V${i.version} 生成。请检查收件人、正文及附件。保存后可下载 .eml；本系统不会发送邮件。</p><div class="form-grid">${field('收件邮箱','recipient',i.recipient,'email',false,true,'required')}${field('邮件主题','subject',subject,'text',false,true,'required maxlength="500"')}${field('邮件正文','body',body,'textarea',false,true)}</div><h3 style="margin-top:18px;font-size:12px">选择随邮件发送的附件</h3>${i.documents.length?i.documents.map(d=>`<label class="checkbox"><input type="checkbox" name="document_ids" value="${d.id}" ${['图稿/规格','工厂报价','加工说明'].includes(d.category)?'checked':''}>${esc(d.name)} <small>${esc(d.category)}</small></label>`).join(''):'<p class="helper">还没有附件，可先关闭并归档产品资料。</p>'}<div class="error" id="modal-error"></div></form>`,footer('保存邮件草稿','mail-form'));
  $('textarea[name="body"]',modal).rows=12;
}
function shipmentModal() {
  const i=currentItem(),remaining=i.qty-i.shipments.reduce((s,b)=>s+b.qty,0);
  showModal('登记海运批次',`<form id="shipment-form" class="modal-body"><p>${esc(i.code)} · 尚可登记 ${fmtQty(remaining)} 个。一个产品支持多次装运。</p><div class="form-grid">${field('本次装运数量','qty',remaining,'number',false,false,`min="1" max="${remaining}" step="1" required`)}${field('船名','vessel','','text',false,false,'required')}${field('航次','voyage','','text',false,false,'required')}${field('提单号','bl','','text',false,false,'required')}${field('开船日期','etd','','date',false,false,'required')}${field('预计到港日期','eta','','date',false,false,'required')}</div><div class="error" id="modal-error"></div></form>`,footer('保存海运批次','shipment-form'));
}
async function runAction(fn) {
  try {await fn();} catch(e) {toast(e.message,true);}
}
let pendingOptionalTransition=null;
let pendingApprovalTransition=null;
async function showApprovalSubmission(payload) {
  const preview=await api('/api/approval-preview',payload);
  pendingApprovalTransition=payload;
  showModal('填写审批人邮箱并准备邮件',`<form id="approval-submit-form" class="modal-body"><p>本次提交将准备审批邮件和附件，收件人每次重新填写。确认后进入下一审批节点，邮件仍需手动发送。老板审批邮件会附专属链接，老板无需登录即可确认或退回；当前为本机演示，外部使用需部署。</p>${field('审批人邮箱（本次必填）','approval_email','','email',false,true,'required maxlength="250" placeholder="approver@example.com"')}<h3 style="margin:16px 0 8px">${esc(preview.subject)}</h3><pre class="approval-email-preview">${esc(preview.body)}</pre><h3>随邮件准备的附件</h3><p>固定包含本次审批资料摘要 approval-summary.txt；以下默认勾选，可调整，合计不超过20MB。</p>${preview.attachments.map(d=>`<label class="checkbox"><input type="checkbox" name="approval_attachment_keys" value="${esc(d.key)}" checked>${esc(d.name)} <small>${d.source==='order'?'Invoice 来源':'产品附件'} · ${fmtSize(d.size)}</small></label>`).join('')}<div id="modal-error" class="error"></div></form>`,`<div class="modal-footer"><button data-action="close">取消</button><button form="approval-submit-form" type="submit" class="primary">提交审批并准备邮件</button></div>`);
}
function showApprovalDraftReady(result) {
  showModal('审批邮件已准备，等待发送',`<div class="modal-body"><p>已提交下一审批节点。邮件正文、本次资料摘要及所选附件均已归档，尚未发送。请下载草稿并检查后手动发送。</p><a class="badge green" href="/api/message/${result.approval_message_id}" download>下载审批邮件 .eml（含附件）</a><p style="margin-top:15px">老板审批邮件包含免登录确认链接（7天有效）。当前链接仅本机演示可用，尚未部署外网审批。也可在产品的“邮件档案”查看收件人、正文和资料版本。</p></div>`,`<div class="modal-footer"><button class="primary" data-action="close">返回订单</button></div>`);
}
function showOptionalAttachmentReminder(result,payload) {
  pendingOptionalTransition=payload;
  showModal('可选附件未附，是否继续提交？',`<form id="optional-attachments-form" class="modal-body"><p>以下附件为可选，尚未上传：</p><ul>${result.optional_missing.map(c=>`<li>${esc(c)}</li>`).join('')}</ul><p>可返回补充，也可确认继续提交。当前填写资料已保存，本次确认会记入操作历史。</p><div id="modal-error" class="error"></div></form>`,`<div class="modal-footer"><button data-action="close">返回补充</button><button type="submit" form="optional-attachments-form" class="primary">仍然提交</button></div>`);
}
function executionFormChanged() {
  const f=$('#item-form'),i=currentItem();
  if(!f||!i)return false;
  return Object.entries(Object.fromEntries(new FormData(f))).some(([k,v])=>
    ['qty','unit_cost'].includes(k)?Number(v)!==Number(i[k]):String(v).trim()!==String(i[k]??'').trim());
}
function updateExecutionSaveStatus() {
  const status=$('#execution-save-status');if(!status)return;
  const dirty=executionFormChanged();
  status.classList.toggle('unsaved-notice',dirty);
  status.textContent=dirty?'有未保存修改：右侧清单仍按上次保存的资料检查。点“保存修改”，或点提交按钮先保存再检查。':'清单按已保存资料检查。填写后可点“保存修改”；提交审核也会先保存当前填写内容。';
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.filter){filter=b.dataset.filter;section='info';render();return;}
  if(b.dataset.order){selectedOrder=b.dataset.order;selectedItem=currentOrder().items.find(matches)?.id||currentOrder().items[0].id;section='info';render();return;}
  if(b.dataset.item){selectedItem=b.dataset.item;section='info';render();return;}
  if(b.dataset.section){section=b.dataset.section;render();return;}
  if(b.dataset.arrive) {await runAction(async()=>{b.disabled=true;const r=await api('/api/arrive',{item_id:selectedItem,shipment_id:b.dataset.arrive});await load();toast(r.message);});b.disabled=false;return;}
  const action=b.dataset.action;
  if(b.dataset.sourceImage){
    const doc=currentOrder().source_documents.find(d=>d.id===b.dataset.sourceImage);
    if(doc)showModal(doc.category,`<div class="source-image-preview"><img src="/api/order-image/${doc.id}" alt="${esc(doc.category)}"><a href="/api/order-document/${doc.id}" download>下载原始截图</a></div>`);
    return;
  }
  if(action==='close')return modal.close();
  if(action==='new-order')return newOrder();
  if(action==='import-invoice')return importModal();
  if(action==='preview-import'){
    b.disabled=true;
    try{
      $('#modal-error').textContent='';importPreview=null;
      importFile=await readFilePayload($('#invoice-file').files[0]);
      importPreview=await api('/api/import-preview',{file:importFile,pdf_date_order:$('#import-form [name=pdf_date_order]').value});
      showImportPreview();
    }catch(err){$('#modal-error').textContent=err.message;}finally{b.disabled=false;}
    return;
  }
  if(action==='upload')return uploadModal();
  if(action==='compose')return composeModal();
  if(action==='reissue-boss-approval')return runAction(async()=>{if(executionFormChanged())throw new Error('请先保存当前资料，再重新准备邮件。');const i=currentItem();await showApprovalSubmission({item_id:i.id,version:i.version,stage:i.stage,reissue:true,note:$('#action-note')?.value||''});});
  if(action==='new-shipment')return shipmentModal();
  if(action==='add-line')return $('#new-lines').insertAdjacentHTML('beforeend',lineRow());
  if(action==='remove-line'){if($$('.new-line',modal).length>1)b.closest('.new-line').remove();else toast('至少保留一个产品。');return;}
  if(action==='refresh')return runAction(async()=>{await load();toast('已刷新资料。');});
  if(['next','return','comment'].includes(action)) await runAction(async()=>{
    let i=currentItem();const note=$('#action-note').value.trim();
    b.disabled=true;
    let saved=false;
    try{
      if(action==='next'&&executionFormChanged()){
        const f=$('#item-form');if(!f.reportValidity())return;
        const oldStage=i.stage;
        await api('/api/item',{...Object.fromEntries(new FormData(f)),item_id:i.id,version:i.version});
        saved=true;await load();i=currentItem();
        const noteField=$('#action-note');if(noteField)noteField.value=note;
        if(i.stage!==oldStage)throw new Error('填写内容已保存；关键资料变化，已退回待补资料，请重新提交审核。');
      }
      const payload={item_id:i.id,version:i.version,stage:i.stage,decision:action==='return'?'return':'next',note};
      if(action==='next'&&['待补资料','财务审核'].includes(i.status)&&!i.missing.length&&!(i.status==='待补资料'&&i.optional_missing?.length)){await showApprovalSubmission(payload);return;}
      const r=await api(action==='comment'?'/api/comment':'/api/transition',payload);
      if(r.confirmation_required){showOptionalAttachmentReminder(r,payload);return;}
      await load();toast(r.message);
    }catch(err){
      if(saved&&!err.message.startsWith('填写内容已保存'))throw new Error('填写内容已保存。'+err.message);
      throw err;
    }finally{b.disabled=false;}
  });
});
const $$=(q,root=document)=>Array.from(root.querySelectorAll(q));
document.addEventListener('change',e=>{if(e.target.closest('#item-form'))updateExecutionSaveStatus();if(e.target.matches('#production-form [name=route]')){e.target.className=routeTone(e.target.value);$$('.production-guide [data-production-route]').forEach(card=>card.classList.toggle('is-selected',card.dataset.productionRoute===e.target.value));}if(e.target.id==='role'){role=e.target.value;localStorage.setItem('ecobag-demo-role',role);render();}if(e.target.id==='invoice-file'){
  importFile=null;importPreview=null;$('#import-preview').innerHTML='';
  for(const name of ['invoice','customer','invoice_date','payment_due','currency','tax_rate','pdf_date_order']){const input=$(`#import-form [name=${name}]`);input.value='';delete input.dataset.autoValue;}
  $('#pdf-date-control').hidden=!/\.pdf$/i.test(e.target.files[0]?.name||'');
  $('#pdf-review-control').hidden=true;const review=$('#import-form [name=confirm_pdf_review]');review.disabled=true;review.checked=false;
}if(e.target.matches('#import-form [name=pdf_date_order]')){importPreview=null;$('#import-preview').innerHTML='<p class="helper">日期格式已更改，请重新点击“读取并预览产品”。</p>';$('#import-form [name=confirm_pdf_review]').checked=false;}});
document.addEventListener('input',e=>{if(e.target.closest('#item-form'))updateExecutionSaveStatus();if(e.target.id==='search'){
  const pos=e.target.selectionStart;search=e.target.value;render();const input=$('#search');input.focus();input.setSelectionRange(pos,pos);
}});
document.addEventListener('submit',async e=>{
  e.preventDefault();const f=e.target;const form=new FormData(f);const values=Object.fromEntries(form);
  const error=$('#modal-error');if(error)error.textContent='';
  const submit=document.querySelector(`button[form="${f.id}"]`)||$('button[type="submit"]',f);
  if(submit)submit.disabled=true;
  try {
    let r;
    if(f.id==='approval-submit-form'){
      if(!pendingApprovalTransition)throw new Error('请重新打开提交审批窗口。');
      r=await api(pendingApprovalTransition.reissue?'/api/reissue-boss-approval':'/api/transition',{...pendingApprovalTransition,approval_email:values.approval_email,approval_attachment_keys:form.getAll('approval_attachment_keys')});
      pendingApprovalTransition=null;await load();showApprovalDraftReady(r);
    }else if(f.id==='optional-attachments-form'){
      if(!pendingOptionalTransition)throw new Error('请关闭弹窗并重新提交。');
      await showApprovalSubmission({...pendingOptionalTransition,confirm_optional_missing:true});
      pendingOptionalTransition=null;
    }else if(f.id==='import-form'){
      if(!importFile||!importPreview)throw new Error('请先读取并预览文件。');
      if(importPreview.extracted?.date_format_required)throw new Error('请先选择 PDF 日期格式，再重新读取并核对。');
      values.confirm_pdf_review=$('#import-form [name=confirm_pdf_review]').checked;
      const extra=form.getAll('attachments').filter(file=>file.size);
      if(extra.length>5)throw new Error('最多可附5个额外来源文件。');
      const attachments=[];for(const file of extra)attachments.push(await readFilePayload(file));
      r=await api('/api/import-invoice',{...values,file:importFile,attachments});
      selectedOrder=r.order_id;selectedItem=null;filter='all';search='';section='info';modal.close();await load();toast(r.message);
    }else if(f.id==='production-form'){
      const i=currentItem();r=await api('/api/production-type',{...values,item_id:i.id,version:i.version});await load();toast(r.message);
    }else if(f.id==='new-order-form'){
      values.items=$$('.new-line',f).map(row=>({name:$('[name="line-name"]',row).value,qty:$('[name="line-qty"]',row).value}));
      r=await api('/api/orders',values);selectedOrder=r.order_id;selectedItem=null;filter='all';search='';section='info';modal.close();await load();toast('订单已建立，每个产品分别跟进。');
    }else if(f.id==='item-form'){
      const i=currentItem();r=await api('/api/item',{...values,item_id:i.id,version:i.version});await load();toast(r.message);
    }else if(f.id==='upload-form'){
      const file=form.get('file');if(!file?.size||file.size>10*1024*1024)throw new Error('请选择一个不超过10MB的文件。');
      const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败。'));reader.readAsDataURL(file);});
      r=await api('/api/document',{item_id:selectedItem,category:values.category,name:file.name,data:content});modal.close();await load();toast(r.message);
    }else if(f.id==='mail-form'){
      r=await api('/api/message',{...values,item_id:selectedItem,version:Number(f.dataset.version),document_ids:form.getAll('document_ids')});
      section='mail';await load();showModal('邮件草稿已归档',`<div class="modal-body"><div class="mail-success">${icon('check')}<h3>正文、附件和版本已保存</h3><p>尚未发送邮件。下载后，在邮件客户端打开并手动发送。<br>实际发送后，跟单可在“资料与进度”确认交接。</p><a class="badge green" href="/api/message/${r.message_id}" download>${icon('download')} 下载邮件草稿 .eml</a></div><p style="margin:15px 0 0">若电脑没有关联邮件客户端，可打开 .eml 查看内容；自动通过 Yahoo 发送将在后续接入。</p></div>`,`<div class="modal-footer"><button class="primary" data-action="close">返回订单</button></div>`);
    }else if(f.id==='shipment-form'){
      r=await api('/api/shipment',{...values,item_id:selectedItem});modal.close();await load();toast(r.message);
    }
  }catch(err){if(modal.open&&$('#modal-error'))$('#modal-error').textContent=err.message;else toast(err.message,true);}
  finally{if(submit)submit.disabled=false;}
});
load().catch(e=>{$('#app').innerHTML=`<div class="main-error"><h2>暂时无法打开工作台</h2><p>${esc(e.message)}</p><p>请运行同目录的“启动工作台.cmd”，再打开 http://127.0.0.1:8766。</p><button onclick="location.reload()">重试</button></div>`;});
