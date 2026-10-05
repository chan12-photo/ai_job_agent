"""Small loopback-only UI over the existing job and analysis application functions."""

import argparse
from email import policy
from email.parser import BytesParser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from . import app, llm, ocr, storage
from .__main__ import DEFAULT_DB
from .domain import STATUSES


DEFAULT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
MAX_FORM_BYTES = 2 * 1024 * 1024
MAX_UPLOAD_BODY = 31 * 1024 * 1024
STATUS_NAMES = {
    "planned": "관심", "preparing": "준비 중", "submitted": "지원 완료",
    "interview": "면접", "offer": "제안 받음", "rejected": "불합격", "withdrawn": "철회",
}
REVIEW_NAMES = {"pending": "미검토", "reviewed": "검토 완료", "needs_changes": "수정 필요"}
ASSESSMENT_NAMES = {
    "supported": "근거가 전체 요구와 연결된다는 모델 제안",
    "partial": "일부만 연결된다는 모델 제안 · 전체 요건 충족 아님",
    "insufficient_evidence": "현재 근거로 확인하기 어렵다는 모델 제안",
    "conflicting_evidence": "서로 충돌할 수 있는 근거라는 모델 제안",
    "evidence_not_found": "현재 검색 범위에서 후보를 찾지 못함",
}
RUN_STATUS_NAMES = {
    "review_ready": "초안 저장 · 사람 검토 필요",
    "no_evidence": "검색 근거 없음 · 문서 등록과 검색 범위 확인 필요",
    "partial": "일부 단계 오류 · 결과 확인 필요",
    "failed": "분석 실패 · 단계 오류 확인 필요",
    "timed_out": "분석 시간 초과 · 단계 오류 확인 필요",
    "cancelled": "분석 중단 · 단계 오류 확인 필요",
}
NOTICES = {
    "created": "공고를 등록했습니다.", "existing": "같은 원문이 이미 있어 기존 공고를 보여줍니다.",
    "updated": "지원 기록을 저장했습니다.", "reviewed": "사람의 검토 상태를 저장했습니다.",
    "busy": "다른 공고의 분석이 진행 중입니다. 완료 후 다시 실행해 주세요.",
    "image_created": "확인한 공고 원문과 원본 이미지를 등록했습니다.",
    "image_existing": "같은 공고 원문이 있어 기존 공고에 원본 이미지를 연결했습니다.",
    "reordered": "이미지 순서를 저장했습니다. 최종 원문 순서도 확인해 주세요.",
    "saved_draft": "수정 내용을 임시 저장했습니다.",
    "cleared": "마지막 이미지를 제거했습니다. 다시 업로드하거나 수동으로 등록하세요.",
}


def e(value):
    return escape(str(value), quote=True)


def source_quote(value):
    """Render an extracted field stored as a verified span {"quote", "start", "end"}."""
    if isinstance(value, dict) and value.get("quote"):
        return f"{value['quote']} [{value.get('start')}:{value.get('end')}]"
    if isinstance(value, str) and value:
        return value
    return "미확인"


def deadline_label(row):
    if row["deadline_date"]:
        return f"{row['deadline_date']} · 날짜만 확인, 시각 미확인"
    if row["deadline_precision"] == "rolling":
        return f"{row['deadline_raw'] or '채용 시 마감'} · 수시"
    return f"{row['deadline_raw'] or '미확인'} · 날짜 미확인"


def layout(title, body, *, refresh=False):
    meta = '<meta http-equiv="refresh" content="2">' if refresh else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · AI Job Agent</title>{meta}
