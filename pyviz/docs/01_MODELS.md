# Phase 1: The Shared Data Model (models.py)

## What it does
Defines the Python dataclasses and enums that every phase uses to communicate. This is the single
source of truth for the graph structure. Defining it first — before any analysis code — forces the
contract between phases to be explicit. Implement this file before anything else.

## Input
None — this is the foundation.

## Output
A `pyviz/models.py` module containing:
- `NodeKind` enum (PACKAGE, MODULE, CLASS, FUNCTION, METHOD, CLASSMETHOD, STATICMETHOD, PROPERTY, DECORATOR, LAMBDA, UNKNOWN)
- `EdgeKind` enum (IMPORTS, CALLS, INHERITS, DECORATES, CONTAINS)
- `Confidence` enum (STATIC, RUNTIME, BOTH, DYNAMIC, UNRESOLVED)
- `GraphNode` dataclass
- `GraphEdge` dataclass
- `AnalysisWarning` dataclass
- `ProjectGraph` dataclass

These additional dataclasses are defined in their owning phase's section of the guide but should
live in `models.py` so every phase can import them:
- `DiscoveryResult` (Phase 2 / guide §3)
- `ParsedModule`, `ParseResult` (Phase 3 / guide §4)
- `ResolvedBinding`, `UnresolvedBinding`, `ResolverResult` (Phase 4 / guide §5)
- `RuntimeEdge` (Phase 10 / guide §11) — may live in `tracer.py` instead

## Exact schema (from guide §2)
All enums subclass `str, Enum` so JSON serialization emits plain strings.

```python
# pyviz/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

class NodeKind(str, Enum):
    PACKAGE     = 'package'
    MODULE      = 'module'
    CLASS       = 'class'
    FUNCTION    = 'function'
    METHOD      = 'method'
    CLASSMETHOD = 'classmethod'
    STATICMETHOD= 'staticmethod'
    PROPERTY    = 'property'
    DECORATOR   = 'decorator'
    LAMBDA      = 'lambda'
    UNKNOWN     = 'unknown'

class EdgeKind(str, Enum):
    IMPORTS   = 'imports'     # A imports B
    CALLS     = 'calls'       # A calls B
    INHERITS  = 'inherits'    # class A inherits from class B
    DECORATES = 'decorates'   # decorator D is applied to A
    CONTAINS  = 'contains'    # package/module A contains B

class Confidence(str, Enum):
    STATIC     = 'static'
    RUNTIME    = 'runtime'
    BOTH       = 'both'
    DYNAMIC    = 'dynamic'      # best-effort, may be wrong
    UNRESOLVED = 'unresolved'   # gave up

@dataclass
class GraphNode:
    id: str                      # fully-qualified: 'mypkg.core.MyClass.method'
    kind: NodeKind
    name: str                    # short name: 'method'
    file: Optional[str]          # relative to project root
    line: Optional[int]
    end_line: Optional[int]
    docstring: Optional[str]
    is_async: bool = False
    is_abstract: bool = False
    is_protocol: bool = False
    is_dataclass: bool = False
    is_mixin: bool = False
    bases: list[str] = field(default_factory=list)       # FQNs of parent classes
    decorators: list[str] = field(default_factory=list)  # decorator names (raw text)
    all_exports: list[str] = field(default_factory=list) # if module: its __all__
    warnings: list[str] = field(default_factory=list)    # analysis warnings for UI

@dataclass
class GraphEdge:
    src: str                     # source node id
    dst: str                     # destination node id
    kind: EdgeKind
    confidence: Confidence = Confidence.STATIC
    file: Optional[str] = None   # file where this relationship is expressed
    line: Optional[int] = None
    is_type_only: bool = False   # True if inside TYPE_CHECKING block

@dataclass
class AnalysisWarning:
    kind: str                    # 'unresolved_import', 'dynamic_call', 'syntax_error'
    message: str
    file: Optional[str]
    line: Optional[int]

@dataclass
class ProjectGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)   # id -> node
    edges: list[GraphEdge] = field(default_factory=list)
    warnings: list[AnalysisWarning] = field(default_factory=list)
    root: str = ''
    python_version: str = ''
    generated_at: str = ''
```

## Key algorithms
None — pure data structure definitions. Every field name and type must match exactly.

## Edge cases
1. **EdgeKind.DECORATES** — edges point *from* the decorator definition *to* the decorated target.
2. **Confidence levels** — must be an enum (subclassing `str`) so JSON serialization yields strings.
3. **Optional fields** — external-package nodes may have no `file`/`line`; keep them `Optional`.
4. **Warnings list** — both nodes (`GraphNode.warnings`) and the graph (`ProjectGraph.warnings`)
   carry warnings; node warnings are UI hints, graph warnings are `AnalysisWarning` records.
5. **Fields the guide references later** — the JSON schema (§10) also surfaces `community` and `role`
   per node. These are computed in Phase 8/7 and may be attached at serialization time rather than
   stored on `GraphNode`. If you add them to the dataclass, default them to `None`.

## Library APIs
None — only Python's `dataclasses` and `enum` modules.

## Common mistakes
1. Using a mutable default (`= []`) on a list field instead of `field(default_factory=list)`.
2. Emitting Enum objects (not `.value` strings) into JSON — the frontend should never see Python enums.
3. Missing or wrong type hints on dataclass fields (breaks the contract other phases rely on).

## Test fixtures
None — this is pure data definition. `tests/test_models.py` verifies instantiation and JSON-ability.

## Implementation notes
Implement every class exactly as in guide §2. Review every field name and type before proceeding —
this file is the contract that all other phases depend on. After implementing, write
`tests/test_models.py` to verify: all enums serialize to JSON strings; all dataclasses instantiate
with and without optional fields; `field(default_factory=list)` produces independent lists per instance.
