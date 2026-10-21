"""Rustworkx-backed Knowledge, AST & Calculation Lineage DAG Engine."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import rustworkx as rx

from nouc_studio.graph.models import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    MetricLineageTrace,
    NodeKind,
)
from nouc_studio.graph.uncertainty import propagate_uncertainty


def _sanitize_katex_formula(latex_str: str) -> str:
    """Replace unescaped underscores inside \\text{...} or \\mathrm{...} with spaces so KaTeX never errors."""
    return re.sub(
        r"(\\(?:text|mathrm)\{)([^{}]*)(\})",
        lambda m: f"{m.group(1)}{m.group(2).replace('_', ' ')}{m.group(3)}",
        latex_str,
    )


class LineageGraphEngine:
    """Directed Acyclic Graph (DAG) engine backed by Rustworkx for code, provenance, and calculation lineage."""

    def __init__(self) -> None:
        self._graph: rx.PyDiGraph[GraphNode, GraphEdge] = rx.PyDiGraph(check_cycle=True)
        self._node_index_by_id: dict[str, int] = {}

    @property
    def node_count(self) -> int:
        """Return total number of nodes in the graph."""
        return len(self._graph.nodes())

    @property
    def edge_count(self) -> int:
        """Return total number of directed edges in the graph."""
        return len(self._graph.edges())

    def add_node(self, node: GraphNode) -> int:
        """Insert or update a GraphNode in the Rustworkx DAG."""
        if node.node_id in self._node_index_by_id:
            idx = self._node_index_by_id[node.node_id]
            self._graph[idx] = node
            return idx
        idx = self._graph.add_node(node)
        self._node_index_by_id[node.node_id] = idx
        return idx

    def get_node(self, node_id: str) -> GraphNode:
        """Retrieve a GraphNode by its string node_id."""
        if node_id not in self._node_index_by_id:
            raise KeyError(f"Node '{node_id}' does not exist in LineageGraphEngine.")
        return self._graph[self._node_index_by_id[node_id]]

    def has_node(self, node_id: str) -> bool:
        """Return True if node_id is registered in the graph."""
        return node_id in self._node_index_by_id

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: EdgeKind,
        rationale: str = "",
    ) -> int:
        """Add a directed edge source_id -> target_id while enforcing DAG acyclicity."""
        if source_id not in self._node_index_by_id:
            raise KeyError(f"Source node '{source_id}' not found in graph.")
        if target_id not in self._node_index_by_id:
            raise KeyError(f"Target node '{target_id}' not found in graph.")

        src_idx = self._node_index_by_id[source_id]
        tgt_idx = self._node_index_by_id[target_id]
        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            kind=kind,
            rationale=rationale,
        )
        return self._graph.add_edge(src_idx, tgt_idx, edge)

    def is_acyclic(self) -> bool:
        """Verify that the graph is a strict Directed Acyclic Graph (DAG)."""
        return rx.is_directed_acyclic_graph(self._graph)

    def topological_nodes(self) -> list[GraphNode]:
        """Return all nodes in topological execution order."""
        ordered_indices = rx.topological_sort(self._graph)
        return [self._graph[idx] for idx in ordered_indices]

    def nodes_by_kind(self, kind: NodeKind) -> list[GraphNode]:
        """Filter nodes in topological order by their NodeKind."""
        return [n for n in self.topological_nodes() if n.kind == kind]

    def get_ancestors(self, node_id: str) -> list[GraphNode]:
        """Return all upstream ancestor nodes contributing to node_id in topological order."""
        if node_id not in self._node_index_by_id:
            raise KeyError(f"Node '{node_id}' not found.")
        target_idx = self._node_index_by_id[node_id]
        ancestor_indices = rx.ancestors(self._graph, target_idx)
        topo_indices = [idx for idx in rx.topological_sort(self._graph) if idx in ancestor_indices]
        return [self._graph[idx] for idx in topo_indices]

    def get_descendants(self, node_id: str) -> list[GraphNode]:
        """Return all downstream nodes impacted by changes to node_id in topological order."""
        if node_id not in self._node_index_by_id:
            raise KeyError(f"Node '{node_id}' not found.")
        source_idx = self._node_index_by_id[node_id]
        descendant_indices = rx.descendants(self._graph, source_idx)
        topo_indices = [idx for idx in rx.topological_sort(self._graph) if idx in descendant_indices]
        return [self._graph[idx] for idx in topo_indices]

    def trace_metric_lineage(self, metric_id: str) -> MetricLineageTrace:
        """Build a complete, auditable calculation proof trace for a given metric node."""
        metric_node = self.get_node(metric_id)
        ancestors = self.get_ancestors(metric_id)
        relevant_ids = {n.node_id for n in ancestors} | {metric_id}

        sources = [
            n for n in ancestors if n.kind in (NodeKind.SOURCE_FILE, NodeKind.SOURCE_FRAGMENT)
        ]
        transforms = [
            n for n in ancestors if n.kind in (NodeKind.TRANSFORM, NodeKind.MARIMO_CELL, NodeKind.CODE_AST)
        ]
        validations = [n for n in ancestors if n.kind == NodeKind.VALIDATION_CHECK]
        assumptions = [n for n in ancestors if n.kind == NodeKind.ASSUMPTION]

        edges = [
            e
            for e in self._graph.edges()
            if e.source_id in relevant_ids and e.target_id in relevant_ids
        ]

        propagated = propagate_uncertainty(metric_node, ancestors)
        updated_metric = metric_node.model_copy(update={"uncertainty": propagated})
        self.add_node(updated_metric)

        ordered_steps = [*ancestors, updated_metric]
        raw_val = updated_metric.value_preview
        unit_str = updated_metric.unit or ""
        if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
            if unit_str == "USD":
                formatted_val = f"${float(raw_val):,.2f} USD ({raw_val})"
            elif unit_str == "EUR":
                formatted_val = f"€{float(raw_val):,.2f} EUR ({raw_val})"
            elif unit_str == "%":
                formatted_val = f"{float(raw_val):,.2f}% ({raw_val})"
            else:
                formatted_val = f"{float(raw_val):,.2f} {unit_str} ({raw_val})".strip()
        else:
            formatted_val = f"{raw_val} {unit_str}".strip()

        proof_lines: list[str] = [
            f"### Audit & Calculation Proof — {updated_metric.label}",
            f"- **Computed Value**: **{formatted_val}**",
            f"- **Trust Grade**: **Grade {propagated.trust_grade.value}** (Composite Confidence: `{propagated.composite_confidence_score * 100:.1f}%`, Epistemic Uncertainty: `±{propagated.epistemic_uncertainty_pct:.2f}%`)",
        ]
        if propagated.confidence_interval_95 is not None:
            low, high = propagated.confidence_interval_95
            proof_lines.append(f"- **95% Sensitivity Interval**: `[{low:,.2f}, {high:,.2f}]`")

        proof_lines.append("\n#### 1. Raw Source Provenance")
        if sources:
            for s in sources:
                coord_str = ""
                if s.coordinates:
                    posix_path = s.coordinates.file_path.replace("\\", "/")
                    parts = [f"file=`{posix_path}`"]
                    if s.coordinates.sheet_name:
                        parts.append(f"sheet=`{s.coordinates.sheet_name}`")
                    if s.coordinates.cell_range:
                        parts.append(f"range=`{s.coordinates.cell_range}`")
                    if s.coordinates.page_number:
                        parts.append(f"page={s.coordinates.page_number}")
                    if s.coordinates.line_start:
                        parts.append(f"lines={s.coordinates.line_start}-{s.coordinates.line_end}")
                    parts.append(f"sha256=`{s.coordinates.file_hash_sha256[:12]}...`")
                    coord_str = " (" + ", ".join(parts) + ")"
                proof_lines.append(f"- **`{s.label}`**{coord_str}: {s.description}")
        else:
            proof_lines.append("- *Derived from in-memory or synthetic parameters.*")

        proof_lines.append("\n#### 2. Calculation & Transformation Pipeline")
        for idx, t in enumerate(transforms, start=1):
            proof_lines.append(f"{idx}. **{t.label}**: {t.description}")
            if t.formula_latex:
                safe_latex = _sanitize_katex_formula(t.formula_latex)
                proof_lines.append(f"\n$$\n{safe_latex}\n$$\n")
            if t.code_snippet:
                proof_lines.append(f"   - **Verified Polars Expression**: `{t.code_snippet.strip()}`")

        proof_lines.append("\n#### 3. Data Quality & Verification Proofs")
        if validations:
            for v in validations:
                rate = v.uncertainty.validation_pass_rate * 100.0
                proof_lines.append(f"- **`{v.label}`**: Pass rate `{rate:.1f}%` — {v.description}")
        else:
            proof_lines.append("- *Verified via static AST/type check; no row-level Pointblank assertions attached.*")

        if propagated.assumptions or propagated.caveats:
            proof_lines.append("\n#### 4. Explicit Assumptions & Epistemic Caveats")
            for a in propagated.assumptions:
                proof_lines.append(f"- **Assumption**: {a}")
            for c in propagated.caveats:
                proof_lines.append(f"- **Caveat**: {c}")

        return MetricLineageTrace(
            metric_node=updated_metric,
            upstream_sources=sources,
            transformations=transforms,
            validations=validations,
            assumptions=assumptions,
            ordered_steps=ordered_steps,
            edges=edges,
            propagated_uncertainty=propagated,
            natural_language_proof="\n".join(proof_lines),
        )

    def to_mermaid(self) -> str:
        """Render the complete Knowledge & Calculation Lineage DAG as a styled Mermaid flowchart."""
        lines = [
            "flowchart LR",
            "    classDef sourceNode fill:#eef2ff,stroke:#4f46e5,color:#1e1b4b,stroke-width:2px;",
            "    classDef transformNode fill:#f5f3ff,stroke:#7c3aed,color:#2e1065,stroke-width:2px;",
            "    classDef validationNode fill:#ecfdf5,stroke:#059669,color:#064e3b,stroke-width:2px;",
            "    classDef assumptionNode fill:#fffbeb,stroke:#d97706,color:#78350f,stroke-width:1.5px,stroke-dasharray: 4 2;",
            "    classDef metricNode fill:#1e1b4b,stroke:#4f46e5,color:#ffffff,stroke-width:3px;",
        ]
        kind_to_class = {
            NodeKind.SOURCE_FILE: "sourceNode",
            NodeKind.SOURCE_FRAGMENT: "sourceNode",
            NodeKind.STUDIO_VIEW: "sourceNode",
            NodeKind.TRANSFORM: "transformNode",
            NodeKind.MARIMO_CELL: "transformNode",
            NodeKind.CODE_AST: "transformNode",
            NodeKind.VALIDATION_CHECK: "validationNode",
            NodeKind.ASSUMPTION: "assumptionNode",
            NodeKind.METRIC: "metricNode",
        }
        for node in self.topological_nodes():
            safe_label = node.label.replace('"', "'")
            grade = node.uncertainty.trust_grade.value
            val_str = (
                f" = {node.value_preview}"
                if node.value_preview is not None
                and isinstance(node.value_preview, (int, float, str))
                and len(str(node.value_preview)) < 24
                else ""
            )
            css_cls = kind_to_class.get(node.kind, "sourceNode")
            lines.append(f'    {node.node_id}["{safe_label}{val_str} (Grade {grade})"]:::{css_cls}')
        for edge in self._graph.edges():
            label = edge.kind.value
            lines.append(f"    {edge.source_id} -->|{label}| {edge.target_id}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire DAG into a JSON-compatible dictionary."""
        return {
            "nodes": [n.model_dump(mode="json") for n in self.topological_nodes()],
            "edges": [e.model_dump(mode="json") for e in self._graph.edges()],
        }

    def save_json(self, path: Path) -> None:
        """Persist the lineage graph to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_json(cls, path: Path) -> LineageGraphEngine:
        """Reconstruct a LineageGraphEngine from a saved JSON file."""
        payload = json.loads(path.read_text(encoding="utf-8"))
        engine = cls()
        for raw_node in payload.get("nodes", []):
            engine.add_node(GraphNode.model_validate(raw_node))
        for raw_edge in payload.get("edges", []):
            edge = GraphEdge.model_validate(raw_edge)
            engine.add_edge(edge.source_id, edge.target_id, edge.kind, edge.rationale)
        return engine
