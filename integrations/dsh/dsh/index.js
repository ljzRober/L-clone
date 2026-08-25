// L-clone 记忆钩子 (DSH 静态插件 bundle): 每轮结束自动 capture 沉淀。
//
// 事件签名已从 dsh-session 源码确认:
//   ctx.on('session/event', (session, event) => ...)
//     - turn/end:          event.data = { turn, reason }           每轮结束
//     - user/message:      event.data.content = [{type:'text', text}]
//     - assistant/message: event.data.message.content = [{type:'text'|'reasoning', text}]
//
// 安装: dsh plugin --profile web add <本目录绝对路径>
// 环境变量 LCLONE_CMD 可覆盖 lclone 命令 (默认 'lclone',
// 例如 '.venv/bin/python -m lclone' 或绝对路径)。
//
// 诊断日志写到仓库根 lclone-plugin.log (排查用, 稳定后可删)。

import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { existsSync, appendFileSync } from 'node:fs'

const LOG_PATH = join(dirname(fileURLToPath(import.meta.url)), '../../../lclone-plugin.log')

function log(msg) {
  try {
    appendFileSync(LOG_PATH, new Date().toISOString() + ' ' + msg + '\n')
  } catch {}
}

// 解析 lclone 命令: LCLONE_CMD 优先; 否则定位仓库 .venv/bin/python -m lclone;
// 再兜底 PATH 上的 lclone。
function resolveLclone() {
  if (process.env.LCLONE_CMD) return process.env.LCLONE_CMD.trim().split(/\s+/)
  const repo = join(dirname(fileURLToPath(import.meta.url)), '../../..')
  const py = join(repo, '.venv/bin/python')
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

function runCapture(text) {
  const t = (text || '').trim()
  if (!t) return
  log(`capture ${t.length} chars via ${lcloneBin} ${lcloneBaseArgs.join(' ')}`)
  const child = spawn(lcloneBin, [...lcloneBaseArgs, 'capture', t], {
    stdio: 'ignore',
    detached: true,
  })
  child.on('error', (e) => log('spawn error: ' + e.message))
  child.on('exit', (code) => log('capture exit code ' + code))
  child.unref()
}

export const name = 'lclone-memory'

export function apply(ctx) {
  log('plugin loaded, lclone = ' + lcloneBin + ' ' + lcloneBaseArgs.join(' '))
  // 按 session 累计本轮 user + assistant 文本, turn/end 时 flush 进 lclone capture
  const buffers = new Map()

  ctx.on('session/event', (session, event) => {
    if (event.type === 'user/message' || event.type === 'assistant/message') {
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
      runCapture(cur.join('\n'))
    }
  })
}
