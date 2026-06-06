# Python Codebase Visualizer

A tool that analyzes Python projects and generates interactive call/dependency graphs.

## Features
- Resolves `__init__.py` re-exports (real definitions, not placeholders)
- Detects circular imports
- Identifies dead code and unused symbols
- Traces async/sync call surfaces
- Supports runtime call tracing (optional)
- Produces JSON graphs for web visualization

## Project Status
🚧 **In Development** — Core analyzer implementation phase

## Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+ (for the web frontend, later)

### Installation
```bash
cd pyviz
pip install -e .
pip install -e ".[dev]"
```

### Run Tests
```bash
pytest tests/
```

### Use the CLI (once implemented)
```bash
pyviz analyze ./my-python-project --output graph.json
```

## Architecture

The tool is split into phases (see `docs/` for full specs and `claude.md` for tracking):

1. **Models** — Shared dataclasses (the contract every phase reads/writes)
2. **Discovery** — Find all Python files and compute dotted module names
3. **Parsing** — Convert source to AST, gracefully handling failures
4. **Import Resolution** — Follow `__init__.py` re-export chains to real definitions
5. **Definition Extraction** — Emit nodes for classes, functions, methods, etc.
6. **Call Edge Extraction** — Find who calls whom
7. **Decorator Analysis** — Emit DECORATES edges, tag framework roles
8. **Graph Assembly** — Build networkx graph; detect cycles, dead code, clusters
9. **Serialization** — Output JSON for the web frontend
10. **Runtime Tracing** (optional) — Confirm calls with `sys.settrace`

See `claude.md` for implementation tracking.

## Documentation

- `docs/` — Detailed specs for each phase
- `Core_Implementation_Guide.docx` — Complete reference (located in the repo root)
