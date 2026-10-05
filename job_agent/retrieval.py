"""Explainable keyword ranking over stored source spans; never judges eligibility."""

import re
import unicodedata


TOKEN = re.compile(r"[a-z0-9][a-z0-9+#._-]*|[가-힣]+")


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def terms(value: str) -> list[str]:
    return list(dict.fromkeys(TOKEN.findall(normalize(value))))


def contains(source: str, term: str) -> bool:
    if re.search(r"[가-힣]", term):
        return term in source
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", source) is not None


def parse_aliases(values: list[str]) -> dict[str, list[str]]:
    result = {}
    for value in values:
        left, separator, right = value.partition("=")
        if not separator or len(terms(left)) != 1 or len(terms(right)) != 1:
            raise ValueError("동의어는 질의어=문서표현 형식의 단일 단어여야 합니다")
        result.setdefault(terms(left)[0], []).append(terms(right)[0])
    return result


def rank(query: str, rows, limit: int = 5, aliases=None):
    query_terms = terms(query)
    if not query_terms:
        raise ValueError("검색어를 입력해 주세요")
    if not 1 <= limit <= 20:
        raise ValueError("검색 개수는 1~20이어야 합니다")
    aliases = aliases or {}
    normalized_query = normalize(query)
    scored = []
    for row in rows:
        source = normalize(row["text"])
        matched = []
        for term in query_terms:
            variants = [term, *aliases.get(term, [])]
            if any(contains(source, variant) for variant in variants):
                matched.append(term)
        if matched:
            # More distinct terms and an exact phrase make a span easier to inspect.
            score = len(matched) + (2 if normalized_query in source else 0)
            scored.append({"row": row, "score": score, "matched_terms": matched})
    scored.sort(key=lambda item: (-item["score"], item["row"]["evidence_id"]))
    return scored[:limit]
