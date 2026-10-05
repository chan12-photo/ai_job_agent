"""Read an explicitly selected text document and retain exact source offsets."""

from pathlib import Path
import hashlib
import re


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def read_document(path: Path) -> str:
    path = Path(path).expanduser()
    if path.suffix.lower() not in {".txt", ".md"}:
        raise ValueError("검토한 .txt 또는 .md 파일만 등록할 수 있습니다")
    if path.is_symlink():
        raise ValueError("심볼릭 링크 대신 원본 파일을 직접 지정해 주세요")
    if not path.is_file():
        raise ValueError("일반 파일 경로를 지정해 주세요")
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("문서 크기는 2 MiB 이하여야 합니다")
    raw = path.read_bytes()
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("문서 크기는 2 MiB 이하여야 합니다")
    if b"\x00" in raw:
        raise ValueError("바이너리 파일은 등록할 수 없습니다")
    text = raw.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("빈 문서는 등록할 수 없습니다")
    return text


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_spans(text: str) -> list[tuple[str, int, int, str]]:
    """One paragraph per span; offsets index the original Python string exactly."""
    spans = []
    section = "본문"
    start = None
    offset = 0

    def flush(end):
        nonlocal start
        if start is not None:
            segment = text[start:end]
            left = len(segment) - len(segment.lstrip())
            right = len(segment.rstrip())
            if right > left:
                begin, finish = start + left, start + right
                spans.append((section, begin, finish, text[begin:finish]))
        start = None

    for line in text.splitlines(keepends=True):
        heading = HEADING.match(line.rstrip("\r\n"))
        if heading:
            flush(offset)
            section = heading.group(1)
        elif not line.strip():
            flush(offset)
        elif start is None:
            start = offset
        offset += len(line)
    flush(len(text))
    return spans
