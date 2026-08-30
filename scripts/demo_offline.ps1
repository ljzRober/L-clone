# 外置大脑 - 离线一键演示 (Windows PowerShell)
# 无需 API Key、无需安装任何第三方依赖
# 用法: powershell -ExecutionPolicy Bypass -File .\scripts\demo_offline.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
Set-Location $root

$env:BRAIN_LLM = "dummy"
$env:BRAIN_DB_PATH = Join-Path $env:TEMP "lclone_demo.db"
Remove-Item "$env:BRAIN_DB_PATH*" -ErrorAction SilentlyContinue

Write-Host "=== 1. 初始化数据库 ===" -ForegroundColor Cyan
python -m lclone init

Write-Host "`n=== 2. 注册项目 + 同步 spec 索引 ===" -ForegroundColor Cyan
python -m lclone proj add demo examples/demo_project --charter "示例项目"
python -m lclone proj sync demo

Write-Host "`n=== 3. 主动记忆 (C: 决策默认进待确认) ===" -ForegroundColor Cyan
python -m lclone remember "后端用 FastAPI, 边界: 单用户" --project demo

Write-Host "`n=== 4. 自动捕获 (dummy 后端: 记录直接生效) ===" -ForegroundColor Cyan
python -m lclone capture "讨论后确定: 6月1日上线; 部署用 Docker Compose" --project demo

Write-Host "`n=== 5. 批量确认待确认决策 ===" -ForegroundColor Cyan
python -m lclone review --all keep

Write-Host "`n=== 6. 回顾环: 检索记忆 ===" -ForegroundColor Cyan
python -m lclone recall "FastAPI 边界" --project demo

Write-Host "`n=== 7. 规范环: 边界监督 ===" -ForegroundColor Cyan
python -m lclone supervise "把数据库换成 PostgreSQL" --project demo

Write-Host "`n=== 8. 回顾环: 问答 ===" -ForegroundColor Cyan
python -m lclone ask "我们项目定了什么? 有什么边界?" --project demo

Write-Host "`n演示完成! 数据库在 $env:BRAIN_DB_PATH" -ForegroundColor Green
Remove-Item Env:BRAIN_LLM, Env:BRAIN_DB_PATH -ErrorAction SilentlyContinue
