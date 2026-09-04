// L-clone 记忆钩子 (DSH 静态插件 bundle): 每轮结束自动 capture 沉淀 + 决策确认改由客户端 UI 呈现 (不劫持主 agent)。
//
// 本变更 (decision-confirm-dsh-ui):
//   - 捕获输入变丰富: 改为累计「用户 + 助手」消息, turn/end 时把整段交换喂给 capture,
//     分类器据此判断「用户定了什么 + 助手是否确认/落地 → 可否落成一条决策」。
//   - 决策强确认呈现分端: 去掉 agent.steer 劫持主 agent; DSH 改由客户端轮询
//     /api/lclone-decisions 弹窗 + 角标呈现 (保留/删除), 主 agent 全程不参与。
//   - host 端新增 /api/lclone-decisions (GET pending) 与 /api/lclone-review (POST keep/delete)
//     两个同源代理路由, 避免客户端跨 :8000 的 CORS/鉴权。
//
// 本变更 (dsh-bootstrap-spec-dispatch / skill-load-env-inject):
//   - read-side 不再由插件硬触发注入记忆。lclone-memory skill 始终在场, 由 agent 依 skill 规则
//     按当前环境 (cwd 是否落进已知项目) 决定加载 全局 还是 全局+项目 记忆; 插件只保证 skill 在场。
//     写侧 (capture) 仍在 turn/end 硬触发, 决策确认仍由客户端 UI 呈现。
//
// 事件签名已从 dsh-session 源码确认:
//   ctx.on('session/event', (session, event) => ...)
//     - turn/end:          event.data = { turn, reason }           每轮结束
//     - user/message:      event.data.content = [{type:'text', text}]
//     - assistant/message: event.data.message.content = [{type:'text'|'reasoning', text}]
//
// 安装(发布后): dsh plugin --profile web add lclone-memory-dsh -w
// 后端地址用 LCLONE_WEB_URL(默认 http://127.0.0.1:8000); 不走本机 lclone 命令。

