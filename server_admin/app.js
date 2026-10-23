(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const tokenKey = "finfusion.admin.access-token", verifierKey = "finfusion.admin.pkce-verifier", stateKey = "finfusion.admin.oauth-state";
  let config = null, snapshot = null, authenticated = false, loading = false, activeForm = null;
  const descriptions = {
    overview: ["工作空间", "Finfusion 管理空间", "管理用户与程序接入，让每一份权限都有明确的归属。"],
    users: ["用户账号", "用户账号", "管理用户身份、账号状态与接入权限。"],
    clients: ["API 客户端", "API 接入空间", "登记公钥，批准客户端，按需分配查询与交易权限。"],
    accounts: ["账户分配", "账户分配", "将券商账户分配给明确的用户，随时收回授权。"],
    controls: ["权限与交易控制", "权限与交易控制", "统一管理全局、用户与账户的交易开关。"]
  };
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
  const message = text => { $("message").textContent = text; $("message").hidden = false; };
  const badge = (text, style = "neutral") => `<span class="badge ${style}">${escapeHtml(text)}</span>`;
  const cell = (main, sub = "") => `<span class="cell-main">${escapeHtml(main)}</span>${sub ? `<span class="cell-sub" title="${escapeHtml(sub)}">${escapeHtml(sub)}</span>` : ""}`;
  const permissions = row => [["can_read","查询"],["can_trade","交易"],["can_cancel","撤单"]].filter(([key])=>row[key]).map(([,name])=>`<span class="permission">${name}</span>`).join("") || "未授权";
  const date = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
  const readable = () => authenticated || config?.preview === true;
  function navigate(page) {
    $("message").hidden = true;
    if (!descriptions[page]) page = "overview";
    const [name,title,description] = descriptions[page];
    $("breadcrumb").textContent = name; $("pageTitle").textContent = title; $("pageDescription").textContent = description;
    document.querySelectorAll("[data-panel]").forEach(el=>el.hidden = el.dataset.panel !== page);
    document.querySelectorAll("nav [data-page]").forEach(el=>{const active=el.dataset.page===page; el.classList.toggle("active",active); if(active) el.setAttribute("aria-current","page"); else el.removeAttribute("aria-current");});
  }
  function locks() {
    document.querySelectorAll("form button[type=submit], form button:not([type]), [data-global]").forEach(el=>el.disabled = !authenticated || config?.preview === true);
    $("login").disabled = !config || config.preview === true;
    $("refresh").disabled = loading || !readable();
  }
  function signOut(text = "已退出管理员登录") {
    sessionStorage.removeItem(tokenKey); sessionStorage.removeItem(verifierKey); sessionStorage.removeItem(stateKey);
    authenticated=false; snapshot=null; $("login").hidden=false; $("logout").hidden=true;
    $("connectionBadge").textContent="未登录"; $("sideConnection").textContent="管理服务 · 未登录";
    if ($("formDialog").open) $("formDialog").close(); document.querySelectorAll("form").forEach(f=>f.reset());
    $("readinessState").textContent="尚未读取";
    render(); locks(); if(text) message(text);
  }
  async function request(path, options = {}) {
    if(config?.preview && options.method && options.method!=="GET") throw new Error("当前为只读界面预览，管理操作需登录正式服务。");
    const abort = new AbortController(); const timeout=setTimeout(()=>abort.abort(),12000);
    try {
      const response = await fetch(path,{...options,signal:abort.signal,redirect:"error",cache:"no-store",headers:{"Authorization":`Bearer ${sessionStorage.getItem(tokenKey)||""}`,"Content-Type":"application/json",...(options.headers||{})}});
      const body = await response.json().catch(()=>({}));
      if(!response.ok) {
        if(response.status===401 || response.status===403) signOut("登录已失效或当前账号没有管理员权限，请重新登录。");
        throw new Error(body.error?.message || `请求失败（HTTP ${response.status}）`);
      }
      return body;
    } catch(error) {
      if(error.name==="AbortError") throw new Error("请求超时。请刷新并核对服务器状态，管理命令不会自动重发。");
      throw error;
    } finally {clearTimeout(timeout);}
  }
  const b64=bytes=>btoa(String.fromCharCode(...new Uint8Array(bytes))).replaceAll("+","-").replaceAll("/","_").replaceAll("=","");
  const random=()=>b64(crypto.getRandomValues(new Uint8Array(32)));
  async function login() {
    if(!config?.authorizationEndpoint || config.preview) {message("请先启用管理员登录服务。");return;}
    const verifier=random(), state=random(), challenge=b64(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(verifier)));
    sessionStorage.setItem(verifierKey,verifier);sessionStorage.setItem(stateKey,state);
    const url=new URL(config.authorizationEndpoint);
    Object.entries({client_id:config.clientId,response_type:"code",redirect_uri:config.redirectUri,scope:config.scope,state,code_challenge:challenge,code_challenge_method:"S256"}).forEach(([key,value])=>url.searchParams.set(key,value));
    location.assign(url);
  }
  async function finishLogin(code,state) {
    if(!code || !state || state!==sessionStorage.getItem(stateKey)) throw new Error("登录回调校验失败，请重新登录。");
    const verifier=sessionStorage.getItem(verifierKey);if(!verifier) throw new Error("登录会话已失效，请重新登录。");
    const body=new URLSearchParams({grant_type:"authorization_code",client_id:config.clientId,code,redirect_uri:config.redirectUri,code_verifier:verifier});
    const response=await fetch(config.tokenEndpoint,{method:"POST",redirect:"error",signal:AbortSignal.timeout(12000),headers:{"Content-Type":"application/x-www-form-urlencoded"},body});
    const tokens=await response.json();
    if(!response.ok || !tokens.access_token) throw new Error("无法取得管理员令牌，请重新登录。");
    sessionStorage.setItem(tokenKey,tokens.access_token);sessionStorage.removeItem(verifierKey);sessionStorage.removeItem(stateKey);
    history.replaceState({},"","/admin/");
  }
  function table(headers, rows) {
    return rows.length ? `<table><thead><tr>${headers.map(h=>`<th scope="col">${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(c=>`<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>` : `<div class="empty">${readable()?"暂无匹配记录。":"登录后读取服务器记录。"}</div>`;
  }
  const match=(row,keys,query)=>keys.some(key=>String(row[key]||"").toLowerCase().includes(query.trim().toLowerCase()));
  const action=(form,id,value,text="管理")=>`<button class="text-link row-action" data-form="${form}" data-field="${id}" data-value="${escapeHtml(value)}">${text}</button>`;
  function render() {
    const users=snapshot?.users||[], clients=snapshot?.clients||[], accounts=snapshot?.accounts||[], control=snapshot?.control;
    $("userCount").textContent=snapshot?users.length:"—";$("clientCount").textContent=snapshot?clients.length:"—";$("accountCount").textContent=snapshot?accounts.filter(a=>a.user_id).length:"—";
    $("userDetail").textContent=snapshot?`${users.filter(u=>u.enabled).length} 个已启用`:"尚未读取";
    $("clientDetail").textContent=snapshot?`${clients.filter(c=>c.enabled).length} 个已批准`:"尚未读取";
    $("accountDetail").textContent=snapshot?`共 ${accounts.length} 个登记账户`:"尚未读取";
    const global=control ? (control.global_trade_enabled?"允许新单与改单":"已中断新单与改单") : "等待管理员登录";
    $("globalState").textContent=global;$("controlDisplay").textContent=global;
    $("globalBadge").textContent=control?(control.global_trade_enabled?"全局开关开启":"全局开关关闭"):"尚未读取";
    $("globalBadge").className=`badge ${control?(control.global_trade_enabled?"good":"off"):"neutral"}`;
    $("lastUpdated").textContent=date(control?.updated_at);
    $("recentClients").innerHTML=table(["客户端 / 所属用户","访问权限","状态"],clients.slice(0,4).map(c=>[cell(c.label,c.user_id),permissions(c),badge(c.enabled?"已批准":"待批准 / 已停用",c.enabled?"good":"warn")]));
    $("usersTable").innerHTML=table(["用户 / ID","账号状态","交易开关","操作"],users.filter(u=>match(u,["user_id","casdoor_name"],$("userSearch").value)).map(u=>[cell(u.casdoor_name,u.user_id),badge(u.enabled?"已启用":"已禁用",u.enabled?"good":"off"),u.trade_enabled?"允许":"中断",action("userStatusForm","userId",u.user_id)]));
    $("clientsTable").innerHTML=table(["客户端 / clientId","所属用户","访问权限","状态","操作"],clients.filter(c=>match(c,["label","client_id","user_id"],$("clientSearch").value)).map(c=>[cell(c.label,c.client_id),escapeHtml(c.user_id),permissions(c),badge(c.enabled?"已批准":"待批准 / 已停用",c.enabled?"good":"warn"),action("clientPermissionsForm","clientId",c.client_id,"分配权限")]));
    $("accountsTable").innerHTML=table(["账户 / accountRef","券商账户","所属用户","交易开关","操作"],accounts.filter(a=>match(a,["alias","account_ref","user_id"],$("accountSearch").value)).map(a=>[cell(a.alias,a.account_ref),escapeHtml(a.account_mask),escapeHtml(a.user_id||"未分配"),a.trade_enabled?"允许":"中断",action("bindingForm","accountRef",a.account_ref,"绑定用户")]));
    $("dataOrigin").textContent=config?.preview?"示例接入状态 · 不代表真实服务器":"登录后读取服务器状态";
    $("stateSource").textContent=config?.preview?"只读预览":snapshot?"服务器状态":"等待鉴权";
    if(authenticated) $("dataOrigin").textContent="来自已鉴权的服务器管理接口";
  }
  async function refresh() {
    if(loading)return;loading=true;locks();
    try {
      snapshot=await request("/admin/v1/state");
      authenticated=config?.preview!==true;
      $("login").hidden=authenticated;$("logout").hidden=!authenticated;
      $("connectionBadge").textContent=config?.preview?"界面预览":"管理员已登录";
      $("sideConnection").textContent=config?.preview?"管理服务 · 未连接":"管理服务 · 已鉴权";
      render();locks();
      if(config?.preview){$("readinessState").textContent="未连接管理服务";return;}
      try {
        const response=await fetch("/readyz",{cache:"no-store",redirect:"error",signal:AbortSignal.timeout(10000)});
        const ready=await response.json();
        $("readinessState").textContent=ready.effectiveTradeEnabled===true?"允许交易":ready.effectiveTradeEnabled===false?"未就绪或交易关闭":"状态未知";
      } catch {$("readinessState").textContent="交易健康状态不可用";}
    } finally {loading=false;locks();}
  }
  function openForm(id,field,value) {
    const form=$(id);if(!form)return;
    if(activeForm) $("formTemplates").append(activeForm);
    activeForm=form;form.reset();
    if(field && form.elements[field]) form.elements[field].value=value;
    if(id==="clientPermissionsForm" && value){const row=snapshot?.clients.find(c=>c.client_id===value);if(row)[["enabled","enabled"],["canRead","can_read"],["canTrade","can_trade"],["canCancel","can_cancel"]].forEach(([input,key])=>form.elements[input].checked=!!row[key]);}
    if(id==="userStatusForm" && value){const row=snapshot?.users.find(u=>u.user_id===value);if(row)form.elements.enabled.value=String(!!row.enabled);}
    $("dialogTitle").textContent=form.dataset.title;$("dialogDescription").textContent=form.dataset.description;
    $("formHost").append(form);locks();$("formDialog").showModal();
    if(config?.preview)message("可查看表单。当前为只读预览，提交功能在管理员登录后启用。");
  }
  async function mutate(form,path,method,payload,success) {
    if(!authenticated || config?.preview) throw new Error("请登录正式管理服务后操作。");
    const button=form.querySelector("button");if(button.disabled)return;
    button.disabled=true;
    try {
      const result=await request(path,{method,body:JSON.stringify(payload)});
      form.reset();if($("formDialog").open)$("formDialog").close();
      message(`${success}${result.clientId?` · clientId：${result.clientId}`:result.userId?` · 用户 ID：${result.userId}`:result.accountRef?` · accountRef：${result.accountRef}`:""}`);
      try {await refresh();}catch {message(`${success}。列表刷新失败，请手动刷新核对，勿重复提交。`);}
    } finally {locks();}
  }
  function bindForm(id,makeRequest) {
    $(id).addEventListener("submit",async event=>{
      event.preventDefault();const form=event.currentTarget;const data=Object.fromEntries(new FormData(form));
      try {const args=makeRequest(data,form);if(args)await mutate(form,...args);}catch(error){message(error.message);}
    });
  }
  async function start() {
    document.querySelectorAll("[data-page],[data-jump]").forEach(button=>button.addEventListener("click",()=>{location.hash=button.dataset.page||button.dataset.jump;}));
    window.addEventListener("hashchange",()=>navigate(location.hash.slice(1)));navigate(location.hash.slice(1));
    document.querySelectorAll("[data-dialog]").forEach(button=>button.addEventListener("click",()=>openForm(button.dataset.dialog)));
    document.addEventListener("click",event=>{const button=event.target.closest(".row-action");if(button)openForm(button.dataset.form,button.dataset.field,button.dataset.value);});
    $("closeDialog").addEventListener("click",()=>$("formDialog").close());
    $("formDialog").addEventListener("close",()=>{if(activeForm){activeForm.reset();$("formTemplates").append(activeForm);activeForm=null;}});
    ["userSearch","clientSearch","accountSearch"].forEach(id=>$(id).addEventListener("input",render));
    $("login").addEventListener("click",()=>login().catch(e=>message(e.message)));
    $("logout").addEventListener("click",()=>signOut());
    $("refresh").addEventListener("click",()=>refresh().catch(e=>message(e.message)));
    bindForm("userForm",d=>["/admin/v1/users","POST",d,"用户已创建"]);
    bindForm("accountForm",d=>["/admin/v1/accounts","POST",d,"账户已登记"]);
    bindForm("bindingForm",d=>["/admin/v1/bindings","POST",d,"账户已绑定"]);
    bindForm("registerClientForm",d=>{if(d.publicKeyPem.includes("PRIVATE KEY"))throw new Error("此处只能提交公钥，请不要提交私钥。");return ["/admin/v1/clients","POST",d,"客户端已登记，默认停用，需另行批准"]});
    bindForm("clientPermissionsForm",(d,f)=>[`/admin/v1/clients/${encodeURIComponent(d.clientId)}`,"PATCH",Object.fromEntries(["enabled","canRead","canTrade","canCancel"].map(key=>[key,f.elements[key].checked])),"客户端权限已更新"]);
    bindForm("rotateClientForm",d=>{if(d.publicKeyPem.includes("PRIVATE KEY"))throw new Error("此处只能提交公钥，请不要提交私钥。");if(!confirm("轮换公钥会立即停用客户端并关闭现有事件连接。继续轮换？"))return;return [`/admin/v1/clients/${encodeURIComponent(d.clientId)}`,"PATCH",{publicKeyPem:d.publicKeyPem},"公钥已轮换，请重新批准客户端"]});
    bindForm("userStatusForm",d=>[`/admin/v1/users/${encodeURIComponent(d.userId)}/status`,"POST",{enabled:d.enabled==="true"},"用户状态已更新"]);
    bindForm("passwordForm",d=>[`/admin/v1/users/${encodeURIComponent(d.userId)}/password`,"POST",{password:d.password},"密码已重置"]);
    bindForm("clientForm",d=>[`/admin/v1/clients/${encodeURIComponent(d.clientId)}`,"POST",{enabled:d.enabled==="true"},"客户端状态已更新"]);
    bindForm("unbindForm",d=>{if(!confirm("解绑会立即撤销原用户对此账户的访问权限。继续解绑？"))return;return [`/admin/v1/bindings/${encodeURIComponent(d.accountRef)}/remove`,"POST",{},"账户已解绑并撤权"]});
    bindForm("controlForm",d=>[`/admin/v1/controls/${d.scope}`,"POST",{key:d.key,enabled:d.enabled==="true",reason:d.reason},"交易权限已更新"]);
    document.querySelectorAll("[data-global]").forEach(button=>button.addEventListener("click",async()=>{
      if(button.disabled || !authenticated)return;
      const enabled=button.dataset.global==="true";
      if(!confirm(enabled?"将开启全局交易开关。实际交易仍由服务器门禁决定。继续开启？":"将中断所有用户的新单与改单。继续中断？"))return;
      button.disabled=true;
      try {await request("/admin/v1/controls/global",{method:"POST",body:JSON.stringify({enabled,reason:"管理员管理台操作"})});await refresh();message("全局交易开关已更新");}catch(error){message(error.message);}finally{locks();}
    }));
    render();locks();
    try {
      const response=await fetch("/admin/config",{cache:"no-store",redirect:"error",signal:AbortSignal.timeout(10000)});
      if(!response.ok)throw new Error("管理服务尚未启用");config=await response.json();
      if(config.preview){$("previewNotice").hidden=false;await refresh();}
      else {
        if(!["authorizationEndpoint","tokenEndpoint","clientId","redirectUri","scope"].every(key=>config[key]))throw new Error("管理员登录配置不完整");
        const params=new URLSearchParams(location.search);if(params.has("code"))await finishLogin(params.get("code"),params.get("state"));
        if(sessionStorage.getItem(tokenKey))await refresh();
        else $("sideConnection").textContent="管理服务 · 待登录";
      }
    }catch(error){$("offlineNotice").hidden=false;message(error.message);}finally{locks();}
  }
  start().catch(error=>message(error.message));
})();
