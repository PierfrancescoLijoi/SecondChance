"""ADR-015 knowledge service: early rejection, ingestion, ACL before retrieval, atomic versions."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from secondchance import admission, jobs, storage
from secondchance.auth import mint_token
from secondchance.knowledge import ingest
from secondchance.knowledge.pdf import UploadRejected, validate_pdf
from secondchance.knowledge.sample import load_demo_documents, make_pdf
from secondchance.knowledge.text import detect_language
from secondchance.main import app
from secondchance.queues import MalformedMessage, MemoryQueue, drain
from secondchance.routes.agents import agents_queue
from secondchance.routes.knowledge import jobs_queue
from secondchance.seed import _id

client = TestClient(app)
IT_INTERNAL, IT_DONORS = _id("space/it/internal"), _id("space/it/donors")


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(subject)}"}


@pytest.fixture(scope="module", autouse=True)
def demo_documents() -> None:
    assert set(load_demo_documents()) == {"published"}


@pytest.fixture
def queue():
    memory = MemoryQueue()
    app.dependency_overrides[jobs_queue] = lambda: memory
    app.dependency_overrides[agents_queue] = lambda: memory
    yield memory
    app.dependency_overrides.clear()


def upload(subject: str, data: bytes, space=IT_INTERNAL, title: str | None = None, document_id=None):
    files = {"file": ("doc.pdf", data, "application/pdf")}
    if document_id:
        return client.post(f"/documents/{document_id}/versions", files=files, headers=auth(subject))
    form = {"space_id": str(space), "title": title or f"Test {uuid.uuid4().hex[:6]}", "language": "it",
            "document_type": "procedure"}
    return client.post("/documents", files=files, data=form, headers=auth(subject))


def titles(subject: str, query: str) -> set[str]:
    response = client.post("/knowledge/search", json={"query": query}, headers=auth(subject))
    assert response.status_code == 200
    return {hit["title"] for hit in response.json()}


def unique_pdf(word: str) -> bytes:
    body = f"Questa procedura sintetica descrive il controllo {word} dei pacchi alimentari ricevuti dai donatori."
    return make_pdf([[f"1 Controllo {word}", body, body, body]])


# --- rejected before storage, queue or model (ADR-016) ---

@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"hello, not a pdf", "not_a_pdf"),
        (b"%PDF-1.4\nthis is not a real pdf", "unreadable_pdf"),
        (make_pdf([["x"]]).replace(b"<< /Type /Catalog /Pages 2 0 R >>",
                                   b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>"),
         "active_content"),
    ],
    ids=["not-pdf", "unreadable", "javascript"],
)
def test_bad_files_are_rejected_before_storage(data: bytes, reason: str) -> None:
    with pytest.raises(UploadRejected) as rejected:
        validate_pdf(data, max_pages=60)
    assert rejected.value.reason == reason


def test_too_many_pages_is_a_422(queue, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(admission.LIMITS, "pdf_pages", 1)
    response = upload("demo-it-admin", make_pdf([["page one"], ["page two"]]))
    assert response.status_code == 422 and response.json()["detail"] == "too_many_pages"
    assert not queue.messages


def test_only_admins_upload(queue) -> None:
    assert upload("demo-it-coordinator", unique_pdf("vietato")).status_code == 403


def test_upload_quota(queue, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(admission.LIMITS, "uploads_daily", 0)
    assert upload("demo-it-admin", unique_pdf("quota")).status_code == 429


# --- ingestion ---

def test_upload_is_idempotent_and_publishes(queue) -> None:
    data = unique_pdf("idempotente")
    first = upload("demo-it-admin", data)
    assert first.status_code == 202
    assert drain(queue, jobs.handle) == 1
    job = client.get(f"/ingestion/jobs/{first.json()['id']}", headers=auth("demo-it-admin")).json()
    assert job["status"] == "published" and job["quality"]["passed"] is True

    again = upload("demo-it-admin", data, document_id=first.json()["document_id"])
    assert again.json()["id"] == first.json()["id"] and not queue.messages


def test_quality_gate_rejects_documents_without_text(queue) -> None:
    created = upload("demo-it-admin", make_pdf([["x"], [""]]))
    drain(queue, jobs.handle)
    job = client.get(f"/ingestion/jobs/{created.json()['id']}", headers=auth("demo-it-admin")).json()
    assert (job["status"], job["error_category"]) == ("failed", "quality_gate:needs_ocr_or_empty")


# --- malware scan on AWS: GuardDuty Malware Protection for S3 tags every upload (ADR-022) ---

@pytest.fixture
def scanner(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """GuardDuty's verdict tag as the worker reads it; an empty list means the scan is still running."""
    verdicts: list[str | None] = []
    monkeypatch.setenv("SECONDCHANCE_MALWARE_SCAN", "guardduty")
    monkeypatch.setattr(ingest, "SCAN_WAIT", timedelta(0))
    monkeypatch.setattr(storage, "scan_status", lambda key, s3=None: verdicts.pop(0) if verdicts else None)
    return verdicts


