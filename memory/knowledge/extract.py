# Copyright (c) 2026 Nenad Vasic. All rights reserved.
# Licensed under the Business Source License 1.1 (BSL-1.1)
# See LICENSE file in the project root for full license text.

"""
Knowledge Graph Extraction Pipeline — Rule-based markdown entity extraction.

Pure rule-based, no LLM calls. Extracts entities and relationships from
markdown documents using pattern matching.

Extractors:
  - Definitions: heading text, bold terms, "X is Y" patterns, table headers
  - References: section refs, layer mentions, version refs, named concepts
  - Metrics: numbers with units, performance claims
  - Constraints: "must"/"shall" patterns, enumeration claims
  - Dependencies: "X depends on Y", "built on Y"
"""

import hashlib
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("elara.knowledge.extract")


# ============================================================================
# Section parsing
# ============================================================================

def _parse_sections(text: str) -> List[Dict]:
    """Parse markdown headings into a section tree with line ranges."""
    sections = []
    lines = text.split("\n")
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)(?:\s*\{.*\})?\s*$")

    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            sections.append({
                "level": level,
                "title": title,
                "line": i + 1,  # 1-indexed
                "end_line": None,  # filled in below
            })

    # Fill end_line for each section
    for i, sec in enumerate(sections):
        if i + 1 < len(sections):
            sec["end_line"] = sections[i + 1]["line"] - 1
        else:
            sec["end_line"] = len(lines)

    return sections


def _find_section_for_line(sections: List[Dict], line_num: int) -> Optional[str]:
    """Find the most specific section title for a given line number."""
    best = None
    for sec in sections:
        if sec["line"] <= line_num <= (sec["end_line"] or float("inf")):
            if best is None or sec["level"] > best["level"]:
                best = sec
    return best["title"] if best else None


# ============================================================================
# Semantic ID generation
# ============================================================================

def _generate_semantic_id(text: str) -> str:
    """Normalize text to a canonical semantic_id: lowercase, underscores, stripped."""
    sid = text.lower().strip()
    # Remove special chars, keep alphanumeric and spaces
    sid = re.sub(r"[^\w\s.-]", "", sid)
    # Collapse whitespace to underscores
    sid = re.sub(r"\s+", "_", sid)
    # Remove leading/trailing underscores
    sid = sid.strip("_")
    return sid


