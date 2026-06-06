"""Phase 10 (stretch) — Runtime tracing via sys.settrace.

Records cross-file function calls that fire during the test suite, then
merges them into the assembled ProjectGraph:
  - Matching static CALLS edges → Confidence.BOTH
  - Runtime-only calls → new GraphEdge with Confidence.RUNTIME

Entirely optional; the static pipeline works without it.
"""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from pyviz.models import Confidence, DiscoveryResult, EdgeKind, GraphEdge, ProjectGraph


# ---------------------------------------------------------------------------
# Runtime observation dataclass
# ---------------------------------------------------------------------------

@dataclass
class RuntimeEdge:
    caller_file: str
    caller_qualname: str
    callee_file: str
    callee_qualname: str
    count: int = 1


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class RuntimeTracer:
    def __init__(self, project_root) -> None:
        self.root = Path(project_root)
        self.edges: dict[tuple, RuntimeEdge] = {}
        self._local = threading.local()
        # Cache a stable bound-method so sys.settrace and identity checks work consistently
        self._trace = self._trace

    def _is_project_file(self, filename: str) -> bool:
        try:
            Path(filename).relative_to(self.root)
            return True
        except ValueError:
            return False

    def _trace(self, frame, event, arg):
        if event != 'call':
            return self._trace
        callee_file = frame.f_code.co_filename
        if not self._is_project_file(callee_file):
            return None                          # stop tracing into stdlib / third-party
        caller = frame.f_back
        if caller is None:
            return self._trace
        if not self._is_project_file(caller.f_code.co_filename):
            return self._trace
        if caller.f_code.co_filename == callee_file:
            return self._trace                   # only cross-file calls are interesting
        key = (
            caller.f_code.co_filename,
            caller.f_code.co_qualname,
            callee_file,
            frame.f_code.co_qualname,
        )
        if key in self.edges:
            self.edges[key].count += 1
        else:
            self.edges[key] = RuntimeEdge(*key)
        return self._trace

    def start(self) -> None:
        sys.settrace(self._trace)
        threading.settrace(self._trace)

    def stop(self) -> None:
        sys.settrace(None)
        threading.settrace(None)

    def merge_into_graph(
        self,
        pg: ProjectGraph,
        discovery: DiscoveryResult,
    ) -> None:
        """Merge observed runtime calls into *pg*, upgrading or adding edges."""
        # Invert module_map: abs_path_str → dotted module name
        file_to_mod: dict[str, str] = {
            str(path): mod_name
            for mod_name, path in discovery.module_map.items()
        }
        # Index existing static CALLS edges for O(1) upgrade lookup
        static_calls: dict[tuple[str, str], GraphEdge] = {
            (e.src, e.dst): e
            for e in pg.edges
            if e.kind == EdgeKind.CALLS
        }
        for re in self.edges.values():
            src_mod = file_to_mod.get(re.caller_file)
            dst_mod = file_to_mod.get(re.callee_file)
            if src_mod is None or dst_mod is None:
                continue                         # file not in the analysed project
            src_fqn = f'{src_mod}.{re.caller_qualname}'
            dst_fqn = f'{dst_mod}.{re.callee_qualname}'
            key = (src_fqn, dst_fqn)
            if key in static_calls:
                static_calls[key].confidence = Confidence.BOTH
            else:
                pg.edges.append(GraphEdge(
                    src=src_fqn,
                    dst=dst_fqn,
                    kind=EdgeKind.CALLS,
                    confidence=Confidence.RUNTIME,
                ))


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def trace_test_suite(
    project_root,
    discovery: DiscoveryResult,
    project_graph: ProjectGraph,
) -> RuntimeTracer:
    """Run the project's test suite under tracing and merge results into *project_graph*."""
    tracer = RuntimeTracer(project_root)
    tracer.start()
    try:
        import pytest
        pytest.main(
            [str(Path(project_root) / 'tests'), '--no-header', '-q'],
            plugins=[],
        )
    except SystemExit:
        pass  # pytest calls sys.exit; stop() / merge must still run
    finally:
        tracer.stop()
    tracer.merge_into_graph(project_graph, discovery)
    return tracer
