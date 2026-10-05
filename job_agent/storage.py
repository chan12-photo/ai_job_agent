"""SQLite schema and explicit, atomic data operations."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import sqlite3


class RevisionConflict(Exception):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def atomic(conn):
    """Allow existing job creation to participate in an image-registration transaction."""
    if conn.in_transaction:
        name = "nested_" + os.urandom(8).hex()
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield
            conn.execute(f"RELEASE SAVEPOINT {name}")
        except BaseException:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            conn.execute(f"RELEASE SAVEPOINT {name}")
            raise
    else:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            yield


@contextmanager
def connect(path: Path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS job_postings (
                job_id INTEGER PRIMARY KEY,
                raw_text TEXT NOT NULL CHECK(length(trim(raw_text)) > 0),
                content_hash TEXT NOT NULL,
                dedupe_key TEXT UNIQUE,
                source_url TEXT,
                captured_at TEXT NOT NULL,
                deadline_raw TEXT,
                deadline_date TEXT,
                deadline_precision TEXT NOT NULL CHECK(deadline_precision IN ('unknown', 'rolling', 'date_only')),
                CHECK ((deadline_precision = 'date_only') = (deadline_date IS NOT NULL))
            );
            CREATE INDEX IF NOT EXISTS idx_job_hash ON job_postings(content_hash);
            CREATE INDEX IF NOT EXISTS idx_job_deadline ON job_postings(deadline_date);
            CREATE TABLE IF NOT EXISTS applications (
                job_id INTEGER PRIMARY KEY REFERENCES job_postings(job_id),
                status TEXT NOT NULL CHECK(status IN ('planned','preparing','submitted','interview','offer','rejected','withdrawn')),
                notes TEXT NOT NULL DEFAULT '',
                submitted_at TEXT,
                updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_versions (
                version_id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(document_id),
                title TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                supersedes_id INTEGER REFERENCES document_versions(version_id),
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                user_verified INTEGER NOT NULL CHECK(user_verified = 1)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_version
                ON document_versions(document_id) WHERE active = 1;
            CREATE TABLE IF NOT EXISTS evidence_spans (
                evidence_id INTEGER PRIMARY KEY,
                version_id INTEGER NOT NULL REFERENCES document_versions(version_id),
                section TEXT NOT NULL,
                span_start INTEGER NOT NULL CHECK(span_start >= 0),
                span_end INTEGER NOT NULL CHECK(span_end > span_start),
                text TEXT NOT NULL,
                UNIQUE(version_id, span_start, span_end)
            );
            CREATE INDEX IF NOT EXISTS idx_spans_version ON evidence_spans(version_id);
            CREATE TABLE IF NOT EXISTS analysis_results (
                analysis_id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                job_id INTEGER NOT NULL REFERENCES job_postings(job_id),
                status TEXT NOT NULL CHECK(status IN ('review_ready','partial','no_evidence','failed','timed_out','cancelled')),
                input_snapshot TEXT NOT NULL,
                result_json TEXT NOT NULL,
                source_version_ids TEXT NOT NULL,
                run_manifest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(review_status IN ('pending','reviewed','needs_changes')),
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_analysis_job ON analysis_results(job_id, analysis_id);
            CREATE TABLE IF NOT EXISTS job_images (
                image_id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES job_postings(job_id),
                draft_id TEXT NOT NULL,
                page_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL CHECK(mime_type IN ('image/png', 'image/jpeg')),
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL CHECK(byte_size > 0),
                pixel_width INTEGER NOT NULL CHECK(pixel_width > 0),
                pixel_height INTEGER NOT NULL CHECK(pixel_height > 0),
                confirmed_text TEXT NOT NULL,
                display_order INTEGER NOT NULL CHECK(display_order >= 0),
                created_at TEXT NOT NULL,
                UNIQUE(job_id, draft_id, page_id),
                UNIQUE(file_name)
            );
            CREATE INDEX IF NOT EXISTS idx_job_images_order ON job_images(job_id, display_order, image_id);
        """)
        _migrate_analysis_statuses(conn)
        yield conn
    finally:
        conn.close()


