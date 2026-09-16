## ADDED Requirements

### Requirement: 清单携带引用计数

`GET /api/evolution/index` SHALL 在每个条目上追加 `ref_count`（整数）与 `refs`（数组，元素含 `id` / `project_id` / `project_name`），使看板一次请求即可显示「谁在引用这个资产」。零引用 SHALL 以 `ref_count=0` 与 `refs=[]` 表达，SHALL NOT 返回 null 或省略字段。既有 `GET /api/evolutions` 的响应形状 SHALL 保持不变（只允许追加字段；本需求不向其追加任何字段）。

#### Scenario: 计数随清单下发

WHEN 看板请求 `/api/evolution/index`
THEN 每个条目带 `ref_count` 与 `refs`；零引用资产返回 `ref_count=0`、`refs=[]`

#### Scenario: 既有端点不受影响

WHEN 请求 `/api/evolutions`
THEN 条目仍含 name/ext/size/mtime/is_dir/children/content，形状与既有前端兼容

#### Scenario: 引用随资产状态变化

WHEN 某资产的引用者被删除或从 active 变为 pending
THEN 该资产的 `ref_count` 与 `refs` 同步反映 active 引用者数量，不残留已失效引用