import { randomUUID } from 'node:crypto'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { existsSync, appendFileSync, mkdirSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'

// 插件自身的状态目录 (日志等): 不依赖仓库根, 发布后装到哪都能写。
// 优先 $LCLONE_STATE_DIR, 其次 $LCLONE_HOME/.lclone, 最后 ~/.lclone。
const STATE_DIR = process.env.LCLONE_STATE_DIR
  || join(process.env.LCLONE_HOME || homedir(), '.lclone')
const LOG_PATH = join(STATE_DIR, 'dsh-plugin.log')
try { mkdirSync(STATE_DIR, { recursive: true }) } catch {}
// 后端基址 + 文档链接 (可配置: LCLONE_WEB_URL / LCLONE_DOCS_URL, 默认本地 + GitHub)
const WEB_URL = (process.env.LCLONE_WEB_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')
const DOCS_URL = process.env.LCLONE_DOCS_URL || 'https://github.com/ljzRober/L-clone'
const WEB = new URL(WEB_URL)
// 包内前端 (前后台分离): 插件 serve 自带的 index.html, 并把 LCLONE_API_BASE 设为后端地址。
const FRONTEND_INDEX = join(dirname(dirname(fileURLToPath(import.meta.url))),
  'brain', 'lclone', 'frontend', 'index.html')

function log(msg) {
  try {
    appendFileSync(LOG_PATH, new Date().toISOString() + ' ' + msg + '\n')
  } catch {}
}

// 插件走后端 HTTP, 不再需要本机 lclone 命令 (也无需 LCLONE_CMD)。

function extractText(event) {
  const d = event.data || {}
  let blocks = []
  if (event.type === 'user/message') blocks = Array.isArray(d.content) ? d.content : []
  else if (event.type === 'assistant/message') {
    blocks = d.message && Array.isArray(d.message.content) ? d.message.content : []
  }
  return blocks
    .filter((b) => b && b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text)
    .join('\n')
}

// 助手消息截断上限: 分类器只需看到「助手是否确认/落地」的轮廓, 不必吞整段长回复
// (整段长回复会稀释决策信号并膨胀 token)。
const ASSISTANT_CAP = 1500

function buildCaptureText(userText, assistantText) {
  const u = (userText || '').trim()
  const a = (assistantText || '').trim()
  if (!u && !a) return ''
  if (u && a) return '用户：' + u + '\n\n助手：' + a.slice(0, ASSISTANT_CAP)
  if (u) return '用户：' + u
  return '助手：' + a.slice(0, ASSISTANT_CAP)
}

// 写侧: 走后端 HTTP POST /api/capture (后台由 lclone web / scripts/install.js 提供)。
function runCapture(text, sessionKey, cwd, onDone) {
  const t = (text || '').trim()
  if (!t) { if (onDone) onDone(); return }
  const body = { text: t, session_key: sessionKey || '', global_fallback: true }
  if (cwd) body.cwd = cwd // git 仓库 → 后端自动归属/注册
  log(`capture ${t.length} chars cwd=${cwd || '(无)'}`)
  lcloneRequester('POST', '/api/capture', body, (ok, json) => {
    log('capture via http ' + (ok ? 'ok' : 'fail') + (json ? ' ' + JSON.stringify(json).slice(0, 160) : ''))
    if (onDone) onDone()
  })
}

// 读侧: 走后端 HTTP GET /api/bootstrap (返回会话引导文本)。
function runBootstrap(cwd, onDone) {
  let path = '/api/bootstrap'
  if (cwd) path += '?cwd=' + encodeURIComponent(cwd)
  lcloneRequester('GET', path, null, (ok, json) => {
    const text = ok && json ? (json.text || '') : ''
    log('bootstrap via http ' + (ok ? '' + text.length : 'fail'))
    onDone(text.trim())
  })
}

// 组装注入文本: [skill 全文] + [bootstrap 记忆]。
function buildBootText(skillBody, bootOut) {
  const parts = []
  const skill = (skillBody || '').trim()
  if (skill) parts.push('【lclone-memory skill 全文】(会话主导)\n' + skill)
  if (bootOut && bootOut !== '(暂无记忆)' && bootOut !== '') parts.push('【记忆】\n' + bootOut)
  return parts.join('\n\n')
}

async function injectSessionStart(ctx, sessionId, cwd) {
  const agent = ctx.agents.get(sessionId)
  if (!agent) { log(`bootstrap: agent not found for ${sessionId}`); return }
  runBootstrap(cwd, (bootOut) => {
    readFile(SKILL_FILE, { encoding: 'utf8' })
      .then((skillBody) => {
        probeLcloneHealth((ok) => {
          const text = buildBootText(skillBody, bootOut)
          const tip = ok
            ? ''
            : '⚠️ [lclone-memory] 后端不可达：请先启动 L-clone 后端（运行 `<包>/scripts/install.js` 一键初始化，或 `python -m lclone web`）。装好后重启 DSH web 会话。\n\n'
          if (!tip && !text) return
          try {
            agent.steer({
              id: randomUUID(),
              role: 'user',
              content: [{ type: 'text', text: tip + text }],
              source: { kind: 'plugin', plugin: 'lclone-memory' },
            })
            log(`bootstrap injected once for ${sessionId}: ${text.length} chars${ok ? '' : ' (+后端缺失引导)'}`)
          } catch (e) {
            log('bootstrap steer failed: ' + (e && e.message))
          }
        })
      })
      .catch(() => {})
  })
}

// 统一请求后端 (可配置 LCLONE_WEB_URL, 支持 http/https + LCLONE_API_KEY 鉴权)。
function lcloneRequester(method, path, body, onDone) {
  const mod = WEB.protocol === 'https:' ? httpsRequest : httpRequest
  const apiKey = process.env.LCLONE_API_KEY
  const headers = {}
  if (apiKey) headers['X-API-Key'] = apiKey
  let payload = null
  if (body !== null && body !== undefined) {
    payload = JSON.stringify(body)
    headers['Content-Type'] = 'application/json'
    headers['Content-Length'] = Buffer.byteLength(payload)
  }
  const req = mod(
    {
      hostname: WEB.hostname,
      port: WEB.port ? Number(WEB.port) : (WEB.protocol === 'https:' ? 443 : 80),
      path, method, timeout: 3000, headers,
    },
    (res) => {
      let data = ''
      res.on('data', (d) => { data += d.toString() })
      res.on('end', () => {
        let json = null
        try { json = JSON.parse(data || 'null') } catch (e) {}
        onDone(res.statusCode >= 200 && res.statusCode < 300, json)
      })
    },
  )
  req.on('timeout', () => { req.destroy(); onDone(false, null) })
  req.on('error', () => onDone(false, null))
  if (payload) req.write(payload)
  req.end()
}

// 健康检查: 探测后端存活, 供 client 端「大脑看板」按钮显示在线状态。
function probeLcloneHealth(onDone) {
  lcloneRequester('GET', '/api/health', null, (ok, json) => onDone(ok && json && json.ok === true))
}

// 组装「就绪引导清单」: 按 后端/skill 缺失情况给出可执行步骤 (前后台分离后无 CLI 依赖)。
function buildSetupGuide(ok, skill) {
  const setup = []
  if (!ok) setup.push('启动后端：`node <包>/scripts/install.js` 一键初始化，或 `python -m lclone web`（后台常驻 `lclone serve start`）；必要时用 LCLONE_WEB_URL 指定地址')
  if (!skill) setup.push('安装记忆 skill：`lclone integrate --target skill`')
  return setup
}

// 读 HTTP 请求体 (POST body), 供 /api/lclone-review 用。
function readBody(request, cb) {
  let data = ''
  request.on('data', (d) => { data += d.toString() })
  request.on('end', () => cb(data))
  request.on('error', () => cb(''))
}

// 代理到后端。带 LCLONE_API_KEY 鉴权; 与健康探测同源, 避免客户端跨域。
function lcloneFetch(method, path, body, onDone) {
  lcloneRequester(method, path, body, onDone)
}

// skill 安装路径 (与 lclone integrate 一致: ~/.agents/skills/lclone-memory/SKILL.md)
function skillPath() {
  const home = process.env.LCLONE_HOME || homedir()
  return join(home, '.agents', 'skills', 'lclone-memory', 'SKILL.md')
}

// 全量加载 lclone-memory skill: 注册 ctx.skills provider 读取已安装的 SKILL.md,
// 保证该 skill 完整在场 (无论会话环境, 由 agent 依 skill 规则按环境决定加载 全局/全局+项目 记忆)。
// 格式照 validated 先例 (superdesign / dsh-skill-badge): list/get 稳定 contract, 不复用 fs skill。
const SKILL_NAME = 'lclone-memory'
const PROVIDER_NAME = 'lclone-memory'
const BUNDLED_SKILL_RANK = 600
const INVOCATION = { modelInvocable: true, userInvocable: true }
const SKILL_FILE = fileURLToPath(new URL(`file://${skillPath()}`))
const SKILL_DIR = dirname(SKILL_FILE)
const RESOURCE_BASE = { kind: 'directory', path: SKILL_DIR }

function readDescription(body) {
  const fm = /^---\r?\n([\s\S]*?)\r?\n---/.exec(body)
  if (!fm) return undefined
  const line = /^description:[ \t]*(.+)$/m.exec(fm[1])
  if (!line) return undefined
  return line[1].trim().replace(/^["']|["']$/g, '').replace(/\\"/g, '"')
}

async function loadSkill(signal) {
  try {
    const content = await readFile(SKILL_FILE, { encoding: 'utf8', signal })
    const description = readDescription(content)
    return description ? { description, content } : undefined
  } catch {
    return undefined
  }
}

const skillProvider = {
  name: PROVIDER_NAME,
  async list(options = {}) {
    const s = await loadSkill(options.signal)
    if (!s) return []
    return [{
      name: SKILL_NAME,
      description: s.description,
      invocation: INVOCATION,
      provider: PROVIDER_NAME,
      source: 'bundled',
      resourceBase: RESOURCE_BASE,
      rank: BUNDLED_SKILL_RANK,
      locator: new URL(`file://${SKILL_FILE}`),
    }]
  },
  async get(_candidate, options = {}) {
    const s = await loadSkill(options.signal)
    if (!s) return undefined
    return {
      name: SKILL_NAME,
      description: s.description,
      invocation: INVOCATION,
      provider: PROVIDER_NAME,
      source: 'bundled',
      resourceBase: RESOURCE_BASE,
      content: s.content,
    }
  },
}

export const name = 'lclone-memory'
// cordis 依赖注入: 注册 skill provider 需声明 skills; 会话首轮一次性注入记忆需声明 agents。
export const inject = ['skills', 'agents']

export function apply(ctx) {
  log('plugin loaded (backend-driven, LCLONE_WEB_URL=' + WEB_URL + ')')
  // 全量加载 lclone-memory skill (保证完整在场; 记忆注入由 agent 依 skill 按环境驱动)。
  try {
    ctx.skills.registerProvider(() => skillProvider)
    log('registered lclone-memory skill provider')
  } catch (e) {
    log('skill provider register skipped: ' + (e && e.message))
  }
  // 健康检查 + 决策代理路由: client 端同源探测/确认 (无 CORS 问题)
  try {
    ctx.inject(['webServer'], (hostCtx) => {
      hostCtx.effect(() => {
        log('registering lclone web routes')
        const disposers = []
        const register = (cfg) => {
          const d = hostCtx.webServer.register(cfg)
          if (typeof d === 'function') disposers.push(d)
        }
        register({
          kind: 'exact',
          path: '/api/lclone-health',
          handler: (request, response) => {
            if (request.method !== 'GET') {
              response.writeHead(405, { allow: 'GET' })
              response.end()
              return
            }
            probeLcloneHealth((ok) => {
              const skill = existsSync(skillPath())
              response.writeHead(200, { 'content-type': 'application/json' })
              response.end(JSON.stringify({
                ok, skill,
                setup: buildSetupGuide(ok, skill),
                webUrl: WEB_URL, docsUrl: DOCS_URL,
                boardUrl: '/__lclone/board',
              }))
            })
          },
        })
        // 前后台分离: 插件 serve 包内前端, 并把 LCLONE_API_BASE 指向后端(CORS 跨域)。
        register({
          kind: 'exact',
          path: '/__lclone/board',
          handler: (request, response) => {
            if (request.method !== 'GET') {
              response.writeHead(405, { allow: 'GET' })
              response.end()
              return
            }
            readFile(FRONTEND_INDEX, { encoding: 'utf8' })
              .then((html) => {
                const apiBase = WEB_URL.replace(/"/g, '')
                // 在 <head> 最前面设置 LCLONE_API_BASE, 先于 fetch 包装脚本执行。
                html = html.replace('<head>',
                  '<head><script>window.LCLONE_API_BASE="' + apiBase + '";</script>')
                response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' })
                response.end(html)
              })
              .catch(() => { response.writeHead(404); response.end() })
          },
        })
        // 待确认决策列表 (client 轮询, 弹窗 + 角标用)
        register({
          kind: 'exact',
          path: '/api/lclone-decisions',
          handler: (request, response) => {
            if (request.method !== 'GET') {
              response.writeHead(405, { allow: 'GET' })
              response.end()
              return
            }
            lcloneFetch('GET', '/api/pending', null, (ok, json) => {
              response.writeHead(200, { 'content-type': 'application/json' })
              response.end(JSON.stringify({ ok, items: (json && json.items) || [] }))
            })
          },
        })
        // 决策确认 (keep/delete); 落地为 active 或删除
        register({
          kind: 'exact',
          path: '/api/lclone-review',
          handler: (request, response) => {
            if (request.method !== 'POST') {
              response.writeHead(405, { allow: 'POST' })
              response.end()
              return
            }
            readBody(request, (raw) => {
              let body = {}
              try { body = JSON.parse(raw || '{}') } catch (e) {}
              if (typeof body.id !== 'number' || !Number.isFinite(body.id)) {
                response.writeHead(400, { 'content-type': 'application/json' })
                response.end(JSON.stringify({ ok: false, error: 'missing/invalid id' }))
                return
              }
              lcloneFetch('POST', '/api/review', { id: body.id, action: body.action || 'keep' }, (ok, json) => {
                const good = ok && json && json.ok === true
                // 后端失败返回非 2xx, 让 client 能区分「已落地」与「未生效」
                response.writeHead(good ? 200 : 502, { 'content-type': 'application/json' })
                response.end(JSON.stringify({ ok: good, ...(json || {}) }))
              })
            })
          },
        })
        return () => { for (const d of disposers) { try { d() } catch {} } }
      }, 'lclone-memory: web routes')
    })
  } catch (e) {
    log('web routes skipped: ' + (e && e.message))
  }
  // 按 session 累计本轮 user+assistant 文本, turn/end 时 flush 进 lclone capture。
  // read-side: 会话首轮(第一个 user/message)一次性注入 [skill 全文 + bootstrap 记忆],
  // 让 lclone-memory skill 主导整段会话; 之后不再重复注入 (每轮只 capture, 不重注入)。
  const buffers = new Map()
  const bootstrapped = new Set() // 每个会话只注入一次

  ctx.on('session/event', (session, event) => {
    // 会话首轮: 注入 skill 全文 + bootstrap 记忆 (一次)。
    if (event.type === 'user/message' && !bootstrapped.has(session.id)) {
      bootstrapped.add(session.id)
      const cwd = (session.header && session.header.cwd) || session.cwd || session.meta?.cwd
      log(`session/start inject for ${session.id} cwd=${cwd || '(无)'}`)
      injectSessionStart(ctx, session.id, cwd)
    }
    // 同时捕获用户消息与助手回复: 分类器据此判断「用户定了什么 + 助手是否确认/落地」。
    if (event.type === 'user/message' || event.type === 'assistant/message') {
      const text = extractText(event)
      if (text) {
        const cur = buffers.get(session.id) || { user: [], assistant: [] }
        cur[event.type === 'user/message' ? 'user' : 'assistant'].push(text)
        buffers.set(session.id, cur)
      }
    }
    if (event.type === 'turn/end') {
      log(`turn/end fired: session=${session.id} turn=${event.data && event.data.turn}`)
      const cur = buffers.get(session.id) || { user: [], assistant: [] }
      buffers.delete(session.id)
      const cwd = (session.header && session.header.cwd) || session.cwd || session.meta?.cwd
      // capture 完成即止; 决策确认由客户端轮询 /api/lclone-decisions 呈现, 不再劫持主 agent
      runCapture(buildCaptureText(cur.user.join('\n'), cur.assistant.join('\n')), session.id, cwd)
    }
  })
}
