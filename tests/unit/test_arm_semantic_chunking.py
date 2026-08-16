"""
ARM semantic chunking — restored from the original DeepSeek Analyzer.

The original's `SemanticChunker` closed a chunk when brace depth returned to zero.
Python has no braces, so every Python function chunk ended on its own `def` line.
These tests pin the corrected behaviour, and in particular pin the property the
original could not offer: **no content is lost or reordered**, whatever the input.

Why it matters: `deepseek_code_analyzer.run_analysis` sends only `chunks[0]` to the
model, so on any file above the budget the first chunk *is* the analysis.
"""
import pytest

from apps.arm.services.deepseek.file_processor_deepseek import FileProcessor

pytestmark = pytest.mark.app_profile


def _proc(tokens: int = 50) -> FileProcessor:
    # 50 tokens ≈ 200 chars — small enough to force splitting on tiny fixtures.
    return FileProcessor({"max_chunk_tokens": tokens})


def _py_source(n_funcs: int, body_lines: int = 6) -> str:
    parts = ["import os", ""]
    for i in range(n_funcs):
        parts.append(f"def function_{i}(a, b):")
        parts.extend([f"    x{j} = a + b + {j}" for j in range(body_lines)])
        parts.append(f"    return x0 + {i}")
        parts.append("")
    return "\n".join(parts)


def test_small_file_is_one_chunk():
    assert _proc().chunk_file("print('hi')", "t.py") == ["print('hi')"]


def test_empty_content_returns_single_empty_chunk():
    assert _proc().chunk_file("", "t.py") == [""]


def test_python_never_splits_mid_function():
    src = _py_source(6)
    chunks = _proc().chunk_file(src, "mod.py")
    assert len(chunks) > 1, "fixture must be large enough to split"

    for chunk in chunks:
        lines = chunk.split("\n")
        for idx, line in enumerate(lines):
            if line.startswith("def "):
                # The body must travel with its own def, not start the next chunk.
                assert idx + 1 < len(lines), f"def is the last line of a chunk:\n{chunk}"
                assert lines[idx + 1].startswith("    "), (
                    f"def not followed by its body — the original bug:\n{chunk}"
                )


def test_python_chunks_start_at_a_definition_or_module_head():
    src = _py_source(6)
    chunks = _proc().chunk_file(src, "mod.py")
    for chunk in chunks[1:]:
        first = next((ln for ln in chunk.split("\n") if ln.strip()), "")
        assert first.startswith(("def ", "class ", "@")), f"chunk starts mid-unit: {first!r}"


@pytest.mark.parametrize(
    "source,filename",
    [
        (_py_source(6), "mod.py"),
        ("\n".join(f"function f{i}() {{\n  const a = {i};\n  return a;\n}}" for i in range(8)), "mod.js"),
        ("\n".join(f"line {i} of some plain text file" for i in range(60)), "notes.txt"),
        ("def broken(:\n  this is not python\n" + "x = 1\n" * 60, "bad.py"),
    ],
    ids=["python", "javascript", "unknown-ext", "syntax-error"],
)
def test_no_content_is_lost_or_reordered(source, filename):
    """The load-bearing property: chunks rejoin to exactly the original lines."""
    chunks = _proc().chunk_file(source, filename)
    assert chunks, "must always return at least one chunk"
    rejoined = "\n".join(chunks).split("\n")
    assert rejoined == source.split("\n")


def test_syntax_error_falls_back_without_raising():
    # A file ARM is asked to analyse is exactly the file likely not to parse.
    src = "def broken(:\n  nonsense\n" + "filler = 1\n" * 80
    chunks = _proc().chunk_file(src, "bad.py")
    assert len(chunks) > 1
    assert "\n".join(chunks).split("\n") == src.split("\n")


def test_oversized_single_definition_is_line_split():
    # One function larger than the whole budget must still be emitted, split.
    body = "\n".join(f"    value_{i} = {i}" for i in range(200))
    src = f"def enormous():\n{body}\n"
    proc = _proc()
    chunks = proc.chunk_file(src, "big.py")
    assert len(chunks) > 1
    assert all(len(c) <= proc.chars_per_chunk for c in chunks)
    assert "\n".join(chunks).split("\n") == src.split("\n")


def test_decorated_function_keeps_its_decorator():
    src = (
        "import os\n\n"
        + "".join(
            f"@decorator_{i}\ndef fn_{i}():\n" + "".join(f"    v{j} = {j}\n" for j in range(8)) + "\n"
            for i in range(5)
        )
    )
    chunks = _proc().chunk_file(src, "dec.py")
    for chunk in chunks:
        lines = [ln for ln in chunk.split("\n") if ln.strip()]
        for idx, line in enumerate(lines):
            if line.startswith("def fn_") and idx > 0:
                continue
        # A decorator must never be the final meaningful line of a chunk.
        if lines:
            assert not lines[-1].startswith("@"), f"decorator orphaned from its def:\n{chunk}"


def test_chunk_content_still_line_splits():
    """The line-based path is unchanged and still available."""
    proc = _proc()
    src = "\n".join(f"line {i}" for i in range(200))
    chunks = proc.chunk_content(src)
    assert len(chunks) > 1
    assert "\n".join(chunks) == src
