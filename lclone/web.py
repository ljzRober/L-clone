"""Web 面板: FastAPI + 单页 HTML。任何电脑浏览器打开即可访问大脑。

两个页面 (共享 CSS):
  /     记忆工作台: 层级树 + 卡片流; 拖拽卡片到左侧层级节点 = 上升/下降;
        右上角「+ 添加记忆」弹窗写入。所有记忆即 spec, 界面不做区分。
  /ask  问答页: 带记忆聊天 + 边界监督, 与记忆管理完全分开。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import chat as chat_mod
from . import config
from . import db as db_mod
from . import llm
from . import memory as mem_mod
from . import projects as proj_mod
from . import supervise as sup_mod

# 注意: 模型必须定义在模块级。若定义在 create_app 内部, 配合
# `from __future__ import annotations` 会产生未解析的 ForwardRef, 导致
# FastAPI 无法生成 schema、请求体会被误判为 query 参数。

from pydantic import BaseModel
from typing import Optional


class AskIn(BaseModel):
    question: str
    project_id: Optional[int] = None
    thread_id: Optional[str] = None
    k: int = 5
    with_specs: bool = True


class RememberIn(BaseModel):
    content: str
    level: str = "decision"
    project_id: Optional[int] = None
    reason: str = ""


class CaptureIn(BaseModel):
    text: str
    title: str = ""
    project_id: Optional[int] = None


class ReviewIn(BaseModel):
    id: int
    action: str = "keep"
    content: Optional[str] = None


class DemoteIn(BaseModel):
    project_id: int


class RecallIn(BaseModel):
    query: str
    project_id: Optional[int] = None
    k: int = 5


class SuperviseIn(BaseModel):
    proposal: str
    project_id: int


class ProjectIn(BaseModel):
    name: str
    path: str = ""
    charter: str = ""


# ================================================================ 共享样式
CSS = r"""
:root {
  --bg:#0b0f17; --surface:#111827; --card:#151d2e; --card2:#1a2337; --line:#243047;
  --fg:#e7ebf4; --dim:#8b95a9; --acc:#e0b15c; --acc2:#5b8def;
  --ok:#4ade80; --warn:#fbbf24; --bad:#f87171;
  --serif:Georgia,"Songti SC","Noto Serif SC","SimSun",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
* { box-sizing:border-box; }
html,body { height:100%; }
body { margin:0; font-family:var(--sans); background:var(--bg); color:var(--fg);
       background-image:
         radial-gradient(1100px 480px at 18% -8%, rgba(224,177,92,.06), transparent),
         radial-gradient(900px 420px at 92% 0%, rgba(91,141,239,.07), transparent); }
.app { display:flex; flex-direction:column; height:100vh; }
header { display:flex; align-items:center; gap:14px; padding:14px 24px;
         border-bottom:1px solid var(--line); flex:0 0 auto; background:rgba(11,15,23,.72); }
.brand { font-family:var(--serif); font-size:20px; font-weight:600; letter-spacing:.06em; }
.brand em { font-style:normal; color:var(--acc); }
.tag { font-size:11px; color:var(--dim); font-family:var(--mono); }
.sp { flex:1; }
button { font-family:inherit; }
.act { background:var(--acc); color:#241d08; border:0; border-radius:9px; padding:8px 16px;
       cursor:pointer; font-size:13px; font-weight:600; }
.act:hover { filter:brightness(1.08); }
.ghost { background:transparent; color:var(--dim); border:1px solid var(--line); border-radius:8px;
         padding:6px 12px; cursor:pointer; font-size:12px; }
.ghost:hover { color:var(--fg); border-color:var(--acc); }
a.navbtn { text-decoration:none; color:var(--dim); border:1px solid var(--line); border-radius:8px;
           padding:6px 12px; font-size:12px; }
a.navbtn:hover { color:var(--fg); border-color:var(--acc); }

/* ---- 记忆工作台 ---- */
.shell { display:flex; flex:1 1 auto; min-height:0; }
.sidebar { width:252px; flex:0 0 auto; border-right:1px solid var(--line); padding:14px 10px 26px;
           overflow-y:auto; background:var(--surface); }
.eyebrow { font-family:var(--mono); font-size:10px; color:var(--dim); letter-spacing:.16em;
           text-transform:uppercase; margin:16px 8px 6px; }
.eyebrow:first-child { margin-top:2px; }
.layer { display:flex; align-items:center; gap:10px; width:100%; text-align:left; border:1px solid transparent;
         background:transparent; color:var(--dim); border-radius:9px; padding:8px 10px; cursor:pointer;
         font-size:13px; }
.layer:hover { background:var(--card); color:var(--fg); }
.layer.on { background:var(--card2); color:var(--fg); border-color:var(--line); }
.layer.drop { border-color:var(--acc); background:var(--card); box-shadow:inset 0 0 0 1px var(--acc); }
.rail { width:4px; height:16px; border-radius:2px; flex:0 0 auto; }
.rail.global { background:var(--acc); }
.rail.project { background:var(--acc2); }
.layer .nm { flex:0 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.layer .cnt { margin-left:auto; font-family:var(--mono); font-size:11px; color:var(--dim); }
.layer .cnt b { color:var(--fg); }
#reg-form { display:none; padding:8px; }
#reg-form.on { display:block; }
#reg-form input { width:100%; background:#0d1424; color:var(--fg); border:1px solid var(--line);
                  border-radius:8px; padding:7px 9px; font-size:12px; margin-bottom:6px; font-family:inherit; }
.main { flex:1 1 auto; min-width:0; overflow-y:auto; padding:18px 24px 56px; }
.sec-head { display:flex; align-items:baseline; gap:10px; margin-bottom:16px; }
.sec-head h2 { margin:0; font-family:var(--serif); font-size:18px; font-weight:600; }
.sec-head .sub { color:var(--dim); font-size:12px; font-family:var(--mono); }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:13px 14px;
        display:flex; flex-direction:column; gap:8px; cursor:grab;
        transition:border-color .15s, transform .15s; }
