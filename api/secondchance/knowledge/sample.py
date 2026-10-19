"""Synthetic knowledge for demos and tests: a tiny PDF writer and five documents (PRD 8.1).

`python -m secondchance.knowledge.sample` (local only) creates the demo spaces' documents through
the real upload and ingestion code, so the web app has something to search from minute one.
"""

import textwrap

from secondchance.seed import TENANT_DK, TENANT_IT, TENANT_PLATFORM, _id


# WinAnsi lacks Polish letters: they take over byte codes of symbols the samples never use
# (currency sign, fractions...), named through /Differences so text extraction maps them back.
_EXTRA_GLYPHS = {
    "Ą": (0xA1, "Aogonek"), "ą": (0xA4, "aogonek"), "Ć": (0xA6, "Cacute"), "ć": (0xA8, "cacute"),
    "Ę": (0xAA, "Eogonek"), "ę": (0xAC, "eogonek"), "Ł": (0xAF, "Lslash"), "ł": (0xB2, "lslash"),
    "Ń": (0xB3, "Nacute"), "ń": (0xB4, "nacute"), "Ś": (0xB8, "Sacute"), "ś": (0xB9, "sacute"),
    "Ź": (0xBA, "Zacute"), "ź": (0xBC, "zacute"), "Ż": (0xBD, "Zdotaccent"), "ż": (0xBE, "zdotaccent"),
}
_DIFFERENCES = " ".join(f"{code} /{name}" for code, name in _EXTRA_GLYPHS.values())
_FONT = ("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding"
         f" /BaseEncoding /WinAnsiEncoding /Differences [{_DIFFERENCES}] >> >>").encode()


def _encode(text: str) -> bytes:
    return b"".join(bytes([_EXTRA_GLYPHS[c][0]]) if c in _EXTRA_GLYPHS else c.encode("cp1252") for c in text)


