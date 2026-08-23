"""Web 面板: FastAPI + 单页 HTML。任何电脑浏览器打开即可访问大脑。"""

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

HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>外置大脑</title>
<style>
  :root { --bg:#0f1115; --card:#171a21; --line:#2a2f3a; --fg:#e6e9ef;
          --dim:#8b93a3; --acc:#4f8cff; --ok:#3fb950; --warn:#d29922; --bad:#f85149; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--fg); }
  header { display:flex; align-items:center; gap:12px; padding:10px 16px;
           border-bottom:1px solid var(--line); }
  header h1 { font-size:16px; margin:0; }
  header .tag { font-size:12px; color:var(--dim); }
  nav { display:flex; gap:4px; padding:8px 16px; border-bottom:1px solid var(--line); }
  nav button { background:transparent; color:var(--dim); border:1px solid transparent;
               padding:6px 12px; border-radius:8px; cursor:pointer; font-size:13px; }
  nav button.on { color:var(--fg); background:var(--card); border-color:var(--line); }
  main { max-width:860px; margin:0 auto; padding:16px; }
  .panel { display:none; }
  .panel.on { display:block; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:12px 14px; margin-bottom:12px; }
  .card h3 { margin:0 0 8px; font-size:14px; }
  .muted { color:var(--dim); font-size:12px; }
  input, textarea, select { width:100%; background:#10131a; color:var(--fg);
          border:1px solid var(--line); border-radius:8px; padding:8px 10px;
          font-size:14px; font-family:inherit; margin-bottom:8px; }
  textarea { min-height:64px; resize:vertical; }
  button.act { background:var(--acc); color:#fff; border:0; border-radius:8px;
          padding:8px 16px; cursor:pointer; font-size:14px; }
  button.ghost { background:transparent; color:var(--fg); border:1px solid var(--line);
          border-radius:8px; padding:6px 10px; cursor:pointer; font-size:12px; }
  #chat { height:52vh; overflow-y:auto; display:flex; flex-direction:column; gap:10px;
          padding:10px; }
  .msg { max-width:80%; padding:8px 12px; border-radius:10px; white-space:pre-wrap;
         font-size:14px; line-height:1.55; }
  .msg.user { align-self:flex-end; background:var(--acc); color:#fff; }
  .msg.assistant { align-self:flex-start; background:var(--card);
                   border:1px solid var(--line); }
  .mem { padding:6px 0; border-bottom:1px dashed var(--line); font-size:13px; }
  .badge { display:inline-block; font-size:11px; border-radius:6px; padding:1px 6px;
           margin-right:6px; }
  .b-decision { background:#1d2b4a; color:#7fb0ff; }
  .b-milestone { background:#2b1d4a; color:#c79bff; }
  .b-note { background:#26303c; color:#9fb3c8; }
  .b-pending { background:#3a2f14; color:#ffd479; }
  .row { display:flex; gap:8px; align-items:center; }
  .grow { flex:1; }
</style>
</head>
<body>
<header>
  <h1>🧠 外置大脑</h1>
  <span class="tag" id="backend"></span>
</header>
<nav>
  <button class="on" data-p="ask">问答</button>
  <button data-p="mem">记忆</button>
  <button data-p="proj">项目</button>
  <button data-p="spec">监督</button>
  <button data-p="pending">待确认</button>
</nav>
<main>
  <div id="p-ask" class="panel on">
    <div class="card">
      <div class="row">
        <select id="ask-proj" class="grow"><option value="">个人区</option></select>
      </div>
      <div id="chat"></div>
      <div class="row">
        <textarea id="ask-input" class="grow" placeholder="问我任何事，或描述你想做的事…"></textarea>
        <button class="act" onclick="ask()">发送</button>
      </div>
    </div>
  </div>

  <div id="p-mem" class="panel">
    <div class="card">
      <h3>记录一段对话（自动提炼决策，进待确认）</h3>
      <textarea id="cap-input" placeholder="把与 Claude/AI 的对话内容粘到这里，大脑会提炼出决策草稿…"></textarea>
      <button class="act" onclick="capture()">提炼为草稿</button>
      <div id="cap-out" class="muted"></div>
    </div>
    <div class="card">
      <h3>主动记忆（你说算，直接生效）</h3>
      <div class="row">
        <input id="mem-content" class="grow" placeholder="要记住的内容（主动记忆，直接生效）">
        <select id="mem-level" style="width:120px">
          <option value="decision">决策</option>
          <option value="milestone">重要修改点</option>
          <option value="note">记录</option>
        </select>
        <select id="mem-proj" style="width:140px"><option value="">个人区</option></select>
        <button class="act" onclick="remember()">记住</button>
      </div>
    </div>
    <div class="card">
      <h3>回顾检索</h3>
      <div class="row">
        <input id="recall-q" class="grow" placeholder="搜索记忆…">
        <button class="act" onclick="recall()">检索</button>
      </div>
      <div id="recall-out"></div>
    </div>
  </div>

  <div id="p-proj" class="panel">
    <div class="card">
      <h3>注册项目</h3>
      <div class="row">
        <input id="pj-name" placeholder="项目名" style="width:160px">
        <input id="pj-path" class="grow" placeholder="仓库路径（绝对路径，如 /home/u/repos/myproj）">
        <button class="act" onclick="addProject()">注册</button>
      </div>
      <input id="pj-charter" placeholder="大方向一句话（charter，可选）">
      <div id="proj-out"></div>
    </div>
  </div>

  <div id="p-spec" class="panel">
    <div class="card">
      <h3>边界监督（规范环）</h3>
      <select id="sup-proj" style="width:100%"><option value="">选择项目…</option></select>
      <textarea id="sup-input" placeholder="新提议，例如：我想把数据库从 SQLite 换成 Postgres…"></textarea>
      <button class="act" onclick="supervise()">对照检查</button>
      <div id="sup-out"></div>
    </div>
  </div>

  <div id="p-pending" class="panel">
    <div class="card">
      <h3>自动捕获的草稿（确认后生效）</h3>
      <div id="pending-out"></div>
      <button class="act" onclick="loadPending()">刷新</button>
    </div>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
let THREAD = null;
const API = {
  projects: async () => (await fetch('/api/projects')).json(),
  ask: async body => (await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  remember: async body => (await fetch('/api/remember', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  capture: async body => (await fetch('/api/capture', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  recall: async body => (await fetch('/api/recall', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  supervise: async body => (await fetch('/api/supervise', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  pending: async () => (await fetch('/api/pending')).json(),
  review: async body => (await fetch('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  addProject: async body => (await fetch('/api/projects', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})).json(),
  sync: async id => (await fetch('/api/projects/'+id+'/sync', {method:'POST'})).json(),
};

function selOpts(sel, rows) {
  const cur = sel.value;
  sel.innerHTML = '<option value="">个人区</option>' +
    rows.map(r => `<option value="${r.id}">${r.name}</option>`).join('');
  if (cur) sel.value = cur;
}
async function refreshProjects() {
  const rows = await API.projects();
  selOpts($('ask-proj'), rows); selOpts($('mem-proj'), rows); selOpts($('sup-proj'), rows);
  return rows;
}
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
  if ($('ask-proj').value) body.project_id = Number($('ask-proj').value);
  if (THREAD) body.thread_id = THREAD;
  const out = document.createElement('div'); out.className='muted';
  out.textContent = '思考中…'; $('chat').appendChild(out);
  try {
    const r = await API.ask(body);
    THREAD = r.thread_id;
    out.remove();
    addMsg('assistant', r.answer);
    if (r.recalls && r.recalls.length) {
      const ref = document.createElement('div'); ref.className='muted';
      ref.textContent = '召回: ' + r.recalls.map(x => x.content.slice(0,40)).join(' | ');
      $('chat').appendChild(ref);
    }
  } catch(e) { out.textContent = '错误: ' + e; }
}
async function capture() {
  const text = $('cap-input').value.trim(); if (!text) return;
  const body = { text };
  if ($('mem-proj').value) body.project_id = Number($('mem-proj').value);
  const out = $('cap-out');
  out.textContent = '提炼中…';
  try {
    const r = await API.capture(body);
    $('cap-input').value = '';
    out.textContent = r.ids.length
      ? '已生成 ' + r.ids.length + ' 条决策草稿，请到「待确认」页签确认'
      : '未提炼出确定的决策（内容里可能没有结论）';
    await loadPending();
  } catch(e) { out.textContent = '错误: ' + e; }
}
async function remember() {
  const content = $('mem-content').value.trim(); if (!content) return;
  const body = { content, level: $('mem-level').value };
  if ($('mem-proj').value) body.project_id = Number($('mem-proj').value);
  const r = await API.remember(body);
  alert('已记住 #' + r.id); $('mem-content').value = '';
  loadRecents();
}
async function recall() {
  const q = $('recall-q').value.trim(); if (!q) return;
  const body = { query: q };
  const r = await API.recall(body);
  $('recall-out').innerHTML = r.items.length
    ? r.items.map(x => `<div class="mem">[${x.project}/${x.level}] ${esc(x.content)}<br><span class="muted">${x.created_at}</span></div>`).join('')
    : '<span class="muted">(无结果)</span>';
}
async function addProject() {
  const body = { name: $('pj-name').value.trim(), path: $('pj-path').value.trim(),
                 charter: $('pj-charter').value.trim() };
  if (!body.name) return alert('需要项目名');
  await API.addProject(body);
  $('pj-name').value=''; $('pj-path').value=''; $('pj-charter').value='';
  await loadProjects();
}
async function loadProjects() {
  const rows = await API.projects();
  $('proj-out').innerHTML = rows.map(r => `
    <div class="mem">
      <b>#${r.id} ${esc(r.name)}</b> <span class="muted">${esc(r.path||'')}</span><br>
      <span class="muted">${esc(r.charter||'')}</span><br>
      记忆 ${r.mem_count} 条 | spec 索引 ${r.spec_count} 个
      <button class="ghost" onclick="syncProj(${r.id})">同步 spec</button>
    </div>`).join('') || '<span class="muted">(暂无项目)</span>';
}
async function syncProj(id) {
  const r = await API.sync(id);
  alert('同步完成: 新增 ' + r.added + ', 更新 ' + r.updated + ', 未变 ' + r.unchanged);
  await loadProjects();
}
async function supervise() {
  const pid = Number($('sup-proj').value); if (!pid) return alert('请选择项目');
  const proposal = $('sup-input').value.trim(); if (!proposal) return;
  const r = await API.supervise({ proposal, project_id: pid });
  $('sup-out').innerHTML = '<h3>检查报告</h3><pre style="white-space:pre-wrap">' + esc(r.report) + '</pre>';
}
async function loadPending() {
  const r = await API.pending();
  $('pending-out').innerHTML = r.items.length
    ? r.items.map(x => `<div class="mem">
        <span class="badge b-pending">待确认</span><span class="badge b-${x.level}">${x.level}</span>
        ${esc(x.content)}
        <div class="row" style="margin-top:6px">
          <button class="ghost" onclick="doReview(${x.id},'keep')">保留</button>
          <button class="ghost" onclick="doReview(${x.id},'delete')">删除</button>
        </div></div>`).join('')
    : '<span class="muted">(没有待确认的记忆)</span>';
}
async function doReview(id, action) {
  await API.review({ id, action });
  await loadPending();
}
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); $('p-' + b.dataset.p).classList.add('on');
});
$('ask-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } });
(async function boot() {
  $('backend').textContent = 'LLM: ' + await (await fetch('/api/health')).json().then ? '' : '';
  const h = await (await fetch('/api/health')).json();
  $('backend').textContent = '后端: ' + h.backend + ' | 数据库: ' + h.db;
  await refreshProjects(); await loadProjects(); await loadPending();
})();
</script>
</body>
</html>
"""


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

    app = FastAPI(title="外置大脑", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML

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

    @app.post("/api/review")
    def review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            mem_mod.review(conn, body.id, body.action, new_content=body.content)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

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
