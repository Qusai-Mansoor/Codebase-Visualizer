# Phase 3: Parsing (engine/parser.py)

> Guide §4 ("Phase 2 — Parsing").

## What it does
Converts every `.py` file in the module map into an AST. It must handle real-world files gracefully:
encoding issues, syntax errors, empty files. Failures must be logged and skipped, never crash. The
output feeds every subsequent phase.

## Input
`DiscoveryResult`.

## Output
`ParseResult`:
```python
import ast

@dataclass
class ParsedModule:
    module_name: str
    file: Path
    source: str         # raw source text (needed by jedi in Phase 4)
    tree: ast.Module    # the AST root
    encoding: str       # 'utf-8', 'latin-1', etc.

@dataclass
class ParseResult:
    parsed: dict[str, ParsedModule]   # dotted_name -> ParsedModule
    failed: dict[str, str]            # dotted_name -> error message
```

## Key algorithm (guide §4.4)
```python
def parse_all(discovery: DiscoveryResult) -> ParseResult:
    parsed, failed = {}, {}
    for module_name, py_file in discovery.module_map.items():
        try:
            source = read_source(py_file)
            tree = ast.parse(source, filename=str(py_file), type_comments=True)
            ast.fix_missing_locations(tree)
            parsed[module_name] = ParsedModule(module_name, py_file, source, tree, 'utf-8')
        except SyntaxError as e:
            failed[module_name] = f'SyntaxError at line {e.lineno}: {e.msg}'
        except Exception as e:
            failed[module_name] = f'Unexpected error: {e}'
    return ParseResult(parsed=parsed, failed=failed)

def read_source(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return path.read_text(encoding='latin-1')  # latin-1 decodes any byte sequence
```

## Edge cases (guide §4.5)
1. **`ast.fix_missing_locations`** — always call after parse; required so programmatically-generated
   nodes (e.g. in decorator analysis) inherit line numbers from parents.
2. **Python version mismatch** — target uses 3.10+ syntax (`match`/`case`) under a 3.9 analyzer →
   `SyntaxError`. Record a helpful `'Possible Python version mismatch'` message and move on.
3. **Empty files** — valid Python, valid AST with empty body. Do not skip; they still get a module node.
4. **Type comments** — pre-3.6 `# type: int` hints. `type_comments=True` exposes them as
   `type_comment` attributes for the type-flow stretch feature.
5. **Encoding fallback** — try UTF-8, then latin-1 (never raises). Record the encoding used.

## Library APIs
| API | Purpose |
|-----|---------|
| `ast.parse(source, filename, type_comments=True)` | Parse → `ast.Module`; surfaces type comments. |
| `ast.fix_missing_locations(tree)` | Fill missing `lineno`/`col_offset`. |
| `ast.get_docstring(node)` | Extract module/class/function docstring (used in Phase 5). |
| `tokenize.detect_encoding(readline)` | Read `# -*- coding: ... -*-` declarations if needed. |

## Common mistakes
1. Letting a single bad file crash the whole run — every parse must be in `try/except`.
2. Skipping empty files (they still need a module node downstream).
3. Forgetting `fix_missing_locations`, causing `None` line numbers later.

## Test fixtures
All fixtures exercise the parser implicitly. A fixture with a deliberately broken file (and one empty
file) validates graceful failure and the empty-file path.

## Implementation notes
Parse once, cache `ParsedModule` keyed by `(path, mtime)` (perf, guide §12.11). Never re-parse the
same file. For large repos, parsing can be parallelized with `ProcessPoolExecutor`.
