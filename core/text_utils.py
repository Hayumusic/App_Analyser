import re
from typing import Iterable, List, Set

EMPTY_STRINGS = {"", "nan", "none", "null", "n/a", "na", "not available", "unknown"}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in EMPTY_STRINGS:
        return ""
    return re.sub(r"\s+", " ", text)


def is_populated(value) -> bool:
    return clean_text(value) != ""


def normalize_header(value: str) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def split_multi_value(value) -> List[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(r"[,;|/\n\r]+", text)
    out = []
    for p in parts:
        p = clean_text(p).lower()
        if p:
            out.append(p)
    return out


def tokenize(value) -> Set[str]:
    text = clean_text(value).lower()
    if not text:
        return set()
    parts = re.split(r"[,;|/\n\r]+", text)
    tokens = []
    for part in parts:
        part = clean_text(part)
        if not part:
            continue
        if len(part.split()) <= 5:
            tokens.append(part)
        tokens.extend(re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", part))
    stop = {"and", "the", "for", "with", "from", "into", "using", "this", "that", "application", "system"}
    return {t for t in tokens if t not in stop}


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    hay = clean_text(text).lower()
    return any(k.lower() in hay for k in keywords)


def first_available(row, columns):
    for col in columns:
        if col in row and is_populated(row[col]):
            return row[col]
    return "Not Available"
