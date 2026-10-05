"""Local image drafts and one macOS Vision OCR adapter."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from . import app, storage


MAX_IMAGES = 5
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_DIMENSION = 8000
DRAFT_SECONDS = 24 * 60 * 60
SWIFT_HELPER = Path(__file__).with_name("ocr_vision.swift")
ID_RE = re.compile(r"[0-9a-f]{32}\Z")
STORED_RE = re.compile(r"[0-9]+/[0-9a-f]{32}-[0-9a-f]{32}\.(?:png|jpg)\Z")


def assets_root(db_path):
    path = Path(db_path).expanduser()
    return path.with_name(path.name + ".assets")


def _private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def _write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _draft_dir(db_path, draft_id):
    if not ID_RE.fullmatch(draft_id):
        raise ValueError("이미지 초안 ID가 올바르지 않습니다")
    return assets_root(db_path) / "drafts" / draft_id


def _save_draft(db_path, draft):
    folder = _draft_dir(db_path, draft["id"])
    temp = folder / f"metadata-{uuid4().hex}.tmp"
    try:
        _write_private(temp, json.dumps(draft, ensure_ascii=False).encode("utf-8"))
        os.replace(temp, folder / "draft.json")
    finally:
        temp.unlink(missing_ok=True)


def cleanup_drafts(db_path):
    root = assets_root(db_path) / "drafts"
    if not root.exists():
        return
    now = datetime.now(timezone.utc).timestamp()
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or not ID_RE.fullmatch(folder.name):
            continue
        try:
            try:
                metadata = json.loads((folder / "draft.json").read_text(encoding="utf-8"))
                created = datetime.fromisoformat(metadata["created_at"]).timestamp()
            except (OSError, ValueError, KeyError, TypeError):
                created = folder.stat().st_mtime
            if now - created > DRAFT_SECONDS:
                shutil.rmtree(folder)
        except FileNotFoundError:
            pass


def _expected_format(filename, content):
    extension = Path(filename).suffix.lower()
    if extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png", "png"
    if extension in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"):
        return "jpeg", "image/jpeg", "jpg"
    raise ValueError("PNG/JPG/JPEG 확장자와 실제 파일 형식이 일치해야 합니다")


def _inspect_image(path, expected):
    try:
        result = subprocess.run(
            ["/usr/bin/sips", "-g", "format", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Mac 이미지 검사 도구를 실행하지 못했습니다") from exc
    if result.returncode:
        raise ValueError("이미지 내용을 읽을 수 없습니다. 파일이 손상됐을 수 있습니다")
    details = {}
    for line in result.stdout.splitlines():
        if ": " in line:
            key, value = line.strip().split(": ", 1)
            details[key] = value
    try:
        width = int(details["pixelWidth"])
        height = int(details["pixelHeight"])
    except (KeyError, ValueError) as exc:
        raise ValueError("이미지 해상도를 읽을 수 없습니다") from exc
    if details.get("format", "").lower() != expected:
        raise ValueError("확장자와 실제 이미지 형식이 다릅니다")
    if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION
            and width * height <= MAX_PIXELS):
        raise ValueError("이미지는 한 변 8000픽셀 이하, 전체 2400만 픽셀 이하여야 합니다")
    return width, height


def create_draft(db_path, uploads):
    """Validate actual image metadata before exposing an unregistered draft."""
    if not 1 <= len(uploads) <= MAX_IMAGES:
        raise ValueError("이미지는 한 번에 1~5장 올릴 수 있습니다")
    if sum(len(content) for _, content in uploads) > MAX_TOTAL_BYTES:
        raise ValueError("이미지 합계는 30 MiB 이하여야 합니다")
    root = assets_root(db_path) / "drafts"
    _private_dir(assets_root(db_path))
    _private_dir(root)
    draft_id = uuid4().hex
    folder = _draft_dir(db_path, draft_id)
    folder.mkdir(mode=0o700)
    pages = []
    try:
        for filename, content in uploads:
            if not content or len(content) > MAX_IMAGE_BYTES:
                raise ValueError("이미지 한 장은 8 MiB 이하여야 합니다")
            actual, mime, extension = _expected_format(filename, content)
            page_id = uuid4().hex
            file_name = f"{page_id}.{extension}"
            path = folder / file_name
            _write_private(path, content)
            width, height = _inspect_image(path, actual)
            pages.append({"id": page_id, "file": file_name, "mime": mime,
                          "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
                          "width": width, "height": height, "ocr_text": None,
                          "ocr_error": None})
        draft = {"id": draft_id, "created_at": datetime.now(timezone.utc).isoformat(),
                 "revision": 0, "pages": pages, "final_text": "", "ocr_done": False,
                 "source_url": "", "deadline_raw": "", "deadline_date": "",
                 "rolling": False, "new_round": False}
        _save_draft(db_path, draft)
        return draft
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def load_draft(db_path, draft_id):
    folder = _draft_dir(db_path, draft_id)
    try:
        draft = json.loads((folder / "draft.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("이미지 초안을 찾을 수 없습니다. 다시 업로드해 주세요") from exc
    if draft.get("id") != draft_id:
        raise ValueError("이미지 초안 정보가 올바르지 않습니다")
    created = datetime.fromisoformat(draft["created_at"])
    if (datetime.now(timezone.utc) - created).total_seconds() > DRAFT_SECONDS:
        raise ValueError("이미지 초안의 24시간 보관 기간이 지났습니다. 다시 업로드해 주세요")
    return draft


def save_draft(db_path, draft):
    draft["revision"] += 1
    _save_draft(db_path, draft)


def list_drafts(db_path):
    root = assets_root(db_path) / "drafts"
    if not root.exists():
        return []
    drafts = []
    for folder in root.iterdir():
        if folder.is_symlink() or not ID_RE.fullmatch(folder.name):
            continue
        try:
            draft = load_draft(db_path, folder.name)
            drafts.append(draft)
        except ValueError:
            continue
    return sorted(drafts, key=lambda draft: draft["created_at"], reverse=True)


def draft_image_path(db_path, draft, page_id):
    page = next((row for row in draft["pages"] if row["id"] == page_id), None)
    if page is None or not re.fullmatch(r"[0-9a-f]{32}\.(?:png|jpg)", page["file"]):
        raise ValueError("이미지를 찾을 수 없습니다")
    return _draft_dir(db_path, draft["id"]) / page["file"], page["mime"]


def discard_draft(db_path, draft_id):
    shutil.rmtree(_draft_dir(db_path, draft_id))


def recognize(path):
    """Run Apple's installed Vision framework locally; return only observed lines."""
    try:
        result = subprocess.run(["/usr/bin/swift", str(SWIFT_HELPER), str(path)],
                                capture_output=True, text=True, timeout=90, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("OCR이 90초 안에 끝나지 않았습니다") from exc
    except OSError as exc:
        raise ValueError("Mac Swift/Vision 실행 도구를 찾을 수 없습니다") from exc
    if result.returncode:
        raise ValueError(result.stderr.strip()[:300] or "Vision OCR 실행에 실패했습니다")
    try:
        lines = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("OCR 결과 형식을 읽을 수 없습니다") from exc
    if not isinstance(lines, list) or any(not isinstance(item, dict)
                                          or not isinstance(item.get("text"), str) for item in lines):
        raise ValueError("OCR 결과에 예상하지 못한 값이 있습니다")
    text = "\n".join(item["text"].strip() for item in lines if item["text"].strip())
    if len(text) > 30000:
        raise ValueError("추출문이 너무 깁니다. 이미지를 나누거나 수동으로 입력해 주세요")
    return text


def compose_text(pages):
    return "\n\n".join(page["ocr_text"].strip() for page in pages
                      if page.get("ocr_text") and page["ocr_text"].strip())


def _copy_images(db_path, job_id, draft, copied):
    """Prepare originals; the caller owns rollback of copied files."""
    root = assets_root(db_path) / "images" / str(job_id)
    _private_dir(assets_root(db_path))
    _private_dir(root)
    records = []
    for page in draft["pages"]:
        source, _ = draft_image_path(db_path, draft, page["id"])
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != page["sha256"]:
            raise ValueError("보관 전 이미지 원본 검증에 실패했습니다")
        name = f"{draft['id']}-{page['file']}"
        destination = root / name
        if not destination.exists():
            _write_private(destination, content)
            copied.append(destination)
        elif hashlib.sha256(destination.read_bytes()).hexdigest() != page["sha256"]:
            raise ValueError("같은 이름의 보관 이미지 내용이 다릅니다")
        records.append({**page, "stored_name": f"{job_id}/{name}"})
    return records


def register_confirmed(conn, db_path, draft):
    """Commit the existing registration operation and image links together."""
    copied = []
    try:
        with storage.atomic(conn):
            job, created = app.register(
                conn, draft["final_text"], source_url=draft["source_url"],
                deadline_raw=draft["deadline_raw"], deadline_date=draft["deadline_date"] or None,
                rolling=draft["rolling"], new_round=draft["new_round"])
            records = _copy_images(db_path, job["job_id"], draft, copied)
            storage.add_job_images(conn, job["job_id"], draft["id"], records)
    except BaseException:
        for path in copied:
            path.unlink(missing_ok=True)
        raise
    # A cleanup problem must not turn a committed registration into a failure.
    shutil.rmtree(_draft_dir(db_path, draft["id"]), ignore_errors=True)
    return job, created


def stored_image_path(db_path, file_name):
    if not STORED_RE.fullmatch(file_name):
        raise ValueError("보관 이미지 경로가 올바르지 않습니다")
    return assets_root(db_path) / "images" / file_name
