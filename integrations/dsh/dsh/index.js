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

import { spawn } from 'node:child_process'

const LCLONE_CMD = (process.env.LCLONE_CMD || 'lclone').trim()
const [lcloneBin, ...lcloneBaseArgs] = LCLONE_CMD.split(/\s+/)

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
  const child = spawn(lcloneBin, [...lcloneBaseArgs, 'capture', t], {
    stdio: 'ignore',
    detached: true,
  })
  child.on('error', () => {}) // 失败静默, 不干扰 DSH
  child.unref()
}

export const name = 'lclone-memory'

export function apply(ctx) {
  // 按 session 累计本轮 user + assistant 文本, turn/end 时 flush 进 lclone capture
  const buffers = new Map()

  ctx.on('session/event', (session, event) => {
    const text = extractText(event)
    if (text) {
      const cur = buffers.get(session.id) || []
      cur.push(text)
      buffers.set(session.id, cur)
    }
    if (event.type === 'turn/end') {
      const cur = buffers.get(session.id) || []
      buffers.delete(session.id)
      runCapture(cur.join('\n'))
    }
  })
}
