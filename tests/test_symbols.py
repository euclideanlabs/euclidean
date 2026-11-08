from euclidean.dataset.symbols import enclosing_symbol, extract_symbols

SOURCE = '''\
import os

class Option:
    """Doc."""

    @property
    def name(self):
        return 1

    def get_default(self, ctx):
        def inner():
            return 2
        return inner()

def top():
    pass
'''


def test_enclosing_symbol_picks_innermost():
    syms = extract_symbols(SOURCE)
    assert enclosing_symbol(syms, 1) == "<module>"
    assert enclosing_symbol(syms, 4) == "Option"
    assert enclosing_symbol(syms, 6) == "Option.name"  # decorator line
    assert enclosing_symbol(syms, 12) == "Option.get_default.inner"
    assert enclosing_symbol(syms, 13) == "Option.get_default"
    assert enclosing_symbol(syms, 16) == "top"