def _generate_aliases(text: str, semantic_id: str) -> List[str]:
    """Generate variant forms of a term for matching."""
    aliases = set()
    aliases.add(semantic_id)
    aliases.add(text.lower().strip())

    # Hyphenated ↔ spaced
    if "-" in text:
        aliases.add(text.replace("-", " ").lower().strip())
        aliases.add(text.replace("-", "_").lower().strip())
    if " " in text:
        aliases.add(text.replace(" ", "-").lower().strip())
        aliases.add(text.replace(" ", "_").lower().strip())

    # Strip common prefixes
    for prefix in ("the ", "a ", "an "):
        lower = text.lower()
        if lower.startswith(prefix):
            stripped = lower[len(prefix):].strip()
            aliases.add(stripped)
            aliases.add(_generate_semantic_id(stripped))

    # Layer pattern: "Layer 1.5: Performance Runtime" → layer_1_5, layer_1.5
    layer_m = re.match(r"layer\s+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if layer_m:
        num = layer_m.group(1)
        aliases.add(f"layer_{num.replace('.', '_')}")
        aliases.add(f"layer_{num}")
        aliases.add(f"layer {num}")

    # Strip subtitle after colon/dash: "Layer 1.5: Performance Runtime" → "Layer 1.5"
    for sep in (":", " — ", " - ", " – "):
        if sep in text:
            prefix_part = text.split(sep)[0].strip()
            if len(prefix_part) >= 3:
                aliases.add(prefix_part.lower())
                aliases.add(_generate_semantic_id(prefix_part))

    return [a for a in aliases if a and a != semantic_id]


def _node_id(semantic_id: str, doc_id: str, source_section: str, line: int) -> str:
    """Generate a deterministic node id."""
    raw = f"{semantic_id}:{doc_id}:{source_section}:{line}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ============================================================================
# Sub-extractors
# ============================================================================

def _extract_definitions(
    text: str, doc_id: str, version: str, sections: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Extract definition nodes from headings, bold terms, and 'X is Y' patterns."""
    nodes = []
    edges = []
    aliases_list = []
    lines = text.split("\n")

    # 1. Headings as definitions
    for sec in sections:
        title = sec["title"]
        # Skip generic headings
        if title.lower() in ("introduction", "overview", "summary", "conclusion",
                              "table of contents", "references", "appendix"):
            continue

        semantic_id = _generate_semantic_id(title)
        if not semantic_id or len(semantic_id) < 2:
            continue

        nid = _node_id(semantic_id, doc_id, title, sec["line"])
        nodes.append({
            "id": nid,
            "semantic_id": semantic_id,
            "time": version,
            "source_doc": doc_id,
            "source_section": title,
            "source_line": sec["line"],
            "type": "definition",
            "granularity": "section",
            "confidence": 0.8,
            "content": title,
        })

        for alias in _generate_aliases(title, semantic_id):
            aliases_list.append((semantic_id, alias))

    # 2. Bold terms as definitions: **Term** or __Term__
    bold_re = re.compile(r"\*\*([^*]{2,60})\*\*|__([^_]{2,60})__")
    is_definition_re = re.compile(
        r"(?:\*\*[^*]+\*\*|__[^_]+__)\s*(?:is|are|refers?\s+to|means?|represents?)\s",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines):
        line_num = i + 1
        if is_definition_re.search(line):
            for m in bold_re.finditer(line):
                term = m.group(1) or m.group(2)
                term = term.strip()
                semantic_id = _generate_semantic_id(term)
                if not semantic_id or len(semantic_id) < 2:
                    continue

                section = _find_section_for_line(sections, line_num)
                nid = _node_id(semantic_id, doc_id, section or "", line_num)
                nodes.append({
                    "id": nid,
                    "semantic_id": semantic_id,
                    "time": version,
                    "source_doc": doc_id,
                    "source_section": section,
                    "source_line": line_num,
                    "type": "definition",
                    "granularity": "line",
                    "confidence": 0.7,
                    "content": line.strip(),
                })

                for alias in _generate_aliases(term, semantic_id):
                    aliases_list.append((semantic_id, alias))

    # 3. Table headers as definitions (markdown tables)
    table_header_re = re.compile(r"^\|(.+)\|$")
    separator_re = re.compile(r"^\|[\s:|-]+\|$")

    for i, line in enumerate(lines):
        line_num = i + 1
        if table_header_re.match(line) and i + 1 < len(lines) and separator_re.match(lines[i + 1]):
            cells = [c.strip() for c in line.strip("|").split("|")]
            section = _find_section_for_line(sections, line_num)
            for cell in cells:
                cell = re.sub(r"\*\*([^*]+)\*\*", r"\1", cell).strip()
                if cell and len(cell) > 1 and not cell.startswith("-"):
                    semantic_id = _generate_semantic_id(cell)
                    if semantic_id and len(semantic_id) >= 2:
                        nid = _node_id(semantic_id, doc_id, section or "", line_num)
                        nodes.append({
                            "id": nid,
                            "semantic_id": semantic_id,
                            "time": version,
                            "source_doc": doc_id,
                            "source_section": section,
                            "source_line": line_num,
                            "type": "definition",
                            "granularity": "line",
                            "confidence": 0.5,
                            "content": f"Table column: {cell}",
                        })

    return nodes, edges, aliases_list


def _extract_references(
    text: str, doc_id: str, version: str, sections: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Extract reference nodes: section refs, layer mentions, version refs."""
    nodes = []
    edges = []
    aliases_list = []
    lines = text.split("\n")

    # Layer references (Layer 0, Layer 1, Layer 1.5, Layer 2, etc.)
    layer_re = re.compile(r"Layer\s+(\d+(?:\.\d+)?)", re.IGNORECASE)

    # Version references (v0.2.8, v1.3.2, etc.)
    version_re = re.compile(r"v(\d+\.\d+\.\d+)")

    # Named concept references (capitalized multi-word terms)
    concept_re = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")

    # Specific protocol/component references
    component_re = re.compile(
        r"\b(DAM\s*VM|Rust\s+DAM|elara[-_]runtime|elara[-_]core|"
        r"MCP\s+(?:server|tool|protocol)|"
        r"ChromaDB|SQLite|PyO3|"
        r"Protocol\s+WP|Hardware\s+WP|Core\s+WP)\b",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines):
        line_num = i + 1
        section = _find_section_for_line(sections, line_num)

        # Layer references
        for m in layer_re.finditer(line):
            layer_num = m.group(1)
            semantic_id = f"layer_{layer_num.replace('.', '_')}"
            nid = _node_id(semantic_id, doc_id, section or "", line_num)
            nodes.append({
                "id": nid,
                "semantic_id": semantic_id,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "reference",
                "granularity": "token",
                "confidence": 0.9,
                "content": f"Layer {layer_num}: {line.strip()[:120]}",
            })
            aliases_list.append((semantic_id, f"layer {layer_num}"))

        # Component references
        for m in component_re.finditer(line):
            term = m.group(1).strip()
            semantic_id = _generate_semantic_id(term)
            if not semantic_id:
                continue
            nid = _node_id(semantic_id, doc_id, section or "", line_num)
            nodes.append({
                "id": nid,
                "semantic_id": semantic_id,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "reference",
                "granularity": "token",
                "confidence": 0.8,
                "content": f"{term}: {line.strip()[:120]}",
            })
            for alias in _generate_aliases(term, semantic_id):
                aliases_list.append((semantic_id, alias))

        # Version references
        for m in version_re.finditer(line):
            ver = m.group(0)
            semantic_id = _generate_semantic_id(ver)
            nid = _node_id(semantic_id, doc_id, section or "", line_num)
            nodes.append({
                "id": nid,
                "semantic_id": semantic_id,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "reference",
                "granularity": "token",
                "confidence": 0.7,
                "content": f"Version ref {ver}: {line.strip()[:120]}",
            })

    return nodes, edges, aliases_list


def _extract_metrics(
    text: str, doc_id: str, version: str, sections: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Extract metric nodes: numbers with units, performance claims."""
    nodes = []
    edges = []
    aliases_list = []
    lines = text.split("\n")

    # Number + unit patterns
    metric_re = re.compile(
        r"(\d+(?:\.\d+)?)\s*"
        r"(ms|seconds?|minutes?|hours?|days?|"
        r"bytes?|[KMGT]B|"
        r"tokens?|lines?|files?|modules?|tools?|"
        r"collections?|sessions?|"
        r"%|percent|"
        r"x\b|times?\b)",
        re.IGNORECASE,
    )

    # Performance claims
    perf_re = re.compile(
        r"(?:latency|throughput|speed|performance|response\s+time|"
        r"context\s+(?:saved|reduction|usage)|boot\s+time)\s*"
        r"(?:is|of|:)?\s*~?(\d+(?:\.\d+)?)\s*(%|ms|s|x)",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines):
        line_num = i + 1
        # Skip code blocks
        if line.strip().startswith("```"):
            continue

        section = _find_section_for_line(sections, line_num)

        for m in perf_re.finditer(line):
            value = m.group(1)
            unit = m.group(2)
            metric_name = line.strip()[:60]
            semantic_id = _generate_semantic_id(f"metric_{metric_name[:30]}")
            nid = _node_id(semantic_id, doc_id, section or "", line_num)
            nodes.append({
                "id": nid,
                "semantic_id": semantic_id,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "metric",
                "granularity": "line",
                "confidence": 0.8,
                "content": f"{value}{unit}: {line.strip()[:120]}",
            })

        # General metrics (lower confidence to avoid noise)
        if not perf_re.search(line):
            for m in metric_re.finditer(line):
                value = m.group(1)
                unit = m.group(2)
                # Skip years and version numbers
                if float(value) > 1900 and unit.lower() in ("", "x"):
                    continue
                section = _find_section_for_line(sections, line_num)
                semantic_id = _generate_semantic_id(f"metric_{section or 'unknown'}_{value}{unit}")
                nid = _node_id(semantic_id, doc_id, section or "", line_num)
                nodes.append({
                    "id": nid,
                    "semantic_id": semantic_id,
                    "time": version,
                    "source_doc": doc_id,
                    "source_section": section,
                    "source_line": line_num,
                    "type": "metric",
                    "granularity": "line",
                    "confidence": 0.5,
                    "content": f"{value} {unit}: {line.strip()[:120]}",
                })

    return nodes, edges, aliases_list


def _extract_constraints(
    text: str, doc_id: str, version: str, sections: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Extract constraints: must/shall patterns, enumeration claims."""
    nodes = []
    edges = []
    aliases_list = []
    lines = text.split("\n")

    # Must/shall/required patterns
    constraint_re = re.compile(
        r"\b(must|shall|required|requires|cannot|must\s+not|shall\s+not)\b",
        re.IGNORECASE,
    )

    # Enumeration claims ("Three-Layer", "4 modules", "N-something")
    enum_re = re.compile(
        r"\b((?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
        r"[-\s]+(?:layer|module|component|phase|stage|step|tier|level|part|tool|collection)s?)\b",
        re.IGNORECASE,
    )

    # Word-to-number mapping for enumeration validation
    word_to_num = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }

    for i, line in enumerate(lines):
        line_num = i + 1
        if line.strip().startswith("```"):
            continue

        section = _find_section_for_line(sections, line_num)

        # Constraint statements
        if constraint_re.search(line):
            semantic_id = _generate_semantic_id(f"constraint_{section or 'unknown'}_{line_num}")
            nid = _node_id(semantic_id, doc_id, section or "", line_num)
            nodes.append({
                "id": nid,
                "semantic_id": semantic_id,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "constraint",
                "granularity": "line",
                "confidence": 0.7,
                "content": line.strip()[:200],
            })

        # Enumeration claims
        for m in enum_re.finditer(line):
            claim = m.group(1).strip()
            # Parse the number
            parts = re.split(r"[-\s]+", claim, maxsplit=1)
            num_word = parts[0].lower()
            num_val = word_to_num.get(num_word)
            if num_val is None:
                try:
                    num_val = int(num_word)
                except ValueError:
                    continue

            thing = parts[1] if len(parts) > 1 else "items"
            semantic_id = _generate_semantic_id(f"enum_{num_val}_{thing}")
            nid = _node_id(semantic_id, doc_id, section or "", line_num)
            nodes.append({
                "id": nid,
                "semantic_id": semantic_id,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "constraint",
                "granularity": "line",
                "confidence": 0.8,
                "content": f"Enumeration: {claim} ({num_val} {thing}): {line.strip()[:120]}",
            })

    return nodes, edges, aliases_list


def _extract_dependencies(
    text: str, doc_id: str, version: str, sections: List[Dict],
) -> Tuple[List[Dict], List[Dict], List[str]]:
    """Extract dependency relationships."""
    nodes = []
    edges = []
    aliases_list = []
    lines = text.split("\n")

    dep_re = re.compile(
        r"(?:depends?\s+on|built\s+on|requires|uses|leverages|"
        r"powered\s+by|based\s+on|wraps|extends|integrates?\s+with)\s+"
        r"([A-Z][\w\s-]{2,30})",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines):
        line_num = i + 1
        if line.strip().startswith("```"):
            continue

        section = _find_section_for_line(sections, line_num)

        for m in dep_re.finditer(line):
            target = m.group(1).strip().rstrip(".,;:")
            if not target or len(target) < 2:
                continue

            target_sid = _generate_semantic_id(target)
            dep_sid = _generate_semantic_id(f"dep_{section or 'unknown'}_{target}")
            nid = _node_id(dep_sid, doc_id, section or "", line_num)

            nodes.append({
                "id": nid,
                "semantic_id": dep_sid,
                "time": version,
                "source_doc": doc_id,
                "source_section": section,
                "source_line": line_num,
                "type": "dependency",
                "granularity": "line",
                "confidence": 0.6,
                "content": f"Dependency on {target}: {line.strip()[:120]}",
            })

            # Create a depends_on edge (target node may not exist yet)
            edge_id = hashlib.sha256(f"dep:{nid}:{target_sid}".encode()).hexdigest()[:16]
            edges.append({
                "id": edge_id,
                "source_node": nid,
                "target_node": None,  # resolved later when target is found
                "target_doc": None,
                "edge_type": "depends_on",
                "confidence": 0.6,
                "explanation": f"{section or doc_id} depends on {target}",
            })

            for alias in _generate_aliases(target, target_sid):
                aliases_list.append((target_sid, alias))

    return nodes, edges, aliases_list


# ============================================================================
# Main extraction function
# ============================================================================

def extract_from_markdown(
    text: str,
    doc_id: str,
    version: str,
) -> Tuple[List[Dict], List[Dict], List[Tuple[str, str]]]:
    """
    Extract entities and relationships from a markdown document.

    Returns:
        (nodes, edges, aliases) — ready to be stored in KnowledgeStore
    """
    sections = _parse_sections(text)
    all_nodes = []
    all_edges = []
    all_aliases = []

    extractors = [
        _extract_definitions,
        _extract_references,
        _extract_metrics,
        _extract_constraints,
        _extract_dependencies,
    ]

    for extractor in extractors:
        try:
            nodes, edges, aliases = extractor(text, doc_id, version, sections)
            all_nodes.extend(nodes)
            all_edges.extend(edges)
            all_aliases.extend(aliases)
        except Exception as e:
            logger.warning("Extractor %s failed: %s", extractor.__name__, e)

    # Deduplicate nodes by id
    seen_ids = set()
    unique_nodes = []
    for node in all_nodes:
        if node["id"] not in seen_ids:
            seen_ids.add(node["id"])
            unique_nodes.append(node)

    # Deduplicate aliases
    unique_aliases = list(set(all_aliases))

    logger.info(
        "Extracted from %s: %d nodes, %d edges, %d aliases",
        doc_id, len(unique_nodes), len(all_edges), len(unique_aliases),
    )

    return unique_nodes, all_edges, unique_aliases
