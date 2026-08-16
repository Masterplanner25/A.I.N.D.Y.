"""
ARM File Processor

Handles file reading, chunking, and session metadata creation.
Splits large files into token-safe chunks to stay within OpenAI context limits.

Chunking is *semantic* where the language allows it (see ``chunk_file``): a chunk
boundary falls between top-level definitions rather than at an arbitrary line.
This matters more than it looks, because ``deepseek_code_analyzer`` sends only
``chunks[0]`` to the model — so on any file above the budget, the first chunk is
the entire analysis. A boundary mid-function means the model reasons about half a
function and is told nothing is missing beyond a truncation note.
"""
import ast
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone

# Languages whose top-level constructs can be tracked by counting braces.
_BRACE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".go", ".rs", ".cs", ".php"}


class FileProcessor:
    """
    Reads files and prepares their content for ARM reasoning operations.

    Core responsibilities:
    - Read files with encoding fallback
    - Chunk content semantically where possible, by line boundaries otherwise
    - Generate UUID session IDs for grouping related operations
    - Build structured session log dictionaries for DB persistence
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self.max_chunk_tokens = config.get("max_chunk_tokens", 4000)
        # Rough approximation: 4 characters ≈ 1 token
        self.chars_per_chunk = self.max_chunk_tokens * 4

    # ── File reading ─────────────────────────────────────────────────────────

    def read_file(self, path: Path) -> str:
        """Read file content with UTF-8 encoding and replacement fallback."""
        return path.read_text(encoding="utf-8", errors="replace")

    # ── Chunking ─────────────────────────────────────────────────────────────

    def chunk_content(self, content: str) -> list:
        """
        Split file content into chunks that fit within the token limit.

        Splits on newline boundaries to preserve code structure — a line
        is never split across two chunks.

        Returns a list of string chunks. Single-chunk files return a
        one-element list.
        """
        if len(content) <= self.chars_per_chunk:
            return [content]

        chunks = []
        lines = content.split("\n")
        current_chunk = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1  # +1 for the newline character
            if current_size + line_size > self.chars_per_chunk and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    # ── Semantic chunking ────────────────────────────────────────────────────

    def chunk_file(self, content: str, filename: str | None = None) -> list:
        """
        Chunk ``content`` on definition boundaries where the language permits,
        falling back to :meth:`chunk_content` otherwise.

        Restores a capability from the original DeepSeek Analyzer, whose
        ``SemanticChunker`` was dropped when ARM was ported. **Not restored
        verbatim** — the original closed a chunk when its brace depth returned to
        zero, and Python has no braces, so every Python function chunk ended on
        its own ``def`` line. Python is handled with :mod:`ast` here instead.

        Guarantees, in priority order:
          1. Never splits a top-level definition across chunks *unless* that one
             definition exceeds the budget on its own, in which case it is
             line-split (a chunk that cannot fit is worse than a split one).
          2. Never returns an empty chunk.
          3. Falls back to line chunking on any parse failure — a syntactically
             invalid file is exactly the kind ARM is asked to analyse.
        """
        if not content:
            return [""]
        if len(content) <= self.chars_per_chunk:
            return [content]

        suffix = Path(filename).suffix.lower() if filename else ""
        if suffix == ".py":
            spans = self._python_spans(content)
        elif suffix in _BRACE_SUFFIXES:
            spans = self._brace_spans(content)
        else:
            spans = None

        if not spans:
            return self.chunk_content(content)
        return self._pack(content.split("\n"), spans)

    def _python_spans(self, content: str) -> list | None:
        """Top-level def/class line spans (1-based, inclusive) via ast, or None."""
        try:
            tree = ast.parse(content)
        except (SyntaxError, ValueError, RecursionError):
            return None
        spans = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                end = getattr(node, "end_lineno", None)
                if end:
                    spans.append((start, end))
        return spans or None

    def _brace_spans(self, content: str) -> list | None:
        """
        Top-level brace-balanced block spans (1-based, inclusive), or None.

        This is the original's approach, kept for the languages it is actually
        correct for. Braces inside strings and comments are not tracked; the
        consequence of miscounting is a suboptimal boundary, never data loss,
        because :meth:`_pack` re-emits every line exactly once regardless.
        """
        spans = []
        depth = 0
        start = None
        for i, line in enumerate(content.split("\n"), start=1):
            opens, closes = line.count("{"), line.count("}")
            if depth == 0 and opens > 0:
                start = i
            depth += opens - closes
            if start is not None and depth <= 0:
                spans.append((start, i))
                start = None
                depth = 0
        return spans or None

    def _pack(self, lines: list, spans: list) -> list:
        """
        Pack lines into budget-sized chunks, breaking only between spans.

        Every line is emitted exactly once and in order, whether or not it falls
        inside a span — so gaps between definitions (imports, module docstrings,
        trailing code) are preserved rather than dropped.
        """
        # Map each line to the end of the span it belongs to, so we never break inside one.
        span_end = {}
        for start, end in spans:
            for ln in range(start, end + 1):
                span_end[ln] = max(end, span_end.get(ln, end))

        chunks: list = []
        current: list = []
        size = 0
        i = 0
        total = len(lines)
        while i < total:
            lineno = i + 1
            end = span_end.get(lineno, lineno)
            unit = lines[i:end]              # the whole definition, or a single line
            unit_size = sum(len(x) + 1 for x in unit)

            if current and size + unit_size > self.chars_per_chunk:
                chunks.append("\n".join(current))
                current, size = [], 0

            if unit_size > self.chars_per_chunk:
                # One definition larger than the budget: line-split it on its own.
                if current:
                    chunks.append("\n".join(current))
                    current, size = [], 0
                chunks.extend(self.chunk_content("\n".join(unit)))
            else:
                current.extend(unit)
                size += unit_size
            i = end

        if current:
            chunks.append("\n".join(current))
        return chunks or [""]

    # ── Session utilities ────────────────────────────────────────────────────

    def create_session_id(self) -> str:
        """Generate a UUID v4 session ID for grouping related ARM operations."""
        return str(uuid.uuid4())

    def create_session_log(
        self,
        session_id: str,
        file_path: str,
        operation: str,
        start_time: float,
        input_tokens: int,
        output_tokens: int,
        status: str,
        error: str = None,
    ) -> dict:
        """
        Build a structured session log entry for DB persistence.

        Includes Infinity Algorithm Execution Speed metric
        (tokens processed per second).
        """
        elapsed = time.time() - start_time
        total_tokens = input_tokens + output_tokens
        return {
            "session_id": session_id,
            "file_path": file_path,
            "operation": operation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_seconds": round(elapsed, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "status": status,
            "error": error,
            # Infinity Algorithm metric: Execution Speed (tokens/second)
            "execution_speed": round(
                total_tokens / max(elapsed, 0.001), 1
            ),
        }
