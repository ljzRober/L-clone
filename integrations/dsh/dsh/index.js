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
// 事件签名已从 dsh-session 源码确认:
//   ctx.on('session/event', (session, event) => ...)
//     - turn/end:          event.data = { turn, reason }           每轮结束
//     - user/message:      event.data.content = [{type:'text', text}]
//     - assistant/message: event.data.message.content = [{type:'text'|'reasoning', text}]
//
// 安装: dsh plugin --profile web add <本目录绝对路径>
// 环境变量 LCLONE_CMD 可覆盖 lclone 命令。
// 关键: spawn 时必须 cwd=仓库根, 否则 `python -m lclone` 找不到 lclone 包。

import { spawn } from 'node:child_process'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { existsSync, appendFileSync } from 'node:fs'
import { homedir } from 'node:os'

// 仓库根 (插件经 symlink 链入仓库, import.meta.url 是真实路径)
const REPO = join(dirname(fileURLToPath(import.meta.url)), '../../..')
const LOG_PATH = join(REPO, 'lclone-plugin.log')
// 后端基址 + 文档链接 (可配置: LCLONE_WEB_URL / LCLONE_DOCS_URL, 默认本地 + GitHub)
const WEB_URL = (process.env.LCLONE_WEB_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')
const DOCS_URL = process.env.LCLONE_DOCS_URL || 'https://github.com/ljzRober/L-clone'
const WEB = new URL(WEB_URL)

function log(msg) {
  try {
    appendFileSync(LOG_PATH, new Date().toISOString() + ' ' + msg + '\n')
  } catch {}
}

// 解析 lclone 命令: LCLONE_CMD 优先; 否则定位仓库 .venv 里的 python -m lclone。
function resolveLclone() {
  if (process.env.LCLONE_CMD) return process.env.LCLONE_CMD.trim().split(/\s+/)
  // Windows 用 Scripts/python.exe, 否则 bin/python; 都试一遍再退回 PATH 上的 lclone
  const pys = process.platform === 'win32'
    ? [join(REPO, '.venv', 'Scripts', 'python.exe'), join(REPO, '.venv', 'bin', 'python')]
    : [join(REPO, '.venv', 'bin', 'python'), join(REPO, '.venv', 'Scripts', 'python.exe')]
  for (const py of pys) {
    if (existsSync(py)) return [py, '-m', 'lclone']
  }
  return ['lclone']
}

const [lcloneBin, ...lcloneBaseArgs] = resolveLclone()

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

function runCapture(text, sessionKey, cwd, onDone) {
  const t = (text || '').trim()
  if (!t) { if (onDone) onDone(); return }
  log(`capture ${t.length} chars cwd=${cwd || '(无)'}`)
  const args = [...lcloneBaseArgs, 'capture', t]
  if (sessionKey) args.push('--session-key', sessionKey)
  if (cwd) {
    args.push('--cwd', cwd) // git 仓库 → 代码自动归属/注册
  } else {
    args.push('--project', 'global') // 无会话 cwd: 显式归全局层, 不误归 lclone 仓库
  }
  args.push('--global-fallback') // cwd 存在但非 git: 后台静默落全局, 不丢数据
  const child = spawn(lcloneBin, args, {
    cwd: REPO, // 关键: 让 `python -m lclone` 能 import 到 lclone 包
    env: { ...process.env, BRAIN_DB_PATH: join(REPO, 'lclone.db') },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: true,
  })
  let err = ''
  child.stderr.on('data', (d) => { err += d.toString() })
  child.on('error', (e) => log('spawn error: ' + e.message))
  child.on('exit', (code) => {
    log('capture exit code ' + code + (err ? '\n' + err.slice(0, 800) : ''))
    if (onDone) onDone()
  })
  child.unref()
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

export const name = 'lclone-memory'
// cordis 依赖注入: 访问 ctx.agents 前必须声明。本变更已去掉 steer, 不再用 agents。
export const inject = []

export function apply(ctx) {
  log('plugin loaded, lclone = ' + lcloneBin + ' ' + lcloneBaseArgs.join(' '))
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
              response.writeHead(200, { 'content-type': 'application/json' })
              response.end(JSON.stringify({ ok, skill: existsSync(skillPath()), webUrl: WEB_URL, docsUrl: DOCS_URL }))
            })
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
  // 按 session 累计本轮 user+assistant 文本, turn/end 时 flush 进 lclone capture
  const buffers = new Map()

  ctx.on('session/event', (session, event) => {
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
