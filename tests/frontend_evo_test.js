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
const code = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

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
  this.style = {}; this.dataset = {}; this.children = []; this.title = ''; this._ls = {};
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
El.prototype.addEventListener = function (t, fn) { (this._ls[t] = this._ls[t] || []).push(fn); };
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

// 触发 #evo-list 的 click 处理器 (桩没有真 DOM 树, 用 closestMap 指定 .evo-row 命中)
function click(byId, id, closestMap) {
  const fns = (byId[id] && byId[id]._ls && byId[id]._ls.click) || [];
  const ev = { target: { closest: sel => closestMap[sel] || null } };
  fns.forEach(fn => fn(ev));
  return fns.length;
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

// 模拟浏览器解析属性值: 先解实体, 再把解码结果当 JS 编译执行
function decodeEntities(s) {
  return String(s).replace(/&lt;/g, '<').replace(/&gt;/g, '>')
                  .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
                  .replace(/&amp;/g, '&');
}

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

  // 304 任意名字都不破坏属性/内联处理器
  // 判据是**浏览器语义**: 属性值先解实体, 再编译成 JS, 真正调用后 openEvo 收到逐字相同的名字
  {
    const NAMES = ['a"b<c>&d.txt', "it's.txt", 'back\\slash.txt', 'line\nbreak.txt',
                   'tick`${x}.txt', 'literal&#39;.txt', 'sep\u2028line.txt', 'note.md'];
    let bad = '', checked = 0, roundTrip = 0;
    for (const nasty of NAMES) {
      const { sandbox, byId } = loadSandbox();
      sandbox.fetch = http([
        { match: '/api/evolutions', reply: () => okJson({ items: [{ name: nasty, ext: 'txt', size: 3, mtime: 't', is_dir: false, content: 'x' }] }) },
        { match: '/api/evolution/index', reply: () => okJson({ items: [{ name: nasty, version: 2, editable: true, editable_reason: '', base_version: 2 }], dirs: {} }) },
        { match: '/api/projects', reply: () => okJson({ items: [] }) },
        { match: '/api/memories', reply: () => okJson({ items: [] }) },
        { match: '/api/links', reply: () => okJson({ items: [] }) },
        { match: '/api/pending', reply: () => okJson({ items: [] }) },
      ]).f;
      await sandbox.loadAll();           // 看板卡片路径 (行内 onclick)
      await sandbox.openEvoExplorer();   // 清单路径 (data-name + 事件委托)
      const graph = byId['graph'].innerHTML;
      const list = byId['evo-list'].innerHTML;
      // (a) 属性完整性: 反斜杠转义只按 [^"]* 抓取, 名字里有裸引号就会抓残 -> 必然编译失败
      for (const raw of [...graph.matchAll(/onclick="([^"]*)"/g)].map(m => m[1])) {
        checked++;
        const dec = decodeEntities(raw);
        let fn;
        try { fn = new vm.Script('(function(){' + dec + '})()'); }
        catch (e) { bad = 'PARSE ' + JSON.stringify(dec) + ' | ' + e.message; continue; }
        const rec = [];
        const ctx = { openEvo: n => rec.push(n), openMem() {}, toggleProj() {},
                      openAddLevel() {}, prevPage() {}, nextPage() {} };
        vm.createContext(ctx);
        try { fn.runInContext(ctx); } catch (e) { bad = 'RUN ' + JSON.stringify(dec); continue; }
        if (dec.indexOf('openEvo(') === 0) {
          if (rec.length !== 1 || rec[0] !== nasty) bad = 'NAME ' + JSON.stringify(rec) + ' != ' + JSON.stringify(nasty);
          else roundTrip++;
        }
      }
      // (b) 清单行: data-name 解实体后必须逐字还原
      const dn = [...list.matchAll(/data-name="([^"]*)"/g)].map(m => m[1]);
      if (dn.length !== 1 || decodeEntities(dn[0]) !== nasty) bad = 'DATA-NAME ' + JSON.stringify(dn);
      // (c) 含 < & " 的名字不得以原样出现在标记里
      if (/[<>&"]/.test(nasty) && (list.indexOf(nasty) >= 0 || graph.indexOf(nasty) >= 0)) bad = 'RAW ' + nasty;
    }
    check('304 含引号/尖括号/换行/反斜杠的资产名不破坏属性与内联处理器',
      checked > 0 && bad === '' && roundTrip >= NAMES.length,
      `checked=${checked} roundTrip=${roundTrip} bad=${JSON.stringify(bad)}`);
  }

  // 305 未保存的编辑: 重新打开同一资产必须先确认, 取消则草稿保留
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([{ match: '/api/evolution/content', reply: () => okJson(CONTENT()) }]).f;
    await sandbox.showEvo('note.md');
    byId['evo-editor'].value = 'draft';
    sandbox.confirm = () => false;          // 用户选择"不放弃"
    await sandbox.showEvo('note.md');
    check('305 未保存编辑时重新打开先确认 (取消则不丢草稿)',
      byId['evo-editor'].value === 'draft',
      `value=${JSON.stringify(byId['evo-editor'].value)}`);
  }

  // 306 清单接口不可达时: 不抛给调用方, 面板仍打开并给出提示 (Task 9 工具条依赖此点)
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = async () => { throw new Error('boom'); };
    let threw = '';
    try { await sandbox.openEvoExplorer(); } catch (e) { threw = String(e && e.message); }
    check('306 清单加载失败时面板仍打开并提示 (不抛异常)',
      threw === '' && byId['evo-exp'].classList.contains('on') &&
      /失败/.test(byId['evo-note'].textContent),
      `threw=${threw} note=${JSON.stringify(byId['evo-note'].textContent)}`);
  }

  // 307 面板入口 (看板卡片 / 工具条) 有草稿时必须先确认; 取消则不 reset、不开面板
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([{ match: '/api/evolution/content', reply: () => okJson(CONTENT()) }]).f;
    await sandbox.showEvo('note.md');
    byId['evo-editor'].value = 'draft';
    sandbox.confirm = () => false;
    await sandbox.openEvoExplorer('note.md');
    check('307 面板入口不静默丢弃草稿 (取消则不 reset)',
      byId['evo-editor'].value === 'draft' && !byId['evo-exp'].classList.contains('on'),
      `value=${JSON.stringify(byId['evo-editor'].value)} on=${byId['evo-exp'].classList.contains('on')}`);
  }

  // 308 切到另一个资产也要先确认; 确认后才换成新资产内容
  {
    const { sandbox, byId } = loadSandbox();
    let phase = 0;
    sandbox.fetch = http([{ match: '/api/evolution/content',
      reply: () => (++phase === 1 ? okJson(CONTENT()) : okJson(CONTENT({ name: 'other.txt', content: 'other body', base_version: 1 }))) }]).f;
    await sandbox.showEvo('note.md');
    byId['evo-editor'].value = 'draft';
    sandbox.confirm = () => false;
    await sandbox.showEvo('other.txt');
    const keptOnCancel = byId['evo-editor'].value === 'draft';
    sandbox.confirm = () => true;
    await sandbox.showEvo('other.txt');
    check('308 切资产先确认 (取消保草稿, 确认才切换)',
      keptOnCancel && byId['evo-editor'].value === 'other body' && byId['evo-pname'].textContent === 'other.txt',
      `cancel=${JSON.stringify(keptOnCancel ? 'draft' : 'lost')} after=${JSON.stringify(byId['evo-editor'].value)}`);
  }

  // 309 只读资产即便被程序化调用 evoSave 也不得发布
  {
    const { sandbox, byId } = loadSandbox();
    const h = http([
      { match: '/api/evolution/content', reply: () => okJson(CONTENT({ editable: false, editable_reason: 'too_large', content: 'BIG' })) },
      { match: '/api/evolution/publish', reply: () => okJson({ result: { changed: true, version: 9 } }) },
    ]);
    sandbox.fetch = h.f;
    await sandbox.showEvo('big.txt');
    await sandbox.evoSave();
    check('309 只读资产被程序化调用也不发布',
      h.seen.every(x => x.url.indexOf('/api/evolution/publish') < 0) && /不可编辑/.test(byId['evo-note'].textContent),
      `seen=${h.seen.map(x => x.url).join(',')} note=${JSON.stringify(byId['evo-note'].textContent)}`);
  }

  // 310 类型徽标必须转义 ext, 且原型键不得污染 class
  {
    const { sandbox, byId } = loadSandbox();
    sandbox.fetch = http([
      { match: '/api/evolutions', reply: () => okJson({ items: [
        { name: 'evil.txt', ext: '<b>x</b>', size: 1, mtime: 't', is_dir: false, content: 'x' },
        { name: 'proto.txt', ext: 'constructor', size: 1, mtime: 't', is_dir: false, content: 'y' }] }) },
      { match: '/api/evolution/index', reply: () => okJson({ items: [], dirs: {} }) },
    ]).f;
    await sandbox.openEvoExplorer();
    const list = byId['evo-list'].innerHTML;
    check('310 类型徽标转义 ext + 原型键不污染 class',
      list.indexOf('<b>') < 0 && list.indexOf('&lt;b&gt;') >= 0 &&
      list.indexOf('native code') < 0 && list.indexOf('[object Object]') < 0,
      list.slice(0, 200));
  }

  // 311 清单点击经事件委托真正打开该资产 (data-name 解实体后逐字传入)
  {
    const nasty = 'a"b<c>&d.txt';
    const { sandbox, byId } = loadSandbox();
    const h = http([
      { match: '/api/evolutions', reply: () => okJson({ items: [{ name: nasty, ext: 'txt', size: 1, mtime: 't', is_dir: false, content: 'x' }] }) },
      { match: '/api/evolution/index', reply: () => okJson({ items: [], dirs: {} }) },
      { match: '/api/evolution/content', reply: () => okJson(CONTENT({ name: nasty, content: 'body' })) },
    ]);
    sandbox.fetch = h.f;
    await sandbox.openEvoExplorer();
    const n = click(byId, 'evo-list', { '.evo-row': { dataset: { name: nasty } } });
    await new Promise(r => setTimeout(r, 0));   // 放行 showEvo 的 await 链 (setTimeout 在桩外, node 主上下文可用)
    const hit = h.seen.find(x => x.url.indexOf('/api/evolution/content') >= 0) || {};
    check('311 清单点击经事件委托打开该资产 (名字逐字传入)',
      n > 0 && hit.url.indexOf('name=' + encodeURIComponent(nasty)) >= 0 && byId['evo-editor'].value === 'body',
      `listeners=${n} url=${hit.url} value=${JSON.stringify(byId['evo-editor'].value)}`);
  }

  console.log('FRONTEND ' + (fails.length ? 'FAILED ' + passed + ' ' + fails.join(' | ') : 'OK ' + passed));
  process.exit(fails.length ? 1 : 0);
})().catch(e => {
  console.log('FRONTEND FAILED 0 桩执行期异常: ' + ((e && e.stack) || e));
  process.exit(1);
});
