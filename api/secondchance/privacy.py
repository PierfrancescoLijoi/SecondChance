"""Privacy by design (ADR-014): PII redaction, subject pseudonyms, data inventory.

`python -m secondchance.privacy` prints the data inventory for the record of processing
activities (GDPR art. 30), generated from the column comments of the live schema.
"""

import hashlib
import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

PII_CLASSES = ("none", "personal", "sensitive")

# Order matters: an IBAN contains digit runs that would otherwise match the phone pattern.
_REDACTIONS = (
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("[IBAN]", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")),
    (
        "[PHONE]",
        re.compile(
            r"(?<![\w.-])"
            r"(?!\d{4}-\d{2}-\d{2}\b)(?!\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b)"  # dates are not phones
            r"\+?\d(?:[ .\-/]?\d){7,14}(?![\w-])"
        ),
    ),
)


def redact(value: str) -> str:
    """Baseline redaction before logs, memory and prompts.

    ponytail: regex catches emails, IBANs and phone numbers only; names and addresses
    need Bedrock Guardrails PII masking (AWS) or an NER model before real data arrives.
    """
    for placeholder, pattern in _REDACTIONS:
        value = pattern.sub(placeholder, value)
    return value


def subject_hash(tenant_id: uuid.UUID, subject: str) -> str:
    """Pseudonym for analytics tables: recomputable for erasure requests, not reversible."""
    return hashlib.sha256(f"{tenant_id}:{subject}".encode()).hexdigest()


def inventory(session: Session) -> list[dict[str, str]]:
    """Every column of the application schema with its classification and purpose."""
    rows = session.execute(
        text(
            "SELECT c.relname AS table_name, a.attname AS column_name,"
            " coalesce(col_description(c.oid, a.attnum), '') AS comment"
            " FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'"
            " JOIN pg_roles r ON r.oid = c.relowner AND r.rolname = 'secondchance_migrator'"
            " JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped"
            " WHERE c.relkind = 'r' AND c.relname <> 'alembic_version'"
            " ORDER BY c.relname, a.attnum"
        )
    ).mappings()
    result = []
    for row in rows:
        label, _, purpose = row["comment"].partition(";")
        result.append(
            {
                "table": row["table_name"],
                "column": row["column_name"],
                "pii": label.removeprefix("pii:").strip() if label.startswith("pii:") else "",
                "purpose": purpose.strip(),
            }
        )
    return result


if __name__ == "__main__":
    from secondchance.db import SessionLocal

    with SessionLocal() as session:
        print("| Table | Column | PII | Purpose |\n|---|---|---|---|")
        for item in inventory(session):
            print(f"| {item['table']} | {item['column']} | {item['pii'] or '?'} | {item['purpose']} |")
