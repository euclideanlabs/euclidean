"""Python symbol extraction: functions, classes, and methods with line ranges.

A symbol id is 'path::Qualified.name', for example
'src/click/core.py::Option.get_default'. Lines outside every def or class
belong to 'path::<module>'.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

MODULE = "<module>"


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

    visit(tree, "")
    return found


def enclosing_symbol(symbols: list[Symbol], line: int) -> str:
    """Innermost symbol that contains the line, else '<module>'."""
    best: Symbol | None = None
    for sym in symbols:
        if sym.start <= line <= sym.end and (best is None or sym.start >= best.start):
            best = sym
    return best.qualname if best else MODULE


def symbol_ids(path: str, source: str) -> set[str]:
    return {f"{path}::{s.qualname}" for s in extract_symbols(source)} | {f"{path}::{MODULE}"}
