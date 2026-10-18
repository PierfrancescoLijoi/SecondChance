"""PDF validation (fail fast, ADR-016 stage 8) and the pypdf baseline parser (ADR-015)."""

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from secondchance.knowledge.text import CanonicalDocument, detect_language, sections_from_pages

SCHEMA_VERSION = "canonical-v1"
PIPELINE_VERSION = "pypdf-6.19+sections-v1+chunks-650"

logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed files are rejected, not logged at length


class UploadRejected(ValueError):
    """The file is refused before storage or queueing; `reason` is a stable category."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_pdf(data: bytes, max_pages: int) -> int:
    """Cheap structural checks; returns the page count. Malware scanning on AWS
    (GuardDuty Malware Protection for S3, before parsing) is planned, not yet deployed."""
    if not data.startswith(b"%PDF-"):
        raise UploadRejected("not_a_pdf")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise UploadRejected("encrypted")
        pages = len(reader.pages)
        root = reader.trailer["/Root"]
        names = root.get("/Names") or {}
        active = "/JavaScript" in names or "/EmbeddedFiles" in names or "/AA" in root
        open_action = root.get("/OpenAction")
        if hasattr(open_action, "get_object"):
            open_action = open_action.get_object()
        if isinstance(open_action, dict) and open_action.get("/S") in ("/JavaScript", "/Launch"):
            active = True
    except UploadRejected:
        raise
    except (PdfReadError, KeyError, ValueError, TypeError, AttributeError) as exc:
        raise UploadRejected("unreadable_pdf") from exc
    if active:
        raise UploadRejected("active_content")
    if not 0 < pages <= max_pages:
        raise UploadRejected("too_many_pages")
    return pages


def parse(data: bytes, title: str, language: str | None) -> CanonicalDocument:
    reader = PdfReader(io.BytesIO(data), strict=False)
    pages = [page.extract_text() or "" for page in reader.pages]
    detected = language or detect_language(" ".join(pages)[:5000])
    return CanonicalDocument(SCHEMA_VERSION, title, detected, len(pages), sections_from_pages(pages))


def quality(document: CanonicalDocument) -> dict:
    """Quality gate before publication: too little text usually means a scanned PDF."""
    characters = sum(len(s.content) for s in document.sections)
    per_page = characters / document.page_count
    passed = characters >= 200 and per_page >= 80 and len(document.sections) >= 1
    return {
        "passed": passed,
        "reason": None if passed else "needs_ocr_or_empty",
        "characters": characters,
        "characters_per_page": round(per_page, 1),
        "sections": len(document.sections),
        "detected_language": detect_language(" ".join(s.content for s in document.sections)[:5000]),
    }
