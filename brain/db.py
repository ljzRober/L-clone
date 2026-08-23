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

-- L1 层: 决策 / 重要修改点 / 记录
-- status: pending(草稿, 待确认) | active(正式) | archived(归档)
-- source_type: auto(自动捕获) | manual(主动触发)
CREATE TABLE IF NOT EXISTS memories (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id   INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  level        TEXT NOT NULL DEFAULT 'note',   -- decision | milestone | note
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

CREATE TABLE IF NOT EXISTS threads (
  id         TEXT PRIMARY KEY,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
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
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN "
        "INSERT INTO memories_fts(memories_fts, rowid, content, reason) "
        "VALUES ('delete', old.id, old.content, old.reason); END"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------- 向量编解码
def pack_vec(vec: List[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vec(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
