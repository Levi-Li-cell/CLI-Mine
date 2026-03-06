"""Code/artifact viewer with lightweight syntax highlighting (M3-004)."""

import mimetypes
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


ANSI_RESET = "\033[0m"
ANSI_BLUE = "\033[94m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN = "\033[96m"


KEYWORDS: Dict[str, set] = {
    "python": {
        "def", "class", "return", "if", "else", "elif", "for", "while", "import",
        "from", "try", "except", "finally", "with", "as", "pass", "raise", "True", "False", "None",
    },
    "json": {"true", "false", "null"},
    "markdown": set(),
}


@dataclass
class ArtifactPreview:
    """Preview payload for a code/artifact file."""

    path: str
    language: str
    is_binary: bool
    mime_type: str
    preview: str
    truncated: bool
    size_bytes: int


def detect_language(path: Path, content: str = "") -> str:
    suffix = path.suffix.lower()
    if suffix in {".py", ".pyw"}:
        return "python"
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".js", ".mjs", ".cjs"}:
        return "javascript"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".yml", ".yaml"}:
        return "yaml"

    if content.lstrip().startswith("{") or content.lstrip().startswith("["):
        return "json"
    return "text"


def _is_binary_bytes(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    sample = data[:4096]
    text_chars = sum(1 for b in sample if b in b"\t\n\r" or 32 <= b <= 126)
    ratio = text_chars / max(1, len(sample))
    return ratio < 0.75


def highlight_code(text: str, language: str) -> str:
    if language not in KEYWORDS:
        return text

    highlighted_lines = []
    keywords = KEYWORDS[language]
    for line in text.splitlines():
        if language == "python":
            comment_index = line.find("#")
            comment = ""
            head = line
            if comment_index >= 0:
                head = line[:comment_index]
                comment = line[comment_index:]

            def repl(match):
                token = match.group(0)
                if token in keywords:
                    return f"{ANSI_BLUE}{token}{ANSI_RESET}"
                return token

            head = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", repl, head)
            head = re.sub(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", f"{ANSI_GREEN}\\1{ANSI_RESET}", head)
            if comment:
                comment = f"{ANSI_CYAN}{comment}{ANSI_RESET}"
            highlighted_lines.append(head + comment)
        elif language == "json":
            line = re.sub(r'"([^"\\]|\\.)*"(?=\s*:)', f"{ANSI_YELLOW}\\g<0>{ANSI_RESET}", line)
            line = re.sub(r'(:\s*)("([^"\\]|\\.)*")', f"\\1{ANSI_GREEN}\\2{ANSI_RESET}", line)
            highlighted_lines.append(line)
        else:
            highlighted_lines.append(line)
    return "\n".join(highlighted_lines)


def preview_artifact(path: Path, max_chars: int = 4000) -> ArtifactPreview:
    path = Path(path)
    mime_type, _ = mimetypes.guess_type(str(path))
    mime = mime_type or "application/octet-stream"
    size = path.stat().st_size if path.exists() else 0

    raw = path.read_bytes()
    is_binary = _is_binary_bytes(raw)
    if is_binary:
        preview = f"<binary artifact: {path.name}, size={size} bytes, mime={mime}>"
        return ArtifactPreview(
            path=str(path),
            language="binary",
            is_binary=True,
            mime_type=mime,
            preview=preview,
            truncated=False,
            size_bytes=size,
        )

    text = raw.decode("utf-8", errors="replace")
    truncated = len(text) > max(1, int(max_chars))
    shown = text[:max(1, int(max_chars))]
    language = detect_language(path, shown)
    highlighted = highlight_code(shown, language)
    return ArtifactPreview(
        path=str(path),
        language=language,
        is_binary=False,
        mime_type=mime,
        preview=highlighted,
        truncated=truncated,
        size_bytes=size,
    )


def export_artifact(source: Path, destination: Path) -> Path:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
