# 手工冒烟清单（evolution-inplace-crud）

前端 node 桩（`node:vm` + DOM 桩）**证明不了**这些：真 textarea 的取值归一、真 `closest()`/`dataset` 解码、760px 断点下 5 个工具条按钮的排版、焦点行为、以及浏览器里的真实渲染。归档前跑一遍这份清单。

## 0. 启动（推荐：隔离库，零风险）

```powershell
# 隔离库: 不碰你的真实大脑库; 验证完直接删目录
$env:BRAIN_DB_PATH     = "$env:TEMP\lclone-smoke\brain.db"
$env:LCLONE_EVO_BLOB_DIR = "$env:TEMP\lclone-smoke\blobs"
$env:LCLONE_EVO_DIR      = "$env:TEMP\lclone-smoke\cache"
New-Item -ItemType Directory -Force "$env:TEMP\lclone-smoke" | Out-Null
.\.venv\Scripts\python.exe -m lclone web      # 前台跑; 记下 URL (默认 http://127.0.0.1:8000)
```

> 想在真实库上跑就跳过前 4 行（测试资产会真的留在库里；用完可用面板的「删除」打成墓碑）。

**浏览器**：打开 `http://127.0.0.1:8000` → 若顶部有 API Key 框，把 `LCLONE_API_KEY` 粘进去回车（页面会重载并加载工作台）。

**发资产的辅助命令**（另一个终端；没开鉴权就删掉 `-Headers`）：

```powershell
$h = @{ 'X-API-Key' = $env:LCLONE_API_KEY }
function Pub($name, $content) {
  Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/evolution/publish' -Method Post `
    -ContentType 'application/json' -Headers $h `
    -Body (@{ name = $name; content = $content } | ConvertTo-Json -Compress)
}
Pub 'smoke-bin.bin' ([string][char]0 + 'raw')   # 含 NUL -> 不可编辑
Pub 'smoke-crlf.txt' "l1`r`nl2"                 # 真 CRLF (textarea 录不进 CRLF, 必须外部发)
Pub 'smoke-a"b<c>&d.txt' 'x'                    # 注入用名字
```

## 1. 清单（★ = 桩测不到、只能人工看）

| # | 步骤 | 期望 |
|---|---|---|
| 1 | 点工具条「进化」 | 面板打开；未选资产时工具条只有「＋ 新建」 |
| 2 | ＋新建 → 名字 `smoke-a.txt` + 内容 `hello` → 保存 | 版本牌成 `v1`，左侧与看板「进化」档位都出现该卡片 |
| 3 | 改内容为 `hello2` → 保存 | 版本牌 `v2`，历史区两行 |
| 4 | ★ 另开终端 `Pub 'smoke-a.txt' 'third'`，回到页面**直接点保存** | 提示"保存被拒：服务器已有 v3"，**编辑区文字仍在**；按提示刷新（会先弹"放弃编辑"确认）后内容变成服务端版本 |
| 5 | ★ 选中 `smoke-bin.bin` | 只有只读预览 + 徽标「二进制内容 · 只读」；**没有保存按钮/编辑器** |
| 6 | ★ 选中 `smoke-crlf.txt` | **不弹"有未保存的编辑"**；版本牌 `v1`；直接点「保存新版本」→ 提示"内容与 v1 相同，未产生新版本"（**不得**+1，也不得把行尾改成 LF） |
| 7 | ＋新建 → 名字 `smoke-a.txt` → 保存 | 提示"新建被拒：… 已是活跃资产"，**名字与内容都保留**，不新增版本 |
| 8 | 选中资产 → 删除 → confirm | 从默认清单消失；note 说可恢复；开「显示已删除」后该行变灰划线、标「已删除」、带「恢复」 |
| 9 | ★ 选中墓碑行（显示已删除开着） | **没有保存按钮/编辑器**，只有「恢复」；若还能看到保存入口（或点保存后提示"刷新后重试"）说明 I1 未修好 |
| 10 | 点「恢复」 | 回到默认清单，版本号与删除前一致 |
| 11 | 重命名 → `smoke-b.txt` | 新名 `v1`；旧名墓碑显示 `已删除 → smoke-b.txt`；★ 改名模式下**编辑器不可见**（内容只读呈现） |
| 12 | ★ 点历史某行「预览」→ 点「← 返回当前版本」→ 对 v1 点「回滚」 | 预览时：只读、版本牌 `vN（历史）`、有返回按钮；回滚后版本牌变 `v1`，**历史行数不变**（回滚不删版本） |
| 13 | ★ 窗口拖到 < 760px | 工具条 5 个按钮不溢出（换行也可）、编辑器单列且高度受限 |
| 14 | ★ 系统开「减少动态效果」后刷新 | 无过渡动画 |
| 15 | ★ 选中名字含 `"` `<` `>` `&` 的资产 | 清单/看板/历史处都显示为**文字**、点击能打开；F12 console 无报错 |

## 2. 收尾

- 隔离库：停掉服务后 `Remove-Item -Recurse -Force "$env:TEMP\lclone-smoke"`。
- 真实库：把 `smoke-*` 逐个「删除」（墓碑，保留历史），或保留当样本。
- **发现问题**：把"第几项 / 看到什么 / F12 有无报错"贴给我即可；我会直接记进
  `.superpowers/sdd/evolution-inplace-crud/progress.md` 并决定是否在归档前修。
