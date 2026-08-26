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
from . import auth
from . import mcp_server as mcp_srv

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
    module: str = ""


class CaptureIn(BaseModel):
    text: str
    title: str = ""
    project_id: Optional[int] = None
    module: str = ""


class ReviewIn(BaseModel):
    id: int
    action: str = "keep"
    content: Optional[str] = None
    module: Optional[str] = None


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


class AddModuleIn(BaseModel):
    name: str


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
.layer.sub { padding-left:24px; font-size:12px; }
.layer.sub .nm { font-weight:normal; }
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
         border-radius:14px; padding:20px; box-shadow:0 20px 60px rgba(0,0,0,.5);
         max-height:88vh; overflow-y:auto; }
.modal h3 { margin:0 0 14px; font-family:var(--serif); font-size:16px; font-weight:600; }
.modal input, .modal textarea, .modal select { width:100%; background:#0d1424; color:var(--fg);
         border:1px solid var(--line); border-radius:8px; padding:9px 11px; font-size:13px;
         margin-bottom:10px; font-family:inherit; }
.modal textarea { min-height:150px; resize:vertical; }
.row { display:flex; gap:8px; align-items:center; }

/* ---- 待确认弹窗 ---- */
.pending-list { display:flex; flex-direction:column; gap:8px; max-height:52vh; overflow-y:auto; }
.pending-item { background:var(--card2); border:1px solid var(--line); border-radius:10px;
                padding:11px 13px; }
.pending-item .p-body { font-size:14px; line-height:1.6; color:var(--fg); }
.pending-item .p-meta { font-family:var(--mono); font-size:10px; color:var(--dim); margin:6px 0; }
.pending-item .p-ops { display:flex; gap:8px; justify-content:flex-end; }
.pending-item .p-ops button { padding:4px 14px; }

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

/* ---- 架构图 ---- */
.toolbar { display:flex; align-items:center; gap:8px; margin-bottom:12px; }
.toolbar .sum { font-family:var(--mono); font-size:11px; color:var(--dim); }
.zoomb { width:30px; height:28px; padding:0; }
#graph { height: calc(100vh - 210px); min-height:520px; overflow:auto;
         border:1px solid var(--line); border-radius:14px; position:relative;
         background:#f6f8fb; }
