"""Utilities for managing the partner directory."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from flask import current_app
from sqlalchemy import func

from app.models import db
from app.models.partner import (
    Partner,
    PartnerCategory,
    PartnerSubscription,
    generate_invoice_number,
)


def active_partners_for_category(category: PartnerCategory, *, reference: date | None = None) -> list[Partner]:
    reference = reference or date.today()
    return [
        partner
        for partner in category.partners
        if partner.is_publicly_visible(reference)
    ]


def slots_usage(category: PartnerCategory, *, reference: date | None = None) -> tuple[int, int]:
    visible = active_partners_for_category(category, reference=reference)
    return len(visible), category.max_slots


def slots_available(category: PartnerCategory, *, reference: date | None = None) -> int:
    used, maximum = slots_usage(category, reference=reference)
    return max(maximum - used, 0)


def can_approve_partner(partner: Partner, *, reference: date | None = None) -> bool:
    if partner.status == "approved":
        return True
    available = slots_available(partner.category, reference=reference)
    return available > 0


def next_invoice_sequence(year: int) -> int:
    base = (
        db.session.query(func.count(PartnerSubscription.id))
        .filter(PartnerSubscription.year == year)
        .scalar()
        or 0
    )
    pending = sum(
        1
        for obj in db.session.new
        if isinstance(obj, PartnerSubscription) and obj.year == year
    )
    return base + pending + 1


def create_subscription(
    partner: Partner,
    *,
    year: int,
    price_eur: Decimal,
    payment_method: str,
    payment_ref: str | None,
    paid_at: datetime,
) -> PartnerSubscription:
    sequence = next_invoice_sequence(year)
    invoice_number = generate_invoice_number(sequence, year=year)

    subscription = PartnerSubscription(
        partner=partner,
        year=year,
        price_eur=price_eur,
        payment_method=payment_method,
        payment_ref=payment_ref,
        invoice_number=invoice_number,
    )
    subscription.set_validity(paid_at)
    db.session.add(subscription)
    return subscription


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_invoice_pdf(subscription: PartnerSubscription) -> Path:
    invoices_dir = Path(current_app.static_folder or "static") / "invoices" / str(subscription.year)
    invoices_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = invoices_dir / f"{subscription.invoice_number}.pdf"

    partner = subscription.partner
    lines = [
        "EtnaMonitor",
        "Via digitale, 95100 Catania (CT)",
        "P.IVA: IT00000000000",
        "",
        f"Fattura {subscription.invoice_number}",
        f"Data pagamento: {(subscription.paid_at or datetime.now(timezone.utc)).date().isoformat()}",
        f"Validità: {subscription.valid_from} -> {subscription.valid_to}",
        "",
        "Destinatario:",
        partner.name,
        partner.address or "",
        partner.city or "",
        "",
        "Dettaglio servizio:",
        "Directory Partner EtnaMonitor",
        f"Categoria: {partner.category.name}",
        f"Metodo: {subscription.payment_method}",
        f"Totale EUR {float(subscription.price_eur):.2f}",
        "",
        "Grazie per aver sostenuto la rete EtnaMonitor.",
    ]

    content_stream = ["BT", "/F1 12 Tf"]
    y = 760
    for line in lines:
        if not line:
            y -= 12
            continue
        content_stream.append(f"1 0 0 1 72 {y} Tm ({_pdf_escape(line)}) Tj")
        y -= 16
    content_stream.append("ET")
    content_bytes = "\n".join(content_stream).encode("latin-1")

    objects: list[bytes] = []
    offsets: list[int] = []

    def _add_object(payload: str | bytes) -> None:
        offset = sum(len(obj) for obj in objects)
        offsets.append(offset)
        if isinstance(payload, str):
            payload = payload.encode("latin-1")
        objects.append(payload + b"\n")

    _add_object("1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj")
    _add_object("2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj")
    _add_object(
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj"
    )
    _add_object("4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj")
    _add_object(
        f"5 0 obj << /Length {len(content_bytes)} >> stream\n".encode("latin-1")
        + content_bytes
        + b"\nendstream endobj"
    )

    xref_offset = sum(len(obj) for obj in objects)
    xref_entries = [b"0000000000 65535 f "]
    for offset in offsets:
        xref_entries.append(f"{offset:010d} 00000 n ".encode("ascii"))

    trailer = (
        b"xref\n0 6\n"
        + b"\n".join(xref_entries)
        + b"\ntrailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF"
    )

    pdf_content = b"%PDF-1.4\n" + b"".join(objects) + trailer
    pdf_path.write_bytes(pdf_content)
    return pdf_path
