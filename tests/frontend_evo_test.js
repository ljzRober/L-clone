'use strict';
/* 前端行为测试 (零第三方依赖): 用 node:vm + 最小 DOM 桩载入 index.html 的内联脚本,
 * 直测进化面板编辑器与规范场景 (可编辑→textarea/保存; 不可编辑→只读预览+原因码; 409 不丢内容)。
 *
 * 由 tests/test_offline.py 调用:
 *   node tests/frontend_evo_test.js <index.html 绝对路径>
 * 末行输出 "FRONTEND OK <n>" 或 "FRONTEND FAILED <n> <失败清单>"; 退出码 0/1。
 */
const fs = require('fs');
const vm = require('vm');

const htmlPath = process.argv[2];
if (!htmlPath || !fs.existsSync(htmlPath)) {
  console.log('FRONTEND FAILED 0 未提供可读的 index.html 路径');
  process.exit(1);
}
const html = fs.readFileSync(htmlPath, 'utf8');
// index.html 有两段内联脚本 (head 里的 API BASE 前缀器 + 主体), 都要执行
const code = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

let passed = 0;
const fails = [];
function check(name, cond, extra) {
  if (cond) { passed++; console.log('PASS ' + name); }
  else { fails.push(name); console.log('FAIL ' + name + (extra === undefined ? '' : '  [' + extra + ']')); }
}

/* ---------------- 最小 DOM 桩 ---------------- */
function El(tag) {
  this.tag = tag || 'div';
  this.id = ''; this._cls = ''; this.value = ''; this._text = ''; this._html = '';
  this.style = {}; this.dataset = {}; this.children = []; this.title = '';
  const self = this;
  this.classList = {
    add(c) { if (self._cls.split(/\s+/).indexOf(c) < 0) self._cls = (self._cls + ' ' + c).trim(); },
    remove(c) { self._cls = self._cls.split(/\s+/).filter(x => x && x !== c).join(' '); },
    toggle(c, on) { if (on === undefined) on = !self.classList.contains(c); if (on) self.classList.add(c); else self.classList.remove(c); },
    contains(c) { return self._cls.split(/\s+/).indexOf(c) >= 0; },
  };
}
Object.defineProperty(El.prototype, 'textContent', {
  get() { return this._text; },
  set(v) { this._text = String(v == null ? '' : v); this._html = ''; },
});
Object.defineProperty(El.prototype, 'innerHTML', {
  get() { return this._html; },
  set(v) { this._html = String(v == null ? '' : v); this._text = ''; },
});
El.prototype.addEventListener = function () {};
El.prototype.appendChild = function (c) { this.children.push(c); return c; };
El.prototype.focus = function () {};
El.prototype.querySelectorAll = function () { return []; };
El.prototype.querySelector = function () { return null; };
El.prototype.setAttribute = function (k, v) { this[k] = v; };
El.prototype.closest = function () { return null; };

const IDS = ['graph', 'graph-sum', 'graph-svg', 'pending-n', 'btn-pending', 'm-owner',
             'evo-exp', 'evo-list', 'evo-path', 'evo-pname', 'evo-ver', 'evo-reason',
             'evo-editor', 'evo-save', 'evo-preview', 'evo-note'];

function loadSandbox() {
  const byId = {};
  IDS.forEach(id => { const e = new El('div'); e.id = id; byId[id] = e; });
  const document = {
    getElementById(id) { if (!byId[id]) { byId[id] = new El('div'); byId[id].id = id; } return byId[id]; },
    createElement(t) { return new El(t); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
    body: new El('body'),
  };
  const alerts = [];
  const sandbox = {
    document,
    localStorage: { getItem: () => 'test-key', setItem() {} },
    setInterval: () => 0, clearInterval() {},
    confirm: () => true,
    alert: m => alerts.push(String(m)),
    addEventListener() {}, removeEventListener() {},
    location: { reload() {} },
    fetch: () => new Promise(() => {}),   // 顶层 boot() 的 /api/health: 挂起即可, pending promise 不阻塞退出
    console,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: 'index.html', timeout: 5000 });
  return { sandbox, byId, alerts };
}

/* ---------------- fetch 桩 ---------------- */
function http(routes) {
  const seen = [];
  const f = async (url, init) => {
    const u = String(url);
    seen.push({ url: u, method: (init && init.method) || 'GET', body: (init && init.body) || '' });
    for (const r of routes) if (u.indexOf(r.match) >= 0) return r.reply(u, init);
    return { ok: false, status: 404, json: async () => ({ detail: 'no route: ' + u }) };
  };
  return { f, seen };
}
const okJson = payload => ({ ok: true, status: 200, json: async () => payload });
const errJson = (status, payload) => ({ ok: false, status, json: async () => payload });
const CONTENT = over => Object.assign({
  name: 'note.md', version: 3, hash: 'h', content: 'hello', ref: '',
  editable: true, editable_reason: '', base_version: 3, deleted_at: '', renamed_to: '',
}, over || {});