def job_of(created) -> dict:
    return client.get(f"/ingestion/jobs/{created.json()['id']}", headers=auth("demo-it-admin")).json()


def test_infected_uploads_are_never_parsed(queue, scanner) -> None:
    scanner.append("THREATS_FOUND")
    created = upload("demo-it-admin", unique_pdf("infetto"))
    drain(queue, jobs.handle)
    assert (job_of(created)["status"], job_of(created)["error_category"]) == ("failed", "malware_scan:threats_found")
    assert not titles("demo-it-coordinator", "infetto")


def test_a_failed_scan_fails_closed(queue, scanner) -> None:
    scanner.append("FAILED")
    created = upload("demo-it-admin", unique_pdf("scansionefallita"))
    drain(queue, jobs.handle)
    assert job_of(created)["error_category"] == "malware_scan:failed"


def test_ingestion_waits_for_the_scan_verdict(queue, scanner) -> None:
    created = upload("demo-it-admin", unique_pdf("inattesa"))
    message = dict(queue.messages[0])
    drain(queue, jobs.handle)  # no verdict yet: the job goes back to 'uploaded' for the requeue
    assert job_of(created)["status"] == "uploaded"
    scanner.append("NO_THREATS_FOUND")
    queue.send(message)
    drain(queue, jobs.handle)
    assert job_of(created)["status"] == "published" and titles("demo-it-coordinator", "inattesa")


def test_new_version_replaces_the_old_one_atomically(queue) -> None:
    v1 = upload("demo-it-admin", unique_pdf("primaversione"))
    drain(queue, jobs.handle)
    document_id = v1.json()["document_id"]
    upload("demo-it-admin", unique_pdf("secondaversione"), document_id=document_id)
    # Until the new version is published, retrieval keeps serving the old one.
    assert titles("demo-it-coordinator", "primaversione") and not titles("demo-it-coordinator", "secondaversione")
    drain(queue, jobs.handle)
    assert not titles("demo-it-coordinator", "primaversione") and titles("demo-it-coordinator", "secondaversione")


def test_malformed_job_messages_are_dropped_not_retried() -> None:
    with pytest.raises(MalformedMessage):
        jobs.handle({"type": "ingest", "tenant_id": "not-a-uuid"})
    memory = MemoryQueue()
    memory.send({"type": "unknown", "tenant_id": str(uuid.uuid4())})
    assert drain(memory, jobs.handle) == 0 and not memory.messages


# --- security before retrieval ---

COLD_CHAIN = "temperatura alimenti refrigerati"


def test_search_cites_document_section_and_page() -> None:
    hits = client.post("/knowledge/search", json={"query": COLD_CHAIN}, headers=auth("demo-it-coordinator")).json()
    [cold_chain] = [h for h in hits if h["title"] == "Procedura catena del freddo (sintetica)"][:1]
    assert cold_chain["section_path"][0].startswith("1 Ricevimento") and cold_chain["page_start"] == 1
    assert cold_chain["version"] == 1 and "4 gradi" in cold_chain["snippet"]


def test_donor_never_sees_internal_procedures() -> None:
    seen = titles("demo-it-donor", COLD_CHAIN + " guida donatori")
    assert "Procedura catena del freddo (sintetica)" not in seen
    assert "Guida per i donatori della rete (sintetica)" in seen


def test_other_network_never_sees_private_documents() -> None:
    assert "Procedura catena del freddo (sintetica)" not in titles("demo-dk-coordinator", COLD_CHAIN)


def test_public_guides_are_visible_to_every_network() -> None:
    assert "Food donation guide for businesses (synthetic)" in titles("demo-dk-donor", "best-before date donated")


