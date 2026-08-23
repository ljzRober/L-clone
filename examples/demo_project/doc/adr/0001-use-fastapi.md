# ADR-0001: 使用 FastAPI 而非 Flask

- 状态: 已接受 (Accepted)
- 日期: 2025-01-15

## 背景

需要为大脑提供 REST API 和 Web 面板, 团队熟悉 Python。

## 决策

采用 FastAPI: 自动 OpenAPI 文档、Pydantic 校验、异步支持。

## 后果

- 正面: 开发效率高, 文档免费获得
- 负面: 依赖较重; 本项目中由大脑记忆该决策, 若改为 Flask 需先经过监督
