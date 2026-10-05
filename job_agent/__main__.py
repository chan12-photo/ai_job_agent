"""Command line interface for local job tracking and document search."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

from . import app, llm, match, readonly_agent, replay, storage
from .domain import STATUSES


DEFAULT_DB = Path.home() / "Library" / "Application Support" / "AIJobAgent" / "jobs.sqlite3"


def log_event(db_path, command, outcome, job_id=None, error_type=None):
    """Keep only operational metadata; never store posting text or notes here."""
    path = Path(db_path).expanduser().parent / "events.jsonl"
    event = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "command": command, "outcome": outcome}
    if job_id is not None:
        event["job_id"] = job_id
    if error_type:
        event["error_type"] = error_type
    try:
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        print("경고: 로컬 실행 로그를 기록하지 못했습니다", file=sys.stderr)


def parser():
    p = argparse.ArgumentParser(description="로컬 채용공고 관리·근거 연결 초안 (Phase 4 M1)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 파일 경로")
    commands = p.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="공고 원문 등록")
    source = add.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="공고 원문")
    source.add_argument("--file", type=Path, help="UTF-8 원문 파일")
    add.add_argument("--source-url")
    add.add_argument("--deadline-raw", help="공고에 적힌 마감 표현")
    deadline = add.add_mutually_exclusive_group()
    deadline.add_argument("--deadline-date", help="사용자가 확인한 YYYY-MM-DD 날짜")
    deadline.add_argument("--rolling", action="store_true", help="채용 시 마감")
    add.add_argument("--new-round", action="store_true", help="동일 원문의 별도 모집 회차로 저장")

    show = commands.add_parser("show", help="공고와 지원 기록 조회")
    show.add_argument("job_id", type=int)
    listing = commands.add_parser("list", help="확인된 마감 날짜순 조회")
    listing.add_argument("--status", choices=STATUSES)
    update = commands.add_parser("update", help="지원 상태와 메모 수정")
    update.add_argument("job_id", type=int)
    update.add_argument("--revision", type=int, required=True, help="show/list에 표시된 현재 revision")
    update.add_argument("--status", choices=STATUSES)
    update.add_argument("--notes", help="빈 문자열을 주면 메모 삭제")
    backup = commands.add_parser("backup", help="일관된 SQLite 스냅샷 저장")
    backup.add_argument("destination", type=Path)

    doc_add = commands.add_parser("doc-add", help="검토한 TXT/MD 문서 버전 등록")
    doc_add.add_argument("--file", type=Path, required=True)
    doc_add.add_argument("--title")
    doc_add.add_argument("--replace", type=int, metavar="DOCUMENT_ID",
                         help="이 문서의 새 버전으로 등록하고 활성 버전 교체")
    doc_add.add_argument("--verified", action="store_true", help="사용자가 원문을 직접 검토했음")
    commands.add_parser("doc-list", help="문서와 활성 버전 조회")
    versions = commands.add_parser("doc-versions", help="문서의 모든 버전 조회")
    versions.add_argument("document_id", type=int)
    activate = commands.add_parser("doc-activate", help="지정 버전을 활성화")
    activate.add_argument("version_id", type=int)
    search = commands.add_parser("search", help="활성 문서 근거 검색")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--version", type=int, help="이전 버전을 명시적으로 검색")
    search.add_argument("--alias", action="append", default=[], metavar="질의어=문서표현",
                        help="이번 검색에만 적용할 수동 동의어")
    evidence = commands.add_parser("evidence", help="원문 근거 구간 조회")
    evidence.add_argument("evidence_id", type=int)
    commands.add_parser("model-list", help="로컬 Ollama에 설치된 모델 조회")
    analyze = commands.add_parser("analyze", help="저장된 공고의 JD 추출 초안 (저장하지 않음)")
    analyze.add_argument("job_id", type=int)
    analyze.add_argument("--model", required=True, help="설치된 로컬 모델명을 명시")
    analyze.add_argument("--timeout", type=int, default=120)
    run = commands.add_parser("run", help="JD 추출·근거 연결 초안을 저장")
    run.add_argument("job_id", type=int)
    run.add_argument("--model", required=True, help="이미 설치된 로컬 모델명")
    run.add_argument("--top-k", type=int, default=5, help="요구사항별 근거 후보 수 1~5")
    run.add_argument("--alias", action="append", default=[], metavar="질의어=문서표현")
    run.add_argument("--timeout", type=int, default=120)
    analyses = commands.add_parser("analysis-list", help="저장된 분석 목록")
    analyses.add_argument("--job", type=int)
    detail = commands.add_parser("analysis-show", help="저장된 분석과 근거 조회")
    detail.add_argument("analysis_id", type=int)
    detail.add_argument("--json", action="store_true", help="스냅샷과 실행 기록을 포함한 JSON")
    review = commands.add_parser("analysis-review", help="분석 초안의 수동 검토 상태 변경")
    review.add_argument("analysis_id", type=int)
    review.add_argument("--revision", type=int, required=True)
    review.add_argument("--status", choices=("pending", "reviewed", "needs_changes"), required=True)
    agent = commands.add_parser("agent-read", help="지정 workspace에서 제한된 읽기 전용 로컬 Agent 실행")
    agent.add_argument("--workspace", type=Path, help="읽기 경계를 정하는 폴더 (--replay 사용 시 생략 가능)")
    agent.add_argument("--question", help="workspace 안에서 확인할 자연어 질문 (--replay 사용 시 생략 가능)")
    agent.add_argument("--replay", type=Path, help="기록된 모델 응답을 재생하는 fixture. Ollama를 호출하지 않고 도구와 정책은 실제로 실행")
    agent.add_argument("--model", default=readonly_agent.DEFAULT_MODEL, help="이미 설치된 로컬 Ollama 모델")
    agent.add_argument("--log-dir", type=Path, default=readonly_agent.DEFAULT_LOG_DIR, help="실행 JSON 로그 저장 폴더")
    agent.add_argument("--timeout", type=float, default=readonly_agent.DEFAULT_TOTAL_TIMEOUT_SECONDS, help="전체 실행 제한 초")
    agent.add_argument("--max-model-calls", type=int, default=readonly_agent.DEFAULT_MAX_MODEL_CALLS)
    agent.add_argument("--max-tool-calls", type=int, default=readonly_agent.DEFAULT_MAX_TOOL_CALLS)
    agent.add_argument("--json", action="store_true", help="화면 출력도 JSON으로 표시")
    return p


def print_job(row, detail=False):
    deadline = row["deadline_date"] or row["deadline_raw"] or "미확인"
    if row["deadline_date"]:
        deadline += " (날짜만 확인, 시각 미확인)"
    elif row["deadline_precision"] == "rolling":
        deadline += " (수시 마감)"
    else:
        deadline += " (날짜 미확인)"
    print(f"#{row['job_id']} | 마감 {deadline} | 상태 {row['status']} | revision {row['revision']}")
    if detail:
        print(f"출처: {row['source_url'] or '미입력'}")
        print(f"등록: {row['captured_at']}")
        print(f"지원일: {row['submitted_at'] or '미확인'}")
        print(f"메모: {row['notes']}")
        print("공고 원문:\n" + row["raw_text"])


def print_analysis(result, conn=None):
    print(f"분석 #{result['analysis_id']} | 공고 #{result['job_id']} | {result['status']} | "
          f"검토 {result['review_status']} | revision {result['revision']}")
    print(f"실행 ID {result['run_id']} | 저장 {result['created_at']}")
    manifest = result["run_manifest"]
    print(f"모델 {manifest.get('model') or '미확인'} | JD {manifest.get('jd_prompt_version') or '미확인'} | "
          f"매칭 {manifest.get('match_prompt_version') or '미확인'}")
    if manifest.get("match_prompt_version") in {"match-v1", "match-v2"}:
        print("주의: 이전 매칭 결과에는 모델이 자유롭게 쓴 해석 문장이 포함될 수 있습니다.")
    elif manifest.get("match_prompt_version") != match.PROMPT_VERSION:
        print("주의: 현재 설정과 다른 버전에서 생성된 분석입니다.")
    if result["previous_version_ids"]:
        print("주의: 현재 비활성화된 문서 버전: "
              + ", ".join(map(str, result["previous_version_ids"])))
    print("모델 판정은 검토 전 초안입니다. 근거 원문과 미확인 요구 범위를 직접 확인해 주세요.")
    for row in result["result"]["requirements"]:
        print(f"\n{row['requirement_id']} [{row['kind']}] {row['requirement_quote']}")
        print(f"제안: {row['assessment'] or '판정 실패'} | {row['reason'] or '-'}")
        if row["missing_conditions"]:
            print(f"미확인 요구 범위: {row['missing_conditions']}")
        if row["error"]:
            print(f"오류: {row['error']}")
        for evidence in row["evidence"]:
            print(f"  근거 #{evidence['evidence_id']} | 문서 #{evidence['document_id']} "
                  f"{evidence['title']} | 버전 #{evidence['version_id']} | "
                  f"{evidence['section']} [{evidence['start']}:{evidence['end']}]")
            print("  " + evidence["text"])
        selected_ids = {evidence["evidence_id"] for evidence in row["evidence"]}
        candidates = row.get("candidates")
        if candidates is None and conn is not None:
            candidates = []
            for evidence_id in row.get("candidate_ids", []):
                source = app.get_evidence(conn, evidence_id)
                candidates.append({"evidence_id": source["evidence_id"],
                                   "document_id": source["document_id"],
                                   "title": source["title"], "version_id": source["version_id"],
                                   "section": source["section"],
                                   "start": source["span_start"], "end": source["span_end"],
                                   "text": source["text"]})
        unselected = [candidate for candidate in candidates or []
                      if candidate["evidence_id"] not in selected_ids]
        if unselected:
            print("  모델이 선택하지 않은 검색 후보 (자격 충족 판정 아님):")
        for candidate in unselected:
            print(f"  후보 #{candidate['evidence_id']} | 문서 #{candidate['document_id']} "
                  f"{candidate['title']} | 버전 #{candidate['version_id']} | "
                  f"{candidate['section']} [{candidate['start']}:{candidate['end']}]")
            print("  " + candidate["text"])
    for error in result["result"]["errors"]:
        print(f"단계 오류: {error['stage']} | {error['type']}")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "model-list":
            models = llm.OllamaClient("unused", timeout=5).local_models()
            if not models:
                print("로컬 설치 모델이 없습니다")
            for model in models:
                print(f"{model.get('name')} | {model.get('size')} bytes | "
                      f"digest {model.get('digest')} | {model.get('details', {}).get('quantization_level')}")
            return 0
        if args.command == "agent-read":
            client = None
            workspace, question, model = args.workspace, args.question, args.model
            if args.replay:
                fixture = replay.load_replay(args.replay)
                if question is not None and question != fixture["question"]:
                    raise ValueError("--question differs from the replay fixture question")
                workspace = workspace or replay.replay_workspace(fixture)
                question = fixture["question"]
                client = replay.ReplayClient(fixture)
                model = client.model
            elif workspace is None or question is None:
                raise ValueError("agent-read requires --workspace and --question unless --replay is given")
            result = readonly_agent.run_question(
                workspace_path=workspace,
                question=question,
                model=model,
                client=client,
                log_dir=args.log_dir,
                max_model_calls=args.max_model_calls,
                max_tool_calls=args.max_tool_calls,
                total_timeout_seconds=args.timeout,
            )
            readonly_agent.print_result(result, as_json=args.json)
            return readonly_agent.exit_code(result)
        with storage.connect(args.db) as conn:
            logged_job_id = None
            exit_code = 0
            outcome = "success"
            if args.command == "add":
                raw_text = args.file.read_text(encoding="utf-8") if args.file else args.text
                row, created = app.register(conn, raw_text, args.source_url, args.deadline_raw,
                                            args.deadline_date, args.rolling, args.new_round)
                print("등록 완료" if created else "동일 원문 기존 기록 재사용")
                print_job(row, detail=True)
                logged_job_id = row["job_id"]
            elif args.command == "show":
                row = storage.get_job(conn, args.job_id)
                if row is None:
                    raise ValueError(f"공고 {args.job_id}를 찾을 수 없습니다")
                print_job(row, detail=True)
                logged_job_id = row["job_id"]
            elif args.command == "list":
                rows = storage.list_jobs(conn, args.status)
                if not rows:
                    print("저장된 공고가 없습니다")
                for row in rows:
                    print_job(row)
            elif args.command == "update":
                row, changed = app.change_application(conn, args.job_id, args.revision,
                                                      args.status, args.notes)
                print("수정 완료" if changed else "변경 사항 없음")
                print_job(row, detail=True)
                logged_job_id = row["job_id"]
            elif args.command == "backup":
                storage.backup(conn, args.destination)
                print(f"백업 완료: {args.destination.expanduser()}")
            elif args.command == "doc-add":
                document_id, version_id, created = app.import_document(
                    conn, args.file, args.title, args.replace, args.verified)
                print("문서 버전 등록 완료" if created else "활성 버전과 동일하여 재사용")
                print(f"문서 #{document_id} | 버전 #{version_id} | 활성")
            elif args.command == "doc-list":
                rows = storage.list_documents(conn)
                if not rows:
                    print("등록된 문서가 없습니다")
                for row in rows:
                    print(f"문서 #{row['document_id']} | {row['title']} | "
                          f"활성 버전 #{row['version_id']} | 근거 구간 {row['span_count']}개")
            elif args.command == "doc-versions":
                title = storage.get_document_title(conn, args.document_id)
                if title is None:
                    raise ValueError(f"문서 {args.document_id}를 찾을 수 없습니다")
                print(f"문서 #{args.document_id} | {title}")
                for row in storage.list_versions(conn, args.document_id):
                    state = "활성" if row["active"] else "이전"
                    print(f"버전 #{row['version_id']} | {row['title']} | {state} | 등록 {row['imported_at']} | "
                          f"이전 버전 {row['supersedes_id'] or '-'} | SHA256 {row['content_hash']}")
            elif args.command == "doc-activate":
                document_id, changed = storage.activate_version(conn, args.version_id)
                print("활성 버전 변경 완료" if changed else "이미 활성 버전입니다")
                print(f"문서 #{document_id} | 활성 버전 #{args.version_id}")
            elif args.command == "search":
                matches = app.search_evidence(conn, args.query, args.limit, args.version, args.alias)
                print("검색 범위: " + (f"버전 #{args.version}" if args.version else "모든 활성 버전"))
                print("검색 점수는 단어 일치 순위이며 자격 충족 판정이 아닙니다")
                if not matches:
                    print("이 검색 범위에서 근거를 찾지 못했습니다")
                for match in matches:
                    row = match["row"]
                    print(f"근거 #{row['evidence_id']} | 문서 #{row['document_id']} {row['title']} | "
                          f"버전 #{row['version_id']} | {row['section']} | "
                          f"원문 문자 [{row['span_start']}:{row['span_end']}] | "
                          f"점수 {match['score']} | 일치 {', '.join(match['matched_terms'])}")
                    print(row["text"])
            elif args.command == "evidence":
                row = app.get_evidence(conn, args.evidence_id)
                print(f"근거 #{row['evidence_id']} | 문서 #{row['document_id']} {row['title']} | "
                      f"버전 #{row['version_id']} | {'활성' if row['active'] else '이전'} | "
                      f"{row['section']} | 원문 문자 [{row['span_start']}:{row['span_end']}]")
                print(row["text"])
            elif args.command == "analyze":
                client = llm.OllamaClient(args.model, args.timeout)
                result = app.analyze_job(conn, args.job_id, client)
                print("검토 전 초안입니다. 원문 인용이 맞아도 의미와 누락 여부를 확인해 주세요")
                print(json.dumps(result, ensure_ascii=False, indent=2))
                logged_job_id = args.job_id
            elif args.command == "run":
                client = llm.OllamaClient(args.model, args.timeout)
                result = app.run_workflow(conn, args.job_id, client, args.top_k, args.alias)
                print_analysis(result, conn)
                logged_job_id = args.job_id
                outcome = result["status"]
                if outcome == "partial":
                    exit_code = 2
                elif outcome == "cancelled":
                    exit_code = 130
                elif outcome in {"failed", "timed_out"}:
                    exit_code = 1
            elif args.command == "analysis-list":
                for row in storage.list_analyses(conn, args.job):
                    print(f"분석 #{row['analysis_id']} | 공고 #{row['job_id']} | {row['status']} | "
                          f"검토 {row['review_status']} | revision {row['revision']} | {row['created_at']}")
            elif args.command == "analysis-show":
                result = app.get_analysis(conn, args.analysis_id)
                if args.json:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                else:
                    print_analysis(result, conn)
                logged_job_id = result["job_id"]
            elif args.command == "analysis-review":
                result = app.review_analysis(conn, args.analysis_id, args.revision, args.status)
                print_analysis(result, conn)
                logged_job_id = result["job_id"]
        log_event(args.db, args.command, outcome, logged_job_id)
        return exit_code
    except (ValueError, llm.LocalModelError, storage.RevisionConflict, sqlite3.Error, OSError, UnicodeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        if args.command != "agent-read":
            log_event(args.db, args.command, "failure", error_type=type(exc).__name__)
        return 1
    except KeyboardInterrupt:
        print("사용자가 실행을 중단했습니다", file=sys.stderr)
        if args.command != "agent-read":
            log_event(args.db, args.command, "cancelled", error_type="KeyboardInterrupt")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
