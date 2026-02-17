# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""
Knowledge Graph — Business logic orchestration.

Functions map 1:1 with MCP tools:
  - index_document()     → elara_kg_index
  - query_graph()        → elara_kg_query
  - validate_documents() → elara_kg_validate
  - diff_versions()      → elara_kg_diff
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from daemon.events import bus, Events
from memory.knowledge.store import get_store
from memory.knowledge.extract import extract_from_markdown
from memory.knowledge.validate import validate_corpus

logger = logging.getLogger("elara.knowledge")


# ============================================================================
# Helpers
# ============================================================================

def _infer_doc_id(path: str) -> str:
    """Infer a doc_id from a file path."""
    name = Path(path).stem
    # Strip version suffix: ELARA-PROTOCOL-WHITEPAPER.v0.2.8 → elara_protocol_whitepaper
    name = re.sub(r"\.v\d+\.\d+\.\d+$", "", name)
    # Normalize
    doc_id = name.lower().replace("-", "_").replace(" ", "_")
    return doc_id


def _infer_version(path: str) -> str:
    """Infer a version from a file path or content."""
    name = Path(path).stem
    m = re.search(r"v(\d+\.\d+\.\d+)", name)
    if m:
        return m.group(0)
    return "v0.0.0"


def _read_document(path: str) -> str:
    """Read a document file. Supports markdown and plain text."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    if p.suffix == ".pdf":
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(p) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            return "\n\n".join(text_parts)
        except ImportError:
            raise ImportError("pdfplumber required for PDF support: pip install pdfplumber")

    return p.read_text(encoding="utf-8")


# ============================================================================
# Core operations
# ============================================================================

def index_document(
    path: str,
    doc_id: Optional[str] = None,
    version: Optional[str] = None,
) -> Dict:
    """
    Read a file, extract entities, store in knowledge graph.

    Args:
        path: File path to index
        doc_id: Document identifier (inferred from filename if not given)
        version: Document version (inferred from filename if not given)

    Returns:
        {doc_id, version, nodes, edges, aliases}
    """
    if not doc_id:
        doc_id = _infer_doc_id(path)
    if not version:
        version = _infer_version(path)

    logger.info("Indexing document: %s (doc_id=%s, version=%s)", path, doc_id, version)

    text = _read_document(path)
    store = get_store()

    # Clear previous version of this doc_id
    existing = store.get_document(doc_id)
    if existing:
        logger.info("Clearing previous index for %s", doc_id)
        store.clear_document(doc_id)

    # Extract entities
    nodes, edges, aliases = extract_from_markdown(text, doc_id, version)

    # Store in batches (much faster than per-item)
    store.add_nodes_batch(nodes)
    store.add_edges_batch(edges)
    store.add_aliases_batch(aliases)

    # Register document
    store.register_document(
        doc_id=doc_id,
        version=version,
        path=os.path.abspath(path),
        node_count=len(nodes),
        edge_count=len(edges),
    )

    result = {
        "doc_id": doc_id,
        "version": version,
        "nodes": len(nodes),
        "edges": len(edges),
        "aliases": len(aliases),
    }

    logger.info("Indexed %s: %d nodes, %d edges, %d aliases", doc_id, len(nodes), len(edges), len(aliases))
    return result


def query_graph(
    query: Optional[str] = None,
    doc: Optional[str] = None,
    node_type: Optional[str] = None,
    semantic_id: Optional[str] = None,
) -> Dict:
    """
    Search the knowledge graph.

    Supports semantic search (ChromaDB) and/or filtered SQLite queries.

    Returns:
        {results, count}
    """
    store = get_store()

    # If semantic_id given, direct lookup
    if semantic_id:
        # Check aliases too
        resolved = store.resolve_alias(semantic_id) or semantic_id
        nodes = store.get_nodes_by_semantic_id(resolved)
        if not nodes:
            # Try the original if alias resolution didn't help
            nodes = store.get_nodes_by_semantic_id(semantic_id)
        return {
            "results": nodes,
            "count": len(nodes),
            "query_type": "semantic_id_lookup",
        }

    # If only doc filter, get all nodes for that doc
    if doc and not query:
        nodes = store.get_nodes_by_doc(doc)
        if node_type:
            nodes = [n for n in nodes if n["type"] == node_type]
        return {
            "results": nodes,
            "count": len(nodes),
            "query_type": "doc_filter",
        }

    # Semantic search via ChromaDB
    if query:
        results = store.semantic_search(
            query,
            n=20,
            doc_filter=doc,
            type_filter=node_type,
        )
        return {
            "results": results,
            "count": len(results),
            "query_type": "semantic_search",
        }

    # No filters — return stats
    stats = store.stats()
    docs = store.list_documents()
    return {
        "results": [],
        "count": 0,
        "query_type": "stats",
        "stats": stats,
        "documents": docs,
    }


def validate_documents(doc_ids: Optional[List[str]] = None) -> Dict:
    """
    Run cross-document consistency validation.

    Returns full validation results.
    """
    store = get_store()
    return validate_corpus(store, doc_ids)


def diff_versions(doc_id: str, v1: str, v2: str) -> Dict:
    """
    Compare nodes for a document across two versions.

    Requires both versions to be indexed (possibly with different doc_ids
    like protocol_wp_v027 and protocol_wp_v028). If same doc_id is used,
    only the latest version exists — so we compare by version field in nodes.
    """
    store = get_store()
    db = store._db()

    # Get nodes for each version
    nodes_v1 = db.execute(
        "SELECT * FROM nodes WHERE source_doc = ? AND time = ? ORDER BY source_line",
        (doc_id, v1),
    ).fetchall()
    nodes_v2 = db.execute(
        "SELECT * FROM nodes WHERE source_doc = ? AND time = ? ORDER BY source_line",
        (doc_id, v2),
    ).fetchall()

    # If we didn't find nodes by version in same doc_id, try doc_id variants
    if not nodes_v1:
        # Try doc_id with version suffix
        variant = f"{doc_id}_{v1.replace('.', '_')}"
        nodes_v1 = db.execute(
            "SELECT * FROM nodes WHERE source_doc = ? ORDER BY source_line",
            (variant,),
        ).fetchall()
    if not nodes_v2:
        variant = f"{doc_id}_{v2.replace('.', '_')}"
        nodes_v2 = db.execute(
            "SELECT * FROM nodes WHERE source_doc = ? ORDER BY source_line",
            (variant,),
        ).fetchall()

    v1_nodes = [dict(r) for r in nodes_v1]
    v2_nodes = [dict(r) for r in nodes_v2]

    # Compare by semantic_id
    v1_ids = {n["semantic_id"] for n in v1_nodes}
    v2_ids = {n["semantic_id"] for n in v2_nodes}

    added = v2_ids - v1_ids
    removed = v1_ids - v2_ids
    common = v1_ids & v2_ids

    # Find modified concepts (same semantic_id, different content)
    modified = []
    for sid in common:
        n1 = [n for n in v1_nodes if n["semantic_id"] == sid]
        n2 = [n for n in v2_nodes if n["semantic_id"] == sid]
        if n1 and n2:
            c1 = n1[0].get("content", "")
            c2 = n2[0].get("content", "")
            if c1 != c2:
                modified.append({
                    "semantic_id": sid,
                    "content_v1": c1[:120],
                    "content_v2": c2[:120],
                })

    return {
        "doc_id": doc_id,
        "v1": v1,
        "v2": v2,
        "v1_node_count": len(v1_nodes),
        "v2_node_count": len(v2_nodes),
        "added": sorted(added),
        "removed": sorted(removed),
        "modified": modified,
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
    }
