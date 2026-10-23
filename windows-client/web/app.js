(() => {
'use strict';
const $ = id => document.getElementById(id);
let state = {}, type = 'MARKET', symbol = '', busy = false, detail = null, polling = false, closing = false, pollTimer = null;
window.addEventListener('finfusion-closing', () => { closing = true; clearInterval(pollTimer); });
const text = (id, value) => { if ($(id)) $(id).textContent = value ?? '—'; };
const displayValue = v => v === null || v === undefined ? '暂无数据' : String(v);
function toast(message) { text('toast', message); $('toast').classList.add('show'); setTimeout(() => $('toast').classList.remove('show'), 4500); }
async function call(op, args = {}) {
  const r = await window.pywebview.api.action(op, args);
  if (r.error) toast(r.error);
  else if (r.accounts) render(r);
  return r;
}
function row(parent, values, className) {
  const element = document.createElement('div'); element.className = className;
  for (const v of values) { const e = document.createElement('span'); e.textContent = displayValue(v); element.append(e); }
  parent.append(element); return element;
}
function render(s) {
  state = s;
  if (!symbol && s.market.symbol) symbol = s.market.symbol;
  text('statusText', s.connection);
  text('versionText', '客户端 ' + (s.clientVersion || '未知') + ' · 服务器 ' + (s.server?.version || '未确认'));
  const gates = {database: '数据库', brokerEvents: '券商事件', market: '行情', reconciliation: '订单对账', tunnel: 'Tunnel', nodeActive: '节点启用', globalTradeEnabled: '全局交易开关'};
  const blocked = Object.entries(gates).filter(([key]) => s.readiness?.[key] === false).map(([,label]) => label);
  const operations = s.server?.operations || {};
  text('statusDetail', '订单事件：' + (s.events || s.event_connection || s.event_status || '未连接') + (blocked.length ? ' · 服务器交易条件未满足：' + blocked.join('、') : '') + (operations.status === 'ALERT' || operations.status === 'WARNING' ? ' · 运行告警：' + (operations.issues || []).join('、') : ''));
  text('modeBadge', s.context.environment || 'UNKNOWN'); text('accountText', s.selected || (s.accounts.length ? '请选择授权账户' : '无已授权账户'));
  text('popoverAccountName', s.selected || '未选择账户'); text('popoverConnectionState', s.connected ? 'AUTHENTICATED' : 'OFFLINE');
  $('statusDot').classList.toggle('connected', s.connected);
  const accounts = $('accountSelect');
  if (accounts.dataset.list !== JSON.stringify(s.accounts)) {
    accounts.replaceChildren(new Option('选择授权账户', ''));
    s.accounts.forEach(a => accounts.add(new Option((a.alias || a.accountRef) + ' ' + (a.accountMask || ''), a.accountRef)));
    accounts.dataset.list = JSON.stringify(s.accounts);
  }
  accounts.value = s.selected || '';
  const power = s.balance.usdBuyingPower;
  text('headerUsdBuyingPower', displayValue(power)); text('buyingPower', displayValue(power));
  text('usdCashBalance', displayValue(s.balance.usdCashBalance));
  text('availablePosition', (s.positions.positions || []).find(p=>p.symbol===symbol)?.quantity);
  text('riskAccount', s.selected); $('riskSummary').hidden = !s.selected;
  const context = s.context;
  const gateHint = {NOT_SUPPORTED:'状态接口未部署',DENIED:'无读取权限',EDGE_BLOCKED:'公网入口拒绝访问'}[s.context_status];
  text('liveToggleHint', '只读 · 权限及风控由服务器执行'); text('serverGate', gateHint || (context.tradeEnabled === true ? '允许' : '未就绪'));
  const risk = context.riskRules || {};
  text('riskLimits', risk.maxOrderQty == null ? '暂无数据' : `${risk.maxOrderQty} 股 / ${displayValue(risk.maxOrderValue)} USD`);
  const deploymentAllowed = context.environment === 'SANDBOX' || (context.environment === 'LIVE' && context.tradeDeploymentAllowed === true);
  const allowed = s.connected && s.selected && deploymentAllowed && context.tradeEnabled === true && symbol;
  const pending = s.pending.some(p => p.account_ref === s.selected && ['submit', 'replace'].includes(p.operation));
  $('buyButton').disabled = $('sellButton').disabled = !allowed || busy || pending;
  $('tradeBlock').hidden = allowed && !pending;
  $('tradeBlock').querySelector('p').textContent = pending ? '该账户有待确认请求，只能补查原请求' : s.context_status === 'NOT_SUPPORTED' ? '服务器尚未部署 UI 权限状态接口；交易保持禁用' : context.environment === 'LIVE' && !deploymentAllowed ? '服务器当前为 LIVE 只读部署' : '请连接服务器、选择授权账户及股票；交易权限及门禁由服务器确认';
  const matchingDetail = detail && detail.accountRef === s.selected && !['FILLED','CANCELLED','REJECTED'].includes(detail.status);
  const targetPending = matchingDetail && s.pending.some(p => p.account_ref === s.selected && p.target === detail.clientOrderId);
  $('replaceOrder').disabled = !matchingDetail || !deploymentAllowed || context.tradeEnabled !== true || busy || pending || targetPending;
  $('cancelOrder').disabled = !matchingDetail || !deploymentAllowed || context.cancelEnabled !== true || busy || targetPending;
  const m = s.market;
  text('symbolName', m.symbol || symbol || '—'); text('previewSymbol', symbol || '—');
  text('lastPrice', m.lastPrice); text('priceChange', m.change == null ? '—' : `${m.change} (${displayValue(m.changePercent)}%)`);
  text('marketState', ({READY: '实时', STALE: '过期', DENIED: '无行情权限', EDGE_BLOCKED: '公网入口拒绝访问', NOT_SUPPORTED: '服务器行情接口未部署', UNAVAILABLE: '行情不可用'})[m.status] || '等待行情');
  text('freshnessText', m.asOf == null ? '无有效时间戳' : new Date(Number(m.asOf)*1000).toLocaleString());
  text('feedBadge', m.status || 'OFFLINE'); $('freshnessBar').dataset.level = m.status === 'READY' ? '20' : '0';
  $('priceChange').className = 'price-change ' + (m.change == null ? 'neutral' : Number(m.change) >= 0 ? 'positive' : 'negative');
  for (const k of ['open', 'high', 'low', 'volume']) text(k === 'volume' ? 'volume' : k + 'Price', m[k]);
  for (const side of ['bid', 'ask']) { const book = $(side + 'Book'); book.replaceChildren(); const level = m[side]; if (level) row(book, [side === 'bid' ? '买一' : '卖一', level.price, level.size], 'book-row'); }
  text('spread', m.spread);
  const tape = $('tape'); tape.replaceChildren(); (s.trades.trades || []).forEach(t => row(tape, [t.time, t.price, t.size, t.side], 'tape-row'));
  const positions = $('positionsBody'); positions.replaceChildren();
  (s.positions.positions || []).forEach(p => row(positions, [p.symbol, p.name, p.lastPrice, p.quantity, p.unitCost, p.unrealizedPnl], 'positions-grid position-row'));
  if (!positions.children.length) row(positions, [!s.selected ? '未选择账户' : Array.isArray(s.positions.positions) ? '当前账户无美元股票 / ETF 持仓' : '持仓数据不可用'], 'positions-state');
  text('positionsStatus', s.selected ? 'SERVER' : '未连接');
  const orders = $('orders'); orders.replaceChildren();
  s.orders.forEach(o => { const r = row(orders, [o.updatedAt, `${o.symbol} ${o.side}`, o.quantity, o.limitPrice, o.statusText], 'order-row'); const button = document.createElement('button'); button.className = 'button'; button.textContent = '详情'; button.onclick = async () => { detail = await call('detail', {orderId: o.clientOrderId}); if (!detail.error) { text('detailText', JSON.stringify(detail, null, 2)); $('detailDialog').hidden = false; } }; r.append(button); });
  text('orderCount', `${s.orders.length} ORDERS`);
  const p = $('pending'); p.replaceChildren(); s.pending.forEach(r => row(p, [r.request_id, r.account_ref, r.operation, r.phase], 'pending-row')); if (!p.children.length) row(p, ['无待确认请求'], 'positions-state');
  $('nextPage').disabled = !s.cursor;
  for (const side of ['buy', 'sell']) $(side + 'Button').querySelector('strong').textContent = (side === 'buy' ? '买入 ' : '卖出 ') + (symbol || '—');
  const estimate = Number(type === 'LIMIT' ? $('limitInput').value : m.lastPrice) * Number($('quantityInput').value);
  text('estimatedValue', Number.isFinite(estimate) && estimate > 0 ? estimate.toFixed(2) + ' USD' : '—');
}
async function poll() { if (polling || closing) return; polling = true; document.body.dataset.polling = 'true'; try { const r = await window.pywebview.api.get_state(); if (!r.error && !closing) render(r); } finally { polling = false; document.body.dataset.polling = 'false'; } }
function settings() { $('originInput').value = state.config.origin; $('clientIdInput').value = state.config.client_id; text('keyStatus', state.keyPresent ? '已保存 DPAPI 加密私钥' : '尚未配置密钥'); $('settingsDialog').hidden = false; $('originInput').focus(); }
async function mutation(op, data) {
  if (busy) return; busy = true; render(state);
  try { await call(op, {...data, accountRef: state.selected}); }
  finally { setTimeout(() => { busy = false; poll(); }, 1000); }
}
window.addEventListener('pywebviewready', async () => {
  await call('page_ready'); await poll(); pollTimer = setInterval(poll, 700);
  $('connectButton').onclick = () => state.config.origin && state.keyPresent ? call('connect') : settings();
  $('accountMenuButton').onclick = () => { $('accountPopover').hidden = !$('accountPopover').hidden; $('accountMenuButton').setAttribute('aria-expanded', !$('accountPopover').hidden); };
  $('popoverReconnectButton').onclick = () => call('connect'); $('popoverApiButton').onclick = settings;
  $('popoverDisconnectButton').onclick = async () => { symbol = ''; await call('disconnect'); };
  $('popoverSwitchButton').onclick = () => $('accountSelect').focus();
  $('accountSelect').onchange = async e => { symbol = ''; await call('account', {accountRef: e.target.value || null}); };
  $('refreshButton').onclick = () => call('refresh'); $('nextPage').onclick = () => call('refresh', {cursor: state.cursor});
  $('settingsClose').onclick = () => $('settingsDialog').hidden = true;
  $('saveSettings').onclick = async () => { const r = await window.pywebview.api.save_config($('originInput').value, $('clientIdInput').value); toast(r.error || r.message); await poll(); };
  for (const [id, op] of [['generateKey','generate'], ['importKey','import'], ['exportKey','export']]) $(id).onclick = async () => { const r = await window.pywebview.api.key_operation(op); toast(r.error || r.message); await poll(); settings(); };
  $('symbolForm').onsubmit = async e => { e.preventDefault(); const r = await call('search', {q: $('symbolInput').value}); const list = $('symbolResults'); list.replaceChildren(); for (const candidate of r.symbols || []) { const b = document.createElement('button'); b.className = 'symbol-result'; b.setAttribute('role', 'option'); b.textContent = candidate.symbol + ' ' + (candidate.name || ''); b.onclick = async () => { symbol = candidate.symbol; list.hidden = true; $('symbolInput').setAttribute('aria-expanded', 'false'); await call('symbol', {symbol}); }; list.append(b); } list.hidden = false; $('symbolInput').setAttribute('aria-expanded', 'true'); text('symbolSearchHint', r.error ? r.error : list.children.length ? '请选择完整代码候选' : '没有候选'); };
  document.querySelectorAll('[data-order-type]').forEach(b => b.onclick = () => { type = b.dataset.orderType; document.querySelectorAll('[data-order-type]').forEach(c => c.classList.toggle('active', c === b)); $('limitField').classList.toggle('hidden', type !== 'LIMIT'); });
  document.querySelectorAll('[data-qty]').forEach(b => b.onclick = () => $('quantityInput').value = b.dataset.qty);
  for (const side of ['BUY', 'SELL']) $(side.toLowerCase() + 'Button').onclick = () => mutation('submit', {symbol, side, orderType: type, quantity: $('quantityInput').value, limitPrice: $('limitInput').value});
  $('detailClose').onclick = () => $('detailDialog').hidden = true;
  $('replaceOrder').onclick = () => detail && detail.accountRef === state.selected && mutation('replace', {orderId: detail.clientOrderId, limitPrice: $('replacePrice').value});
  $('cancelOrder').onclick = () => detail && detail.accountRef === state.selected && mutation('cancel', {orderId: detail.clientOrderId});
  document.addEventListener('keydown', e => { if(e.key === 'Tab') {const dialog=[...document.querySelectorAll('.dialog-backdrop')].find(d=>!d.hidden); if(dialog){const focus=[...dialog.querySelectorAll('button,input,select')].filter(n=>!n.disabled);const index=focus.indexOf(document.activeElement);if((e.shiftKey && index<=0)||(!e.shiftKey && index===focus.length-1)){e.preventDefault();focus[e.shiftKey?focus.length-1:0].focus();}}} if (e.key === 'Escape') document.querySelectorAll('.dialog-backdrop').forEach(d => d.hidden = true); });
});

})();
