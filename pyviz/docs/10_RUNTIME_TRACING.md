# Phase 10: Runtime Tracing (engine/tracer.py) — Stretch

> Guide §11 ("Phase 9 (Stretch) — Runtime Tracing").

## What it does
Static analysis sees only what the source says; runtime tracing sees what actually runs. By
instrumenting the test suite it finds: (a) calls static analysis missed (dynamic dispatch), (b) calls
static analysis predicted that never fire (dead branches), and (c) hot paths. This is **optional** and
merges into the graph at the end.

## Input
The project root + `DiscoveryResult` + the assembled `ProjectGraph`.

## Output
Mutates `ProjectGraph.edges`: matching static CALLS edges → `Confidence.BOTH`; runtime-only edges
added with `Confidence.RUNTIME`.

## How `sys.settrace` works (guide §11.2)
`sys.settrace(fn)` installs a global trace function called as `fn(frame, event, arg)`. `event` is one
of `'call'`, `'return'`, `'line'`, `'exception'`. The `frame` exposes `f_code` (with `co_filename`,
`co_qualname`) and `f_back` (the calling frame).

## Key implementation (guide §11.3)
```python
@dataclass
class RuntimeEdge:
    caller_file: str; caller_qualname: str
    callee_file: str; callee_qualname: str
    count: int = 1

class RuntimeTracer:
    def __init__(self, project_root):
        self.root = project_root
        self.edges: dict[tuple, RuntimeEdge] = {}
        self._local = threading.local()

    def _is_project_file(self, filename):
        try: Path(filename).relative_to(self.root); return True
        except ValueError: return False

    def _trace(self, frame, event, arg):
        if event != 'call': return self._trace
        callee_file = frame.f_code.co_filename
        if not self._is_project_file(callee_file): return None   # don't enter stdlib/3rd-party
        caller = frame.f_back
        if caller is None: return self._trace
        if not self._is_project_file(caller.f_code.co_filename): return self._trace
        if caller.f_code.co_filename == callee_file: return self._trace  # cross-file only
        key = (caller.f_code.co_filename, caller.f_code.co_qualname,
               callee_file, frame.f_code.co_qualname)
        if key in self.edges: self.edges[key].count += 1
        else: self.edges[key] = RuntimeEdge(*key)
        return self._trace

    def start(self): sys.settrace(self._trace); threading.settrace(self._trace)
    def stop(self):  sys.settrace(None);        threading.settrace(None)
```
`merge_into_graph` (guide §11.3) builds `file -> module_name` from `discovery.module_map`, forms
`src_fqn = f'{src_mod}.{caller_qualname}'` / `dst_fqn` similarly, and: if a static CALLS edge exists,
upgrade it to `Confidence.BOTH`; otherwise append a new `Confidence.RUNTIME` edge.

## Running under tracing (guide §11.4)
```python
def trace_test_suite(project_root, discovery, project_graph):
    tracer = RuntimeTracer(project_root); tracer.start()
    try:
        import pytest
        pytest.main([str(project_root/'tests'), '--no-header', '-q'], plugins=[])
    except SystemExit:
        pass            # pytest calls sys.exit
    finally:
        tracer.stop()
    tracer.merge_into_graph(project_graph, discovery)
```

## Edge cases
1. **Stdlib/third-party frames** — return `None` to stop tracing into them (perf + relevance).
2. **Same-file calls** — skipped; only cross-file project calls are recorded.
3. **Threads** — also install `threading.settrace`; keep per-thread state in `threading.local`.
4. **pytest `SystemExit`** — pytest calls `sys.exit`; catch it so tracing teardown still runs.
5. **Unmappable files** — if a file isn't in `module_map`, skip the edge during merge.

## Library APIs
| API | Purpose |
|-----|---------|
| `sys.settrace` / `threading.settrace` | Install the trace callback (main + threads). |
| `frame.f_code.co_filename` / `co_qualname` / `frame.f_back` | Identify caller/callee. |
| `pytest.main([...])` | Drive the test suite under tracing. |

## Common mistakes
1. Tracing into stdlib/third-party (huge slowdown, irrelevant edges) — return `None` early.
2. Not catching pytest's `SystemExit`, so `stop()`/merge never run.
3. Forgetting `threading.settrace`, missing calls in threaded tests.

## Test fixtures
- `fixtures/async_surface/` and any fixture with dynamic dispatch — confirm runtime edges appear and
  matching static edges upgrade to `Confidence.BOTH`.

## Implementation notes
Entirely optional and independent of phases 5–9; it only *merges* at the end. Keep it isolated so the
static pipeline works without it.