<style>
:root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif; color: #17212c; background: #f2f5f7; }}
* {{ box-sizing: border-box; }} body {{ margin: 0; line-height: 1.55; }}
header {{ background: #102e3c; color: white; padding: 18px max(20px, calc((100vw - 1000px)/2)); }}
header a {{ color: white; font-weight: 700; text-decoration: none; font-size: 1.1rem; }}
main {{ max-width: 1000px; margin: 26px auto; padding: 0 18px 60px; }}
h1 {{ font-size: 1.7rem; margin: 0 0 8px; }} h2 {{ font-size: 1.18rem; margin: 0 0 14px; }}
p {{ margin: 8px 0 14px; }} .muted {{ color: #536472; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 310px), 1fr)); gap: 18px; }}
.card {{ background: white; border: 1px solid #dce4e9; border-radius: 12px; padding: 19px; margin: 0 0 18px; box-shadow: 0 2px 9px #102e3c0a; }}
.notice {{ border-left: 4px solid #1c7b69; background: #e9f7f2; padding: 12px 15px; margin: 18px 0; }}
.warning {{ border-left: 4px solid #b07313; background: #fff6e7; padding: 12px 15px; margin: 18px 0; }}
.error {{ border-left: 4px solid #b23a39; background: #fff0ef; padding: 12px 15px; margin: 18px 0; }}
label {{ display: block; font-weight: 600; margin: 12px 0 5px; }}
textarea, input, select {{ width: 100%; font: inherit; border: 1px solid #a9b9c4; border-radius: 7px; padding: 9px 11px; background: white; }}
textarea {{ min-height: 110px; resize: vertical; }} textarea.long {{ min-height: 175px; }}
input[type=checkbox] {{ width: auto; }} .check {{ display: flex; gap: 9px; align-items: center; font-weight: 400; }}
button, .button {{ display: inline-block; margin-top: 15px; padding: 10px 15px; border: 0; border-radius: 7px; background: #126b66; color: white; font: inherit; font-weight: 650; cursor: pointer; text-decoration: none; }}
button:hover, .button:hover {{ background: #0e5652; }} button:disabled {{ opacity: .55; cursor: not-allowed; }}
a {{ color: #0d625e; }} .item {{ border-top: 1px solid #e3e9ed; padding: 13px 0; }} .item:first-of-type {{ border-top: 0; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #e8eff1; font-size: .85rem; margin-right: 6px; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; background: #f4f7f8; border-radius: 7px; padding: 12px; margin: 8px 0; }}
small {{ color: #52616e; }} .evidence {{ border-left: 3px solid #6a9b9a; padding-left: 12px; margin: 12px 0; }}
.candidate {{ border-left-color: #b3bbc0; }} .row {{ display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center; }}
.original {{ max-width: 100%; max-height: 650px; width: auto; height: auto; border: 1px solid #cbd5dc; border-radius: 7px; }}
.page {{ border-top: 1px solid #dce4e9; padding-top: 18px; margin-top: 18px; }}
.drop-zone {{ border: 2px dashed #6a9b9a; border-radius: 10px; padding: 20px; margin: 15px 0; background: #f3faf8; }}
.drop-zone:focus, .drop-zone.dragging {{ outline: 3px solid #126b66; }}
</style></head><body><header><a href="/">AI Job Agent · 로컬 공고 관리</a></header><main>{body}</main></body></html>"""


class RunManager:
    """In-process progress only; completed analyses remain in SQLite."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.lock = threading.Lock()
        self.runs = {}
        self.active_by_job = {}

    def active(self, job_id=None):
        with self.lock:
            if job_id is not None:
                run_id = self.active_by_job.get(job_id)
                return dict(self.runs[run_id]) if run_id else None
            return [dict(self.runs[run_id]) for run_id in self.active_by_job.values()]

    def get(self, run_id):
        with self.lock:
            row = self.runs.get(run_id)
            return dict(row) if row else None

    def start(self, job_id, model):
        with self.lock:
            if job_id in self.active_by_job:
                return self.active_by_job[job_id], False
            if self.active_by_job:
                return None, False
            run_id = str(uuid4())
            self.runs[run_id] = {"run_id": run_id, "job_id": job_id, "state": "queued",
                                 "started": time.monotonic(), "model": model}
            self.active_by_job[job_id] = run_id
        try:
            threading.Thread(target=self._work, args=(run_id,), daemon=True,
                             name="job-analysis").start()
        except RuntimeError:
            with self.lock:
                del self.active_by_job[job_id]
                del self.runs[run_id]
            raise
        return run_id, True

    def _work(self, run_id):
        with self.lock:
            self.runs[run_id]["state"] = "running"
            job_id = self.runs[run_id]["job_id"]
            model = self.runs[run_id]["model"]
        try:
            with storage.connect(self.db_path) as conn:
                result = app.run_workflow(conn, job_id, llm.OllamaClient(model))
            update = {"state": "finished", "analysis_id": result["analysis_id"],
                      "result_status": result["status"]}
        except (ValueError, llm.LocalModelError, sqlite3.Error, OSError) as exc:
            update = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:
            update = {"state": "error", "error": f"{type(exc).__name__}: 분석 실행에 실패했습니다"}
        with self.lock:
            self.runs[run_id].update(update)
            self.runs[run_id]["finished"] = time.monotonic()
            self.active_by_job.pop(job_id, None)


class OcrRunManager:
    """Run Vision only after a click, one draft at a time."""

    def __init__(self, db_path, draft_lock):
        self.db_path = Path(db_path)
        self.draft_lock = draft_lock
        self.lock = threading.Lock()
        self.runs = {}
        self.active_id = None

    def get(self, run_id):
        with self.lock:
            row = self.runs.get(run_id)
            return dict(row) if row else None

    def active(self, draft_id=None):
        with self.lock:
            row = self.runs.get(self.active_id) if self.active_id else None
            if row and (draft_id is None or row["draft_id"] == draft_id):
                return dict(row)
            return None

    def start(self, draft_id):
        with self.lock:
            if self.active_id:
                active = self.runs[self.active_id]
                return (self.active_id, False) if active["draft_id"] == draft_id else (None, False)
            run_id = uuid4().hex
            self.runs[run_id] = {"run_id": run_id, "draft_id": draft_id, "state": "queued", "page": 0,
                                 "started": time.monotonic()}
            self.active_id = run_id
        try:
            threading.Thread(target=self._work, args=(run_id,), daemon=True,
                             name="local-image-ocr").start()
        except RuntimeError:
            with self.lock:
                self.active_id = None
                del self.runs[run_id]
            raise
        return run_id, True

    def _work(self, run_id):
        with self.lock:
            self.runs[run_id]["state"] = "running"
            draft_id = self.runs[run_id]["draft_id"]
        try:
            with self.draft_lock:
                draft = ocr.load_draft(self.db_path, draft_id)
            results = {}
            for index, page in enumerate(draft["pages"], 1):
                with self.lock:
                    self.runs[run_id]["page"] = index
                try:
                    path, _ = ocr.draft_image_path(self.db_path, draft, page["id"])
                    value = ocr.recognize(path)
                    results[page["id"]] = (value, None if value else "글자를 찾지 못했습니다. 원본을 보고 직접 입력해 주세요")
                except (OSError, ValueError) as exc:
                    results[page["id"]] = ("", str(exc))
            with self.draft_lock:
                current = ocr.load_draft(self.db_path, draft_id)
                for page in current["pages"]:
                    page["ocr_text"], page["ocr_error"] = results[page["id"]]
                current["ocr_done"] = True
                current["final_text"] = ocr.compose_text(current["pages"])
                ocr.save_draft(self.db_path, current)
            update = {"state": "finished", "errors": sum(bool(error) for _, error in results.values())}
        except Exception as exc:
            update = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
        with self.lock:
            self.runs[run_id].update(update)
            self.active_id = None


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, db_path, port=8765, model=DEFAULT_MODEL):
        self.db_path = Path(db_path).expanduser()
        self.model = model
        self.csrf_token = secrets.token_urlsafe(32)
        self.runs = RunManager(self.db_path)
        self.draft_lock = threading.RLock()
        self.ocr_runs = OcrRunManager(self.db_path, self.draft_lock)
        super().__init__(("127.0.0.1", port), WebHandler)


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Request paths and user content do not belong in the terminal log.
        return

    def _send(self, status, body, content_type="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _send_image(self, path, mime):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, path):
        self.send_response(303)
        self.send_header("Location", path)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _error(self, status, message, back="/"):
        self._send(status, layout("오류", f'<h1>요청을 처리하지 못했습니다</h1><div class="error">{e(message)}</div><p><a href="{e(back)}">돌아가기</a></p>'))

    def _check_host(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self._error(403, "127.0.0.1 주소로만 접속할 수 있습니다")
            return False
        origin = self.headers.get("Origin")
        # The Codex in-app browser sends Origin: null for local form posts.
        # Its requests still need the exact loopback Host and the CSRF token.
        if origin and origin not in {f"http://{expected}", "null"}:
            self._error(403, "다른 사이트에서 보낸 요청을 허용하지 않습니다")
            return False
        return True

    def _check_token(self, token):
        if not hmac.compare_digest(token, self.server.csrf_token):
            raise PermissionError("화면을 새로 열고 다시 제출해 주세요")

    def _form(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
            raise ValueError("지원하지 않는 양식 형식입니다")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("양식 크기를 확인할 수 없습니다") from exc
        if not 0 < size <= MAX_FORM_BYTES:
            raise ValueError("양식은 2 MiB 이하로 입력해 주세요")
        fields = parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True)
        self._check_token(fields.get("_token", [""])[0])
        return {key: values[0] for key, values in fields.items()}

    def _image_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data;"):
            raise ValueError("이미지 업로드 형식이 올바르지 않습니다")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("업로드 크기를 확인할 수 없습니다") from exc
        if not 0 < size <= MAX_UPLOAD_BODY:
            raise ValueError("이미지 업로드 전체 크기는 31 MiB 이하여야 합니다")
        message = BytesParser(policy=policy.default).parsebytes(
            f"MIME-Version: 1.0\r\nContent-Type: {content_type}\r\n\r\n".encode("ascii", "strict")
            + self.rfile.read(size))
        if not message.is_multipart():
            raise ValueError("이미지 업로드 경계를 읽을 수 없습니다")
        parts = list(message.iter_parts())
        if len(parts) > ocr.MAX_IMAGES + 1:
            raise ValueError("이미지는 최대 5장까지 선택해 주세요")
        token = ""
        uploads = []
        for part in parts:
            if part.get_content_disposition() != "form-data":
                raise ValueError("업로드 양식 구성이 올바르지 않습니다")
            name = part.get_param("name", header="content-disposition")
            content = part.get_payload(decode=True) or b""
            if name == "_token":
                token = content.decode("utf-8")
            elif name == "images" and part.get_filename():
                uploads.append((part.get_filename(), content))
            else:
                raise ValueError("예상하지 못한 업로드 항목이 있습니다")
        self._check_token(token)
        return uploads

    def _token(self):
        return f'<input type="hidden" name="_token" value="{e(self.server.csrf_token)}">'

    def do_GET(self):
        if not self._check_host():
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/static/image-input.js":
            self._send(200, Path(__file__).with_name("image-input.js").read_text(encoding="utf-8"),
                       "text/javascript; charset=utf-8")
            return
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                self._home(query.get("notice", [""])[0])
                return
            if path == "/ocr":
                self._ocr_home(query.get("notice", [""])[0])
                return
            found = re.fullmatch(r"/ocr/drafts/([0-9a-f]{32})/images/([0-9a-f]{32})", path)
            if found:
                draft = ocr.load_draft(self.server.db_path, found.group(1))
                image_path, mime = ocr.draft_image_path(self.server.db_path, draft, found.group(2))
                self._send_image(image_path, mime)
                return
            found = re.fullmatch(r"/ocr/drafts/([0-9a-f]{32})", path)
            if found:
                self._ocr_draft(found.group(1), query)
                return
            found = re.fullmatch(r"/jobs/(\d+)/images/(\d+)", path)
            if found:
                job_id, image_id = map(int, found.groups())
                with storage.connect(self.server.db_path) as conn:
                    row = storage.get_job_image(conn, job_id, image_id)
                if row is None:
                    self._error(404, "공고 이미지를 찾을 수 없습니다")
                    return
                self._send_image(ocr.stored_image_path(self.server.db_path, row["file_name"]),
                                 row["mime_type"])
                return
            found = re.fullmatch(r"/jobs/(\d+)", path)
            if found:
                self._job(int(found.group(1)), query)
                return
            found = re.fullmatch(r"/analyses/(\d+)", path)
            if found:
                self._analysis(int(found.group(1)), query.get("notice", [""])[0])
                return
            self._error(404, "화면을 찾을 수 없습니다")
        except ValueError as exc:
            self._error(404 if path.startswith("/ocr/drafts/") else 500, str(exc),
                        "/ocr" if path.startswith("/ocr") else "/")
        except (sqlite3.Error, OSError) as exc:
            self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self):
        if not self._check_host():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/ocr/upload":
                uploads = self._image_upload()
                ocr.cleanup_drafts(self.server.db_path)
                draft = ocr.create_draft(self.server.db_path, uploads)
                self._redirect(f"/ocr/drafts/{draft['id']}")
                return
            form = self._form()
            found = re.fullmatch(r"/ocr/drafts/([0-9a-f]{32})/run", path)
            if found:
                draft_id = found.group(1)
                with self.server.draft_lock:
                    ocr.load_draft(self.server.db_path, draft_id)
                    run_id, _ = self.server.ocr_runs.start(draft_id)
                self._redirect(f"/ocr/drafts/{draft_id}?run={run_id}" if run_id else
                               f"/ocr/drafts/{draft_id}?notice=busy")
                return
            found = re.fullmatch(r"/ocr/drafts/([0-9a-f]{32})/edit", path)
            if found:
                self._edit_ocr_draft(found.group(1), form)
                return
            if path == "/jobs":
                with storage.connect(self.server.db_path) as conn:
                    job, created = app.register(
                        conn, form.get("raw_text", ""), source_url=form.get("source_url"),
                        deadline_raw=form.get("deadline_raw"),
                        deadline_date=form.get("deadline_date") or None,
                        rolling=form.get("rolling") == "on",
                        new_round=form.get("new_round") == "on")
                self._redirect(f"/jobs/{job['job_id']}?notice={'created' if created else 'existing'}")
                return
            found = re.fullmatch(r"/jobs/(\d+)/application", path)
            if found:
                job_id = int(found.group(1))
                with storage.connect(self.server.db_path) as conn:
                    app.change_application(conn, job_id, int(form.get("revision", "-1")),
                                           status=form.get("status"), notes=form.get("notes"))
                self._redirect(f"/jobs/{job_id}?notice=updated")
                return
            found = re.fullmatch(r"/jobs/(\d+)/analysis", path)
            if found:
                job_id = int(found.group(1))
                with storage.connect(self.server.db_path) as conn:
                    if storage.get_job(conn, job_id) is None:
                        raise ValueError(f"공고 {job_id}를 찾을 수 없습니다")
                model = form.get("model", "").strip()
                if not model:
                    raise ValueError("설치된 로컬 모델명을 입력해 주세요")
                run_id, _ = self.server.runs.start(job_id, model)
                self._redirect(f"/jobs/{job_id}?run={run_id}" if run_id else
                               f"/jobs/{job_id}?notice=busy")
                return
            found = re.fullmatch(r"/analyses/(\d+)/review", path)
            if found:
                analysis_id = int(found.group(1))
                with storage.connect(self.server.db_path) as conn:
                    app.review_analysis(conn, analysis_id, int(form.get("revision", "-1")),
                                        form.get("review_status", ""))
                self._redirect(f"/analyses/{analysis_id}?notice=reviewed")
                return
            self._error(404, "요청 주소를 찾을 수 없습니다")
        except PermissionError as exc:
            self._error(403, str(exc))
        except storage.RevisionConflict as exc:
            draft_route = re.match(r"(/ocr/drafts/[0-9a-f]{32})/", path)
            self._error(409, str(exc), draft_route.group(1) if draft_route else "/")
        except (ValueError, UnicodeError) as exc:
            draft_route = re.match(r"(/ocr/drafts/[0-9a-f]{32})/", path)
            self._error(400, str(exc), draft_route.group(1) if draft_route else
                        "/ocr" if path.startswith("/ocr") else "/")
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            draft_route = re.match(r"(/ocr/drafts/[0-9a-f]{32})/", path)
            self._error(500, f"{type(exc).__name__}: {exc}",
                        draft_route.group(1) if draft_route else "/")

    def _home(self, notice):
        with storage.connect(self.server.db_path) as conn:
            jobs = storage.list_jobs(conn)
        parts = ['<h1>공고 목록</h1><p class="muted">확인된 마감 날짜순입니다. 날짜가 불명확하면 그대로 미확인으로 표시합니다.</p>']
        if notice in NOTICES:
            parts.append(f'<div class="notice">{e(NOTICES[notice])}</div>')
        parts.append('<p><a class="button" href="/ocr">공고 이미지로 등록</a></p>')
        parts.append('<div class="grid"><section class="card"><h2>공고 수동 등록</h2>'
                     '<p class="muted">AI 없이 원문을 저장합니다. 같은 원문은 중복 저장하지 않습니다.</p>'
                     f'<form method="post" action="/jobs">{self._token()}'
                     '<label for="raw_text">공고 원문</label><textarea class="long" id="raw_text" name="raw_text" required></textarea>'
                     '<label for="source_url">출처 주소 · 선택</label><input id="source_url" name="source_url" type="text">'
                     '<label for="deadline_raw">마감 표현 원문 · 선택</label><input id="deadline_raw" name="deadline_raw" placeholder="예: 10월 중">'
                     '<label for="deadline_date">확인한 마감 날짜 · 선택</label><input id="deadline_date" name="deadline_date" type="date">'
                     '<small>연·월·일을 직접 확인했을 때만 입력하세요. 시각은 추정하지 않습니다.</small>'
                     '<label class="check"><input type="checkbox" name="rolling"> 채용 시 마감</label>'
                     '<label class="check"><input type="checkbox" name="new_round"> 같은 원문의 별도 모집 회차</label>'
                     '<button type="submit">공고 등록</button></form></section><section class="card"><h2>저장된 공고</h2>')
        if not jobs:
            parts.append('<p class="muted">아직 등록된 공고가 없습니다.</p>')
        for row in jobs:
            preview = row["raw_text"].strip().replace("\n", " ")[:110]
            parts.append(f'<div class="item"><a href="/jobs/{row["job_id"]}"><strong>#{row["job_id"]} {e(preview)}</strong></a>'
                         f'<p><span class="tag">{e(STATUS_NAMES.get(row["status"], row["status"]))}</span>'
                         f'마감 {e(deadline_label(row))}</p></div>')
        parts.append('</section></div>')
        self._send(200, layout("공고 목록", "".join(parts)))

    def _ocr_home(self, notice):
        with self.server.draft_lock:
            ocr.cleanup_drafts(self.server.db_path)
            drafts = ocr.list_drafts(self.server.db_path)
        parts = ['<p><a href="/">← 공고 목록·수동 입력</a></p><h1>공고 이미지 입력</h1>'
                 '<div class="warning">OCR은 입력 보조입니다. 마감일, 경력 연수, 필수·우대, '
                 '“없음·미사용” 같은 부정 표현과 여러 직무의 2열 배치를 원본과 비교해 주세요. '
                 '흐리거나 빠진 내용은 추측해 채우지 않습니다.</div>'
                 '<section class="card"><h2>PNG·JPG·JPEG 업로드</h2>'
                 '<p>한 번에 1~5장, 한 장 8 MiB 이하, 합계 30 MiB 이하입니다. '
                 '순서와 불필요한 이미지는 다음 화면에서 조정할 수 있습니다.</p>']
        if notice in NOTICES:
            parts.append(f'<div class="notice">{e(NOTICES[notice])}</div>')
        parts.append(f'<form id="image-upload" method="post" action="/ocr/upload" enctype="multipart/form-data">{self._token()}'
                     '<div id="image-drop" class="drop-zone" tabindex="0" role="region" aria-label="이미지 붙여넣기·끌어놓기">'
                     '<strong>여기를 누르고 ⌘V로 이미지를 붙여넣거나, 이미지 파일을 끌어 놓으세요.</strong>'
                     '<p>Mac 영역 캡처: ⌃⇧⌘4 → 영역 선택 → 이 화면에서 ⌘V</p>'
                     '<small>여러 번 붙여넣거나 파일을 추가할 수 있습니다. 아래 파일 선택도 사용할 수 있습니다.</small></div>'
                     '<label for="images">공고 이미지 선택</label>'
                     '<input id="images" name="images" type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" multiple required>'
                     '<p id="image-input-status" role="status" aria-live="polite"></p><ol id="image-selection"></ol>'
                     '<button id="image-upload-button" type="submit">이미지 올리기</button></form>'
                     '<noscript><p>붙여넣기·끌어놓기에는 JavaScript가 필요합니다. 파일 선택으로 업로드할 수 있습니다.</p></noscript>'
                     '<script src="/static/image-input.js" defer></script>'
                     '<p class="muted">업로드한 이미지는 이 Mac의 로컬 임시 폴더에만 저장됩니다. '
                     '확인 전 초안은 24시간 뒤 다음 접속 때 정리합니다.</p></section>')
        if drafts:
            parts.append('<section class="card"><h2>이어서 확인할 이미지 초안</h2>')
            for draft in drafts:
                parts.append(f'<p><a href="/ocr/drafts/{draft["id"]}">{len(draft["pages"])}장 초안</a> · '
                             f'{e(draft["created_at"])}</p>')
            parts.append('</section>')
        self._send(200, layout("공고 이미지 입력", "".join(parts)))

    def _ocr_draft(self, draft_id, query):
        with self.server.draft_lock:
            draft = ocr.load_draft(self.server.db_path, draft_id)
        active = self.server.ocr_runs.active(draft_id)
        run_id = query.get("run", [""])[0] or (active["run_id"] if active else "")
        run = self.server.ocr_runs.get(run_id) if run_id else None
        busy = bool(self.server.ocr_runs.active())
        parts = ['<p><a href="/ocr">← 새 이미지 업로드</a> · <a href="/">수동 입력</a></p>'
                 '<h1>이미지 원본과 추출문 확인</h1>'
                 '<div class="warning">최종 공고 원문은 원본과 직접 비교해 수정하세요. '
                 '여러 직무가 섞였으면 해당 직무 문구만 남기세요. '
                 '마감일·경력 연수·부정 표현은 특히 확인해 주세요.</div>']
        notice = query.get("notice", [""])[0]
        if notice in NOTICES:
            parts.append(f'<div class="notice">{e(NOTICES[notice])}</div>')
        refresh = False
        if run_id and (run is None or run["draft_id"] != draft_id):
            parts.append('<div class="warning">이전 서버의 진행 정보는 사라졌습니다. '
                         '아래 추출문을 확인하거나 OCR을 다시 실행해 주세요.</div>')
        elif run and run["state"] in {"queued", "running"}:
            refresh = True
            parts.append(f'<div class="notice" role="status">로컬 OCR 진행 중 · '
                         f'{run["page"]}/{len(draft["pages"])}장 · '
                         f'{int(time.monotonic() - run["started"])}초 경과. '
                         '2초마다 화면을 갱신합니다.</div>')
        elif run and run["state"] == "finished":
            css = "warning" if run["errors"] else "notice"
            parts.append(f'<div class="{css}">OCR이 끝났습니다. '
                         f'글자 없음 또는 실패 {run["errors"]}장. 원본과 비교해 수정하세요.</div>')
        elif run and run["state"] == "error":
            parts.append(f'<div class="error">OCR 처리 실패: {e(run["error"])}. '
                         '원본을 보며 직접 입력하거나 다시 실행할 수 있습니다.</div>')
        if busy and not active:
            parts.append('<div class="warning">다른 이미지 초안을 처리 중입니다. 완료 뒤 실행해 주세요.</div>')
        disabled = " disabled" if busy else ""
        parts.append('<section class="card"><h2>OCR 실행</h2>'
                     '<p>이 버튼을 눌렀을 때만 macOS Vision이 로컬에서 이미지를 읽습니다. '
                     '다시 실행하면 이미지별 수정문과 자동 구성된 최종 원문이 덮어써집니다.</p>'
                     f'<form method="post" action="/ocr/drafts/{draft_id}/run">{self._token()}'
                     f'<button type="submit"{disabled}>{"OCR 다시 실행" if draft["ocr_done"] else "OCR 실행"}</button>'
                     '</form></section>')
        parts.append(f'<form method="post" action="/ocr/drafts/{draft_id}/edit">{self._token()}'
                     f'<input type="hidden" name="revision" value="{draft["revision"]}">'
                     '<section class="card"><h2>이미지 순서와 이미지별 추출문</h2>'
                     '<p class="muted">위·아래 이동 또는 제거 시 최종 원문을 이미지별 글자로 다시 구성합니다. '
                     '최종 원문을 따로 고쳤다면 다시 확인하세요.</p>')
        for index, page in enumerate(draft["pages"], 1):
            image_url = f'/ocr/drafts/{draft_id}/images/{page["id"]}'
            parts.append(f'<div class="page"><h3>이미지 {index} / {len(draft["pages"])}</h3>'
                         f'<p><small>{page["width"]}×{page["height"]}픽셀 · '
                         f'{page["size"] / 1024 / 1024:.1f} MiB</small></p>'
                         f'<p><img class="original" src="{image_url}" alt="공고 원본 이미지 {index}"></p>'
                         f'<div class="row"><button type="submit" name="action" value="up:{page["id"]}"'
                         f'{" disabled" if index == 1 or busy else ""}>위로</button>'
                         f'<button type="submit" name="action" value="down:{page["id"]}"'
                         f'{" disabled" if index == len(draft["pages"]) or busy else ""}>아래로</button>'
                         f'<button type="submit" name="action" value="remove:{page["id"]}"{disabled}>'
                         '이 이미지 제거</button></div>')
            if page.get("ocr_error"):
                parts.append(f'<p class="error">{e(page["ocr_error"])}</p>')
            parts.append(f'<label for="page_{page["id"]}">이미지 {index} 추출문 · 수정 가능</label>'
                         f'<textarea id="page_{page["id"]}" name="page_{page["id"]}"'
                         f'{disabled}>{e(page.get("ocr_text") or "")}</textarea></div>')
        parts.append('</section><section class="card"><h2>최종 공고 원문 · 직접 확인</h2>'
                     '<p>이미지별 문구를 수정한 뒤 아래 버튼으로 다시 구성할 수 있습니다. '
                     '최종 원문은 별도로 자유롭게 편집할 수 있습니다. 여러 직무 중 해당 직무만 남기세요.</p>'
                     '<p class="muted">기존 AI 분석의 입력 상한은 3,000자입니다. 등록할 글자는 직접 확인해 선택하세요.</p>'
                     f'<button type="submit" name="action" value="compose"{disabled}>'
                     '이미지별 수정문으로 다시 구성</button>'
                     f'<label for="final_text">최종 공고 원문</label><textarea class="long" id="final_text" '
                     f'name="final_text"{disabled}>{e(draft["final_text"])}</textarea>'
                     '<label for="source_url">공고 출처 주소 · 선택</label>'
                     f'<input id="source_url" name="source_url" type="text" value="{e(draft["source_url"])}">'
                     '<label for="deadline_raw">마감 표현 원문 · 선택</label>'
                     f'<input id="deadline_raw" name="deadline_raw" value="{e(draft["deadline_raw"])}">'
                     '<label for="deadline_date">확인한 마감 날짜 · 선택</label>'
                     f'<input id="deadline_date" name="deadline_date" type="date" value="{e(draft["deadline_date"])}">'
                     '<small>날짜·시각을 OCR 글자만 보고 추정하지 마세요. 날짜가 확실할 때만 입력합니다.</small>'
                     f'<label class="check"><input type="checkbox" name="rolling"{" checked" if draft["rolling"] else ""}> 채용 시 마감</label>'
                     f'<label class="check"><input type="checkbox" name="new_round"{" checked" if draft["new_round"] else ""}> 같은 원문의 별도 모집 회차</label>'
                     '<label class="check"><input type="checkbox" name="verified" value="on"> '
                     '원본 이미지와 최종 원문을 비교·수정했습니다</label>'
                     f'<div class="row"><button type="submit" name="action" value="save"{disabled}>'
                     '수정 내용 임시 저장</button>'
                     f'<button type="submit" name="action" value="register"{disabled}>'
                     '확인한 원문 등록</button></div>'
                     '<p class="muted">등록 뒤에도 AI 분석은 공고 상세 화면에서 별도로 실행합니다.</p>'
                     '</section></form>')
        self._send(200, layout("이미지 원문 확인", "".join(parts), refresh=refresh))

    def _edit_ocr_draft(self, draft_id, form):
        action = form.get("action", "")
        with self.server.draft_lock:
            if self.server.ocr_runs.active(draft_id):
                raise ValueError("OCR 진행 중에는 이미지와 글자를 수정할 수 없습니다")
            draft = ocr.load_draft(self.server.db_path, draft_id)
            if int(form.get("revision", "-1")) != draft["revision"]:
                raise storage.RevisionConflict("이미지 초안이 다른 화면에서 바뀌었습니다. 다시 조회해 주세요")
            old_final = draft["final_text"]
            for page in draft["pages"]:
                key = "page_" + page["id"]
                if key in form:
                    value = form[key]
                    if len(value) > 30000:
                        raise ValueError("이미지별 추출문은 3만 자 이하여야 합니다")
                    page["ocr_text"] = value
            final_text = form.get("final_text", old_final)
            if len(final_text) > 100000:
                raise ValueError("최종 공고 원문은 10만 자 이하여야 합니다")
            draft["final_text"] = final_text
            draft["source_url"] = form.get("source_url", "")
            draft["deadline_raw"] = form.get("deadline_raw", "")
            draft["deadline_date"] = form.get("deadline_date", "")
            draft["rolling"] = form.get("rolling") == "on"
            draft["new_round"] = form.get("new_round") == "on"
            move = re.fullmatch(r"(up|down|remove):([0-9a-f]{32})", action)
            notice = "saved_draft"
            removed_path = None
            if move:
                operation, page_id = move.groups()
                index = next((i for i, page in enumerate(draft["pages"])
                              if page["id"] == page_id), None)
                if index is None:
                    raise ValueError("이미지 순서 정보를 찾을 수 없습니다")
                if operation == "remove":
                    if len(draft["pages"]) == 1:
                        ocr.discard_draft(self.server.db_path, draft_id)
                        self._redirect("/ocr?notice=cleared")
                        return
                    removed_path, _ = ocr.draft_image_path(self.server.db_path, draft, page_id)
                    draft["pages"].pop(index)
                elif operation == "up" and index > 0:
                    draft["pages"][index - 1], draft["pages"][index] = (
                        draft["pages"][index], draft["pages"][index - 1])
                elif operation == "down" and index < len(draft["pages"]) - 1:
                    draft["pages"][index + 1], draft["pages"][index] = (
                        draft["pages"][index], draft["pages"][index + 1])
                draft["final_text"] = ocr.compose_text(draft["pages"])
                notice = "reordered"
            elif action == "compose":
                draft["final_text"] = ocr.compose_text(draft["pages"])
            elif action not in {"save", "register"}:
                raise ValueError("초안 작업 종류가 올바르지 않습니다")
            ocr.save_draft(self.server.db_path, draft)
            if removed_path:
                removed_path.unlink(missing_ok=True)
            if action == "register":
                if form.get("verified") != "on":
                    raise ValueError("원본과 최종 공고 원문을 확인한 뒤 확인란을 선택해 주세요")
                if not draft["final_text"].strip():
                    raise ValueError("최종 공고 원문이 비어 있습니다. 원본을 보고 직접 입력할 수 있습니다")
                with storage.connect(self.server.db_path) as conn:
                    job, created = ocr.register_confirmed(conn, self.server.db_path, draft)
                self._redirect(f"/jobs/{job['job_id']}?notice={'image_created' if created else 'image_existing'}")
                return
        self._redirect(f"/ocr/drafts/{draft_id}?notice={notice}")

    def _job(self, job_id, query):
        with storage.connect(self.server.db_path) as conn:
            row = storage.get_job(conn, job_id)
            if row is None:
                self._error(404, f"공고 {job_id}를 찾을 수 없습니다")
                return
            analyses = storage.list_analyses(conn, job_id)
            images = storage.list_job_images(conn, job_id)
        parts = [f'<p><a href="/">← 공고 목록</a></p><h1>공고 #{job_id}</h1>']
        notice = query.get("notice", [""])[0]
        if notice in NOTICES:
            parts.append(f'<div class="notice">{e(NOTICES[notice])}</div>')
        active_job_run = self.server.runs.active(job_id)
        run_id = query.get("run", [""])[0] or (
            active_job_run["run_id"] if active_job_run else "")
        run = self.server.runs.get(run_id) if run_id else None
        refresh = False
        if run_id and (run is None or run["job_id"] != job_id):
            parts.append('<div class="warning">이 서버 세션의 진행 정보를 찾지 못했습니다. 저장된 분석 목록을 확인하세요.</div>')
        elif run and run["state"] in {"queued", "running"}:
            refresh = True
            elapsed = int(time.monotonic() - run["started"])
            parts.append(f'<div class="notice" role="status">로컬 분석 {"대기 중" if run["state"] == "queued" else "진행 중"} · {elapsed}초 경과. 이 화면은 2초마다 갱신됩니다.</div>')
        elif run and run["state"] == "finished":
            status = run["result_status"]
            css = "notice" if status == "review_ready" else (
                "error" if status in {"failed", "timed_out", "cancelled"} else "warning")
            parts.append(f'<div class="{css}">분석 기록이 저장됐습니다 · '
                         f'{e(RUN_STATUS_NAMES.get(status, status))}. '
                         f'<a href="/analyses/{run["analysis_id"]}">분석 #{run["analysis_id"]} 보기</a></div>')
        elif run and run["state"] == "error":
            parts.append(f'<div class="error">분석 실행 실패: {e(run["error"])}. 공고와 기존 분석은 계속 조회할 수 있습니다.</div>')
        parts.append('<div class="grid"><section class="card"><h2>공고 원문</h2>'
                     f'<p>마감: {e(deadline_label(row))}</p><p>출처: {e(row["source_url"] or "미입력")}</p>'
                     f'<p class="muted">등록 {e(row["captured_at"])}</p><pre>{e(row["raw_text"])}</pre></section>')
        parts.append('<section class="card"><h2>지원 기록 · 사람이 입력</h2>'
                     f'<p>현재 상태: <strong>{e(STATUS_NAMES.get(row["status"], row["status"]))}</strong> · '
                     f'지원일 {e(row["submitted_at"] or "미확인")} · revision {row["revision"]}</p>'
                     f'<form method="post" action="/jobs/{job_id}/application">{self._token()}'
                     f'<input type="hidden" name="revision" value="{row["revision"]}">'
                     '<label for="status">지원 상태</label><select id="status" name="status">')
        for status in STATUSES:
            selected = ' selected' if row["status"] == status else ''
            parts.append(f'<option value="{e(status)}"{selected}>{e(STATUS_NAMES[status])}</option>')
        parts.append('</select><label for="notes">메모</label>'
                     f'<textarea id="notes" name="notes">{e(row["notes"])}</textarea>'
                     '<button type="submit">지원 기록 저장</button></form>'
                     '<p class="muted">분석을 실행해도 이 기록은 자동 변경되지 않습니다.</p></section></div>')
        if images:
            parts.append('<section class="card"><h2>등록 당시 확인한 이미지 원본</h2>'
                         '<p class="muted">이미지별 추출·수정문에는 오독이 남을 수 있습니다. '
                         '공고 등록에는 위의 최종 공고 원문을 사용했습니다.</p>')
            for index, image in enumerate(images, 1):
                parts.append(f'<div class="page"><h3>이미지 {index}</h3>'
                             f'<p><img class="original" src="/jobs/{job_id}/images/{image["image_id"]}" '
                             f'alt="공고에 연결된 이미지 {index}"></p>'
                             f'<p><small>{image["pixel_width"]}×{image["pixel_height"]}픽셀 · '
                             f'등록 원본</small></p>'
                             f'<pre>{e(image["confirmed_text"])}</pre></div>')
            parts.append('</section>')
        active = self.server.runs.active()
        busy = bool(active)
        parts.append('<section class="card"><h2>새 분석 초안</h2>'
                     '<p>사용자가 버튼을 누를 때만 로컬 Ollama로 JD 추출과 근거 연결을 실행합니다. '
                     '결과는 지원 자격의 확정이 아니며 직접 검토해야 합니다.</p>'
                     '<p class="muted">Ollama가 꺼져 있어도 공고 관리와 저장된 분석 조회는 가능합니다. '
                     '검토한 문서는 기존 CLI의 doc-add 명령으로 등록합니다.</p>')
        if busy:
            parts.append('<div class="warning">현재 분석 작업이 진행 중입니다. 중복 실행을 막기 위해 새 실행을 기다립니다.</div>')
        parts.append(f'<form method="post" action="/jobs/{job_id}/analysis">{self._token()}'
                     f'<label for="model">설치된 로컬 모델 이름</label><input id="model" name="model" value="{e(self.server.model)}" required>'
                     f'<button type="submit"{" disabled" if busy else ""}>분석 실행</button></form></section>')
        parts.append('<section class="card"><h2>저장된 분석</h2>')
        if not analyses:
            parts.append('<p class="muted">저장된 분석이 없습니다.</p>')
        for analysis in analyses:
            parts.append(f'<div class="item"><a href="/analyses/{analysis["analysis_id"]}">분석 #{analysis["analysis_id"]}</a>'
                         f' <span class="tag">{e(RUN_STATUS_NAMES.get(analysis["status"], analysis["status"]))}</span>'
                         f'사람 검토: {e(REVIEW_NAMES[analysis["review_status"]])}'
                         f'<br><small>{e(analysis["created_at"])}</small></div>')
        parts.append('</section>')
        self._send(200, layout(f"공고 #{job_id}", "".join(parts), refresh=refresh))

    def _analysis(self, analysis_id, notice):
        with storage.connect(self.server.db_path) as conn:
            try:
                analysis = app.get_analysis(conn, analysis_id)
            except ValueError:
                self._error(404, f"분석 {analysis_id}를 찾을 수 없습니다")
                return
            parts = [f'<p><a href="/jobs/{analysis["job_id"]}">← 공고 #{analysis["job_id"]}</a></p>'
                     f'<h1>저장된 분석 #{analysis_id}</h1>'
                     '<div class="warning"><strong>AI 판정은 검토 전 초안입니다.</strong> '
                     '근거가 연결돼도 실제 경력이나 전체 지원 요건 충족이 확정되지는 않습니다. '
                     '<strong>partial은 전체 요건 충족을 뜻하지 않습니다.</strong></div>']
            if notice in NOTICES:
                parts.append(f'<div class="notice">{e(NOTICES[notice])}</div>')
            parts.append('<div class="grid"><section class="card"><h2>모델 실행 결과</h2>'
                         f'<p>실행 상태: <strong>{e(RUN_STATUS_NAMES.get(analysis["status"], analysis["status"]))}</strong> '
                         f'<small>({e(analysis["status"])})</small><br>'
                         f'모델: {e(analysis["run_manifest"].get("model") or "미확인")}<br>'
                         f'JD: {e(analysis["run_manifest"].get("jd_prompt_version") or "미확인")} · '
                         f'매칭: {e(analysis["run_manifest"].get("match_prompt_version") or "미확인")}</p>'
                         f'<small>저장 시각 {e(analysis["created_at"])}</small></section>'
                         '<section class="card"><h2>사람의 검토 기록</h2>'
                         f'<p>현재: <strong>{e(REVIEW_NAMES[analysis["review_status"]])}</strong> · '
                         f'revision {analysis["revision"]}</p>'
                         f'<form method="post" action="/analyses/{analysis_id}/review">{self._token()}'
                         f'<input type="hidden" name="revision" value="{analysis["revision"]}">'
                         '<label for="review_status">검토 상태</label><select id="review_status" name="review_status">')
            for status, label in REVIEW_NAMES.items():
                selected = ' selected' if analysis["review_status"] == status else ''
                parts.append(f'<option value="{e(status)}"{selected}>{e(label)}</option>')
            parts.append('</select><button type="submit">사람 검토 저장</button></form>'
                         '<p class="muted">이 상태는 모델 판정과 별개이며 지원 상태도 바꾸지 않습니다.</p></section></div>')
            extracted = analysis["input_snapshot"].get("extracted")
            if extracted:
                parts.append('<section class="card"><h2>공고에서 추출한 정보 · AI 초안</h2>'
                             f'<p>회사: {e(source_quote(extracted.get("company")))} · '
                             f'직무: {e(source_quote(extracted.get("position")))}</p>'
                             f'<p>마감 원문: {e(source_quote(extracted.get("deadline_raw")))}</p>'
                             '<p class="muted">아래 요구 문구와 함께 공고 원문에 대조해 주세요.</p></section>')
            if analysis["previous_version_ids"]:
                parts.append('<div class="warning">분석 당시 문서 버전 중 현재 비활성화된 버전: '
                             + e(", ".join(map(str, analysis["previous_version_ids"]))) + '</div>')
            if analysis["run_manifest"].get("match_prompt_version") in {"match-v1", "match-v2"}:
                parts.append('<div class="warning">이전 매칭 결과에는 모델이 자유롭게 작성한 해석 문장이 포함될 수 있습니다.</div>')
            elif analysis["run_manifest"].get("match_prompt_version") != "match-v5":
                parts.append('<div class="warning">현재 제품과 다른 매칭 버전으로 저장된 분석입니다.</div>')
            parts.append('<section class="card"><h2>요구사항과 근거</h2>')
            rows = analysis["result"].get("requirements", [])
            if not rows:
                parts.append('<p class="muted">표시할 요구사항 판정이 없습니다. 아래 단계 오류를 확인하세요.</p>')
            for row in rows:
                label = ASSESSMENT_NAMES.get(row.get("assessment"), "판정 실패 또는 미확인")
                parts.append('<div class="item">'
                             f'<h2>{e(row.get("requirement_id", "?"))} · {e(row.get("requirement_quote", ""))}</h2>'
                             f'<p><span class="tag">{e(row.get("kind", ""))}</span><strong>{e(label)}</strong></p>')
                if row.get("reason"):
                    parts.append(f'<p>{e(row["reason"])}</p>')
                if row.get("missing_conditions"):
                    parts.append(f'<p class="warning">미확인 요구 범위: {e(row["missing_conditions"])}</p>')
                if row.get("error"):
                    parts.append(f'<p class="error">이 요구의 처리 오류: {e(row["error"])}</p>')
                selected = row.get("evidence") or []
                if selected:
                    parts.append('<h3>모델이 선택한 근거</h3>')
                for source in selected:
                    parts.append(self._source(source, selected=True))
                selected_ids = {source["evidence_id"] for source in selected}
                candidates = row.get("candidates")
                if candidates is None:
                    candidates = []
                    for evidence_id in row.get("candidate_ids", []):
                        source = app.get_evidence(conn, evidence_id)
                        candidates.append({"evidence_id": source["evidence_id"],
                                           "document_id": source["document_id"],
                                           "version_id": source["version_id"], "title": source["title"],
                                           "section": source["section"], "start": source["span_start"],
                                           "end": source["span_end"], "text": source["text"]})
                remaining = [source for source in candidates if source["evidence_id"] not in selected_ids]
                if remaining:
                    parts.append('<h3>모델이 선택하지 않은 검색 후보</h3>'
                                 '<p class="muted">검색 후보일 뿐 자격 충족 판정은 아닙니다. 충돌·누락을 직접 확인하세요.</p>')
                for source in remaining:
                    parts.append(self._source(source, selected=False))
                parts.append('</div>')
            parts.append('</section>')
            if analysis["result"].get("errors"):
                parts.append('<section class="card"><h2>단계 오류</h2>')
                for error in analysis["result"]["errors"]:
                    parts.append(f'<p class="error">{e(error.get("stage", "?"))}: '
                                 f'{e(error.get("type", "?"))} · {e(error.get("message", ""))}</p>')
                parts.append('</section>')
        self._send(200, layout(f"분석 #{analysis_id}", "".join(parts)))

    @staticmethod
    def _source(source, *, selected):
        css = "evidence" if selected else "evidence candidate"
        return (f'<div class="{css}"><small>근거 #{e(source["evidence_id"])} · '
                f'문서 #{e(source["document_id"])} {e(source["title"])} · '
                f'버전 #{e(source["version_id"])} · {e(source["section"])} '
                f'[{e(source["start"])}:{e(source["end"])}]</small>'
                f'<pre>{e(source["text"])}</pre></div>')


def main(argv=None):
    parser = argparse.ArgumentParser(description="127.0.0.1 전용 로컬 공고 관리 화면")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="분석 버튼의 기본 설치 모델")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port는 1~65535여야 합니다")
    server = WebServer(args.db, args.port, args.model)
    address = f"http://127.0.0.1:{server.server_port}/"
    print(f"로컬 화면: {address}", flush=True)
    print("종료: 이 터미널에서 Ctrl+C", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("로컬 화면을 종료합니다", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
