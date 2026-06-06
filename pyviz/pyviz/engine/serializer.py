"""Phase 9 — JSON serialization.

Converts the fully-assembled ProjectGraph + GraphAssemblyResult into the
JSON string consumed by the frontend.  This file IS the analyzer↔frontend
contract — keep field names in lockstep with the TypeScript types.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any

from pyviz.models import ProjectGraph


def serialize(
    pg: ProjectGraph,
    nx_graph: Any,               # networkx.DiGraph — not imported; kept for API symmetry
    communities: dict[str, int],
    unused: list[str],
    cycles: list[list[str]],
    root: Any,                   # str | Path
) -> str:
    """Return a JSON string matching the GraphOutput TypeScript type."""
    nodes_out = [
        {
            'id': nid,
            'kind': n.kind.value,
            'name': n.name,
            'file': n.file,
            'line': n.line,
            'end_line': n.end_line,
            'docstring': n.docstring,
            'is_async': n.is_async,
            'is_abstract': n.is_abstract,
            'is_protocol': n.is_protocol,
            'is_dataclass': n.is_dataclass,
            'is_mixin': n.is_mixin,
            'bases': n.bases,
            'decorators': n.decorators,
            'warnings': n.warnings,
            'community': communities.get(nid),  # int | None
            'role': n.role,                     # str | None
        }
        for nid, n in pg.nodes.items()
    ]

    edges_out = [
        {
            'src': e.src,
            'dst': e.dst,
            'kind': e.kind.value,
            'confidence': e.confidence.value,
            'file': e.file,
            'line': e.line,
            'is_type_only': e.is_type_only,
        }
        for e in pg.edges
        if e.src in pg.nodes and e.dst in pg.nodes  # filter dangling edges
    ]

    output = {
        'nodes': nodes_out,
        'edges': edges_out,
        'meta': {
            'root': str(root),
            'python_version': sys.version,
            'generated_at': datetime.datetime.now(datetime.UTC).isoformat(),
            'circular_imports': cycles,
            'unused_symbols': unused,
            'warnings': [
                {
                    'kind': w.kind,
                    'message': w.message,
                    'file': w.file,
                    'line': w.line,
                }
                for w in pg.warnings
            ],
        },
    }
    return json.dumps(output, indent=2)
