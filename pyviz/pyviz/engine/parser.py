"""Phase 3 — AST parsing.

Reads every .py file in a DiscoveryResult and returns a ParseResult with:
  - parsed:  dotted_name -> ParsedModule  (successfully parsed modules)
  - failed:  dotted_name -> error message (files that could not be parsed)

Encoding strategy: try UTF-8 first; fall back to latin-1 (decodes any byte
sequence — never raises UnicodeDecodeError).
"""
from __future__ import annotations

import ast
from pathlib import Path

from pyviz.models import DiscoveryResult, ParseResult, ParsedModule


def parse_all(discovery: DiscoveryResult) -> ParseResult:
    """Parse every module in *discovery* and return a ParseResult."""
    parsed: dict[str, ParsedModule] = {}
    failed: dict[str, str] = {}

    for module_name, py_file in discovery.module_map.items():
        try:
            source, encoding = _read_source(py_file)
        except OSError as e:
            failed[module_name] = f'IOError reading file: {e}'
            continue

        try:
            tree = ast.parse(source, filename=str(py_file), type_comments=True)
        except SyntaxError as e:
            msg = f'SyntaxError at line {e.lineno}: {e.msg}'
            if _looks_like_version_mismatch(e):
                msg += ' (Possible Python version mismatch)'
            failed[module_name] = msg
            continue
        except Exception as e:
            failed[module_name] = f'Unexpected error: {e}'
            continue

        ast.fix_missing_locations(tree)
        parsed[module_name] = ParsedModule(
            module_name=module_name,
            file=py_file,
            source=source,
            tree=tree,
            encoding=encoding,
        )

    return ParseResult(parsed=parsed, failed=failed)


def _read_source(path: Path) -> tuple[str, str]:
    """Return (source_text, encoding_name). Tries UTF-8 then latin-1."""
    try:
        return path.read_text(encoding='utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return path.read_text(encoding='latin-1'), 'latin-1'


def _looks_like_version_mismatch(exc: SyntaxError) -> bool:
    """Heuristic: match/case and other 3.10+ keywords fail on older parsers."""
    msg = (exc.msg or '').lower()
    text = (exc.text or '').strip()
    return (
        'invalid syntax' in msg
        and any(kw in text for kw in ('match ', 'case ', 'type '))
    )