def make_pdf(pages: list[list[str]]) -> bytes:
    """Minimal valid PDF (Helvetica, WinAnsi plus Polish letters): one text line per entry, wrapped at 90 chars."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", _FONT]
    kids = []
    for lines in pages:
        wrapped = [piece for line in lines for piece in (textwrap.wrap(line, 90) or [""])]
        body = ["BT /F1 11 Tf 50 800 Td 15 TL"]
        for line in wrapped:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            body.append(f"({escaped}) Tj T*")
        body.append("ET")
        stream = _encode("\n".join(body))
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_ref = len(objects)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >>"
                       b" /Contents %d 0 R >>" % content_ref)
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


SPACES = [
    {"id": _id("space/public/donation-guides"), "tenant": TENANT_PLATFORM, "name": "Public donation guides",
     "kind": "public", "visibility": "public",
     "roles": ["donor", "coordinator", "volunteer", "center_staff", "org_admin", "platform_admin"]},
    {"id": _id("space/it/internal"), "tenant": TENANT_IT, "name": "Procedure interne", "kind": "ngo_private",
     "visibility": "tenant", "roles": ["coordinator", "volunteer", "org_admin"]},
    {"id": _id("space/it/donors"), "tenant": TENANT_IT, "name": "Guida per i donatori", "kind": "donor",
     "visibility": "tenant", "roles": ["donor", "coordinator", "org_admin"]},
    {"id": _id("space/dk/internal"), "tenant": TENANT_DK, "name": "Interne procedurer", "kind": "ngo_private",
     "visibility": "tenant", "roles": ["coordinator", "volunteer", "org_admin"]},
]

DOCUMENTS = [
    {"space": _id("space/public/donation-guides"), "tenant": TENANT_PLATFORM, "admin": "demo-platform-admin",
     "title": "Food donation guide for businesses (synthetic)", "language": "en", "type": "guideline",
     "pages": [
         ["1 What businesses can donate",
          "Shops, canteens and producers can donate packaged food that is safe to eat and correctly labelled.",
          "Opened packages, home-made food and products recalled by the producer cannot be donated.",
          "2 Use-by and best-before dates",
          "Food with a use-by date must never be donated after that date, because it can become unsafe.",
          "Food with a best-before date can still be donated after the date if the packaging is intact and it was "
          "stored correctly, where national rules allow it."],
         ["3 Packaging and labelling",
          "Keep the original label with ingredients and allergens. Put chilled products in insulated boxes.",
          "4 Pickup and delivery",
          "Agree a pickup window with the network. Chilled food must travel at 4 degrees Celsius or less and frozen "
          "food at minus 18 degrees Celsius or less."],
     ]},
    {"space": _id("space/public/donation-guides"), "tenant": TENANT_PLATFORM, "admin": "demo-platform-admin",
     "title": "Przewodnik po przekazywaniu żywności (syntetyczny)", "language": "pl", "type": "guideline",
     "pages": [
         ["1 Żywność chłodzona",
          "Wolontariusz mierzy temperaturę przy odbiorze. Żywność chłodzona musi mieć temperaturę nie wyższą "
          "niż 4 stopnie.",
          "Towar cieplejszy niż 4 stopnie nie jest przyjmowany, a niezgodność zostaje zapisana.",
          "2 Daty na etykiecie",
          "Produktu z datą „należy spożyć do” nigdy nie przekazuje się po tej dacie.",
          "Produkt z datą „najlepiej spożyć przed” można przekazać po tej dacie, jeśli opakowanie jest "
          "nienaruszone, a krajowe przepisy na to pozwalają."],
     ]},
    {"space": _id("space/it/internal"), "tenant": TENANT_IT, "admin": "demo-it-admin",
     "title": "Procedura catena del freddo (sintetica)", "language": "it", "type": "procedure",
     "pages": [
         ["1 Ricevimento degli alimenti refrigerati",
          "Il volontario misura la temperatura al momento del ritiro: gli alimenti refrigerati devono arrivare a "
          "una temperatura non superiore a 4 gradi.",
          "Se la temperatura supera i 4 gradi la merce non viene accettata e si registra una non conformità.",
          "2 Registrazione delle temperature",
          "Ogni ritiro di prodotti refrigerati richiede la registrazione della temperatura sul modulo di missione."],
         ["3 Prodotti surgelati",
          "I surgelati vanno trasportati a meno 18 gradi in contenitori isotermici e scaricati entro trenta minuti.",
          "4 Non conformità",
          "Il coordinatore informa il donatore e il centro, e annota la causa: catena del freddo interrotta, "
          "imballaggio danneggiato o data di scadenza superata."],
     ]},
    {"space": _id("space/it/donors"), "tenant": TENANT_IT, "admin": "demo-it-admin",
     "title": "Guida per i donatori della rete (sintetica)", "language": "it", "type": "guideline",
     "pages": [
         ["1 Come preparare una donazione",
          "Separate gli alimenti refrigerati da quelli a temperatura ambiente e indicate la data di scadenza.",
          "2 Orari di ritiro",
          "I volontari ritirano dal lunedì al sabato tra le 9 e le 18. Indicate la finestra di ritiro nell'offerta."],
     ]},
    {"space": _id("space/dk/internal"), "tenant": TENANT_DK, "admin": "demo-dk-admin",
     "title": "Procedure for kølevarer (syntetisk)", "language": "da", "type": "procedure",
     "pages": [
         ["1 Modtagelse af kølevarer",
          "Frivillige måler temperaturen ved afhentning. Kølevarer skal holdes på højst 4 grader.",
          "Varer over 4 grader afvises, og afvigelsen registreres.",
          "2 Frostvarer",
          "Frostvarer transporteres ved minus 18 grader i isolerede kasser og skal være på centret inden for en halv time."],
     ]},
]


def spaces_rows() -> list[dict]:
    return [{"id": s["id"], "tenant_id": s["tenant"], "name": s["name"], "kind": s["kind"],
             "visibility": s["visibility"], "allowed_roles": s["roles"]} for s in SPACES]


def load_demo_documents() -> list[str]:
    """Upload and ingest every demo document through the production code path (idempotent)."""
    from sqlalchemy import text

    from secondchance.db import subject_transaction
    from secondchance.knowledge import ingest
    from secondchance.principal import Claims

    outcomes = []
    for doc in DOCUMENTS:
        with subject_transaction(doc["admin"]) as session:
            role = session.execute(
                text("SELECT role FROM membership WHERE subject = :s AND tenant_id = :t AND status = 'active'"),
                {"s": doc["admin"], "t": doc["tenant"]},
            ).scalar_one()
        claims = Claims(doc["admin"], doc["tenant"], role)
        meta = ingest.DocumentMeta(doc["space"], doc["title"], doc["language"], doc["type"])
        existing = _existing_document(claims, doc["title"])
        job, _ = ingest.upload(claims, make_pdf(doc["pages"]), None if existing else meta, existing, "demo-seed")
        outcomes.append(ingest.process(doc["tenant"], job["id"]) if job["status"] == "uploaded" else job["status"])
    return outcomes


def _existing_document(claims, title: str):
    from sqlalchemy import text

    from secondchance.db import tenant_transaction

    with tenant_transaction(claims.tenant_id, claims.role, claims.sub) as session:
        return session.execute(
            text("SELECT id FROM document WHERE title = :title AND deleted_at IS NULL"), {"title": title}
        ).scalar_one_or_none()


if __name__ == "__main__":
    print(load_demo_documents())
