// L-clone 记忆钩子 (DSH 静态插件 bundle): 每轮结束自动 capture 沉淀。
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

function runCapture(text, sessionKey, cwd) {
  const t = (text || '').trim()
  if (!t) return
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
  })
  child.unref()
}

export const name = 'lclone-memory'

export function apply(ctx) {
  log('plugin loaded, lclone = ' + lcloneBin + ' ' + lcloneBaseArgs.join(' '))
  // 按 session 累计本轮 user + assistant 文本, turn/end 时 flush 进 lclone capture
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
      runCapture(cur.join('\n'), session.id, cwd)
    }
  })
}
