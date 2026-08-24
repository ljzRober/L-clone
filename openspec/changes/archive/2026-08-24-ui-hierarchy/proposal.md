## Why

Web 面板目前是平铺的五个页签，记忆列表只有扁平条目，看不到"全局层 → 项目 → 记忆"的层级归属；用户无法直观理解每条记忆的生命周期位置（全局层无限 / 项目层随项目绑定），上升/下降等整理操作缺乏语境。需要一个把层级结构作为一等公民展示的界面。

## What Changes

- Web 面板改为**左侧层级导航 + 右侧内容区**的两栏布局：左侧固定层级树（全局层 ∞、项目列表、注册入口），右侧内容区随选中层级切换。
- 记忆卡片增加**层级轨道签名元素**（全局=金色轨 / 项目=蓝色轨）与层级徽章、链接 🔗 标记、上升/下降操作。
- 视觉令牌整体重设计（墨蓝黑底 + 黄铜金强调 + 衬线标题 + 等宽档案编号），遵循 frontend-design：非模板默认、一个签名元素、响应式、`prefers-reduced-motion`、动态内容全部转义（XSS）。
- 顶部页签精简为「问答 | 记忆」两个：待确认草稿并入记忆面板、边界监督并入问答面板；项目注册入口保留在左侧层级导航底部；项目选择与左侧层级导航联动。
- 纯 CSS 重构，保持零第三方依赖（无 CDN、无构建）；后端 API 不变。

## Capabilities

- **New Capabilities**:
  - `web-hierarchy`：Web 面板层级导航与层级归属展示（新 spec）
- **Modified Capabilities**: 无（openspec/specs/ 为空，无既有 spec）

## Impact

- 文件：`lclone/web.py`（HTML/CSS/JS 内嵌块重写，后端 API 与 Pydantic 模型不变）
- API：不变（/api/projects、/api/memories、/api/recall、/api/suggest、/api/memories/{id}/promote、/demote 等全部保留）
- 测试：`tests/test_offline.py` 的 Web 路由冒烟检查不受影响
- 依赖：无新增
