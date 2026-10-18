"""Language detection, the canonical document schema and section-aware chunking (ADR-015)."""

import re
from dataclasses import dataclass, field

LANGUAGES = ("it", "en", "da", "pl")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOPWORDS = {
    "it": frozenset("il lo la gli le di che per con non sono una del della dei nel alla come quali cosa perché essere".split()),
    "en": frozenset("the and of to is are with what which how not be that this from on by an".split()),
    "da": frozenset("og det er til af med ikke som hvad hvordan hvilke en den de på at fra skal kan".split()),
    # No one-letter words or words shared with the others ("i", "w", "to", "do").
    "pl": frozenset("nie się jest są jak jakie jaki które który czy dla od przez oraz że należy można przy".split()),
}

# ponytail: stopword vote; good enough to pick the FTS dictionary for it/en/da/pl.
def detect_language(text: str, default: str = "en") -> str:
    words = [w.lower() for w in _WORD.findall(text)]
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default


@dataclass(frozen=True)
class Section:
    heading_path: tuple[str, ...]
    page_start: int
    page_end: int
    content: str


@dataclass(frozen=True)
class CanonicalDocument:
    """Versioned schema shared by every parser (pypdf baseline, Docling adapter)."""

    schema_version: str
    title: str
    language: str
    page_count: int
    sections: tuple[Section, ...]

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "language": self.language,
            "page_count": self.page_count,
            "sections": [
                {"heading_path": list(s.heading_path), "page_start": s.page_start, "page_end": s.page_end, "content": s.content}
                for s in self.sections
            ],
        }


@dataclass(frozen=True)
class Chunk:
    section_path: tuple[str, ...]
    page_start: int
    page_end: int
    ordinal: int
    content: str
    language: str


@dataclass
class _Open:
    path: list[str]
    page_start: int
    page_end: int
    lines: list[str] = field(default_factory=list)


_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(\S.{0,100})$")


def _heading_level(line: str) -> int | None:
    """Numbered headings ('2.1 Storage') give their depth; short title-like lines are level 1."""
    match = _NUMBERED.match(line)
    if match and not line.rstrip().endswith((".", ",", ";", ":")):
        return match.group(1).count(".") + 1
    if 3 <= len(line) <= 80 and not line.endswith((".", ",", ";", ":")) and (line.isupper() or line.istitle()):
        return 1
    return None


def sections_from_pages(pages: list[str]) -> tuple[Section, ...]:
    """ponytail: heuristic headings for digital PDFs; the Docling adapter gives real structure."""
    done: list[Section] = []
    current = _Open(path=[], page_start=1, page_end=1)

    def close() -> None:
        text = " ".join(" ".join(current.lines).split())
        if text:
            done.append(Section(tuple(current.path), current.page_start, current.page_end, text))

    for page_number, page in enumerate(pages, start=1):
        for raw in page.splitlines():
            line = raw.strip()
            if not line:
                continue
            level = _heading_level(line)
            if level is not None:
                close()
                path = current.path[: level - 1] + [line]
                current = _Open(path=path, page_start=page_number, page_end=page_number)
            else:
                current.lines.append(line)
                current.page_end = page_number
    close()
    return tuple(done)


def _tokens(text: str) -> int:
    return round(len(text.split()) * 1.3)  # ponytail: word-based estimate, no tokenizer dependency


def chunk_sections(sections: tuple[Section, ...], language: str, max_tokens: int = 650, target_tokens: int = 500) -> list[Chunk]:
    """One chunk per section; long sections split on sentence boundaries near target_tokens."""
    chunks: list[Chunk] = []
    for section in sections:
        if _tokens(section.content) <= max_tokens:
            pieces = [section.content]
        else:
            pieces, buffer = [], []
            for sentence in re.split(r"(?<=[.!?])\s+", section.content):
                buffer.append(sentence)
                if _tokens(" ".join(buffer)) >= target_tokens:
                    pieces.append(" ".join(buffer))
                    buffer = []
            if buffer:
                pieces.append(" ".join(buffer))
        for piece in pieces:
            # A single sentence longer than the limit is cut hard rather than dropped.
            words = piece.split()
            limit = int(max_tokens / 1.3)
            for start in range(0, len(words), limit):
                chunks.append(Chunk(section.heading_path, section.page_start, section.page_end, len(chunks),
                                    " ".join(words[start:start + limit]), language))
    return chunks
