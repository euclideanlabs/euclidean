"""Python symbol extraction: functions, classes, and methods with line ranges.

A symbol id is 'path::Qualified.name', for example
'src/click/core.py::Option.get_default'. Symbols are defs, classes, and
module-level assignments (constants such as '_SOURCE_FISH'). Defs inside
'if'/'try'/'with' blocks count too (for example 'if t.TYPE_CHECKING:').
Other lines belong to 'path::<module>'.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

MODULE = "<module>"
_BLOCKS = (ast.If, ast.Try, ast.ExceptHandler, ast.With, ast.AsyncWith)


@dataclass(frozen=True)
class Symbol:
    qualname: str
    start: int  # first line, 1-based, includes decorators
    end: int    # last line, inclusive


def extract_symbols(source: str) -> list[Symbol]:
    tree = ast.parse(source)
    found: list[Symbol] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                found.append(Symbol(name, start, child.end_lineno or child.lineno))
                visit(child, name + ".")
            elif prefix == "" and isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        found.append(Symbol(target.id, child.lineno, child.end_lineno or child.lineno))
            elif isinstance(child, _BLOCKS):
                visit(child, prefix)  # same scope: an 'if' does not add a name

    visit(tree, "")
    return found


def enclosing_symbol(symbols: list[Symbol], line: int) -> str:
    """Innermost symbol that contains the line, else '<module>'."""
    best: Symbol | None = None
    for sym in symbols:
        if sym.start <= line <= sym.end and (best is None or sym.start >= best.start):
            best = sym
    return best.qualname if best else MODULE


def module_noise_lines(source: str) -> set[int]:
    """Lines that are never the place of a fix: imports, blank lines, comments.

    The miner ignores these lines when they fall outside every symbol, so
    they do not become '<module>' labels.
    """
    lines = {i for i, text in enumerate(source.splitlines(), 1)
             if not text.strip() or text.lstrip().startswith("#")}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def symbol_ids(path: str, source: str) -> set[str]:
    return {f"{path}::{s.qualname}" for s in extract_symbols(source)} | {f"{path}::{MODULE}"}
