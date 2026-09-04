#!/usr/bin/env node
// lclone-memory-dsh 一键初始化（自包含 bundle 的安装引导）。
// 用法: node <本包>/scripts/install.js
//   1) 创建 ~/.lclone/venv(可用 LCLONE_VENV / LCLONE_STATE_DIR 覆盖)
//   2) 装依赖 (brain/requirements.txt)
//   3) 配模型: env(OPENAI_API_KEY/BRAIN_BASE_URL/BRAIN_CHAT_MODEL/...) 优先写入 .env; 否则提示交互式 setup
//   4) 可选: 启动后端 (lclone serve start / 运行 python -m lclone web)
import { spawnSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { homedir } from 'node:os'
import { existsSync, writeFileSync, mkdirSync } from 'node:fs'

const PKG = dirname(dirname(fileURLToPath(import.meta.url))) // …/integrations/dsh
const BRAIN = join(PKG, 'brain')
const STATE = process.env.LCLONE_STATE_DIR || join(homedir(), '.lclone')
const VENV = process.env.LCLONE_VENV || join(STATE, 'venv')
const PY = process.platform === 'win32'
  ? join(VENV, 'Scripts', 'python.exe') : join(VENV, 'bin', 'python')
const PIP = process.platform === 'win32'
  ? join(VENV, 'Scripts', 'pip.exe') : join(VENV, 'bin', 'pip')

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts })
  if (r.status !== 0) {
    console.error(`✗ ${cmd} ${args.join(' ')} 失败 (退出码 ${r.status})`)
    process.exit(1)
  }
}

// 用 venv python 跑 lclone: 需让它能 import 到内嵌的 brain/lclone (PYTHONPATH)。
function runLclone(args) {
  run(PY, ['-m', 'lclone', ...args], { env: { ...process.env, PYTHONPATH: BRAIN } })
}

console.log('lclone-memory-dsh 一键初始化')
console.log('  brain:', BRAIN)
console.log('  venv :', VENV)

if (!existsSync(PY)) {
  console.log('→ 创建 Python 虚拟环境...')
  const py3 = spawnSync('python3', ['-m', 'venv', VENV], { stdio: 'inherit' })
  const py = spawnSync('python', ['-m', 'venv', VENV], { stdio: 'inherit' })
  if (py3.status !== 0 && py.status !== 0) {
    console.error('✗ 未找到 python3/python，请先安装 Python >=3.10')
    process.exit(1)
  }
} else {
  console.log('✓ venv 已存在')
}

console.log('→ 安装依赖 (brain/requirements.txt)...')
run(PIP, ['install', '-r', join(BRAIN, 'requirements.txt')])

// 配模型: 有 env 就写 .env, 否则提示交互式
const envPath = join(STATE, '.env')
const envKeys = ['BRAIN_DB_PATH', 'BRAIN_LLM', 'OPENAI_API_KEY', 'BRAIN_BASE_URL',
  'BRAIN_CHAT_MODEL', 'BRAIN_EMBED_MODEL', 'BRAIN_EMBED_BACKEND', 'BRAIN_TEMPERATURE']
const have = envKeys.filter((k) => process.env[k])
if (have.length) {
  const lines = envKeys.filter((k) => process.env[k]).map((k) => `${k}=${process.env[k]}`)
  mkdirSync(STATE, { recursive: true })
  writeFileSync(envPath, lines.join('\n') + '\n', 'utf-8')
  console.log(`✓ 已写配置: ${envPath}\n   (${have.join(', ')})`)
} else {
  console.log(`⚠ 未检测到模型环境变量。可设置下面任一后重跑，或用交互式: ` +
    `\n   ${PY} -m lclone setup   (选 provider + 填 key)` +
    `\n   OPENAI_API_KEY / BRAIN_BASE_URL / BRAIN_CHAT_MODEL`)
}

// 可选: 启后端
const start = process.env.LCLONE_INSTALL_START
if (start === '1') {
  console.log('→ 启动后端 (serve start)...')
  runLclone(['serve', 'start'])
  console.log('✓ 后端已后台常驻; 插件看板用 LCLONE_WEB_URL(默认 http://127.0.0.1:8000) 连接')
} else {
  console.log('✓ 完成。默认后端地址 http://127.0.0.1:8000; 手动启动: ' +
    `${PY} -m lclone web  (或 ${PY} -m lclone serve start)` +
    `\n   (需 PYTHONPATH=${BRAIN})`)
}