def test_polish_documents_are_found_with_polish_words() -> None:
    # No Polish stemmer in PostgreSQL: inflected forms still reach the 'simple' chunks via prefixes.
    title = "Przewodnik po przekazywaniu żywności (syntetyczny)"
    assert title in titles("demo-it-volunteer", "żywność chłodzona")
    assert title in titles("demo-it-volunteer", "Jaka temperatura dla żywności chłodzonej?")
    assert title not in titles("demo-it-volunteer", "Quanto costa un volo per Tokyo?")
    assert detect_language("Jak przyjmujemy żywność chłodzoną? Czy należy ją zważyć przy odbiorze?") == "pl"


def test_revoking_a_role_takes_effect_on_the_next_query() -> None:
    query = "orari di ritiro donazione"
    assert "Guida per i donatori della rete (sintetica)" in titles("demo-it-donor", query)
    acl = f"/knowledge/spaces/{IT_DONORS}/acl"
    assert client.post(acl, json={"allowed_roles": ["coordinator", "org_admin"]}, headers=auth("demo-it-admin")).status_code == 204
    try:
        assert "Guida per i donatori della rete (sintetica)" not in titles("demo-it-donor", query)
    finally:
        client.post(acl, json={"allowed_roles": ["donor", "coordinator", "org_admin"]}, headers=auth("demo-it-admin"))


def test_deleted_documents_leave_retrieval_at_once(queue) -> None:
    created = upload("demo-it-admin", unique_pdf("cancellando"))
    drain(queue, jobs.handle)
    assert titles("demo-it-coordinator", "cancellando")
    client.post(f"/documents/{created.json()['document_id']}/delete", headers=auth("demo-it-admin"))
    assert not titles("demo-it-coordinator", "cancellando")


def test_public_spaces_are_curated_by_platform_admins() -> None:
    body = {"name": "Not allowed", "kind": "public", "allowed_roles": ["donor"]}
    assert client.post("/knowledge/spaces", json=body, headers=auth("demo-it-admin")).status_code == 403


# --- answers ---

def test_answer_abstains_without_evidence() -> None:
    result = client.post("/knowledge/answer", json={"question": "Quanto costa un volo per Tokyo?"},
                         headers=auth("demo-it-coordinator")).json()
    assert result["abstained"] is True and result["answer"] is None


def test_answer_is_cited_and_labelled_as_generated() -> None:
    result = client.post("/knowledge/answer", json={"question": "A che temperatura devono arrivare gli alimenti refrigerati?"},
                         headers=auth("demo-it-coordinator")).json()
    assert result["abstained"] is False and result["mode"] == "extractive"
    cited_titles = {result["sources"][n - 1]["title"] for n in result["cited"]}
    assert "Procedura catena del freddo (sintetica)" in cited_titles
    assert result["generated_by"] == "secondchance-knowledge"


# --- one entry point, cheapest path (ADR-015, ADR-016 stage 7) ---

@pytest.mark.parametrize(
    ("subject", "message", "kind"),
    [
        ("demo-it-coordinator", "Come si ricevono gli alimenti refrigerati?", "answer"),
        ("demo-it-donor", "Mostra le mie offerte attive", "navigate"),
        ("demo-it-donor", "Vorrei donare 40 kg di pasta", "navigate"),
        ("demo-it-coordinator", "Pianifica i ritiri di domani e verifica le regole del freddo", "agent_run"),
        ("demo-it-donor", "Pianifica i ritiri di domani e verifica le regole del freddo", "not_allowed"),
        ("demo-it-coordinator", "Ottimizza i percorsi dei volontari", "navigate"),
        ("demo-it-donor", "Ottimizza i percorsi dei volontari", "not_allowed"),
        ("demo-it-coordinator", "Prevedi la domanda del prossimo mese", "unavailable"),
        ("demo-it-coordinator", "Gestisci il pagamento della fattura", "unsupported"),
        ("demo-it-coordinator", "ciao", "clarify"),
        ("demo-dk-coordinator", "Jak przyjmujemy żywność chłodzoną?", "answer"),
        ("demo-dk-coordinator", "Zaplanuj jutrzejsze odbiory oraz sprawdź zasady łańcucha chłodniczego", "agent_run"),
        ("demo-dk-coordinator", "Kto zasługuje na pomoc?", "unsupported"),
    ],
)
def test_assist_routes_each_intent(queue, subject: str, message: str, kind: str) -> None:
    response = client.post("/assist", json={"message": message}, headers=auth(subject))
    assert response.status_code == 200
    assert response.json()["kind"] == kind
    assert bool(queue.messages) == (kind == "agent_run")  # only a real task creates work
