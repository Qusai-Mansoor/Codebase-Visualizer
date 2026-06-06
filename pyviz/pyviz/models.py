"""Shared data model — the single source of truth for every phase."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Enums — subclass str so .value is already a plain string (JSON-safe)
# ---------------------------------------------------------------------------

class NodeKind(str, Enum):
    PACKAGE      = 'package'
    MODULE       = 'module'
    CLASS        = 'class'
    FUNCTION     = 'function'
    METHOD       = 'method'
    CLASSMETHOD  = 'classmethod'
    STATICMETHOD = 'staticmethod'
    PROPERTY     = 'property'
    DECORATOR    = 'decorator'
    LAMBDA       = 'lambda'
    UNKNOWN      = 'unknown'


class EdgeKind(str, Enum):
    IMPORTS   = 'imports'    # A imports B
    CALLS     = 'calls'      # A calls B
    INHERITS  = 'inherits'   # class A inherits from class B
    DECORATES = 'decorates'  # decorator D is applied to A
    CONTAINS  = 'contains'   # package/module A contains B


class Confidence(str, Enum):
    STATIC     = 'static'
    RUNTIME    = 'runtime'
    BOTH       = 'both'
    DYNAMIC    = 'dynamic'    # best-effort, may be wrong
    UNRESOLVED = 'unresolved' # gave up


# ---------------------------------------------------------------------------
# Core graph dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    id: str                        # fully-qualified: 'mypkg.core.MyClass.method'
    kind: NodeKind
    name: str                      # short name: 'method'
    file: Optional[str]            # relative to project root
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
    all_exports: list[str] = field(default_factory=list) # module __all__ contents
    warnings: list[str] = field(default_factory=list)    # per-node UI hints


@dataclass
class GraphEdge:
    src: str                       # source node id
    dst: str                       # destination node id
    kind: EdgeKind
    confidence: Confidence = Confidence.STATIC
    file: Optional[str] = None     # file where this relationship is expressed
    line: Optional[int] = None
    is_type_only: bool = False     # True if inside TYPE_CHECKING block


@dataclass
class AnalysisWarning:
    kind: str                      # 'unresolved_import' | 'dynamic_call' | 'syntax_error'
    message: str
    file: Optional[str]
    line: Optional[int]


@dataclass
class ProjectGraph:
    nodes: dict[str, GraphNode] = field(default_factory=dict)      # id -> node
    edges: list[GraphEdge] = field(default_factory=list)
    warnings: list[AnalysisWarning] = field(default_factory=list)
    root: str = ''
    python_version: str = ''
    generated_at: str = ''


# ---------------------------------------------------------------------------
# Phase 2 — Discovery
# ---------------------------------------------------------------------------

@dataclass
class DiscoveryResult:
    root: Path
    module_map: dict[str, Path]    # dotted_name -> absolute path to .py file
    package_map: dict[str, Path]   # dotted_name -> absolute path to package dir
    skipped: dict[Path, str]       # path -> reason string
    stub_map: dict[str, Path] = field(default_factory=dict)  # dotted_name -> .pyi path


# ---------------------------------------------------------------------------
# Phase 3 — Parsing
# ---------------------------------------------------------------------------

@dataclass
class ParsedModule:
    module_name: str
    file: Path
    source: str          # raw source text (needed by jedi in Phase 4)
    tree: ast.Module     # the AST root
    encoding: str        # 'utf-8', 'latin-1', etc.


@dataclass
class ParseResult:
    parsed: dict[str, ParsedModule]  # dotted_name -> ParsedModule
    failed: dict[str, str]           # dotted_name -> error message


# ---------------------------------------------------------------------------
# Phase 4 — Import Resolution
# ---------------------------------------------------------------------------

@dataclass
class ResolvedBinding:
    name: str            # the original imported name
    real_module: str     # dotted module name where it's actually defined
    real_file: Path
    real_line: int
    real_fqn: str        # fully-qualified name: 'mypkg.core.MyClass'
    is_type_only: bool = False   # came from inside TYPE_CHECKING block
    is_wildcard: bool = False    # came from 'from x import *'


@dataclass
class UnresolvedBinding:
    name: str
    reason: str          # 'external' | 'dynamic' | 'cycle' | 'not_found'
    import_source: str   # importer module (for the warning message)


# Union type used as the value type in ResolverResult.bindings
Binding = Union[ResolvedBinding, UnresolvedBinding]


@dataclass
class ResolverResult:
    # (importer_module_dotted, local_name) -> Binding
    bindings: dict[tuple[str, str], Binding] = field(default_factory=dict)
    warnings: list[AnalysisWarning] = field(default_factory=list)
