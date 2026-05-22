-- Canonical SQLite schema for one snapshot's code graph.
-- One graph.db per snapshot; snapshots are immutable, so this is
-- written exactly once and never mutated row-by-row.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE files (
    path         TEXT PRIMARY KEY,
    language     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size         INTEGER NOT NULL,
    node_count   INTEGER NOT NULL DEFAULT 0,
    errors       TEXT NOT NULL DEFAULT '[]',
    indexed_at   REAL NOT NULL DEFAULT 0
);

CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    qualname    TEXT NOT NULL,
    language    TEXT NOT NULL,
    file        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL,
    signature   TEXT,
    docstring   TEXT,
    summary     TEXT,
    decorators  TEXT NOT NULL DEFAULT '[]',
    bases       TEXT NOT NULL DEFAULT '[]',
    visibility  TEXT NOT NULL DEFAULT 'public',
    is_exported INTEGER NOT NULL DEFAULT 0,
    is_async    INTEGER NOT NULL DEFAULT 0,
    is_abstract INTEGER NOT NULL DEFAULT 0,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE edges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'ast',
    file       TEXT,
    line       INTEGER,
    metadata   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE unresolved (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_node TEXT NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    file      TEXT,
    line      INTEGER
);

CREATE INDEX idx_nodes_kind ON nodes(kind);
CREATE INDEX idx_nodes_qualname ON nodes(qualname);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_nodes_file ON nodes(file);
CREATE INDEX idx_edges_source_kind ON edges(source, kind);
CREATE INDEX idx_edges_target_kind ON edges(target, kind);
CREATE INDEX idx_unresolved_from ON unresolved(from_node);
