# 与生态的关系

> 回到 [README](../README.md)

L-clone 不重复造轮子, 站在已有开源生态之上, 借鉴其思想并解决其缺口。

## 借鉴的项目

| 项目 | 借鉴点 | 我们的改进 |
|---|---|---|
| [GBrain](https://github.com/garrytan/gbrain) | Postgres 原生知识库: pages(编译真相)+ 时间线 | 用 SQLite 落地同思路: sessions + 版本化记忆 |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | 项目内 `.specs/` 规格约定 | 兼容其目录约定, 但**格式无关**, 可换任意 spec 格式 |
| [ADR](https://realpython.com/ref/software-engineering-glossary/architecture-decision-record/) | `doc/adr/` 决策记录约定 | 大脑索引 ADR, 监督时引用原文 |
| [claude-mem](https://github.com/osamarehman/claude-mem) | 会话捕获 → 压缩 → 注入 | 机制已落地(MCP + hooks/插件), 且不绑定 Claude Code(MCP 通用) |
| [Mem0](https://vectorize.io/articles/mem0-vs-letta) | 对话 → 结构化记忆抽取 | 增加 **B 确认制**: AI 写草稿, 你盖章 |

## 解决的问题

1. **AI 无状态**: 每次对话从零开始, 不记得你的决策 → 回顾环注入持久记忆
2. **AI 总结不可信**: 全自动抽取会幻觉 → B 确认制(草稿 + 人工确认)
3. **spec 与记忆分离**: 具体事务留仓库(git 管真相), 大脑管跨会话记忆与监督
4. **生态锁定**: 不绑任何工具 —— MCP 接口(stdio + HTTP)+ DSH / Claude Code / Codex 插件 + OpenAI 兼容 API + 格式无关索引

## 概念映射

| L-clone | 传统概念 |
|---|---|
| sessions(L0) | 工作日志 / changelog |
| memories(L1) | 决策记录 / ADR 摘要 |
| specs_index(L2) | 项目规格索引 |
| supervise(规范环) | spec 合规检查 / 边界守卫 |
| recall(回顾环) | 记忆检索 / RAG |
