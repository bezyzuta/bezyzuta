"""Guards the HARD INVARIANT: gui.generate()'s signature must align 1:1 (same
count AND same order) with the inputs=[...] list on generate_btn.click. A
silent position shift would route the wrong value into the wrong feature.

Pure ast/regex — no Gradio import. Run: `pytest tests/test_gui_alignment.py -v`
"""

import ast
import re
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / "gui.py"


def _generate_params(src):
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "generate")
    return [a.arg for a in fn.args.args]


def _click_inputs(src):
    # The main render button (not hook_generate_btn).
    m = re.search(r'(?<!hook_)generate_btn\.click\(', src)
    assert m, "generate_btn.click( not found in gui.py"
    i2 = src.index('inputs=[', m.start())
    depth = 0
    j = i2 + len('inputs=[') - 1
    start = j
    while True:
        c = src[j]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                break
        j += 1
    inner = re.sub(r'#.*', '', src[start + 1:j])
    return [t.strip() for t in inner.split(',') if t.strip()]


def test_generate_inputs_match_signature():
    src = GUI.read_text(encoding="utf-8")
    params = _generate_params(src)
    names = _click_inputs(src)
    assert len(params) == len(names), (
        f"generate() has {len(params)} params but inputs=[] has {len(names)}")
    # Same names in the same order — catches a position shift, not just a count.
    assert params == names, (
        "param<->input order mismatch; first diff at "
        + str(next(((i, p, n) for i, (p, n) in enumerate(zip(params, names))
                    if p != n), None)))
