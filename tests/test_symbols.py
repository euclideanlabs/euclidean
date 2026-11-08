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


def test_module_noise_lines():
    from euclidean.dataset.symbols import module_noise_lines

    src = "import os\nfrom typing import (\n    Any,\n)\n\n# note\nX = 1\n"
    assert module_noise_lines(src) == {1, 2, 3, 4, 5, 6}  # line 7 is real code


def test_symbols_inside_if_blocks_and_module_constants():
    from euclidean.dataset.symbols import enclosing_symbol, extract_symbols

    # Shapes from real Click fixes: click-9a2d169 (types.py), click-b7e5fd4 (shell_completion.py)
    src = (
        "if t.TYPE_CHECKING:\n"      # 1
        "    class Info(Base):\n"    # 2
        "        x: int\n"           # 3
        "else:\n"                    # 4
        "    class Info(Base):\n"    # 5
        "        x: t.Any\n"         # 6
        '_SOURCE = """\n'            # 7
        "echo $metadata[2];\n"       # 8
        '"""\n'                      # 9
        "def f():\n"                 # 10
        "    y = 1\n"                # 11
    )
    syms = extract_symbols(src)
    assert enclosing_symbol(syms, 3) == "Info"
    assert enclosing_symbol(syms, 6) == "Info"
    assert enclosing_symbol(syms, 8) == "_SOURCE"
    assert enclosing_symbol(syms, 11) == "f"  # local variables are not symbols
    assert enclosing_symbol(syms, 4) == "<module>"
