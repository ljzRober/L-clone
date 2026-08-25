# DSH Cordis 插件（L-clone 记忆钩子）

DSH 的扩展机制是 **Cordis 动态插件**：用 `cordis_define` 定义、`cordis_run` 激活，运行时挂进宿主，不落仓库 bundle。`plugin.js` 是插件源码（plain JS，返回 `{ apply(ctx) {...} }`）。

## 已确认（从 DSH checkout 源码挖到的）

| 事件 | 形态 | 时机 | payload |
|---|---|---|---|
| `agent/session-start` | Cordis 事件 | 会话建立后、驱动启动前 | `{ source }` |
| `session/event` | Cordis 事件（事件溯源流） | 每次会话事件 | 事件对象，`event.type` 区分 |
| `turn/end`（session event type） | 会话事件 | **每轮结束** | `{ turn, reason }` |

所以：**读侧** = `agent/session-start` → `lclone bootstrap`；**写侧** = `session/event` 里过滤 `event.type === 'turn/end'` → `lclone capture`。

## 未确认（激活前需 cordis 工具查）

`plugin.js` 里两处 TODO，需要用 **cordis 预设** 的 `cordis_inspect_query` 确认后补上：

1. **执行外部命令**用哪个 Host service（`bash` / `subprocess`）及其方法签名（`cordis-plugin-development` skill 的「Choose a platform」表确认了这两个 service 存在，但方法签名要实查）。
2. **取本轮文本**：`turn/end` 只带 `{ turn, reason }`，不含正文；要拿到 user+assistant 文本，需确认 session 事件里消息的类型名（已见 `assistant/message`）或 session service 的取消息方法。

## 激活步骤（需切到 cordis 预设，本会话是 standard 预设无 cordis 工具）

1. 用 cordis 预设开一个会话（或让 DSH 以 cordis preset 挂载）。
2. `cordis_inspect_list` → 拿到 Host 的 Service/Event 清单。
3. `cordis_inspect_query` 确认上面两处 TODO 的真实接口。
4. 把补全后的 `plugin.js` 代码传给 `cordis_define`，得到 `pluginId`/`packageId`。
5. `cordis_run` 激活；`awaiting-approval` 时等审批。

## 备选：静态挂载（不动 cordis 工具）

直接把插件包进 DSH 的宿主组合 `base.cordis.yml` / `web.cordis.yml`（`~/.npm-global/lib/node_modules/@deepseek-ai/dsh/config/`），但那是改 DSH 全局安装，需谨慎。

> 读侧（bootstrap）已由 `integrations/skill/SKILL.md` 的软触发兜底；本插件的核心价值是把**写侧（capture）从"模型自觉"变成"每轮结束硬触发"**。
