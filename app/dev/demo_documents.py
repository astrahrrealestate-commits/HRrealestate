"""#9 Document Filing scenario for `make sim-demo`: a tenant emails an invoice and a photo.

Expected after the pipeline's `doc:{attachment_id}` workflows: `factuur_2026-09.pdf` is filed as an invoice (fake
classifier, confidence 0.85, dev MemoryDrive in the worker) and `IMG_1234.jpg` waits for the owner's review card
(photo, confidence 0.5). Drive lives in the worker process, so the checks read the `documents` rows.
"""

import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.enums import DocumentStatus
from app.db.models import AttachmentRow, DocumentRow, MessageRow
from app.dev import fixtures as fx
from app.dev.simulate import Simulator

SENDER = "Mevr. de Vries <huurder-002@example.test>"
INVOICE = fx.Attachment("factuur_2026-09.pdf", "application/pdf", b"%PDF-1.4 EstateOS demo invoice " + b"0" * 4000)
PHOTO = fx.Attachment("IMG_1234.jpg", "image/jpeg", b"\xff\xd8\xff\xe0 EstateOS demo photo " + b"1" * 30_000)
EXPECTED: dict[str, DocumentStatus] = {INVOICE.filename: DocumentStatus.filed, PHOTO.filename: DocumentStatus.review}


@dataclass(frozen=True)
class DocRow:
    filename: str
    status: DocumentStatus
    doc_type: str
    file_name: str
    drive_file_id: str | None


def send_documents(sim: Simulator) -> tuple[str, ...]:
    """Two emails in one thread, one attachment each. Returns their RFC 822 Message-IDs."""
    first = sim.gmail(SENDER, "Factuur reparatie", "Hierbij de factuur van de loodgieter.", attachment=INVOICE)
    second = sim.gmail(SENDER, "Re: Factuur reparatie", "En een foto van de lekkage.", in_reply_to=first,
                       attachment=PHOTO)  # fmt: skip
    return first, second


def load_documents(engine: Engine, company_id: UUID, rfc_ids: tuple[str, ...]) -> list[DocRow]:
    query = (
        select(AttachmentRow.filename, DocumentRow)
        .join(MessageRow, (MessageRow.id == AttachmentRow.message_id) & (MessageRow.company_id == company_id))
        .join(DocumentRow, (DocumentRow.attachment_id == AttachmentRow.id) & (DocumentRow.company_id == company_id))
        .where(AttachmentRow.company_id == company_id, MessageRow.meta["message_id"].astext.in_(rfc_ids))
    )
    with Session(engine) as session:
        return [
            DocRow(name or "", doc.status, doc.doc_type, doc.file_name, doc.drive_file_id)
            for name, doc in session.execute(query)
        ]


def document_problems(rows: list[DocRow]) -> list[str]:
    found = {r.filename: r for r in rows}
    problems = [f"documents: no row for {name}" for name in EXPECTED if name not in found]
    for name, row in found.items():
        want = EXPECTED.get(name)
        if want is not None and row.status is not want:
            problems.append(f"documents: {name} is {row.status.value}, expected {want.value}")
    invoice = found.get(INVOICE.filename)
    filed = invoice is not None and invoice.status is DocumentStatus.filed
    if filed and invoice and (invoice.doc_type != "invoice" or "_invoice_" not in invoice.file_name
                              or not invoice.drive_file_id):  # fmt: skip
        problems.append(f"documents: invoice filed wrongly ({invoice.doc_type}, {invoice.file_name})")
    return problems


def wait_for_documents(engine: Engine, company_id: UUID, rfc_ids: tuple[str, ...], timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    while True:
        found = document_problems(load_documents(engine, company_id, rfc_ids))
        if not found or time.monotonic() >= deadline:
            return found
        time.sleep(0.5)
