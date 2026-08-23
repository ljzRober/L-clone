# 整体架构

> 回到 [README](../README.md) | 设计理念见 [DESIGN.md](DESIGN.md)
>
> 以下图表均为 Mermaid, 在 GitHub 上可直接渲染。

## 1. 系统架构图

```mermaid
flowchart TB
    subgraph 访问层["访问层 (任何设备 / 浏览器)"]
        CLI["CLI 命令行<br/>lclone init / proj / remember / capture / ask / supervise"]
        WEB["Web 面板<br/>FastAPI + 单页 HTML<br/>浏览器打开 http://服务器:8000"]
        API["REST API<br/>/api/ask /api/capture /api/supervise ..."]
    end

    subgraph 核心逻辑["核心逻辑 (纯函数, 与访问层解耦)"]
        MEM["记忆模块<br/>remember(C) / capture(B) / review / recall"]
        PROJ["项目模块<br/>proj add / sync / spec 格式无关索引"]
        CHAT["问答模块<br/>ask (回顾环)"]
        SUPE["监督模块<br/>supervise (规范环)"]
    end

    subgraph 存储层["存储层"]
        DB[("SQLite lclone.db<br/>projects / sessions / memories<br/>specs_index / threads / messages<br/>memories_fts (全文索引)")]
    end

    subgraph 模型层["模型层 (云端 API, 不本地部署)"]
        LLM["LLM 接口<br/>chat: 提炼决策 / 问答 / 监督"]
        EMB["Embedding 接口<br/>向量化: 记忆相似度检索"]
    end

    CLI --> MEM
    CLI --> PROJ
    CLI --> CHAT
    CLI --> SUPE
    WEB --> MEM
    WEB --> PROJ
    WEB --> CHAT
    WEB --> SUPE
    API --> MEM
    API --> PROJ
    API --> CHAT
    API --> SUPE
    MEM --> DB
    PROJ --> DB
    CHAT --> DB
    SUPE --> DB
    PROJ -. 只读索引 .-> REPO["项目仓库<br/>.specs/ 与 doc/adr/ (权威内容)"]
    MEM --> EMB
    MEM --> LLM
    CHAT --> LLM
    SUPE --> LLM
```

> `BRAIN_LLM=dummy` 时模型层由内置离线后端替代, 无需网络与 API Key。

## 2. 数据存储结构 (ER 图)

```mermaid
erDiagram
    PROJECTS ||--o{ SESSIONS : "归档于"
    PROJECTS ||--o{ MEMORIES : "归档于"
    PROJECTS ||--o{ SPECS_INDEX : "索引于"
    PROJECTS ||--o{ THREADS : "对话关联"
    THREADS ||--o{ MESSAGES : "包含"
    MEMORIES ||--o| MEMORIES_FTS : "全文索引"

    PROJECTS {
        int id PK "项目命名空间"
        text name UK "项目名"
        text path "仓库路径"
        text charter "大方向一句话"
        text created_at
        text updated_at
    }

    SESSIONS {
        int id PK "L0 流水"
        int project_id FK "NULL=个人区"
        text title
        text summary "一句话摘要"
        text started_at
        text ended_at
    }

    MEMORIES {
        int id PK "L1 核心记忆"
        int project_id FK "NULL=个人区"
        text level "decision/milestone/note"
        text content "记忆正文"
        text reason "为什么记"
        text status "pending草稿/active正式/archived归档"
        text source_type "auto自动/manual主动"
        text source_ref "来源: 会话或 ADR 文件"
        blob embedding "向量"
        text created_at
        text confirmed_at "B 确认制生效时间"
    }

    SPECS_INDEX {
        int id PK "L2 项目规划索引"
        int project_id FK
        text rel_path "仓库内相对路径"
        text format "openspec/adr/markdown/other"
        text title
        text summary "摘要"
        text sha "内容哈希(检测变更)"
        text last_indexed_at
    }

    THREADS {
        text id PK "uuid"
        int project_id FK "NULL=个人区"
        text created_at
    }

    MESSAGES {
        int id PK
        text thread_id FK
        text role "user/assistant"
        text content
        text created_at
    }

    MEMORIES_FTS {
        int rowid "= memories.id"
        text content
        text reason
    }
```

## 3. 记忆写入流程 (B 确认制 + C 主动触发)

```mermaid
flowchart LR
    subgraph C["C 主动触发 (你说算)"]
        C1["lclone remember 内容"] --> C2[("正式记忆 active<br/>立即生效")]
    end
    subgraph B["B 自动捕获 (AI 提炼, 你确认)"]
        B1["lclone capture 对话内容"] --> B2["LLM 提炼决策"]
        B2 --> B3[("草稿区 pending")]
        B3 --> B4{"你 review 每条草稿"}
        B4 -- "保留" --> B5[("正式记忆 active")]
        B4 -- "编辑" --> B6["修改内容"] --> B5
        B4 -- "删除" --> B7["丢弃"]
    end
    B5 --> R["参与后续<br/>recall 回顾 / supervise 监督"]
    C2 --> R
    B5 -. 带来源引用 source_ref 可回溯 .-> B1
```

## 4. 回顾环 (新会话想起过去)

```mermaid
sequenceDiagram
    autonumber
    participant U as 你 (CLI / Web)
    participant B as 大脑
    participant DB as SQLite
    participant LLM as 模型 API
    U->>B: ask 问题 --project X
    B->>DB: 向量 + 关键词检索相关记忆
    DB-->>B: 命中的记忆 (含来源)
    B->>DB: 读取项目上下文 (charter / 决策 / spec 索引)
    DB-->>B: 项目上下文
    B->>LLM: 问题 + 记忆 + 项目上下文
    LLM-->>B: 回答
    B->>DB: 存档进线程 messages
    B-->>U: 回答 + 召回的引用
```

## 5. 规范环 (新提议对照边界条件)

```mermaid
sequenceDiagram
    autonumber
    participant U as 你
    participant B as 大脑
    participant REPO as 项目仓库
    participant LLM as 模型 API
    U->>B: supervise 新提议 --project X
    B->>B: 汇总 charter + 已确认决策
    B->>REPO: 读取 .specs/ 与 doc/adr/ 原文 (权威)
    REPO-->>B: 规格 / 边界条件 / 决策记录
    B->>LLM: 新提议 + 边界条件清单, 要求逐条对照
    LLM-->>B: 检查报告 通过/警告/违反
    B-->>U: 检查报告 + 修正建议
```

## 6. 竖向分层: 大脑与项目的分工

```mermaid
flowchart LR
    subgraph PROJECT["项目仓库 (权威, git 管理)"]
        SPEC[".specs/ 当前规格与边界"]
        ADR["doc/adr/ 决策记录"]
        CODE["代码 / PR / issue"]
    end
    subgraph BRAIN["大脑 L-clone (记忆与监督)"]
        IDX["specs_index 格式无关索引"]
        DEC["决策记忆 / 重要修改点"]
        SES["会话流水"]
        CH["charter 大方向"]
    end
    SPEC -->|"proj sync 只读索引"| IDX
    ADR -->|"proj sync 只读索引"| IDX
    IDX --> DEC
```

> 具体事务 (spec 全文 / 代码 / PR) 永远留在项目仓库; 大脑只管大方向、
> 决策记忆、重要修改点, 并在监督时引用仓库原文。
