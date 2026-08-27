// L-clone 记忆钩子 (DSH 静态插件 bundle): 每轮结束自动 capture 沉淀 + 待确认决策强制提醒。
//
// 事件签名已从 dsh-session 源码确认:
//   ctx.on('session/event', (session, event) => ...)
//     - turn/end:          event.data = { turn, reason }           每轮结束
//     - user/message:      event.data.content = [{type:'text', text}]
//     - assistant/message: event.data.message.content = [{type:'text'|'reasoning', text}]
//
// 决策强确认: turn/end 时若存在 pending 决策, 用 agent.followup() 强制注入新一轮 turn,
// 唤醒 agent 让其推一条选择消息给用户 (代码强制, 不靠 agent 自觉)。
//
// 安装: dsh plugin --profile web add <本目录绝对路径>
// 环境变量 LCLONE_CMD 可覆盖 lclone 命令。
// 关键: spawn 时必须 cwd=仓库根, 否则 `python -m lclone` 找不到 lclone 包。

import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { existsSync, appendFileSync } from 'node:fs'

// 仓库根 (插件经 symlink 链入仓库, import.meta.url 是真实路径)
const REPO = join(dirname(fileURLToPath(import.meta.url)), '../../..')
const LOG_PATH = join(REPO, 'lclone-plugin.log')

function log(msg) {
  try {
    appendFileSync(LOG_PATH, new Date().toISOString() + ' ' + msg + '\n')
  } catch {}
}

// 解析 lclone 命令: LCLONE_CMD 优先; 否则定位仓库 .venv/bin/python -m lclone。
function resolveLclone() {
  if (process.env.LCLONE_CMD) return process.env.LCLONE_CMD.trim().split(/\s+/)
  const py = join(REPO, '.venv/bin/python')
  if (existsSync(py)) return [py, '-m', 'lclone']
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
    if (onDone) onDone() // capture 完成后再探测 pending, 避免漏掉本轮刚捕获的决策
  })
  child.unref()
}

// 检查 pending 决策数; 有新增 pending 时用 agent.followup 强制唤醒 agent 提醒用户
const notified = new Map() // sessionId -> 上次已提醒的 pending 数 (去重, 防循环)

function checkPendingAndNotify(ctx, sessionId) {
  const child = spawn(lcloneBin, [...lcloneBaseArgs, 'pending'], {
    cwd: REPO,
    env: { ...process.env, BRAIN_DB_PATH: join(REPO, 'lclone.db') },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: true,
  })
  let out = ''
  child.stdout.on('data', (d) => { out += d.toString() })
  child.on('exit', (code) => {
    if (code !== 0) return
    const n = parseInt(out.trim(), 10)
    if (Number.isNaN(n)) return
    const last = notified.get(sessionId) || 0
    if (n > last) {
      notified.set(sessionId, n)
      const agent = ctx.agents.get(sessionId)
      if (!agent) { log('agent not found for ' + sessionId); return }
      try {
        // 参照 dsh-better-sidebar 的 admitFollowup: followup 用 source {kind:'user'} 唤醒 agent
        agent.followup({
          id: randomUUID(),
          role: 'user',
          content: [{ type: 'text', text: `【系统】当前有 ${n} 条待确认决策（lclone pending）。请立即用 ask_user_question 逐条向用户确认「保留/删除」，用户拍板后调用 lclone review 处理，不要静默跳过。` }],
          source: { kind: 'user' },
        })
        log(`followup injected for ${sessionId}: ${n} pending`)
      } catch (e) {
        log('followup failed: ' + (e && e.message))
      }
    } else if (n === 0) {
      notified.set(sessionId, 0) // 清空后重置, 下次新增再提醒
    }
  })
  child.unref()
}

export const name = 'lclone-memory'
// cordis 依赖注入: 访问 ctx.agents 前必须声明 (否则报 "cannot get property 'agents' without inject")
export const inject = ['agents']

export function apply(ctx) {
  log('plugin loaded, lclone = ' + lcloneBin + ' ' + lcloneBaseArgs.join(' '))
  // 按 session 累计本轮 user 文本, turn/end 时 flush 进 lclone capture
  const buffers = new Map()

  ctx.on('session/event', (session, event) => {
    // 只捕获用户消息: 决策由用户提出, assistant 的总结/元陈述不应被当成决策
    if (event.type === 'user/message') {
      const text = extractText(event)
      if (text) {
        const cur = buffers.get(session.id) || []
        cur.push(text)
        buffers.set(session.id, cur)
      }
    }
    if (event.type === 'turn/end') {
      log(`turn/end fired: session=${session.id} turn=${event.data && event.data.turn}`)
      const cur = buffers.get(session.id) || []
      buffers.delete(session.id)
      const cwd = (session.header && session.header.cwd) || session.cwd || session.meta?.cwd
      runCapture(cur.join('\n'), session.id, cwd, () => {
        checkPendingAndNotify(ctx, session.id) // capture 完成后再探测 pending, 决策强确认
      })
    }
  })
}