def _migrate_analysis_statuses(conn):
    """Preserve earlier M1 rows while adding explicit terminal outcomes."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'analysis_results'").fetchone()[0]
    if "'timed_out'" in sql and "'cancelled'" in sql:
        return
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'analysis_results'").fetchone()[0]
        if "'timed_out'" in sql and "'cancelled'" in sql:
            return
        conn.execute("""
            CREATE TABLE analysis_results_new (
                analysis_id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                job_id INTEGER NOT NULL REFERENCES job_postings(job_id),
                status TEXT NOT NULL CHECK(status IN
                    ('review_ready','partial','no_evidence','failed','timed_out','cancelled')),
                input_snapshot TEXT NOT NULL,
                result_json TEXT NOT NULL,
                source_version_ids TEXT NOT NULL,
                run_manifest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(review_status IN ('pending','reviewed','needs_changes')),
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
            )
        """)
        conn.execute("""
            INSERT INTO analysis_results_new
                (analysis_id, run_id, job_id, status, input_snapshot, result_json,
                 source_version_ids, run_manifest, created_at, review_status, revision)
            SELECT analysis_id, run_id, job_id, status, input_snapshot, result_json,
                   source_version_ids, run_manifest, created_at, review_status, revision
            FROM analysis_results
        """)
        conn.execute("DROP TABLE analysis_results")
        conn.execute("ALTER TABLE analysis_results_new RENAME TO analysis_results")
        conn.execute("CREATE INDEX idx_analysis_job ON analysis_results(job_id, analysis_id)")


def add_job(conn, raw_text, content_hash, source_url, deadline_raw, deadline_date, deadline_precision, new_round=False):
    dedupe_key = None if new_round else hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    with atomic(conn):
        if not new_round:
            existing = conn.execute(
                "SELECT job_id FROM job_postings WHERE raw_text = ? ORDER BY job_id LIMIT 1",
                (raw_text,),
            ).fetchone()
            if existing:
                return existing["job_id"], False
        timestamp = now_utc()
        cur = conn.execute("""
            INSERT INTO job_postings(raw_text, content_hash, dedupe_key, source_url, captured_at,
                                     deadline_raw, deadline_date, deadline_precision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (raw_text, content_hash, dedupe_key, source_url, timestamp, deadline_raw, deadline_date, deadline_precision))
        job_id = cur.lastrowid
        conn.execute("INSERT INTO applications(job_id, status, updated_at) VALUES (?, 'planned', ?)",
                     (job_id, timestamp))
        return job_id, True


def get_job(conn, job_id):
    return conn.execute("""
        SELECT j.*, a.status, a.notes, a.submitted_at, a.updated_at, a.revision
        FROM job_postings j JOIN applications a USING(job_id) WHERE j.job_id = ?
    """, (job_id,)).fetchone()


def add_job_images(conn, job_id, draft_id, images):
    """Link already copied local originals in one SQLite transaction."""
    with atomic(conn):
        if get_job(conn, job_id) is None:
            raise ValueError(f"공고 {job_id}를 찾을 수 없습니다")
        start = conn.execute("SELECT coalesce(max(display_order), -1) + 1 FROM job_images WHERE job_id = ?",
                             (job_id,)).fetchone()[0]
        conn.executemany("""
            INSERT INTO job_images
                (job_id, draft_id, page_id, file_name, mime_type, sha256, byte_size,
                 pixel_width, pixel_height, confirmed_text, display_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, draft_id, page_id) DO NOTHING
        """, [(job_id, draft_id, page["id"], page["stored_name"], page["mime"],
               page["sha256"], page["size"], page["width"], page["height"],
               page.get("ocr_text") or "", start + index, now_utc())
              for index, page in enumerate(images)])


def list_job_images(conn, job_id):
    return conn.execute("""
        SELECT * FROM job_images WHERE job_id = ? ORDER BY display_order, image_id
    """, (job_id,)).fetchall()