.card:hover { border-color:#2e3b55; transform:translateY(-1px); }
.card.dragging { opacity:.45; }
.badge { display:inline-block; font-size:10px; border-radius:6px; padding:2px 7px; font-family:var(--mono); }
.b-decision { background:#1f3a6b; color:#8fb3ff; }
.b-milestone { background:#3a2a55; color:#c9a2ff; }
.b-note { background:#26303f; color:#a9bdd6; }
.b-global { background:#4a3a14; color:var(--acc); }
.b-project { background:#1d2b4a; color:#7fb0ff; }
.card .body { font-size:13px; line-height:1.6; color:var(--fg);
              display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; }
.lk { color:var(--acc); font-family:var(--mono); font-size:11px; }
.card .meta { font-family:var(--mono); font-size:10px; color:var(--dim); }
.card .ops { display:flex; gap:6px; align-items:center; margin-top:auto; }
.empty { color:var(--dim); font-size:13px; padding:34px 12px; text-align:center;
         border:1px dashed var(--line); border-radius:12px; }

/* ---- 添加记忆弹窗 ---- */
.modal-bg { display:none; position:fixed; inset:0; background:rgba(4,6,10,.62); backdrop-filter:blur(3px);
            z-index:40; align-items:center; justify-content:center; }
.modal-bg.on { display:flex; }
.modal { width:min(520px,92vw); background:var(--surface); border:1px solid var(--line);
         border-radius:14px; padding:20px; box-shadow:0 20px 60px rgba(0,0,0,.5); }
.modal h3 { margin:0 0 14px; font-family:var(--serif); font-size:16px; font-weight:600; }
.modal input, .modal textarea, .modal select { width:100%; background:#0d1424; color:var(--fg);
         border:1px solid var(--line); border-radius:8px; padding:9px 11px; font-size:13px;
         margin-bottom:10px; font-family:inherit; }
.modal textarea { min-height:96px; resize:vertical; }
.row { display:flex; gap:8px; align-items:center; }

/* ---- 问答页 ---- */
.ask-wrap { max-width:760px; margin:0 auto; padding:18px 20px 64px; }
.ask-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; }
.ask-card h3 { font-family:var(--serif); font-size:14px; margin:0 0 8px; font-weight:600; }
#chat { height:44vh; overflow-y:auto; display:flex; flex-direction:column; gap:10px; padding:8px 2px; }
.msg { max-width:84%; padding:9px 13px; border-radius:12px; white-space:pre-wrap;
       font-size:14px; line-height:1.6; }
.msg.user { align-self:flex-end; background:var(--acc); color:#241d08; }
.msg.assistant { align-self:flex-start; background:var(--card2); border:1px solid var(--line); }
.ask-card textarea { width:100%; background:#0d1424; color:var(--fg); border:1px solid var(--line);
        border-radius:8px; padding:9px 11px; font-size:13px; font-family:inherit; resize:vertical; min-height:56px; }
.ask-card select { background:#0d1424; color:var(--fg); border:1px solid var(--line); border-radius:8px;
        padding:7px 9px; font-size:13px; margin-bottom:8px; }
.muted { color:var(--dim); font-size:12px; }
pre.out { white-space:pre-wrap; background:#0d1424; border:1px solid var(--line); border-radius:8px;
          padding:10px 12px; font-size:12px; font-family:var(--mono); overflow-x:auto; }

@media (max-width:760px) {
  .shell { flex-direction:column; }
  .sidebar { width:100%; border-right:0; border-bottom:1px solid var(--line);
             display:flex; flex-wrap:wrap; gap:6px; padding:10px; }
  .eyebrow { display:none; }
  #tree { display:contents; }
  .layer { width:auto; }
  .main { padding:14px; }
}
@media (prefers-reduced-motion: reduce) { * { animation:none !important; transition:none !important; } }
"""


# ================================================================ 记忆工作台页
WORK_BODY = r"""
<header>
  <span class="brand">外置<em>大脑</em></span>
  <span class="tag" id="backend"></span>
  <span class="sp"></span>
  <a class="navbtn" href="/ask">问答 →</a>
  <button class="act" onclick="openAdd()">＋ 添加记忆</button>
</header>
<div class="shell">
  <aside class="sidebar">
    <div class="eyebrow">层级</div>
    <div id="tree"></div>
    <div class="eyebrow">整理</div>
    <button class="layer" id="reg-toggle" onclick="toggleReg()">
      <span class="rail" style="background:transparent"></span><span class="nm">＋ 注册项目</span>
    </button>
    <div id="reg-form">
      <input id="pj-name" placeholder="项目名">
      <input id="pj-path" placeholder="仓库路径（可选）">
      <input id="pj-charter" placeholder="charter 一句话（可选）">
      <button class="act" style="width:100%" onclick="addProject()">注册</button>
    </div>
  </aside>
  <main class="main">
    <div class="sec-head">
      <h2 id="sec-title">全局层</h2>
      <span class="sub" id="sec-sub"></span>
    </div>
    <div class="cards" id="cards"></div>
  </main>
</div>
<div class="modal-bg" id="modal">
  <div class="modal">
    <h3>添加记忆</h3>
    <textarea id="mem-content" placeholder="要记住的内容（一句话决策 / 边界 / 记录）"></textarea>
    <div class="row">
      <select id="mem-level" style="width:130px">
        <option value="decision">决策</option>
        <option value="milestone">重要修改点</option>
        <option value="note">记录</option>
      </select>
      <select id="mem-owner" style="flex:1"><option value="">全局层</option></select>
    </div>
    <div class="row" style="justify-content:flex-end">
      <button class="ghost" onclick="closeAdd()">取消</button>
      <button class="act" onclick="addMemory()">记住</button>
    </div>
  </div>
</div>
"""

WORK_JS = r"""
const $ = id => document.getElementById(id);
let CUR = { kind: 'global', pid: null, name: '全局层' };
let PROJS = [];
const API = {
  projects: async () => (await (await fetch('/api/projects')).json()).items,
  memories: async qs => (await fetch('/api/memories' + qs)).json(),
  remember: async body => (await fetch('/api/remember', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  promote: async id => (await fetch('/api/memories/'+id+'/promote', {method:'POST'})).json(),
  demote: async (id, project_id) => (await fetch('/api/memories/'+id+'/demote', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_id})})).json(),
  addProject: async body => (await fetch('/api/projects', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  sync: async id => (await fetch('/api/projects/'+id+'/sync', {method:'POST'})).json(),
};
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmt(t){ return esc(t).replace(/\[\[m:(\d+)\]\]/g, '<span class="lk">🔗 #$1</span>'); }
function makeEl(tag, cls, text){ const d = document.createElement(tag); d.className = cls || ''; d.textContent = text || ''; return d; }
window.addEventListener('unhandledrejection', e => {
  alert('错误: ' + ((e.reason && e.reason.message) || e.reason));
});

/* ---------- 层级树 (含拖拽投放) ---------- */
function treeNode(kind, pid, name, rail, cntHtml, id) {
  const btn = document.createElement('button');
  btn.className = 'layer'; btn.id = id;
  btn.innerHTML = `<span class="rail ${rail}"></span><span class="nm">${esc(name)}</span><span class="cnt">${cntHtml}</span>`;
  btn.onclick = () => selectLayer(kind, pid, name);
  btn.addEventListener('dragover', e => { e.preventDefault(); btn.classList.add('drop'); });
  btn.addEventListener('dragleave', () => btn.classList.remove('drop'));
  btn.addEventListener('drop', e => {
    e.preventDefault(); btn.classList.remove('drop');
    const mid = e.dataTransfer.getData('text/plain');
    if (mid) moveMem(Number(mid), kind, pid, name);
  });
  return btn;
}
function renderTree() {
  const box = $('tree'); box.innerHTML = '';
  box.appendChild(treeNode('global', null, '全局层', 'global', '∞', 'lg-global'));
  PROJS.forEach(p => box.appendChild(
    treeNode('project', p.id, p.name, 'project', `记忆 <b>${p.mem_count}</b>`, 'lg-p' + p.id)));
  if (!PROJS.length) box.appendChild(makeEl('div', 'muted', '(暂无项目)'));
  highlightCur();
}
function highlightCur() {
  document.querySelectorAll('.layer').forEach(x => x.classList.remove('on'));
  const el = $(CUR.kind === 'project' ? 'lg-p' + CUR.pid : 'lg-global');
  if (el) el.classList.add('on');
}
function selectLayer(kind, pid, name) {
  CUR = kind === 'project' ? { kind:'project', pid, name } : { kind:'global', pid:null, name:'全局层' };
  highlightCur();
  $('sec-title').textContent = CUR.name;
  $('sec-sub').textContent = kind === 'project'
    ? '记忆生命周期随项目绑定' : '全局层 · 生命周期无限，多项目共读';
  renderCards();
}

/* ---------- 卡片流 ---------- */
async function renderCards() {
  const qs = CUR.kind === 'project' ? '?project_id=' + CUR.pid : '?layer=global';
  const r = await API.memories(qs);
  const box = $('cards'); box.innerHTML = '';
  if (!r.items.length) {
    box.appendChild(makeEl('div', 'empty', '这一层还没有记忆 — 点右上角「＋ 添加记忆」'));
    return;
  }
  r.items.forEach(x => box.appendChild(cardEl(x)));
}
function cardEl(x) {
  const c = document.createElement('div');
  c.className = 'card'; c.draggable = true; c.dataset.mid = x.id;
  const layerBadge = x.project_id
    ? '<span class="badge b-project">项目</span>'
    : '<span class="badge b-global">全局</span>';
  const lv = esc(x.level || 'note');
  c.innerHTML =
    `<div>${layerBadge}<span class="badge b-${lv}">${lv}</span></div>` +
    `<div class="body">${fmt(x.content)}</div>` +
    `<div class="meta">#${x.id} · ${esc(x.project || x.project_name || '个人区')} · ${x.created_at}</div>` +
    `<div class="ops">` +
    (x.project_id ? `<button class="ghost" onclick="moveMem(${x.id},'global',null,'全局层')">↑ 到全局</button>` : '') +
    `<span class="muted" style="margin-left:auto">拖到左侧层级可移动</span></div>`;
  c.addEventListener('dragstart', e => {
    e.dataTransfer.setData('text/plain', String(x.id));
    c.classList.add('dragging');
  });
  c.addEventListener('dragend', () => c.classList.remove('dragging'));
  return c;
}
async function moveMem(mid, kind, pid, name) {
  try {
    if (kind === 'global') await API.promote(mid);
    else await API.demote(mid, pid);
    await reload();
    alert('记忆 #' + mid + ' → ' + (kind === 'global' ? '全局层' : '项目「' + name + '」'));
  } catch (e) { alert('移动失败: ' + ((e && e.message) || e)); }
}
async function reload() { await loadProjects(); await renderCards(); }

/* ---------- 添加记忆 / 注册项目 ---------- */
function openAdd() { $('modal').classList.add('on'); $('mem-content').focus(); }
function closeAdd() { $('modal').classList.remove('on'); }
async function addMemory() {
  const content = $('mem-content').value.trim();
  if (!content) return alert('内容不能为空');
  const body = { content, level: $('mem-level').value };
  if ($('mem-owner').value) body.project_id = Number($('mem-owner').value);
  const r = await API.remember(body);
  $('mem-content').value = '';
  closeAdd();
  await reload();
  alert('已记住 #' + r.id);
}
function toggleReg() { $('reg-form').classList.toggle('on'); }
async function addProject() {
  const body = { name: $('pj-name').value.trim(), path: $('pj-path').value.trim(),
                 charter: $('pj-charter').value.trim() };
  if (!body.name) return alert('需要项目名');
  const r = await API.addProject(body);
  try { await API.sync(r.id); } catch (e) { /* 路径无效等, 忽略 */ }
  $('pj-name').value=''; $('pj-path').value=''; $('pj-charter').value='';
  toggleReg();
  await loadProjects();
}
async function loadProjects() {
  PROJS = await API.projects();
  renderTree();
  const sel = $('mem-owner');
  const cur = sel.value;
  sel.innerHTML = '<option value="">全局层</option>' +
    PROJS.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  if (cur) sel.value = cur;
}

/* ---------- 启动 ---------- */
(async function boot() {
  const h = await (await fetch('/api/health')).json();
  $('backend').textContent = '后端: ' + h.backend;
  await loadProjects();
  selectLayer('global');
})();
"""


# ================================================================ 问答页
ASK_BODY = r"""
<header>
  <span class="brand">外置<em>大脑</em></span>
  <span class="tag" id="backend"></span>
  <span class="sp"></span>
  <a class="navbtn" href="/">← 记忆工作台</a>
</header>
<div class="ask-wrap">
  <div class="ask-card">
    <select id="ask-scope"><option value="">全局层</option></select>
    <div id="chat"></div>
    <div class="row" style="margin-top:8px">
      <textarea id="ask-input" style="flex:1" placeholder="问我任何事…（Enter 发送）"></textarea>
      <button class="act" onclick="ask()">发送</button>
    </div>
  </div>
  <div class="ask-card" style="margin-top:14px">
    <h3>边界监督（规范环）</h3>
    <select id="sup-proj"><option value="">选择项目…</option></select>
    <textarea id="sup-input" placeholder="新提议，例如：把数据库从 SQLite 换成 Postgres…"></textarea>
    <button class="act" onclick="supervise()">对照检查</button>
    <pre class="out" id="sup-out" hidden></pre>
  </div>
</div>
"""

ASK_JS = r"""
const $ = id => document.getElementById(id);
let THREAD = null;
const API = {
  projects: async () => (await (await fetch('/api/projects')).json()).items,
  ask: async body => (await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  supervise: async body => (await fetch('/api/supervise', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
};
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
window.addEventListener('unhandledrejection', e => {
  alert('错误: ' + ((e.reason && e.reason.message) || e.reason));
});
function addMsg(role, text) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.textContent = text;
  $('chat').appendChild(d);
  $('chat').scrollTop = $('chat').scrollHeight;
}
async function ask() {
  const q = $('ask-input').value.trim(); if (!q) return;
  addMsg('user', q); $('ask-input').value = '';
  const body = { question: q };
  if ($('ask-scope').value) body.project_id = Number($('ask-scope').value);
  if (THREAD) body.thread_id = THREAD;
  const out = document.createElement('div'); out.className = 'muted';
  out.textContent = '思考中…'; $('chat').appendChild(out);
  try {
    const r = await API.ask(body);
    THREAD = r.thread_id;
    out.remove();
    addMsg('assistant', r.answer);
    if (r.recalls && r.recalls.length) {
      const ref = document.createElement('div'); ref.className = 'muted';
      ref.textContent = '召回: ' + r.recalls.map(x => x.content.slice(0, 40)).join(' | ');
      $('chat').appendChild(ref);
    }
  } catch (e) { out.textContent = '错误: ' + ((e && e.message) || e); }
}
$('ask-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
});
async function supervise() {
  const pid = Number($('sup-proj').value); if (!pid) return alert('请选择项目');
  const proposal = $('sup-input').value.trim(); if (!proposal) return;
  const r = await API.supervise({ proposal, project_id: pid });
  const out = $('sup-out');
  out.hidden = false;
  out.textContent = r.report;
}
async function loadProjects() {
  const rows = await API.projects();
  const fill = sel => {
    const cur = sel.value;
    sel.innerHTML = '<option value="">全局层</option>' +
      rows.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
    if (cur) sel.value = cur;
  };
  fill($('ask-scope'));
  const sup = $('sup-proj');
  const supCur = sup.value;
  sup.innerHTML = '<option value="">选择项目…</option>' +
    rows.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  if (supCur) sup.value = supCur;
}
(async function boot() {
  const h = await (await fetch('/api/health')).json();
  $('backend').textContent = '后端: ' + h.backend;
  await loadProjects();
})();
"""


WORK_HTML = ("<!doctype html>\n<html lang=\"zh\">\n<head>\n<meta charset=\"utf-8\">\n"
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
             "<title>外置大脑 · 记忆</title>\n<style>\n" + CSS + "\n</style>\n</head>\n<body>\n"
             + WORK_BODY + "\n<script>\n" + WORK_JS + "\n</script>\n</body>\n</html>")

ASK_HTML = ("<!doctype html>\n<html lang=\"zh\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>外置大脑 · 问答</title>\n<style>\n" + CSS + "\n</style>\n</head>\n<body>\n"
            + ASK_BODY + "\n<script>\n" + ASK_JS + "\n</script>\n</body>\n</html>")


# ================================================================ FastAPI
def create_app(db_path: Optional[str] = None):
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    # 启动时确保 schema 存在; 每个请求使用独立连接 (FastAPI 同步接口跑在线程池)
    db_mod.init(db_path)

    def get_db():
        conn = db_mod.init(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app = FastAPI(title="外置大脑", version="0.2.0")

    def _page(html: str) -> HTMLResponse:
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _page(WORK_HTML)

    @app.get("/ask", response_class=HTMLResponse)
    def ask_page():
        return _page(ASK_HTML)

    @app.get("/api/health")
    def health(conn: sqlite3.Connection = Depends(get_db)):
        return {"ok": True, "backend": llm.backend(),
                "db": conn.execute("select sqlite_version()").fetchone()[0]}

    @app.get("/api/projects")
    def projects(conn: sqlite3.Connection = Depends(get_db)):
        return {"items": [dict(r) for r in proj_mod.list_projects(conn)]}

    @app.post("/api/projects")
    def add_project(body: ProjectIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            pid = proj_mod.add_project(conn, body.name, body.path, body.charter)
        except sqlite3.IntegrityError:
            raise HTTPException(400, "项目名已存在")
        return {"id": pid}

    @app.post("/api/projects/{pid}/sync")
    def sync_project(pid: int, conn: sqlite3.Connection = Depends(get_db)):
        try:
            return proj_mod.sync_project(conn, pid)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/remember")
    def remember(body: RememberIn, conn: sqlite3.Connection = Depends(get_db)):
        pid = body.project_id
        mid = mem_mod.remember(conn, body.content, level=body.level,
                               project_id=pid, reason=body.reason)
        return {"id": mid}

    @app.post("/api/capture")
    def capture(body: CaptureIn, conn: sqlite3.Connection = Depends(get_db)):
        ids = mem_mod.capture(conn, body.text, project_id=body.project_id,
                              title=body.title)
        return {"ids": ids}

    @app.get("/api/pending")
    def pending(conn: sqlite3.Connection = Depends(get_db)):
        return {"items": [dict(r) for r in mem_mod.pending_memories(conn)]}

    @app.get("/api/memories")
    def memories(project_id: Optional[int] = None,
                 level: Optional[str] = None, status: str = "active",
                 limit: int = 20, layer: Optional[str] = None,
                 conn: sqlite3.Connection = Depends(get_db)):
        items = mem_mod.list_memories(conn, project_id=project_id, level=level,
                                      status=status, limit=limit, layer=layer)
        return {"items": [dict(r) for r in items]}

    @app.post("/api/review")
    def review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            mem_mod.review(conn, body.id, body.action, new_content=body.content)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/memories/{mid}/promote")
    def promote(mid: int, conn: sqlite3.Connection = Depends(get_db)):
        """上升: 项目记忆 -> 全局层。"""
        try:
            mem_mod.promote(conn, mid)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {"ok": True, "id": mid, "project_id": None}

    @app.post("/api/memories/{mid}/demote")
    def demote(mid: int, body: DemoteIn,
               conn: sqlite3.Connection = Depends(get_db)):
        """下降: 挂到指定项目。"""
        try:
            mem_mod.demote(conn, mid, body.project_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "id": mid, "project_id": body.project_id}

    @app.get("/api/suggest")
    def suggest(conn: sqlite3.Connection = Depends(get_db)):
        """删除提示: 算法扫描候选, 删除由用户决定。"""
        return {"items": mem_mod.suggest(conn)}

    @app.post("/api/recall")
    def recall(body: RecallIn, conn: sqlite3.Connection = Depends(get_db)):
        items = mem_mod.recall(conn, body.query, k=body.k,
                               project_id=body.project_id)
        return {"items": items}

    @app.post("/api/supervise")
    def supervise(body: SuperviseIn, conn: sqlite3.Connection = Depends(get_db)):
        res = sup_mod.supervise(conn, body.proposal, project_id=body.project_id)
        if not res["ok"]:
            raise HTTPException(400, res["error"])
        return res

    @app.post("/api/ask")
    def ask(body: AskIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            res = chat_mod.ask(conn, body.question, project_id=body.project_id,
                               thread_id=body.thread_id, k=body.k,
                               with_specs=body.with_specs)
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        return res

    @app.get("/api/threads/{tid}/messages")
    def thread_messages(tid: str, conn: sqlite3.Connection = Depends(get_db)):
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages"
            " WHERE thread_id=? ORDER BY id", (tid,)
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    return app


def run(host: Optional[str] = None, port: Optional[int] = None) -> None:
    import uvicorn
    app = create_app()
    uvicorn.run(app, host=host or config.get("BRAIN_HOST"),
                port=port or config.get_int("BRAIN_PORT", 8000))