/* ---------------- 用例 ---------------- */
(async () => {
  // 296 DOM 契约 (源码)
  check('296 编辑器 DOM 契约齐备',
    /<textarea[^>]*id="evo-editor"/.test(html) && html.indexOf('id="evo-save"') >= 0 &&
    html.indexOf('id="evo-reason"') >= 0 && html.indexOf('id="evo-ver"') >= 0 &&
    html.indexOf('id="evo-note"') >= 0 && html.indexOf('id="evo-preview"') >= 0);

  // 297 可编辑资产: textarea 可写 + 保存可见 + 原因徽标隐藏 + 版本牌 = 当前版本
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([{ match: '/api/evolution/content', reply: () => okJson(CONTENT()) }]).f;
    await sandbox.showEvo('note.md');
    check('297 可编辑资产就地渲染 textarea 与保存入口',
      byId['evo-editor'].value === 'hello' && byId['evo-editor'].style.display === '' &&
      byId['evo-save'].style.display === '' && byId['evo-preview'].style.display === 'none' &&
      byId['evo-reason'].style.display === 'none' && byId['evo-ver'].textContent === 'v3' &&
      byId['evo-pname'].textContent === 'note.md',
      `value=${JSON.stringify(byId['evo-editor'].value)} editor=${JSON.stringify(byId['evo-editor'].style.display)} ver=${byId['evo-ver'].textContent}`);
  }

  // 298 不可编辑资产: 只读预览保留内容 + 原因徽标可见 + 无编辑/保存入口
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([{ match: '/api/evolution/content',
      reply: () => okJson(CONTENT({ editable: false, editable_reason: 'binary', content: 'raw\u0000bytes' })) }]).f;
    await sandbox.showEvo('blob.bin');
    check('298 不可编辑资产退回只读预览 + 原因徽标 (binary)',
      byId['evo-editor'].style.display === 'none' && byId['evo-save'].style.display === 'none' &&
      byId['evo-preview'].style.display === '' && byId['evo-preview'].textContent === 'raw\u0000bytes' &&
      byId['evo-reason'].style.display === '' && /只读/.test(byId['evo-reason'].textContent),
      `reason=${JSON.stringify(byId['evo-reason'].textContent)}`);
  }

  // 299 四个原因码都有专属徽标文案 (不是兜底文案), 且互异
  {
    const labels = {};
    for (const code of ['binary', 'too_large', 'ref', 'missing']) {
      const { sandbox, byId } = loadSandbox();
      sandbox.fetch = http([{ match: '/api/evolution/content',
        reply: () => okJson(CONTENT({ editable: false, editable_reason: code })) }]).f;
      await sandbox.showEvo('a.txt');
      labels[code] = byId['evo-reason'].textContent;
    }
    const vals = Object.values(labels);
    const mapped = ['binary', 'too_large', 'ref', 'missing']
      .filter(c => new RegExp("['\"]?" + c + "['\"]?\\s*:\\s*['\"][^'\"]+['\"]").test(html));
    check('299 四个原因码各有专属徽标文案且互异',
      mapped.length === 4 && vals.every(v => v && v.length > 1) && new Set(vals).size === 4,
      JSON.stringify(labels));
  }

  // 300 409: 提示服务器版本, 且编辑区内容原样保留 (SHALL NOT 丢弃)
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([
      { match: '/api/evolution/content', reply: () => okJson(CONTENT()) },
      { match: '/api/evolution/publish', reply: () => errJson(409, { detail: { error: '版本冲突', current_version: 7 } }) },
    ]).f;
    await sandbox.showEvo('note.md');
    byId['evo-editor'].value = '我改过但没保存上的内容';
    await sandbox.evoSave();
    check('300 409 时不丢弃已编辑内容且提示服务器当前版本',
      byId['evo-editor'].value === '我改过但没保存上的内容' &&
      byId['evo-editor'].style.display === '' &&
      byId['evo-note'].classList.contains('err') &&
      byId['evo-note'].textContent.indexOf('v7') >= 0,
      `note=${JSON.stringify(byId['evo-note'].textContent)}`);
  }

  // 301 保存成功: 请求体带 name/content/base_version, 且刷新到新版本
  {
    const { sandbox, byId } = loadSandbox();
    let cur = CONTENT();
    const h = http([
      { match: '/api/evolution/content', reply: () => okJson(cur) },
      { match: '/api/evolution/publish', reply: () => { cur = CONTENT({ version: 4, base_version: 4, content: 'new body' }); return okJson({ result: { name: 'note.md', version: 4, hash: 'abcd1234', changed: true } }); } },
      { match: '/api/evolutions', reply: () => okJson({ items: [] }) },
      { match: '/api/evolution/index', reply: () => okJson({ items: [], dirs: {} }) },
    ]);
    sandbox.fetch = h.f;
    await sandbox.showEvo('note.md');
    byId['evo-editor'].value = 'new body';
    await sandbox.evoSave();
    const pub = h.seen.find(x => x.url.indexOf('/api/evolution/publish') >= 0) || {};
    let body = {};
    try { body = JSON.parse(pub.body || '{}'); } catch (e) { body = {}; }
    check('301 保存带 base_version 且刷新到新版本',
      pub.method === 'POST' && body.name === 'note.md' && body.content === 'new body' &&
      body.base_version === 3 && byId['evo-ver'].textContent === 'v4' &&
      byId['evo-editor'].value === 'new body' && /已保存/.test(byId['evo-note'].textContent),
      `body=${pub.body} ver=${byId['evo-ver'].textContent} note=${byId['evo-note'].textContent}`);
  }

  // 302 内容未变: 后端不新增版本 -> 面板如实显示
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([
      { match: '/api/evolution/content', reply: () => okJson(CONTENT()) },
      { match: '/api/evolution/publish', reply: () => okJson({ result: { name: 'note.md', version: 3, hash: 'h', changed: false } }) },
      { match: '/api/evolutions', reply: () => okJson({ items: [] }) },
      { match: '/api/evolution/index', reply: () => okJson({ items: [], dirs: {} }) },
    ]).f;
    await sandbox.showEvo('note.md');
    await sandbox.evoSave();
    check('302 内容未变的保存如实提示未产生新版本',
      /未产生新版本/.test(byId['evo-note'].textContent),
      `note=${JSON.stringify(byId['evo-note'].textContent)}`);
  }

  // 303 前端不自判可编辑性 (只镜像服务端)
  check('303 前端不含阈值/编码嗅探 (editable 只镜像服务端)',
    html.indexOf('LCLONE_EVO_MAX_EDIT_BYTES') < 0 && html.indexOf('262144') < 0 &&
    html.indexOf('TextDecoder') < 0 && html.indexOf('Uint8Array') < 0);

  // 304 任意名字都不破坏属性/内联处理器 (含引号 < > & 的资产名)
  {
    const nasty = 'a"b<c>&d.txt';
    const { sandbox, byId } = loadSandbox();
    const h = http([
      { match: '/api/evolutions', reply: () => okJson({ items: [{ name: nasty, ext: 'txt', size: 3, mtime: 't', is_dir: false, content: 'x' }] }) },
      { match: '/api/evolution/index', reply: () => okJson({ items: [{ name: nasty, version: 2, editable: true, editable_reason: '', base_version: 2 }], dirs: {} }) },
      { match: '/api/evolution/content', reply: () => okJson(CONTENT({ name: nasty, base_version: 2 })) },
      { match: '/api/projects', reply: () => okJson({ items: [] }) },
      { match: '/api/memories', reply: () => okJson({ items: [] }) },
      { match: '/api/links', reply: () => okJson({ items: [] }) },
      { match: '/api/pending', reply: () => okJson({ items: [] }) },
    ]);
    sandbox.fetch = h.f;
    await sandbox.loadAll();          // 走看板卡片路径渲染 graph
    await sandbox.openEvoExplorer();  // 走文件清单路径渲染 evo-list
    const graph = byId['graph'].innerHTML;
    const list = byId['evo-list'].innerHTML;
    const onclicks = [...graph.matchAll(/onclick="([^"]*)"/g)].map(m => m[1]);
    let allParse = onclicks.length > 0, bad = '';
    for (const c of onclicks) { try { new vm.Script(c); } catch (e) { allParse = false; bad = c; } }
    check('304 含引号/尖括号的资产名不破坏属性与内联处理器',
      allParse && list.indexOf('data-name="a&quot;b&lt;c&gt;&amp;d.txt"') >= 0 &&
      list.indexOf(nasty) < 0,
      `n=${onclicks.length} bad=${JSON.stringify(bad)} list=${list.slice(0, 140)}`);
  }

  console.log('FRONTEND ' + (fails.length ? 'FAILED ' + passed + ' ' + fails.join(' | ') : 'OK ' + passed));
  process.exit(fails.length ? 1 : 0);
})().catch(e => {
  console.log('FRONTEND FAILED 0 桩执行期异常: ' + ((e && e.stack) || e));
  process.exit(1);
});