def get_job_image(conn, job_id, image_id):
    return conn.execute("""
        SELECT * FROM job_images WHERE job_id = ? AND image_id = ?
    """, (job_id, image_id)).fetchone()


def list_jobs(conn, status=None):
    return conn.execute("""
        SELECT j.*, a.status, a.notes, a.submitted_at, a.updated_at, a.revision
        FROM job_postings j JOIN applications a USING(job_id)
        WHERE (? IS NULL OR a.status = ?)
        ORDER BY CASE WHEN j.deadline_date IS NULL THEN 1 ELSE 0 END,
                 j.deadline_date, j.job_id
    """, (status, status)).fetchall()


def update_application(conn, job_id, revision, status=None, notes=None):
    with conn:
        current = get_job(conn, job_id)
        if current is None:
            raise ValueError(f"공고 {job_id}를 찾을 수 없습니다")
        if current["revision"] != revision:
            raise RevisionConflict(f"수정 충돌: 현재 revision은 {current['revision']}입니다")
        next_status = status if status is not None else current["status"]
        next_notes = notes if notes is not None else current["notes"]
        if (next_status, next_notes) == (current["status"], current["notes"]):
            return current, False
        timestamp = now_utc()
        submitted_at = current["submitted_at"]
        # A transition to submitted is not evidence of the submission date.
        result = conn.execute("""
            UPDATE applications SET status = ?, notes = ?, submitted_at = ?,
                                    updated_at = ?, revision = revision + 1
            WHERE job_id = ? AND revision = ?
        """, (next_status, next_notes, submitted_at, timestamp, job_id, revision))
        if result.rowcount != 1:
            raise RevisionConflict("동시 수정이 감지되었습니다. 다시 조회해 주세요")
        return get_job(conn, job_id), True


def backup(conn, destination: Path):
    destination = Path(destination).expanduser()
    if destination.exists():
        raise ValueError("백업 대상 파일이 이미 존재합니다")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(destination)) as target:
            with target:
                conn.backup(target)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def add_document_version(conn, title, raw_text, content_hash, spans, replace_document_id=None):
    """Create a reviewed snapshot; replacement and span writes commit together."""
    with conn:
        timestamp = now_utc()
        if replace_document_id is None:
            document_id = conn.execute(
                "INSERT INTO documents(title, created_at) VALUES (?, ?)",
                (title, timestamp),
            ).lastrowid
            supersedes_id = None
        else:
            document_id = replace_document_id
            found = conn.execute("SELECT document_id FROM documents WHERE document_id = ?",
                                 (document_id,)).fetchone()
            if found is None:
                raise ValueError(f"문서 {document_id}를 찾을 수 없습니다")
            active = conn.execute("""
                SELECT version_id, title, content_hash, raw_text FROM document_versions
                WHERE document_id = ? AND active = 1
            """, (document_id,)).fetchone()
            if (active and active["title"] == title and active["content_hash"] == content_hash
                    and active["raw_text"] == raw_text):
                return document_id, active["version_id"], False
            supersedes_id = active["version_id"] if active else None
            conn.execute("UPDATE document_versions SET active = 0 WHERE document_id = ? AND active = 1",
                         (document_id,))
            conn.execute("UPDATE documents SET title = ? WHERE document_id = ?", (title, document_id))
        version_id = conn.execute("""
            INSERT INTO document_versions(document_id, title, content_hash, raw_text, imported_at,
                                          supersedes_id, active, user_verified)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1)
        """, (document_id, title, content_hash, raw_text, timestamp, supersedes_id)).lastrowid
        conn.executemany("""
            INSERT INTO evidence_spans(version_id, section, span_start, span_end, text)
            VALUES (?, ?, ?, ?, ?)
        """, [(version_id, section, start, end, text) for section, start, end, text in spans])
        return document_id, version_id, True


