"""SQLite 存储层: 分层记忆 schema + FTS + 向量编解码。

横向分层: sessions(L0 流水) / memories(L1 决策与记忆) / specs_index(L2 项目规划索引)
竖向分层: 所有记录通过 project_id 归档; project_id 为 NULL 表示个人/通用区。
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from typing import List, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  path       TEXT NOT NULL DEFAULT '',
  charter    TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  title      TEXT NOT NULL DEFAULT '',
  summary    TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at   TEXT
);

-- L1 层: 决策 / 记录
-- status: pending(草稿, 待确认) | active(正式) | archived(归档)
-- source_type: auto(自动捕获) | manual(主动触发)
CREATE TABLE IF NOT EXISTS memories (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  level        TEXT NOT NULL DEFAULT 'note',   -- decision | note
  module       TEXT NOT NULL DEFAULT '',       -- 项目内可选模块 (次级竖向划分), 空=直接挂项目
  content      TEXT NOT NULL,
  reason       TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'active',
  source_type  TEXT NOT NULL DEFAULT 'manual',
  source_ref   TEXT NOT NULL DEFAULT '',
  embedding    BLOB,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  confirmed_at TEXT
);

-- L2 层: 项目内 spec 文件的索引 (格式无关: openspec / adr / markdown / other)
-- 权威内容永远在项目仓库里, 这里只存定位信息 + 摘要 + 哈希
CREATE TABLE IF NOT EXISTS specs_index (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  rel_path       TEXT NOT NULL,
  format         TEXT NOT NULL DEFAULT 'markdown',
  title          TEXT NOT NULL DEFAULT '',
  summary        TEXT NOT NULL DEFAULT '',
  sha            TEXT NOT NULL DEFAULT '',
  last_indexed_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, rel_path)
);

-- 项目内声明的模块 (modules): 让"添加模块"能创建空模块并显示; 记忆的 module 字段引用模块名
CREATE TABLE IF NOT EXISTS modules (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name       TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(project_id, name)
);
CREATE INDEX IF NOT EXISTS idx_modules_proj ON modules(project_id);

CREATE TABLE IF NOT EXISTS threads (
  id         TEXT PRIMARY KEY,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 记忆间链接: 内容里写 [[m:12]] 即建立指向 #12 的链接
-- (召回时顺藤加载被链接的记忆; 跨项目/跨层级链接不受竖向切分限制)
CREATE TABLE IF NOT EXISTS memory_links (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id  INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  target_id  INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(source_id, target_id)
);

-- 召回日志: 记录每条记忆被召回的时间, 用于"长期未用"删除提示
CREATE TABLE IF NOT EXISTS recall_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id  INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  recalled_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 项目墓碑: proj rm 不删行、不加状态字段, 只在此登记移除事件;
-- 读取时(recall/ask/proj list)据此决定"该项目已死, 记忆不再加载"
CREATE TABLE IF NOT EXISTS project_removals (
  project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  name       TEXT NOT NULL DEFAULT '',
  removed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id  TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role       TEXT NOT NULL,
  content    TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_proj ON memories(project_id, status);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_sessions_proj ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_specs_proj ON specs_index(project_id);
CREATE INDEX IF NOT EXISTS idx_memlinks_source ON memory_links(source_id);
CREATE INDEX IF NOT EXISTS idx_memlinks_target ON memory_links(target_id);
CREATE INDEX IF NOT EXISTS idx_recall_log_mem ON recall_log(memory_id);
"""


def _fts_tokenizer(conn: sqlite3.Connection) -> str:
    ver = conn.execute("select sqlite_version()").fetchone()[0]
    major, minor, *_ = ver.split(".")
    return "trigram" if (int(major), int(minor)) >= (3, 34) else "unicode61"


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or config.db_path()
    parent = Path(path).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    # 迁移: 旧库给 memories 补 module 列 (项目内模块维度, 可选)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(memories)")]
    if "module" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN module TEXT NOT NULL DEFAULT ''")
    tok = _fts_tokenizer(conn)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
        f"USING fts5(content, reason, tokenize='{tok}')"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN "
        "INSERT INTO memories_fts(rowid, content, reason) "
        "VALUES (new.id, new.content, new.reason); END"
    )
    # 修复: FTS5 的 'delete' 特殊命令只适用于 external-content 表, 普通 FTS5
    # 表删除行必须用常规 DELETE; 旧触发器会导致删除记忆时报 SQL logic error
    conn.execute("DROP TRIGGER IF EXISTS memories_ad")
    conn.execute(
        "CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN "
        "DELETE FROM memories_fts WHERE rowid = old.id; END"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------- 向量编解码
def pack_vec(vec: List[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vec(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


# ---------------------------------------------------------------- 在线备份
def backup(db_path: Optional[str] = None, dest_dir: str = "backups") -> str:
    """SQLite 在线备份: 用 backup API 安全快照到 dest_dir/lclone-<时间戳>.db。

    走 SQLite 的 online backup (而非直接 copy 文件), WAL 模式下也安全;
    返回快照文件路径。
    """
    import datetime
    src_path = db_path or config.db_path()
    d = Path(dest_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = d / f"lclone-{stamp}.db"
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return str(dest)
