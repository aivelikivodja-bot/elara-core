# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""
Knowledge Graph Store — SQLite graph + ChromaDB semantic index.

First SQLite module in Elara Core. Graph queries across 6 dimensions need
proper indexing that JSON files can't provide efficiently.

Tables:
  nodes     — 6-tuple addressed entities (time, source, type, granularity, confidence, semantic_id)
  edges     — directed relationships between nodes
  aliases   — maps variant names to canonical semantic_ids
  documents — registry of indexed documents

ChromaDB:
  elara_knowledge — cosine similarity search over node content
"""

import hashlib
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

from core.paths import get_paths

logger = logging.getLogger("elara.knowledge")


# ============================================================================
# Schema
# ============================================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    semantic_id TEXT NOT NULL,
    time TEXT,
    source_doc TEXT,
    source_section TEXT,
    source_line INTEGER,
    type TEXT NOT NULL DEFAULT 'reference',
    granularity TEXT NOT NULL DEFAULT 'section',
    confidence REAL NOT NULL DEFAULT 0.5,
    content TEXT,
    created TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_semantic_id ON nodes(semantic_id);
CREATE INDEX IF NOT EXISTS idx_nodes_source_doc ON nodes(source_doc);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source_node TEXT NOT NULL,
    target_node TEXT,
    target_doc TEXT,
    edge_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    explanation TEXT,
    created TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);

CREATE TABLE IF NOT EXISTS aliases (
    semantic_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    PRIMARY KEY (semantic_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    path TEXT,
    indexed_at TEXT NOT NULL,
    node_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0
);
"""


# ============================================================================
# Store
# ============================================================================