def list_documents(conn):
    return conn.execute("""
        SELECT d.document_id, d.title, v.version_id, v.imported_at,
               (SELECT count(*) FROM evidence_spans s WHERE s.version_id = v.version_id) AS span_count
        FROM documents d JOIN document_versions v ON v.document_id = d.document_id AND v.active = 1
        ORDER BY d.document_id
    """).fetchall()


def list_versions(conn, document_id):
    return conn.execute("""
        SELECT version_id, document_id, title, content_hash, imported_at, supersedes_id, active,
               user_verified FROM document_versions WHERE document_id = ? ORDER BY version_id
    """, (document_id,)).fetchall()


def get_document_title(conn, document_id):
    row = conn.execute("SELECT title FROM documents WHERE document_id = ?", (document_id,)).fetchone()
    return row["title"] if row else None


def get_version(conn, version_id):
    return conn.execute("SELECT version_id FROM document_versions WHERE version_id = ?",
                        (version_id,)).fetchone()


def activate_version(conn, version_id):
    with conn:
        target = conn.execute("SELECT document_id, title, active FROM document_versions WHERE version_id = ?",
                              (version_id,)).fetchone()
        if target is None:
            raise ValueError(f"버전 {version_id}을 찾을 수 없습니다")
        if target["active"]:
            return target["document_id"], False
        conn.execute("UPDATE document_versions SET active = 0 WHERE document_id = ? AND active = 1",
                     (target["document_id"],))
        conn.execute("UPDATE document_versions SET active = 1 WHERE version_id = ?", (version_id,))
        conn.execute("UPDATE documents SET title = ? WHERE document_id = ?",
                     (target["title"], target["document_id"]))
        return target["document_id"], True


def get_evidence(conn, evidence_id):
    return conn.execute("""
        SELECT s.*, v.document_id, v.active, v.raw_text, v.title
        FROM evidence_spans s JOIN document_versions v USING(version_id)
        WHERE s.evidence_id = ?
    """, (evidence_id,)).fetchone()


def search_spans(conn, version_id=None):
    return conn.execute("""
        SELECT s.*, v.document_id, v.active, v.title
        FROM evidence_spans s JOIN document_versions v USING(version_id)
        WHERE (? IS NULL AND v.active = 1) OR (? IS NOT NULL AND v.version_id = ?)
        ORDER BY s.evidence_id
    """, (version_id, version_id, version_id)).fetchall()


def save_analysis(conn, run_id, job_id, status, input_snapshot, result_json,
                  source_version_ids, run_manifest):
    with conn:
        return conn.execute("""
            INSERT INTO analysis_results(run_id, job_id, status, input_snapshot, result_json,
                                         source_version_ids, run_manifest, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, job_id, status, input_snapshot, result_json,
              source_version_ids, run_manifest, now_utc())).lastrowid


def get_analysis(conn, analysis_id):
    return conn.execute("SELECT * FROM analysis_results WHERE analysis_id = ?",
                        (analysis_id,)).fetchone()


def list_analyses(conn, job_id=None):
    return conn.execute("""
        SELECT analysis_id, run_id, job_id, status, created_at, review_status, revision
        FROM analysis_results WHERE (? IS NULL OR job_id = ?)
        ORDER BY analysis_id DESC
    """, (job_id, job_id)).fetchall()


def review_analysis(conn, analysis_id, revision, review_status):
    with conn:
        row = get_analysis(conn, analysis_id)
        if row is None:
            raise ValueError(f"분석 {analysis_id}를 찾을 수 없습니다")
        if row["revision"] != revision:
            raise RevisionConflict(f"검토 상태 충돌: 현재 revision은 {row['revision']}입니다")
        if row["review_status"] == review_status:
            return row, False
        updated = conn.execute("""
            UPDATE analysis_results SET review_status = ?, revision = revision + 1
            WHERE analysis_id = ? AND revision = ?
        """, (review_status, analysis_id, revision))
        if updated.rowcount != 1:
            raise RevisionConflict("동시 수정이 감지되었습니다. 다시 조회해 주세요")
        return get_analysis(conn, analysis_id), True
