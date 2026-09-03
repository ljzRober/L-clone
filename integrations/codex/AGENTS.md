# L-clone 记忆（Codex）

本仓库使用 L-clone 外置大脑做跨会话记忆。遵守以下规则：

- **会话开始**：先调 `lclone bootstrap "<本次话题>"`，把返回的【项目方向】【全局记忆】【相关记忆】纳入上下文；为空则跳过。
- **对话中**：出现确定信息（决定了 X / 边界是 Y / 上线时间 / 值得记的经验教训）时，调 `lclone capture "<内容>"` 沉淀为**洞察草稿**（B 类，用户 review 确认），并在回复里提示草稿号。
- **用户明确说"记住/记一下"**：调 `lclone remember "<内容>"`（C 类，只有洞察一级——已无 note/decision 之分）。默认进待确认；用户当场已确认该洞察时加 `--confirmed` 直接生效。
- **归属**：优先按当前 git 仓库匹配已注册项目（`lclone proj list` 查看）；跨项目/个人偏好落全局层；拿不准问用户。
- **分工**：改变项目 spec（需求/场景/边界）走 sp-spec（openspec）；脑内记忆（洞察/charter）走 lclone。

> 钩子已自动触发 SessionStart(bootstrap) 与 Stop(capture)，见 `integrations/codex/hooks.json`。
> 手动命令：`lclone review` 确认草稿、`lclone memories` 列出、`lclone recall` 检索。
