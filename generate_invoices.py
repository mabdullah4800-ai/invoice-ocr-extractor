"""
generate_invoices.py
--------------------
Creates a folder of synthetic invoice PDFs in `invoices/`.

These are the input the extractor reads. They are generated rather than
real because real invoices are confidential financial documents -- this
keeps the repo safe to publish while still looking like the real thing.

A couple of invoices carry deliberate problems so the validation layer
has something genuine to catch:

    INV-1003  -- the printed total does not equal subtotal + VAT
    INV-1005  -- the invoice date is missing entirely

Everything is generated from a fixed random seed, so re-running this
script reproduces the identical set of PDFs.
"""

import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

SEED = 7
random.seed(SEED)

OUT_DIR = Path(__file__).parent / "invoices"
VAT_RATE = 0.23  # Irish standard VAT rate

# Each vendor has a small catalogue of (description, unit_price) lines.
VENDORS = [
    {
        "name": "Atlantic Office Supplies Ltd",
        "address": "14 Hanover Quay, Dublin 2, D02 XY45",
        "catalogue": [
            ("A4 Printer Paper (box of 5 reams)", 24.50),
            ("Black Ballpoint Pens (pack of 50)", 9.80),
            ("Lever Arch Files (pack of 10)", 18.40),
            ("Sticky Notes, assorted (pack of 12)", 11.25),
            ("Stapler, heavy duty", 14.99),
        ],
    },
    {
        "name": "Liffey Logistics",
        "address": "Unit 7, Eastpoint Business Park, Dublin 3",
        "catalogue": [
            ("Pallet delivery, national", 48.00),
            ("Express courier, next-day", 22.50),
            ("Warehouse handling fee", 35.00),
            ("Fuel surcharge", 7.75),
        ],
    },
    {
        "name": "Shannon Software Solutions",
        "address": "Clare Technology Park, Ennis, Co. Clare",
        "catalogue": [
            ("Annual software licence, per seat", 120.00),
            ("Onboarding and setup", 250.00),
            ("Priority support, monthly", 45.00),
            ("Custom report build", 180.00),
        ],
    },
    {
        "name": "Celtic Catering Co.",
        "address": "5 Marlborough Street, Dublin 1",
        "catalogue": [
            ("Working lunch, per head", 12.50),
            ("Tea & coffee station", 30.00),
            ("Sandwich platter", 42.00),
            ("Fruit bowl, large", 18.00),
        ],
    },
    {
        "name": "Dublin Print & Design",
        "address": "88 Thomas Street, Dublin 8",
        "catalogue": [
            ("Business cards (per 500)", 39.00),
            ("Roller banner, printed", 95.00),
            ("Brochure design, per page", 60.00),
            ("Laminated posters (A2)", 8.50),
        ],
    },
    {
        "name": "Greenfield IT Services",
        "address": "2 Sandyford Business Centre, Dublin 18",
        "catalogue": [
            ("Laptop, refurbished business model", 410.00),
            ("USB-C docking station", 89.00),
            ("On-site engineer, per hour", 75.00),
            ("Data backup service, monthly", 25.00),
        ],
    },
]

styles = getSampleStyleSheet()
RIGHT = ParagraphStyle("right", parent=styles["Normal"], alignment=2)


def money(value: float) -> str:
    """Format a number as a euro amount, e.g. 1234.5 -> 'EUR 1,234.50'."""
    return f"EUR {value:,.2f}"


def build_invoice(vendor: dict, number: int, issued: date | None,
                   total_error: float = 0.0) -> None:
    """Render one invoice PDF.

    total_error -- euros to add to the *printed* total, leaving the real
                   arithmetic wrong on purpose (0.0 means a correct invoice).
    issued      -- the invoice date, or None to omit it entirely.
    """
    invoice_id = f"INV-{number}"
    path = OUT_DIR / f"{invoice_id}.pdf"

    # Pick 3-5 catalogue lines (capped at what the vendor stocks).
    catalogue = vendor["catalogue"]
    chosen = random.sample(catalogue, k=random.randint(3, min(5, len(catalogue))))
    line_items = []
    for description, unit_price in chosen:
        qty = random.randint(1, 6)
        line_items.append((description, qty, unit_price, qty * unit_price))

    subtotal = round(sum(item[3] for item in line_items), 2)
    vat = round(subtotal * VAT_RATE, 2)
    printed_total = round(subtotal + vat + total_error, 2)

    # --- Lay the document out with reportlab's Platypus ---------------
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            topMargin=22 * mm, bottomMargin=22 * mm)
    story = []

    story.append(Paragraph(f"<b>{vendor['name']}</b>", styles["Title"]))
    story.append(Paragraph(vendor["address"], styles["Normal"]))
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph("<b>INVOICE</b>", styles["Heading1"]))
    story.append(Paragraph(f"Invoice number: {invoice_id}", styles["Normal"]))
    if issued is not None:
        story.append(Paragraph(f"Invoice date: {issued.isoformat()}", styles["Normal"]))
    story.append(Paragraph("Bill to: BloxUltra Operations Ltd, Dublin", styles["Normal"]))
    story.append(Spacer(1, 8 * mm))

    # Line-item table: header row + one row per item.
    table_data = [["Description", "Qty", "Unit price", "Line total"]]
    for description, qty, unit_price, line_total in line_items:
        table_data.append([
            Paragraph(description, styles["Normal"]),
            str(qty), money(unit_price), money(line_total),
        ])

    table = Table(table_data, colWidths=[85 * mm, 18 * mm, 32 * mm, 35 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3b52")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b0b8c4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))

    # Totals block, right-aligned under the table.
    totals = Table(
        [["Subtotal", money(subtotal)],
         [f"VAT ({VAT_RATE * 100:.0f}%)", money(vat)],
         ["Total due", money(printed_total)]],
        colWidths=[140 * mm, 35 * mm],
    )
    totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals)
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("Payment terms: 30 days from invoice date.", styles["Normal"]))

    doc.build(story)
    print(f"Wrote {path.name}")


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    base = date(2024, 9, 2)

    for offset, vendor in enumerate(VENDORS):
        number = 1001 + offset
        issued = base + timedelta(days=offset * 6)

        # INV-1003: printed total is 15.00 too high -- a real arithmetic break.
        total_error = 15.00 if number == 1003 else 0.0
        # INV-1005: the invoice date is missing.
        if number == 1005:
            issued = None

        build_invoice(vendor, number, issued, total_error=total_error)

    print(f"\nDone. {len(VENDORS)} invoices in {OUT_DIR}/")
    print("Seeded problems: INV-1003 wrong total, INV-1005 missing date.")


if __name__ == "__main__":
    main()
