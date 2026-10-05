"""User operations shared by the CLI and tests."""

import json
from pathlib import Path
from platform import python_version
from time import monotonic
from uuid import uuid4
from . import __version__
from .domain import check_status, content_hash, deadline_fields, required_text
from . import documents, jd, llm, match, retrieval, storage


def register(conn, raw_text, source_url=None, deadline_raw=None, deadline_date=None,
             rolling=False, new_round=False):
    required_text(raw_text, "공고 원문")
    source_url = source_url.strip() or None if source_url else None
    deadline_raw, deadline_date, precision = deadline_fields(deadline_raw, deadline_date, rolling)
    job_id, created = storage.add_job(conn, raw_text, content_hash(raw_text), source_url,
                                      deadline_raw, deadline_date, precision, new_round)
    return storage.get_job(conn, job_id), created


def change_application(conn, job_id, revision, status=None, notes=None):
    if status is None and notes is None:
        raise ValueError("변경할 상태 또는 메모를 지정해 주세요")
    if status is not None:
        check_status(status)
    return storage.update_application(conn, job_id, revision, status, notes)


def import_document(conn, path: Path, title=None, replace_document_id=None, verified=False):
    if not verified:
        raise ValueError("문서를 직접 검토했다면 --verified를 지정해 주세요")
    raw_text = documents.read_document(path)
    spans = documents.split_spans(raw_text)
    if not spans:
        raise ValueError("검색할 본문 문단이 없습니다")
    if replace_document_id is not None and title is None:
        title = storage.get_document_title(conn, replace_document_id)
        if title is None:
            raise ValueError(f"문서 {replace_document_id}를 찾을 수 없습니다")
    title = required_text(title or Path(path).stem, "문서 제목")
    return storage.add_document_version(conn, title, raw_text, documents.sha256(raw_text),
                                        spans, replace_document_id)


def search_evidence(conn, query, limit=5, version_id=None, alias_values=None):
    if version_id is not None and storage.get_version(conn, version_id) is None:
        raise ValueError(f"버전 {version_id}을 찾을 수 없습니다")
    aliases = retrieval.parse_aliases(alias_values or [])
    matches = retrieval.rank(query, storage.search_spans(conn, version_id), limit, aliases)
    for match in matches:
        get_evidence(conn, match["row"]["evidence_id"])
    return matches


def get_evidence(conn, evidence_id):
    row = storage.get_evidence(conn, evidence_id)
    if row is None:
        raise ValueError(f"근거 {evidence_id}를 찾을 수 없습니다")
    if row["raw_text"][row["span_start"]:row["span_end"]] != row["text"]:
        raise ValueError("저장된 근거 구간과 원문이 일치하지 않습니다")
    return row


def _complete(client, messages, schema, deadline=None):
    if deadline is not None and monotonic() >= deadline:
        raise llm.WorkflowTimeout("M1 작업 전체 300초 제한을 넘었습니다")
    original_timeout = getattr(client, "timeout", None)
    if deadline is not None and original_timeout is not None:
        client.timeout = max(1, min(original_timeout, int(deadline - monotonic()) + 1))
    try:
        response = client.complete(messages, schema)
    finally:
        if original_timeout is not None:
            client.timeout = original_timeout
    if deadline is not None and monotonic() >= deadline:
        raise llm.WorkflowTimeout("M1 작업 전체 300초 제한을 넘었습니다")
    return response


def analyze_job(conn, job_id, client, deadline=None):
    """Return an unreviewed draft; never write or change the application record."""
    row = storage.get_job(conn, job_id)
    if row is None:
        raise ValueError(f"공고 {job_id}를 찾을 수 없습니다")
    raw_text = row["raw_text"]
    if len(raw_text) > jd.MAX_JD_CHARS:
        raise ValueError(f"공고 원문이 {jd.MAX_JD_CHARS}자를 넘습니다. 조용히 자르지 않습니다")
    errors = []
    for attempt in range(2):
        response = _complete(client, jd.messages(raw_text, retry=attempt > 0,
                                                  previous_error=errors[-1] if errors else None),
                             jd.SCHEMA, deadline)
        try:
            if type(response) is not dict or type(response.get("content")) is not str:
                raise jd.InvalidExtraction("모델 응답 본문 형식이 맞지 않습니다")
            extracted = jd.validate(raw_text, response["content"])
            return {
                "job_id": job_id,
                "review_status": "unreviewed",
                "prompt_version": jd.PROMPT_VERSION,
                "attempts": attempt + 1,
                "extracted": extracted,
                "run": {key: value for key, value in response.items() if key != "content"},
            }
        except jd.InvalidExtraction as exc:
            errors.append(str(exc))
    raise jd.InvalidExtraction("2회 출력 검증 실패: " + "; ".join(errors))


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _candidate_snapshot(conn, ranked):
    candidates = []
    for hit in ranked:
        evidence = get_evidence(conn, hit["row"]["evidence_id"])
        candidates.append({"evidence_id": evidence["evidence_id"],
                           "version_id": evidence["version_id"],
                           "document_id": evidence["document_id"],
                           "title": evidence["title"],
                           "section": evidence["section"],
                           "start": evidence["span_start"], "end": evidence["span_end"],
                           "text": evidence["text"], "score": hit["score"]})
    return candidates