class KnowledgeStore:
    """SQLite graph + ChromaDB semantic index for the knowledge graph."""

    def __init__(self):
        self._p = get_paths()
        self._conn: Optional[sqlite3.Connection] = None
        self._chroma_client = None
        self._chroma_collection = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _db(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        db_path = self._p.knowledge_db
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        return self._conn

    def _collection(self):
        if self._chroma_collection is not None:
            return self._chroma_collection

        if not CHROMA_AVAILABLE:
            return None

        try:
            db_dir = self._p.knowledge_vector_db
            db_dir.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(
                path=str(db_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="elara_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            return self._chroma_collection
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("Failed to init knowledge ChromaDB: %s", e)
            return None

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_node(
        self,
        semantic_id: str,
        content: str,
        *,
        node_id: Optional[str] = None,
        time: Optional[str] = None,
        source_doc: Optional[str] = None,
        source_section: Optional[str] = None,
        source_line: Optional[int] = None,
        node_type: str = "reference",
        granularity: str = "section",
        confidence: float = 0.5,
    ) -> str:
        """Add a node to the graph. Returns the node id."""
        if not node_id:
            raw = f"{semantic_id}:{source_doc}:{source_section}:{source_line}:{content[:50]}"
            node_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        now = datetime.now().isoformat()
        db = self._db()
        db.execute(
            """INSERT OR REPLACE INTO nodes
               (id, semantic_id, time, source_doc, source_section, source_line,
                type, granularity, confidence, content, created)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (node_id, semantic_id, time, source_doc, source_section, source_line,
             node_type, granularity, confidence, content, now),
        )
        db.commit()

        # Index in ChromaDB
        coll = self._collection()
        if coll and content and content.strip():
            try:
                metadata = {
                    "semantic_id": semantic_id,
                    "type": node_type,
                    "granularity": granularity,
                    "confidence": confidence,
                }
                if source_doc:
                    metadata["source_doc"] = source_doc
                if time:
                    metadata["time"] = time
                coll.upsert(
                    ids=[node_id],
                    documents=[content],
                    metadatas=[metadata],
                )
            except Exception as e:
                logger.warning("Failed to index node %s in ChromaDB: %s", node_id, e)

        return node_id

    def add_nodes_batch(self, nodes: List[Dict]):
        """Add multiple nodes in one batch — much faster than add_node() in a loop."""
        if not nodes:
            return

        db = self._db()
        now = datetime.now().isoformat()

        # SQLite batch insert
        for node in nodes:
            nid = node.get("id") or node.get("node_id")
            if not nid:
                raw = f"{node['semantic_id']}:{node.get('source_doc')}:{node.get('source_section')}:{node.get('source_line')}:{(node.get('content') or '')[:50]}"
                nid = hashlib.sha256(raw.encode()).hexdigest()[:16]
                node["id"] = nid

            db.execute(
                """INSERT OR REPLACE INTO nodes
                   (id, semantic_id, time, source_doc, source_section, source_line,
                    type, granularity, confidence, content, created)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, node["semantic_id"], node.get("time"), node.get("source_doc"),
                 node.get("source_section"), node.get("source_line"),
                 node.get("type", "reference"), node.get("granularity", "section"),
                 node.get("confidence", 0.5), node.get("content"), now),
            )
        db.commit()

        # ChromaDB batch upsert
        coll = self._collection()
        if not coll:
            return

        ids = []
        documents = []
        metadatas = []
        for node in nodes:
            content = node.get("content", "")
            if not content or not content.strip():
                continue
            nid = node.get("id") or node.get("node_id")
            metadata = {
                "semantic_id": node["semantic_id"],
                "type": node.get("type", "reference"),
                "granularity": node.get("granularity", "section"),
                "confidence": node.get("confidence", 0.5),
            }
            if node.get("source_doc"):
                metadata["source_doc"] = node["source_doc"]
            if node.get("time"):
                metadata["time"] = node["time"]
            ids.append(nid)
            documents.append(content)
            metadatas.append(metadata)

        if ids:
            try:
                coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
            except Exception as e:
                logger.warning("Batch ChromaDB upsert failed: %s", e)

    def add_edges_batch(self, edges: List[Dict]):
        """Add multiple edges in one batch."""
        if not edges:
            return
        db = self._db()
        now = datetime.now().isoformat()
        for edge in edges:
            eid = edge.get("id")
            if not eid:
                raw = f"{edge['source_node']}:{edge['edge_type']}:{edge.get('target_node')}:{edge.get('target_doc')}"
                eid = hashlib.sha256(raw.encode()).hexdigest()[:16]
            db.execute(
                """INSERT OR REPLACE INTO edges
                   (id, source_node, target_node, target_doc, edge_type, confidence, explanation, created)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, edge["source_node"], edge.get("target_node"), edge.get("target_doc"),
                 edge["edge_type"], edge.get("confidence", 0.5), edge.get("explanation"), now),
            )
        db.commit()

    def add_aliases_batch(self, aliases: List[Tuple[str, str]]):
        """Add multiple aliases in one batch."""
        if not aliases:
            return
        db = self._db()
        for semantic_id, alias in aliases:
            db.execute(
                "INSERT OR IGNORE INTO aliases (semantic_id, alias) VALUES (?, ?)",
                (semantic_id, alias.lower()),
            )
        db.commit()

    def get_node(self, node_id: str) -> Optional[Dict]:
        row = self._db().execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row) if row else None

    def get_nodes_by_semantic_id(self, semantic_id: str) -> List[Dict]:
        rows = self._db().execute(
            "SELECT * FROM nodes WHERE semantic_id = ? ORDER BY created",
            (semantic_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_nodes_by_doc(self, doc_id: str) -> List[Dict]:
        rows = self._db().execute(
            "SELECT * FROM nodes WHERE source_doc = ? ORDER BY source_line",
            (doc_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_nodes_by_type(self, node_type: str, doc_id: Optional[str] = None) -> List[Dict]:
        if doc_id:
            rows = self._db().execute(
                "SELECT * FROM nodes WHERE type = ? AND source_doc = ?",
                (node_type, doc_id),
            ).fetchall()
        else:
            rows = self._db().execute(
                "SELECT * FROM nodes WHERE type = ?", (node_type,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source_node: str,
        edge_type: str,
        *,
        edge_id: Optional[str] = None,
        target_node: Optional[str] = None,
        target_doc: Optional[str] = None,
        confidence: float = 0.5,
        explanation: Optional[str] = None,
    ) -> str:
        """Add an edge. Returns the edge id."""
        if not edge_id:
            raw = f"{source_node}:{edge_type}:{target_node}:{target_doc}"
            edge_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        now = datetime.now().isoformat()
        db = self._db()
        db.execute(
            """INSERT OR REPLACE INTO edges
               (id, source_node, target_node, target_doc, edge_type, confidence, explanation, created)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (edge_id, source_node, target_node, target_doc, edge_type, confidence, explanation, now),
        )
        db.commit()
        return edge_id

    def get_edges_from(self, node_id: str) -> List[Dict]:
        rows = self._db().execute(
            "SELECT * FROM edges WHERE source_node = ?", (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_edges_to(self, node_id: str) -> List[Dict]:
        rows = self._db().execute(
            "SELECT * FROM edges WHERE target_node = ?", (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_edges_by_type(self, edge_type: str) -> List[Dict]:
        rows = self._db().execute(
            "SELECT * FROM edges WHERE edge_type = ?", (edge_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_contradictions(self) -> List[Dict]:
        """Get all contradiction edges."""
        return self.get_edges_by_type("contradicts")

    def get_missing(self) -> List[Dict]:
        """Get all missing_from edges (gaps)."""
        return self.get_edges_by_type("missing_from")

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------

    def add_alias(self, semantic_id: str, alias: str):
        db = self._db()
        db.execute(
            "INSERT OR IGNORE INTO aliases (semantic_id, alias) VALUES (?, ?)",
            (semantic_id, alias.lower()),
        )
        db.commit()

    def resolve_alias(self, alias: str) -> Optional[str]:
        """Resolve an alias to its canonical semantic_id."""
        row = self._db().execute(
            "SELECT semantic_id FROM aliases WHERE alias = ?",
            (alias.lower(),),
        ).fetchone()
        return row["semantic_id"] if row else None

    def get_aliases(self, semantic_id: str) -> List[str]:
        rows = self._db().execute(
            "SELECT alias FROM aliases WHERE semantic_id = ?",
            (semantic_id,),
        ).fetchall()
        return [r["alias"] for r in rows]

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def register_document(
        self,
        doc_id: str,
        version: str,
        path: Optional[str] = None,
        node_count: int = 0,
        edge_count: int = 0,
    ):
        now = datetime.now().isoformat()
        db = self._db()
        db.execute(
            """INSERT OR REPLACE INTO documents
               (doc_id, version, path, indexed_at, node_count, edge_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (doc_id, version, path, now, node_count, edge_count),
        )
        db.commit()

    def get_document(self, doc_id: str) -> Optional[Dict]:
        row = self._db().execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_documents(self) -> List[Dict]:
        rows = self._db().execute(
            "SELECT * FROM documents ORDER BY indexed_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_document(self, doc_id: str):
        """Remove all nodes, edges, and the document entry for a doc_id."""
        db = self._db()

        # Get node ids for this doc to clean up edges and ChromaDB
        node_ids = [
            r["id"] for r in
            db.execute("SELECT id FROM nodes WHERE source_doc = ?", (doc_id,)).fetchall()
        ]

        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            db.execute(f"DELETE FROM edges WHERE source_node IN ({placeholders})", node_ids)
            db.execute(f"DELETE FROM edges WHERE target_node IN ({placeholders})", node_ids)
            db.execute(f"DELETE FROM nodes WHERE source_doc = ?", (doc_id,))

            # Remove from ChromaDB
            coll = self._collection()
            if coll:
                try:
                    coll.delete(ids=node_ids)
                except Exception as e:
                    logger.warning("Failed to remove nodes from ChromaDB: %s", e)

        db.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        db.commit()

    # ------------------------------------------------------------------
    # Semantic search
    # ------------------------------------------------------------------

    def semantic_search(
        self,
        query: str,
        n: int = 10,
        doc_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> List[Dict]:
        """Search nodes by semantic similarity via ChromaDB."""
        coll = self._collection()
        if not coll:
            return []

        where = {}
        if doc_filter:
            where["source_doc"] = doc_filter
        if type_filter:
            where["type"] = type_filter

        try:
            results = coll.query(
                query_texts=[query],
                n_results=min(n, coll.count() or 1),
                where=where if where else None,
            )
        except Exception as e:
            logger.warning("ChromaDB search failed: %s", e)
            return []

        items = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i, node_id in enumerate(ids):
            similarity = 1 - distances[i] if distances else 0
            item = {
                "id": node_id,
                "content": docs[i] if docs else "",
                "similarity": round(similarity, 4),
            }
            if metadatas and i < len(metadatas):
                item.update(metadatas[i])
            # Fetch full node from SQLite
            full = self.get_node(node_id)
            if full:
                item["source_doc"] = full.get("source_doc")
                item["source_section"] = full.get("source_section")
                item["source_line"] = full.get("source_line")
                item["semantic_id"] = full.get("semantic_id")
            items.append(item)

        return items

    # ------------------------------------------------------------------
    # Stats & reindex
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        db = self._db()
        node_count = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        alias_count = db.execute("SELECT COUNT(*) FROM aliases").fetchone()[0]
        doc_count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

        type_counts = {}
        for row in db.execute("SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type").fetchall():
            type_counts[row["type"]] = row["cnt"]

        edge_type_counts = {}
        for row in db.execute("SELECT edge_type, COUNT(*) as cnt FROM edges GROUP BY edge_type").fetchall():
            edge_type_counts[row["edge_type"]] = row["cnt"]

        return {
            "nodes": node_count,
            "edges": edge_count,
            "aliases": alias_count,
            "documents": doc_count,
            "node_types": type_counts,
            "edge_types": edge_type_counts,
        }

    def reindex_all(self) -> Dict:
        """Rebuild ChromaDB index from SQLite source of truth."""
        coll = self._collection()
        if not coll:
            return {"error": "ChromaDB not available"}

        # Clear existing
        try:
            existing = coll.count()
            if existing > 0:
                all_ids = coll.get()["ids"]
                if all_ids:
                    coll.delete(ids=all_ids)
        except Exception:
            pass

        db = self._db()
        rows = db.execute("SELECT * FROM nodes WHERE content IS NOT NULL AND content != ''").fetchall()
        indexed = 0

        for row in rows:
            row = dict(row)
            metadata = {
                "semantic_id": row["semantic_id"],
                "type": row["type"],
                "granularity": row["granularity"],
                "confidence": row["confidence"],
            }
            if row.get("source_doc"):
                metadata["source_doc"] = row["source_doc"]
            if row.get("time"):
                metadata["time"] = row["time"]

            try:
                coll.upsert(
                    ids=[row["id"]],
                    documents=[row["content"]],
                    metadatas=[metadata],
                )
                indexed += 1
            except Exception as e:
                logger.warning("Failed to reindex node %s: %s", row["id"], e)

        return {"indexed": indexed, "total_nodes": len(rows)}


# ============================================================================
# Singleton
# ============================================================================

_instance: Optional[KnowledgeStore] = None


def get_store() -> KnowledgeStore:
    global _instance
    if _instance is None:
        _instance = KnowledgeStore()
    return _instance
