# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""Knowledge Graph tools: index, query, validate, diff.

4 tools for document indexing and cross-document consistency checking.
"""

from typing import Optional
from elara_mcp._app import tool


@tool()
def elara_kg_index(
    path: str,
    doc_id: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    """
    Index a document into the knowledge graph.

    Extracts entities (definitions, references, metrics, constraints,
    dependencies) and stores them with 6-tuple addressing for cross-document
    analysis.

    Args:
        path: Path to the document file (markdown or PDF)
        doc_id: Document identifier (inferred from filename if omitted)
        version: Document version (inferred from filename if omitted)

    Returns:
        Indexing summary with node/edge/alias counts
    """
    from daemon.knowledge import index_document

    try:
        result = index_document(path, doc_id, version)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except ImportError as e:
        return f"Error: {e}"

    lines = [
        f"Indexed: {result['doc_id']} ({result['version']})",
        f"  Nodes: {result['nodes']}",
        f"  Edges: {result['edges']}",
        f"  Aliases: {result['aliases']}",
    ]
    return "\n".join(lines)


@tool()
def elara_kg_query(
    query: Optional[str] = None,
    doc: Optional[str] = None,
    type: Optional[str] = None,
    semantic_id: Optional[str] = None,
) -> str:
    """
    Search the knowledge graph.

    Supports semantic search (by meaning), filtered lookups, or
    direct semantic_id resolution.

    Args:
        query: Natural language search query (uses ChromaDB semantic search)
        doc: Filter results to a specific document
        type: Filter by node type: definition, reference, metric, constraint, dependency
        semantic_id: Direct lookup by canonical concept identifier

    Returns:
        Matching nodes with source locations and similarity scores
    """
    from daemon.knowledge import query_graph

    result = query_graph(query=query, doc=doc, node_type=type, semantic_id=semantic_id)

    if result["query_type"] == "stats":
        stats = result.get("stats", {})
        docs = result.get("documents", [])
        lines = [f"Knowledge graph stats:"]
        lines.append(f"  Nodes: {stats.get('nodes', 0)}")
        lines.append(f"  Edges: {stats.get('edges', 0)}")
        lines.append(f"  Aliases: {stats.get('aliases', 0)}")
        lines.append(f"  Documents: {stats.get('documents', 0)}")
        if stats.get("node_types"):
            lines.append(f"  Types: {stats['node_types']}")
        if docs:
            lines.append("\nIndexed documents:")
            for d in docs:
                lines.append(f"  {d['doc_id']} ({d['version']}) — {d['node_count']} nodes, {d['edge_count']} edges")
        return "\n".join(lines)

    nodes = result.get("results", [])
    if not nodes:
        return "No results found."

    lines = [f"Found {result['count']} result(s) ({result['query_type']}):"]
    for n in nodes[:20]:
        sim = n.get("similarity")
        sim_str = f" [{sim:.3f}]" if sim is not None else ""
        ntype = n.get("type", "?")
        doc_id = n.get("source_doc", "?")
        section = n.get("source_section", "")
        line = n.get("source_line", "")
        content = n.get("content", "")[:100]
        sid = n.get("semantic_id", "")

        lines.append(f"  {ntype}{sim_str} [{doc_id}:{line}] {sid}")
        if section:
            lines.append(f"    Section: {section}")
        if content:
            lines.append(f"    {content}")

    return "\n".join(lines)


@tool()
def elara_kg_validate(
    docs: Optional[str] = None,
) -> str:
    """
    Cross-document consistency check.

    Finds contradictions, gaps (referenced but undefined concepts),
    stale version references, and metric conflicts across all indexed
    documents.

    Args:
        docs: Comma-separated doc_ids to validate (default: all)

    Returns:
        Validation report with issues grouped by type
    """
    from daemon.knowledge import validate_documents

    doc_ids = [d.strip() for d in docs.split(",")] if docs else None
    result = validate_documents(doc_ids)
    summary = result["summary"]

    lines = [f"Validation: {summary['status']} ({summary['total_issues']} issue(s))"]

    if summary["contradictions"] > 0:
        lines.append(f"\nContradictions ({summary['contradictions']}):")
        for c in result["contradictions"][:10]:
            lines.append(f"  [{c['semantic_id']}] {c['doc_a']} vs {c['doc_b']}")
            lines.append(f"    A: {c['content_a'][:80]}")
            lines.append(f"    B: {c['content_b'][:80]}")
            lines.append(f"    Similarity: {c['similarity']}")

    if summary["gaps"] > 0:
        lines.append(f"\nGaps ({summary['gaps']}):")
        for g in result["gaps"][:10]:
            lines.append(f"  [{g['semantic_id']}] referenced in {', '.join(g['referenced_in'])} but never defined")
            ref = g["first_reference"]
            lines.append(f"    First ref: {ref['doc']}:{ref.get('line', '?')} — {ref.get('content', '')[:80]}")

    if summary["stale_references"] > 0:
        lines.append(f"\nStale references ({summary['stale_references']}):")
        for s in result["stale_refs"][:10]:
            lines.append(f"  {s['referenced_version']} (latest: {s['latest_version']}) in {s['found_in']}:{s.get('line', '?')}")

    if summary["metric_conflicts"] > 0:
        lines.append(f"\nMetric conflicts ({summary['metric_conflicts']}):")
        for m in result["metric_conflicts"][:10]:
            lines.append(f"  [{m['semantic_id']}] {m['doc_a']}={m['value_a']} vs {m['doc_b']}={m['value_b']}")

    return "\n".join(lines)


@tool()
def elara_kg_diff(
    doc_id: str,
    v1: str,
    v2: str,
) -> str:
    """
    Compare two versions of a document in the knowledge graph.

    Shows concepts added, removed, and modified between versions.
    Both versions must be indexed first (can use same or different doc_ids).

    Args:
        doc_id: Document identifier
        v1: Earlier version (e.g., "v0.2.7")
        v2: Later version (e.g., "v0.2.8")

    Returns:
        Diff summary showing added, removed, and modified concepts
    """
    from daemon.knowledge import diff_versions

    result = diff_versions(doc_id, v1, v2)

    lines = [
        f"Diff: {result['doc_id']} {result['v1']} → {result['v2']}",
        f"  Nodes: {result['v1_node_count']} → {result['v2_node_count']}",
        f"  Added: {result['added_count']} | Removed: {result['removed_count']} | Modified: {result['modified_count']}",
    ]

    if result["added"]:
        lines.append(f"\nAdded ({result['added_count']}):")
        for sid in result["added"][:15]:
            lines.append(f"  + {sid}")

    if result["removed"]:
        lines.append(f"\nRemoved ({result['removed_count']}):")
        for sid in result["removed"][:15]:
            lines.append(f"  - {sid}")

    if result["modified"]:
        lines.append(f"\nModified ({result['modified_count']}):")
        for m in result["modified"][:10]:
            lines.append(f"  ~ {m['semantic_id']}")
            lines.append(f"    {v1}: {m['content_v1'][:60]}")
            lines.append(f"    {v2}: {m['content_v2'][:60]}")

    if not result["added"] and not result["removed"] and not result["modified"]:
        lines.append("\nNo differences found between versions.")

    return "\n".join(lines)
