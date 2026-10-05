"""Input rules independent of the command line and database."""

from datetime import date
import hashlib
import re


STATUSES = ("planned", "preparing", "submitted", "interview", "offer", "rejected", "withdrawn")


def required_text(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name}: 빈 값은 저장할 수 없습니다")
    return value


def content_hash(raw_text: str) -> str:
    # Whitespace variation identifies a duplicate candidate, not a new hiring round.
    normalized = re.sub(r"\s+", " ", required_text(raw_text, "공고 원문"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deadline_fields(raw: str | None, iso_date: str | None, rolling: bool) -> tuple[str | None, str | None, str]:
    raw = raw.strip() if raw else None
    if raw == "":
        raw = None
    if rolling and iso_date:
        raise ValueError("수시 마감과 확정 날짜를 함께 지정할 수 없습니다")
    if rolling:
        return raw or "채용 시 마감", None, "rolling"
    if iso_date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso_date):
            raise ValueError("마감 날짜는 YYYY-MM-DD 형식이어야 합니다")
        try:
            date.fromisoformat(iso_date)
        except ValueError as exc:
            raise ValueError("실제로 존재하지 않는 마감 날짜입니다") from exc
        return raw, iso_date, "date_only"
    return raw, None, "unknown"


def check_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"지원 상태는 {', '.join(STATUSES)} 중 하나여야 합니다")
    return status