#graph svg { display:block; transform-origin:0 0; }
/* 分层块状架构图 (浅色画布, 还原参考图) */
.bandbox { fill:#ffffff; stroke:#e4e9f1; }
.bandhead { fill:#eef2f8; stroke:#e4e9f1; }
.band.bg-g .bh { fill:#2f7d4f; } .band.bg-g .bandhead { fill:#e8f5ee; }
.band.bg-p .bh { fill:#2b6cb0; } .band.bg-p .bandhead { fill:#e8f1fb; }
.band.bg-m .bh { fill:#7a4fb0; } .band.bg-m .bandhead { fill:#f1eafa; }
.band.bg-d .bh { fill:#2b6cb0; } .band.bg-d .bandhead { fill:#e8f1fb; }
.band.bg-n .bh { fill:#67707f; } .band.bg-n .bandhead { fill:#f0f2f5; }
.bh { fill:#2a3342; font-size:14px; font-weight:bold; font-family:Georgia,"Songti SC",serif; }
.bs { fill:#8b95a9; font-size:11px; }
.hd-g{fill:#e8f5ee;} .hd-p{fill:#e8f1fb;} .hd-m{fill:#f1eafa;} .hd-d{fill:#e8f1fb;} .hd-n{fill:#f0f2f5;}
.box { cursor:pointer; }
.box rect { fill:#fff; stroke:#cfd8e4; stroke-width:1; transition:stroke .15s; }
.box:hover rect { stroke:#5b8def; stroke-width:2; }
.bt { fill:#1f2733; font-size:12px; }
/* 项目卡片独立色 (区别于记忆方块) */
.projcard rect { fill:#eef6ff; stroke:#7fb0ff; stroke-width:1; }
.projcard:hover rect { stroke:#3c82f6; stroke-width:2; }
.projcard .bt { fill:#2b6cb0; font-weight:bold; }
.projcard .bm { fill:#5b8def; }
/* 列头模块/等级着色 */
.colhead { stroke:#dfe6ef; stroke-width:1; }
.bm { fill:#8b95a9; font-size:10px; font-family:ui-monospace,Menlo,monospace; }
.box .inner { fill:#f4f7fb; stroke:#e4e9f1; }
.rail-global { fill:#e0b15c; }
.rail-project { fill:#5b8def; }
.flow { stroke:#9aa5b5; stroke-width:2; }
.cap { fill:#5a6474; font-size:14px; font-family:Georgia,"Songti SC",serif; font-weight:bold; }

/* ---- 大弹窗 (记忆详情/编辑) ---- */
.modal-lg { width:min(860px,95vw); }
.modal-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
.modal-head h3 { margin:0; }
.modal-x { background:transparent; border:1px solid var(--line); border-radius:8px; color:var(--dim);
           width:32px; height:32px; cursor:pointer; font-size:15px; line-height:1; }
.modal-x:hover { color:var(--fg); border-color:var(--acc); }
.modal-lg .meta { font-family:var(--mono); font-size:11px; color:var(--dim); margin-bottom:10px; }
.m-preview { background:#0d1424; border:1px solid var(--line); border-radius:8px; padding:10px;
             font-size:13px; white-space:pre-wrap; margin-bottom:8px; max-height:180px; overflow-y:auto; }
.m-preview a { color:var(--acc); cursor:pointer; }
.modal-lg .links { font-size:12px; color:var(--dim); margin:10px 0; }
.modal-lg .links a { color:var(--acc); cursor:pointer; margin-right:10px; }
.modal-lg .row { margin-top:8px; }

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
  <button class="navbtn" onclick="openPending()">待确认 <b id="pending-count">0</b></button>
  <a class="navbtn" href="/ask">问答 →</a>
</header>
<div class="shell">
  <aside class="sidebar">
    <div class="eyebrow">层级</div>
    <div id="tree"></div>
    <div class="eyebrow">整理</div>
    <button class="layer" id="reg-toggle" onclick="toggleReg()">
      <span class="rail" style="background:transparent"></span><span class="nm">＋ 添加项目</span>
    </button>
    <div id="reg-form">
      <input id="pj-name" placeholder="项目名">
      <input id="pj-path" placeholder="仓库路径（可选）">
      <input id="pj-charter" placeholder="charter 一句话（可选）">
      <button class="act" style="width:100%" onclick="addProject()">注册</button>
    </div>
  </aside>
  <main class="main">
    <div class="toolbar">
      <button class="ghost zoomb" onclick="zoom(1.25)" title="放大">＋</button>
      <button class="ghost zoomb" onclick="zoom(0.8)" title="缩小">－</button>
      <button class="ghost zoomb" onclick="zoomFit()" title="适应">⛶</button>
      <span class="sum" id="graph-sum"></span>
      <span style="flex:1"></span>
      <button class="act" onclick="openAdd()">＋ 添加记忆</button>
    </div>
    <div id="graph"></div>
  </main>
</div>

<div class="modal-bg" id="modal">
  <div class="modal modal-lg">
    <div class="modal-head">
      <h3 id="m-title">记忆详情</h3>
      <button class="modal-x" onclick="closeModal()" title="关闭">✕</button>
    </div>
    <div class="meta" id="m-meta"></div>
    <div class="m-preview" id="m-preview"></div>
    <textarea id="m-content" placeholder="记忆内容…"></textarea>
    <div class="row">
      <select id="m-level" style="width:150px">
        <option value="decision">决策</option>
        <option value="note">记录</option>
      </select>
      <select id="m-owner" style="flex:1" onchange="populateModuleSelect()"><option value="">全局层</option></select>
      <span class="muted" id="m-owner-hint"></span>
    </div>
    <div class="row">
      <span class="muted" style="width:150px">模块（底部，选项目后可选）</span>
      <select id="m-module" style="flex:1" disabled><option value="">（全局层无模块）</option></select>
    </div>
    <div class="links" id="m-links"></div>
    <div class="row" style="justify-content:flex-end">
      <button class="ghost" id="btn-del" onclick="delMem()">删除</button>
      <button class="ghost" id="btn-move" onclick="applyMove()">移动到所选</button>
      <button class="act" id="btn-save" onclick="saveEdit()">保存修改</button>
    </div>
  </div>
</div>

<div class="modal-bg" id="pending-modal">
  <div class="modal">
    <div class="modal-head">
      <h3>待确认决策</h3>
      <button class="modal-x" onclick="closePending()" title="关闭">✕</button>
    </div>
    <div id="pending-list" class="pending-list"></div>
    <div class="row" style="justify-content:flex-end;margin-top:10px">
      <button class="ghost" onclick="reviewAllPending('delete')">全部删除</button>
      <button class="act" onclick="reviewAllPending('keep')">全部保留</button>
    </div>
  </div>
</div>
"""

WORK_JS = r"""const $ = id => document.getElementById(id);
let PROJS = [], MEMS = [], LINKS = [];
const EXPANDED = new Set();
let FOCUS_MODULE = null;   // 当前 focus 的模块名 (叶子层)
let MODULES = {};   // pid -> [声明的模块名]
let CUR_MID = null;
const API = {
  projects: async () => (await (await fetch('/api/projects')).json()).items,
  memories: async qs => (await fetch('/api/memories' + qs)).json(),
  links: async () => (await fetch('/api/links')).json(),
  remember: async body => (await fetch('/api/remember', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  promote: async id => (await fetch('/api/memories/'+id+'/promote', {method:'POST'})).json(),
  demote: async (id, project_id) => (await fetch('/api/memories/'+id+'/demote', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_id})})).json(),
  review: async body => (await fetch('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  addProject: async body => (await fetch('/api/projects', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  sync: async id => (await fetch('/api/projects/'+id+'/sync', {method:'POST'})).json(),
  addModule: async (id, name) => (await fetch('/api/projects/'+id+'/modules', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})})).json(),
};
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function linkify(t){ return esc(t).replace(/\[\[m:(\d+)\]\]/g, '<a onclick="openMem($1)">🔗 #$1</a>'); }
function makeEl(tag, cls, text){ const d = document.createElement(tag); d.className = cls || ''; d.textContent = text || ''; return d; }
function short(t){ return (t||'').replace(/\s+/g, ' ').slice(0, 18); }
window.addEventListener('unhandledrejection', e => {
  alert('错误: ' + ((e.reason && e.reason.message) || e.reason));
});
const LN = { decision:'决策', note:'记录' };

async function loadAll() {
  const [p, m, l] = await Promise.all([API.projects(), API.memories('?status=active&limit=500'), API.links()]);
  PROJS = p; MEMS = m.items; LINKS = l.items;
  const mods = await Promise.all(p.map(async pr => [pr.id, (await (await fetch('/api/projects/'+pr.id+'/modules')).json()).items]));
  MODULES = Object.fromEntries(mods);
  fillOwnerSelect();
  renderSidebar(); renderGraph();
}
function fillOwnerSelect() {
  const sel = $('m-owner');
  const cur = sel.value;
  sel.innerHTML = '<option value="">全局层</option>' + PROJS.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
  if (cur) sel.value = cur;
}
function populateModuleSelect() {
  const sel = $('m-module');
  const pid = $('m-owner').value;
  const cur = sel.value;
  if (!pid) { sel.innerHTML = '<option value="">（全局层无模块）</option>'; sel.disabled = true; }
  else {
    const mods = [...new Set(MEMS.filter(m => m.project_id === Number(pid)).map(m => m.module || '').filter(Boolean))];
    sel.innerHTML = '<option value="">无模块</option>' + mods.map(mod => `<option value="${esc(mod)}">${esc(mod)}</option>`).join('');
    sel.disabled = !mods.length;
  }
  if (cur) sel.value = cur;
}

/* ---- 侧边栏 (快速选择) ---- */
function treeBtn(kind, pid, name, rail, cntHtml, id) {
  const b = document.createElement('button');
  b.className = 'layer'; b.id = id;
  b.innerHTML = `<span class="rail ${rail}"></span><span class="nm">${esc(name)}</span><span class="cnt">${cntHtml}</span>`;
  b.onclick = () => selectSidebar(kind, pid);
  return b;
}
function renderSidebar() {
  const box = $('tree'); box.innerHTML = '';
  box.appendChild(treeBtn('global', null, '全局层', 'global', '∞', 'lg-global'));
  PROJS.forEach(p => {
    box.appendChild(treeBtn('project', p.id, p.name, 'project', `记忆 <b>${p.mem_count}</b>`, 'lg-p' + p.id));
    // 展开项目时显示其模块子节点 (树状)
    if (EXPANDED.has(p.id)) {
      const mods = [...new Set([...(MODULES[p.id] || []), ...MEMS.filter(m => m.project_id === p.id).map(m => m.module || '').filter(Boolean)])];
      mods.forEach(mod => {
        const cnt = MEMS.filter(m => m.project_id === p.id && (m.module || '') === mod).length;
        const b = document.createElement('button');
        b.className = 'layer sub'; b.id = 'lg-m-' + p.id + '-' + mod;
        b.innerHTML = `<span class="rail" style="width:3px;height:10px;background:#3c82f6"></span><span class="nm">${esc(mod)}</span><span class="cnt">${cnt}</span>`;
        b.onclick = () => openModule(p.id, mod);
        box.appendChild(b);
      });
      const ab = document.createElement('button');
      ab.className = 'layer sub'; ab.id = 'lg-addm-' + p.id;
      ab.innerHTML = `<span class="rail" style="background:transparent"></span><span class="nm" style="color:var(--acc)">＋ 添加模块</span>`;
      ab.onclick = () => addModule(p.id);
      box.appendChild(ab);
    }
  });
  if (!PROJS.length) box.appendChild(makeEl('div', 'muted', '(暂无项目)'));
  document.querySelectorAll('.layer').forEach(x => x.classList.remove('on'));
  // 高亮: 模块 > 项目 > 全局层
  let sel = 'lg-global';
  if (FOCUS_MODULE && EXPANDED.size === 1) sel = 'lg-m-' + [...EXPANDED][0] + '-' + FOCUS_MODULE;
  else if (EXPANDED.size === 1) sel = 'lg-p' + [...EXPANDED][0];
  const el = $(sel); if (el) el.classList.add('on');
}
function selectSidebar(kind, pid) {
  if (kind === 'project') { if (!EXPANDED.has(pid)) EXPANDED.add(pid); else EXPANDED.delete(pid); FOCUS_MODULE = null; renderGraph(); renderSidebar(); }
  else { EXPANDED.clear(); FOCUS_MODULE = null; renderGraph(); renderSidebar(); }
  $('graph').scrollTop = 0;
}

/* ---- 架构图: 全局/项目/模块 三层, 每层两横向划分; 默认=全局大框(两列+嵌套项目框); 项目=大框(两列+模块框); 模块=大框(两列, 叶子) ---- */
function renderGraph() {
  const globals = MEMS.filter(m => !m.project_id);
  const selProj = EXPANDED.size ? PROJS.find(p => EXPANDED.has(p.id)) : null;
  const selProjMems = selProj ? MEMS.filter(m => m.project_id === selProj.id) : [];
  const selMod = FOCUS_MODULE;
  const selModMems = selProj ? selProjMems.filter(m => (m.module || '') === selMod) : [];
  const cont = document.getElementById('graph');
  const W = Math.max(cont.clientWidth || 1200, 900);
  const padX = 28, HEAD = 56, G_H = 36, GAP = 22, BOX_H = 52, BOXGAP = 10, IN = 14, XGAP = 18;
  const boxLeft = padX, boxW = W - padX * 2;
  const innerLeft = boxLeft + IN, innerW = boxW - IN * 2;
  const levels = [ ['decision','决策','#2b6cb0','#e8f1fb'], ['note','记录','#67707f','#f0f2f5'] ];
  function head(x, y, w, tint, col, title, sub) {
    return `<rect x="${x}" y="${y}" width="${w}" height="${G_H}" rx="16" fill="${tint}"/>` +
      `<text x="${x + IN}" y="${y + G_H / 2 + 6}" class="bh" style="fill:${col}">${title}</text>` +
      `<text x="${x + w - 14}" y="${y + G_H / 2 + 6}" class="bs" text-anchor="end">${sub}</text>`;
  }
  function memBox(m, x, y, w, col) {
    const t1 = (m.content || '').replace(/\s+/g, ' ');
    const a = t1.slice(0, 18) + (t1.length > 18 ? '…' : '');
    const b = t1.length > 18 ? t1.slice(18, 36) + (t1.length > 36 ? '…' : '') : '';
    return `<g class="box" onclick="openMem(${m.id})"><rect x="${x}" y="${y}" width="${w}" height="${BOX_H}" rx="9"/>` +
      `<rect x="${x}" y="${y + 8}" width="4" height="${BOX_H - 16}" rx="2" fill="${col}"/>` +
      `<text x="${x + 12}" y="${y + 20}" class="bt">${esc(a)}</text>` + (b ? `<text x="${x + 12}" y="${y + 33}" class="bt">${esc(b)}</text>` : '') +
      `<text x="${x + 12}" y="${y + BOX_H - 6}" class="bm">#${m.id} · ${(m.created_at || '').slice(0, 10)}${m.module ? ' · ' + esc(m.module) : ''}</text></g>`;
  }
  function levelColumns(ms, ox, oy) {
    let s = '';
    const colW = (innerW - GAP * (levels.length - 1)) / levels.length;
    const cols = levels.map(([lv, n, c, t]) => ({ lv, name: n, col: c, tint: t, mems: ms.filter(m => m.level === lv) }));
    const maxPer = Math.max(...cols.map(c => c.mems.length), 1);
    const gh = G_H + 12 + maxPer * BOX_H + (maxPer - 1) * BOXGAP + 8;
    cols.forEach((c, i) => {
      const cx = ox + i * (colW + GAP);
      s += `<g><rect x="${cx}" y="${oy}" width="${colW}" height="${gh}" rx="12" class="bandbox"/>` +
        `<rect x="${cx}" y="${oy}" width="${colW}" height="${G_H}" rx="12" fill="${c.tint}"/>` +
        `<text x="${cx + 10}" y="${oy + G_H / 2 + 6}" class="bh" style="fill:${c.col}">${c.name}</text>` +
        `<text x="${cx + colW - 38}" y="${oy + G_H / 2 + 6}" class="bs" text-anchor="end">${c.mems.length} 条</text>` +
        `<text x="${cx + colW - 14}" y="${oy + G_H / 2 + 6}" class="bs" style="fill:${c.col};cursor:pointer" text-anchor="middle" onclick="openAddLevel('${c.lv}')">＋</text></g>`;
      let by = oy + G_H + 12;
      if (!c.mems.length) s += `<text x="${cx + 12}" y="${by + 22}" class="bs">无记忆</text>`;
      else c.mems.forEach(m => { s += memBox(m, cx + 10, by, colW - 20, c.col); by += BOX_H + BOXGAP; });
    });
    return { s, gh };
  }

  let bg = '';
  let contentBottom = 0;
  if (selMod && selProj) {
    // ---- 模块视图 (叶子): 两横向划分 ----
    const { s, gh } = levelColumns(selModMems, innerLeft, HEAD + G_H + 18);
    const pvH = G_H + 18 + gh + 30;
    bg += `<rect x="${boxLeft}" y="${HEAD}" width="${boxW}" height="${pvH}" rx="16" class="bandbox"/>`;
    bg += head(boxLeft, HEAD, boxW, '#e8f5ee', '#2f7d4f', '模块「' + esc(selMod) + '」', selModMems.length + ' 条记忆');
    bg += s;
    bg += `<text x="${W / 2}" y="${HEAD + pvH + 18}" class="bs" text-anchor="middle">← 点击项目「${esc(selProj.name)}」/ 侧边栏返回 · 记忆卡片点开编辑</text>`;
    contentBottom = HEAD + pvH + 18;
  } else if (selProj) {
    // ---- 项目视图: 两横向划分 + 嵌套模块框(有模块) ----
    const { s, gh } = levelColumns(selProjMems, innerLeft, HEAD + G_H + 18);
    const modTint = ['#e8f1fb','#f1eafa','#e8f5ee','#fbeede','#f0f2f5'];
    const mods = [...new Set([...(MODULES[selProj.id] || []), ...selProjMems.map(m => m.module || '').filter(Boolean)])];
    let modFrameH = 0;
    if (mods.length) {
      const rowN = 3, gap = 16;
      const cardH = 62;   // 模块卡紧凑固定高
      modFrameH = G_H + 14 + Math.ceil(mods.length / rowN) * cardH + (Math.ceil(mods.length / rowN) - 1) * gap + 14;
    }
    const pvH = G_H + 18 + gh + (mods.length ? XGAP + modFrameH : 0) + 30;
    bg += `<rect x="${boxLeft}" y="${HEAD}" width="${boxW}" height="${pvH}" rx="16" class="bandbox"/>`;
    bg += head(boxLeft, HEAD, boxW, '#f1eafa', '#7a4fb0', '项目「' + esc(selProj.name) + '」', selProjMems.length + ' 条记忆');
    bg += s;
    if (mods.length) {
      const mTop = HEAD + G_H + 18 + gh + XGAP;
      bg += `<rect x="${innerLeft}" y="${mTop}" width="${innerW}" height="${modFrameH}" rx="14" class="bandbox"/>`;
      bg += head(innerLeft, mTop, innerW, '#e8f1fb', '#2b6cb0', '模块（次级竖向划分）', mods.length + ' 个');
      bg += `<text x="${innerLeft + innerW - 80}" y="${mTop + G_H / 2 + 6}" class="bs" style="fill:#2b6cb0;cursor:pointer" onclick="addModule(${selProj.id})">＋ 模块</text>`;
      const rowN = 3, gap = 16, pw = (innerW - 2 * IN - (rowN - 1) * gap) / rowN, cardH = 62;
      let mx = innerLeft + IN, my = mTop + G_H + 20;
      mods.forEach((mod, i) => {
        if (i > 0 && i % rowN === 0) { mx = innerLeft + IN; my += cardH + gap; }
        const ms = selProjMems.filter(m => (m.module || '') === mod);
        const tint = modTint[i % modTint.length];
        bg += `<g class="box" onclick="openModule(${selProj.id}, '${mod.replace(/'/g, "\\'")}')">` +
          `<rect x="${mx}" y="${my}" width="${pw}" height="${cardH}" rx="12" class="bandbox"/>` +
          `<rect x="${mx}" y="${my}" width="${pw}" height="34" rx="12" fill="${tint}"/>` +
          `<text x="${mx + 10}" y="${my + 23}" class="bt" style="fill:#3c82f6;font-weight:bold">${esc(mod)}</text>` +
          `<text x="${mx + pw - 10}" y="${my + 23}" class="bs" text-anchor="end">${ms.length} 条</text>` +
          `<text x="${mx + 10}" y="${my + cardH - 6}" class="bs" style="fill:#8b95a9">点击进入其结构 →</text></g>`;
        mx += pw + gap;
      });
    }
    bg += `<text x="${W / 2}" y="${HEAD + pvH + 18}" class="bs" text-anchor="middle">← 侧边栏「全局层」返回总览 · 记忆卡片点开编辑</text>`;
    contentBottom = HEAD + pvH + 18;
  } else {
    // ---- 全局视图: 两横向划分 + 嵌套项目框 ----
    const { s, gh } = levelColumns(globals, innerLeft, HEAD + G_H + 18);
    const rowN = 4, pw = (innerW - 2 * IN - (rowN - 1) * 16) / rowN, ph = 96;
    const projRows = Math.max(1, Math.ceil(PROJS.length / rowN));
    const projFrameH = G_H + 14 + projRows * ph + (projRows - 1) * 12 + 14;
    const globalH = G_H + 18 + gh + XGAP + projFrameH + 16;
    bg += `<rect x="${boxLeft}" y="${HEAD}" width="${boxW}" height="${globalH}" rx="16" class="bandbox"/>`;
    bg += head(boxLeft, HEAD, boxW, '#e8f5ee', '#2f7d4f', '全局层 ∞', `${globals.length} 条记忆`);
    bg += s;
    const projTop = HEAD + G_H + 18 + gh + XGAP;
    bg += `<rect x="${innerLeft}" y="${projTop}" width="${innerW}" height="${projFrameH}" rx="14" class="bandbox"/>`;
    bg += head(innerLeft, projTop, innerW, '#e8f1fb', '#2b6cb0', '项目（竖向划分）', `${PROJS.length} 个`);
    let bx = innerLeft + IN, byy = projTop + G_H + 20;
    PROJS.forEach((p, i) => {
      if (i > 0 && i % rowN === 0) { bx = innerLeft + IN; byy += ph + 12; }
      bg += `<g class="box" onclick="toggleProj(${p.id})">` +
        `<rect x="${bx}" y="${byy}" width="${pw}" height="${ph}" rx="12" class="bandbox"/>` +
        `<rect x="${bx}" y="${byy}" width="${pw}" height="30" rx="12" fill="#e8f1fb"/>` +
        `<text x="${bx + 12}" y="${byy + 21}" class="bt" style="fill:#2b6cb0;font-weight:bold">${esc(p.name)}</text>` +
        `<text x="${bx + 12}" y="${byy + 48}" class="bm" style="fill:#5b8def">${p.mem_count} 条记忆</text>` +
        `<text x="${bx + 12}" y="${byy + 64}" class="bs">${esc((p.charter || '').slice(0, 22))}</text>` +
        `<text x="${bx + 12}" y="${byy + 84}" class="bs" style="fill:#8b95a9">点击进入 →</text></g>`;
      bx += pw + 16;
    });
    if (!PROJS.length) bg += `<text x="${innerLeft + IN}" y="${byy + 22}" class="bs">暂无项目</text>`;
    contentBottom = HEAD + globalH + 16;
  }

  const H = Math.max(cont.clientHeight || 640, contentBottom + padX);
  const svg = `<svg id="graph-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="${W}" height="${H}" fill="#f6f8fb"/>` + bg + '</svg>';
  $('graph').innerHTML = svg;
  $('graph-svg').style.transform = 'scale(1)';
  $('graph-sum').textContent = `记忆 ${MEMS.length} · 全局 ${globals.length} · 项目 ${PROJS.length}` + (selMod ? ' · 模块：' + selMod : selProj ? ' · 项目：' + selProj.name : '');
}

function toggleProj(pid) {
  if (EXPANDED.has(pid)) EXPANDED.delete(pid); else EXPANDED.add(pid);
  FOCUS_MODULE = null;
  renderGraph(); renderSidebar();
}
function openModule(pid, mod) {
  EXPANDED.add(pid); FOCUS_MODULE = mod;
  renderGraph(); renderSidebar();
}
async function addModule(pid) {
  const name = prompt('新模块名');
  if (!name) return;
  try { await API.addModule(pid, name); } catch (e) { alert('添加失败: ' + ((e && e.message) || e)); }
  await loadAll();
}
function zoom(f) {
  const svg = $('graph-svg'); if (!svg) return;
  const cur = parseFloat(svg.style.transform.replace(/[^0-9.]/g,'') || '1');
  const nxt = Math.min(2.5, Math.max(0.4, cur * f));
  svg.style.transform = `scale(${nxt})`; svg.style.transformOrigin = '0 0';
}
function zoomFit() { const svg = $('graph-svg'); if (svg) { svg.style.transform = 'scale(1)'; svg.style.transformOrigin = '0 0'; } }

/* ---- 记忆弹窗 (查看/编辑/迁移/删除) ---- */
function openMem(mid) {
  const m = MEMS.find(x => x.id === mid); if (!m) return;
  CUR_MID = mid;
  $('m-title').textContent = '记忆详情';
  $('m-content').value = m.content;
  $('m-level').value = m.level || 'note';
  $('m-owner').value = m.project_id || '';
  populateModuleSelect();
  $('m-module').value = m.module || '';
  $('m-meta').textContent = `#${m.id} · ${m.project_id ? '项目「' + (m.project_name || '') + '」' : '全局层'} · ${m.created_at} · ${m.source_type === 'auto' ? '自动捕获' : '主动记忆'}`;
  $('m-preview').innerHTML = linkify(m.content);
  $('m-owner-hint').textContent = m.project_id ? '（改为全局层 = 上升）' : '（选择项目 = 下降）';
  const outs = LINKS.filter(l => l.source_id === mid).map(l => l.target_id);
  const ins = LINKS.filter(l => l.target_id === mid).map(l => l.source_id);
  const build = [];
  outs.forEach(t => { const tm = MEMS.find(x => x.id === t); build.push(`<span>→ <a onclick="openMem(${t})">#${t}${tm ? ' · ' + esc(tm.content.slice(0, 14)) : ''}</a></span>`); });
  ins.forEach(s => { const sm = MEMS.find(x => x.id === s); build.push(`<span>← <a onclick="openMem(${s})">#${s}${sm ? ' · ' + esc(sm.content.slice(0, 14)) : ''}</a></span>`); });
  $('m-links').innerHTML = build.length ? '链接：' + build.join('') : '链接：无';
  $('btn-del').style.display = ''; $('btn-move').style.display = ''; $('btn-save').textContent = '保存修改';
  $('modal').classList.add('on');
}
function closeModal() { $('modal').classList.remove('on'); CUR_MID = null; }
async function saveEdit() {
  if (CUR_MID == null) return saveAdd();
  const content = $('m-content').value.trim(); if (!content) return alert('内容不能为空');
  await API.review({ id: CUR_MID, action: 'edit', content, module: $('m-module').value });
  await loadAll(); closeModal(); alert('已保存 #' + CUR_MID);
}
async function applyMove() {
  if (CUR_MID == null) return;
  const owner = $('m-owner').value;
  if (owner === '') await API.promote(CUR_MID); else await API.demote(CUR_MID, Number(owner));
  await loadAll(); closeModal(); alert('已移动 #' + CUR_MID + (owner === '' ? ' → 全局层' : ' → 项目'));
}
async function delMem() {
  if (CUR_MID == null) return;
  if (!confirm('确定删除记忆 #' + CUR_MID + ' 吗？')) return;
  await API.review({ id: CUR_MID, action: 'delete' });
  await loadAll(); closeModal(); alert('已删除 #' + CUR_MID);
}

/* ---- 添加记忆 / 注册项目 ---- */
function openAdd() {
  $('m-content').value = ''; $('m-level').value = 'decision';
  $('m-owner').value = EXPANDED.size === 1 ? String([...EXPANDED][0]) : '';
  populateModuleSelect();
  $('m-module').value = '';
  $('m-meta').textContent = '新建记忆'; $('m-links').textContent = ''; $('m-preview').textContent = '';
  $('m-title').textContent = '新建记忆';
  $('btn-del').style.display = 'none'; $('btn-move').style.display = 'none'; $('btn-save').textContent = '记住';
  CUR_MID = null;
  $('modal').classList.add('on'); $('m-content').focus();
}
function openAddLevel(level) {
  openAdd();
  $('m-level').value = level || 'decision';
  $('m-owner').value = EXPANDED.size === 1 ? String([...EXPANDED][0]) : '';
  populateModuleSelect();
  $('m-module').value = FOCUS_MODULE || '';
}
async function saveAdd() {
  const content = $('m-content').value.trim(); if (!content) return alert('内容不能为空');
  const body = { content, level: $('m-level').value };
  if ($('m-module').value) body.module = $('m-module').value;
  if ($('m-owner').value) body.project_id = Number($('m-owner').value);
  const r = await API.remember(body);
  await loadAll(); closeModal(); alert('已记住 #' + r.id);
}
function toggleReg() { $('reg-form').classList.toggle('on'); }
async function addProject() {
  const body = { name: $('pj-name').value.trim(), path: $('pj-path').value.trim(), charter: $('pj-charter').value.trim() };
  if (!body.name) return alert('需要项目名');
  const r = await API.addProject(body);
  try { await API.sync(r.id); } catch (e) { /* 路径无效等, 忽略 */ }
  $('pj-name').value=''; $('pj-path').value=''; $('pj-charter').value=''; toggleReg();
  await loadAll();
}
$('modal').addEventListener('click', e => { if (e.target === $('modal')) closeModal(); });
$('m-content').addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
$('pending-modal').addEventListener('click', e => { if (e.target === $('pending-modal')) closePending(); });

/* ---- 待确认决策 (强确认弹窗) ---- */
async function loadPending() {
  try {
    const r = await (await fetch('/api/pending')).json();
    const items = r.items || [];
    $('pending-count').textContent = items.length;
    $('pending-list').innerHTML = items.map(m =>
      `<div class="pending-item">
        <div class="p-body">${esc(m.content)}</div>
        <div class="p-meta">#${m.id} · ${m.project_name || '全局层'} · ${(m.created_at || '').slice(0, 16)}</div>
        <div class="p-ops">
          <button class="ghost" onclick="reviewPending(${m.id},'keep')">保留</button>
          <button class="ghost" onclick="reviewPending(${m.id},'delete')">删除</button>
        </div>
      </div>`).join('') || '<div class="muted">暂无待确认决策 🎉</div>';
  } catch (e) {}
}
function openPending() { $('pending-modal').classList.add('on'); }
function closePending() { $('pending-modal').classList.remove('on'); }
async function reviewPending(id, action) {
  await API.review({ id, action });
  await loadPending();
  await loadAll();
}
async function reviewAllPending(action) {
  const r = await (await fetch('/api/pending')).json();
  for (const m of (r.items || [])) await API.review({ id: m.id, action });
  await loadPending();
  await loadAll();
}

(async function boot() {
  const h = await (await fetch('/api/health')).json();
  $('backend').textContent = '后端: ' + h.backend;
  await loadAll();
  await loadPending();
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
    from pathlib import Path
    from fastapi import Body, Depends, FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    # 启动时确保 schema 存在; 每个请求使用独立连接 (FastAPI 同步接口跑在线程池)
    db_mod.init(db_path)

    def get_db():
        # 每个请求只连库, 不重新执行 schema 初始化 (启动时已 init 一次)
        conn = db_mod.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app = FastAPI(title="外置大脑", version="0.3.0")
    # 鉴权中间件: 设了 LCLONE_API_KEY 时保护 /api/* 与 /mcp

    @app.middleware("http")
    async def auth_mw(request, call_next):
        return await auth.enforce(request, call_next)
    # 静态资源目录可选: 当前 HTML/CSS/JS 全部内联, 无需外部静态文件;
    # 仅当 static/ 存在时才挂载, 避免目录缺失导致应用启动即崩。
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.post("/mcp")
    async def mcp_endpoint(body: dict = Body(...)):
        """MCP over HTTP: JSON-RPC 请求, 复用 mcp_server.handle_message 分发。"""
        resp = mcp_srv.handle_message(body)
        if resp is None:
            return JSONResponse(None, status_code=202)
        return JSONResponse(resp)

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

    @app.get("/api/projects/{pid}/modules")
    def project_modules(pid: int, conn: sqlite3.Connection = Depends(get_db)):
        return {"items": proj_mod.list_modules(conn, pid)}

    @app.post("/api/projects/{pid}/modules")
    def add_project_module(pid: int, body: AddModuleIn,
                           conn: sqlite3.Connection = Depends(get_db)):
        try:
            proj_mod.add_module(conn, pid, body.name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/remember")
    def remember(body: RememberIn, conn: sqlite3.Connection = Depends(get_db)):
        pid = body.project_id
        mid = mem_mod.remember(conn, body.content, level=body.level,
                               project_id=pid, reason=body.reason, module=body.module)
        return {"id": mid}

    @app.post("/api/capture")
    def capture(body: CaptureIn, conn: sqlite3.Connection = Depends(get_db)):
        ids = mem_mod.capture(conn, body.text, project_id=body.project_id,
                              title=body.title, module=body.module)
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

    @app.get("/api/links")
    def links(conn: sqlite3.Connection = Depends(get_db)):
        """记忆链接表 (架构图连线用)。"""
        rows = conn.execute(
            "SELECT source_id, target_id FROM memory_links ORDER BY id"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.post("/api/review")
    def review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            mem_mod.review(conn, body.id, body.action, new_content=body.content,
                           new_module=body.module)
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