def _pack_batches(items):
    batches = []
    current = []
    for item in items:
        if current and (len(current) >= match.MAX_BATCH_REQUIREMENTS
                        or len(_json({"items": [*current, item]})) > match.MAX_BATCH_CHARS):
            batches.append(current)
            current = []
        current.append(item)
    if current:
        batches.append(current)
    return batches


def run_workflow(conn, job_id, client, top_k=5, alias_values=None):
    """Fixed M1 flow. Save a reviewable result without changing application state."""
    deadline = monotonic() + 300
    if not 1 <= top_k <= 5:
        raise ValueError("M1 검색 상한은 1~5여야 합니다")
    job = storage.get_job(conn, job_id)
    if job is None:
        raise ValueError(f"공고 {job_id}를 찾을 수 없습니다")
    aliases = retrieval.parse_aliases(alias_values or [])
    source_versions = [row["version_id"] for row in storage.list_documents(conn)]
    source_spans = [span for version_id in source_versions
                    for span in storage.search_spans(conn, version_id)]
    snapshot = {"raw_text": job["raw_text"], "content_hash": job["content_hash"],
                "source_url": job["source_url"], "captured_at": job["captured_at"]}
    manifest = {"model": getattr(client, "model", None),
                "app_version": __version__, "python_version": python_version(),
                "jd_prompt_version": jd.PROMPT_VERSION,
                "jd_prompt": jd.SYSTEM_PROMPT,
                "match_prompt_version": match.PROMPT_VERSION,
                "match_prompt": match.SYSTEM_PROMPT,
                "source_version_ids": source_versions,
                "top_k": top_k, "aliases": alias_values or [],
                "candidate_order": {}, "llm_calls": 0}
    run_id = str(uuid4())

    try:
        extraction = analyze_job(conn, job_id, client, deadline)
    except (jd.InvalidExtraction, llm.LocalModelError, ValueError, KeyboardInterrupt) as exc:
        manifest["llm_calls"] = None  # extraction attempts are unavailable on this failure path
        status = ("cancelled" if isinstance(exc, KeyboardInterrupt) else
                  "timed_out" if isinstance(exc, llm.ModelTimeout) else "failed")
        result = {"requirements": [], "errors": [{"stage": "extract", "type": type(exc).__name__,
                                                   "message": str(exc) or "사용자가 중단했습니다"}]}
        analysis_id = storage.save_analysis(conn, run_id, job_id, status, _json(snapshot),
                                            _json(result), _json(source_versions), _json(manifest))
        return get_analysis(conn, analysis_id)

    snapshot["extracted"] = extraction["extracted"]
    manifest["llm_calls"] = extraction["attempts"]
    manifest["extraction_run"] = extraction["run"]
    recovery_remaining = 2 - extraction["attempts"]
    rows = []
    ready = []
    errors = []
    full_candidates = {}
    if not extraction["extracted"]["requirements"]:
        errors.append({"stage": "extract", "type": "no_requirements_extracted"})
    try:
        for index, requirement in enumerate(extraction["extracted"]["requirements"], 1):
            if monotonic() >= deadline:
                raise llm.WorkflowTimeout("M1 작업 전체 300초 제한을 넘었습니다")
            requirement_id = f"r{index}"
            ranked = retrieval.rank(requirement["quote"], source_spans, top_k, aliases)
            candidates = _candidate_snapshot(conn, ranked)
            if monotonic() >= deadline:
                raise llm.WorkflowTimeout("M1 작업 전체 300초 제한을 넘었습니다")
            full_candidates[requirement_id] = {candidate["evidence_id"]: candidate
                                               for candidate in candidates}
            manifest["candidate_order"][requirement_id] = [
                {"evidence_id": candidate["evidence_id"], "version_id": candidate["version_id"],
                 "score": candidate["score"]} for candidate in candidates]
            row = {"requirement_id": requirement_id, "kind": requirement["kind"],
                   "requirement_quote": requirement["quote"],
                   "requirement_start": requirement["start"], "requirement_end": requirement["end"],
                   "candidate_ids": [candidate["evidence_id"] for candidate in candidates],
                   "candidates": candidates,
                   "assessment": None, "evidence": [], "reason": None,
                   "missing_conditions": None, "review_status": "pending", "error": None}
            rows.append(row)
            if not candidates:
                row["assessment"] = "evidence_not_found"
                row["reason"] = "현재 활성 문서 범위에서 검색 후보를 찾지 못했습니다."
                continue
            item = {"requirement_id": requirement_id, "kind": requirement["kind"],
                    "requirement_quote": requirement["quote"],
                    "candidates": [{key: candidate[key] for key in
                                    ("evidence_id", "version_id", "title", "text")}
                                   for candidate in candidates]}
            if len(_json({"items": [item]})) > match.MAX_BATCH_CHARS:
                row["error"] = "context_limit"
                errors.append({"stage": "retrieve", "requirement_id": requirement_id,
                               "type": "context_limit"})
                continue
            ready.append(item)
        if monotonic() >= deadline:
            raise llm.WorkflowTimeout("M1 작업 전체 300초 제한을 넘었습니다")
    except (llm.WorkflowTimeout, KeyboardInterrupt) as exc:
        status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "timed_out"
        errors.append({"stage": "retrieve", "type": type(exc).__name__,
                       "message": str(exc) or "사용자가 중단했습니다"})
        analysis_id = storage.save_analysis(conn, run_id, job_id, status, _json(snapshot),
                                            _json({"requirements": rows, "errors": errors}),
                                            _json(source_versions), _json(manifest))
        return get_analysis(conn, analysis_id)

    row_by_id = {row["requirement_id"]: row for row in rows}
    batches = _pack_batches(ready)
    terminal_status = None
    for batch_index, batch in enumerate(batches):
        if manifest["llm_calls"] >= 8:
            remaining = [item for group in batches[batch_index:] for item in group]
            for item in remaining:
                row_by_id[item["requirement_id"]]["error"] = "call_budget_exhausted"
                errors.append({"stage": "match", "requirement_id": item["requirement_id"],
                               "type": "call_budget_exhausted"})
            break
        try:
            manifest["llm_calls"] += 1
            response = _complete(client, match.messages(batch), match.SCHEMA, deadline)
            manifest.setdefault("match_runs", []).append({key: value for key, value in response.items()
                                                           if key != "content"})
            try:
                proposals = match.validate(response["content"], batch)
            except (KeyError, TypeError, match.InvalidMatch) as exc:
                if recovery_remaining <= 0 or manifest["llm_calls"] >= 8:
                    raise match.InvalidMatch("매칭 출력 검증 실패") from exc
                recovery_remaining -= 1
                manifest["llm_calls"] += 1
                response = _complete(client, match.messages(batch, retry=True), match.SCHEMA, deadline)
                manifest.setdefault("match_runs", []).append({key: value for key, value in response.items()
                                                               if key != "content"})
                proposals = match.validate(response["content"], batch)
            for item in batch:
                row = row_by_id[item["requirement_id"]]
                proposal = proposals[item["requirement_id"]]
                row["assessment"] = proposal["assessment"]
                row["reason"] = match.SAFE_REASONS[proposal["assessment"]]
                row["missing_conditions"] = (
                    row["requirement_quote"] if proposal["assessment"] in
                    {"partial", "insufficient_evidence"} else None)
                row["evidence"] = [full_candidates[item["requirement_id"]][evidence_id]
                                   for evidence_id in proposal["evidence_ids"]]
        except (llm.LocalModelError, match.InvalidMatch, KeyError, TypeError, KeyboardInterrupt) as exc:
            for item in batch:
                row_by_id[item["requirement_id"]]["error"] = type(exc).__name__
                errors.append({"stage": "match", "requirement_id": item["requirement_id"],
                               "type": type(exc).__name__})
            if isinstance(exc, (llm.ModelTimeout, KeyboardInterrupt)):
                terminal_status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "timed_out"
            if isinstance(exc, (llm.LocalModelError, KeyboardInterrupt)):
                for later in batches[batch_index + 1:]:
                    for item in later:
                        row_by_id[item["requirement_id"]]["error"] = terminal_status or "model_unavailable"
                        errors.append({"stage": "match", "requirement_id": item["requirement_id"],
                                       "type": terminal_status or "model_unavailable"})
                break

    status = terminal_status or ("partial" if errors else
                                "no_evidence" if rows and all(
                                    row["assessment"] == "evidence_not_found" for row in rows)
                                else "review_ready")
    result = {"requirements": rows, "errors": errors}
    analysis_id = storage.save_analysis(conn, run_id, job_id, status, _json(snapshot),
                                        _json(result), _json(source_versions), _json(manifest))
    return get_analysis(conn, analysis_id)


def get_analysis(conn, analysis_id):
    row = storage.get_analysis(conn, analysis_id)
    if row is None:
        raise ValueError(f"분석 {analysis_id}를 찾을 수 없습니다")
    snapshot = json.loads(row["input_snapshot"])
    result = json.loads(row["result_json"])
    versions = json.loads(row["source_version_ids"])
    manifest = json.loads(row["run_manifest"])
    active_versions = {item["version_id"] for item in storage.list_documents(conn)}
    return {"analysis_id": row["analysis_id"], "run_id": row["run_id"],
            "job_id": row["job_id"], "status": row["status"],
            "review_status": row["review_status"], "revision": row["revision"],
            "created_at": row["created_at"], "input_snapshot": snapshot,
            "result": result, "source_version_ids": versions,
            "previous_version_ids": [version for version in versions if version not in active_versions],
            "run_manifest": manifest}


def review_analysis(conn, analysis_id, revision, review_status):
    if review_status not in {"reviewed", "needs_changes", "pending"}:
        raise ValueError("검토 상태는 pending, reviewed, needs_changes 중 하나여야 합니다")
    storage.review_analysis(conn, analysis_id, revision, review_status)
    return get_analysis(conn, analysis_id)
