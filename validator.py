"""
validator.py
------------
Checks an extracted invoice and decides whether a human needs to look
at it. This is the part of the project that actually matters.

A vision model is good, but it is not always right -- it can misread a
digit, drop a line, or invent a plausible-looking number. In a finance
context, silently trusting that output is the real risk. So every
extraction is checked against arithmetic the invoice must obey:

  * each line:   quantity x unit_price  should equal  line_total
  * the lines:   sum of line_totals     should equal  subtotal
  * the footer:  subtotal + tax         should equal  total

Anything that does not add up, and any field the model returned as null
(it was told to return null rather than guess), becomes a flag. The
invoice is then marked `ok` or `needs_review`. Catching the extraction
error is the entire value here -- a clean spreadsheet full of wrong
numbers is worse than no spreadsheet at all.
"""

from dataclasses import dataclass, field

from extractor import EXPECTED_FIELDS, Extraction

# Money tolerance: 1 cent absorbs ordinary rounding without hiding real errors.
TOLERANCE = 0.01


@dataclass
class ValidationResult:
    """The verdict on one invoice."""
    source_file: str
    status: str                       # "ok", "needs_review" or "extraction_failed"
    issues: list[str] = field(default_factory=list)


def _is_number(value) -> bool:
    """True if value is a usable number (not None, not a leftover string)."""
    return isinstance(value, (int, float))


def validate(extraction: Extraction) -> ValidationResult:
    """Check one extraction and return a ValidationResult."""
    # If extraction itself failed, there is nothing to arithmetic-check.
    if extraction.error:
        return ValidationResult(
            source_file=extraction.source_file,
            status="extraction_failed",
            issues=[f"extraction failed: {extraction.error}"],
        )

    data = extraction.data
    issues: list[str] = []

    # 1. Missing fields -- the model returned null because it could not
    #    read them confidently. Worth a human's eyes.
    for field_name in EXPECTED_FIELDS:
        if data.get(field_name) is None:
            issues.append(f"missing field: {field_name}")

    line_items = data.get("line_items") or []
    if not line_items:
        issues.append("no line items were extracted")

    # 2. Per-line arithmetic: quantity x unit_price should equal line_total.
    for i, item in enumerate(line_items, start=1):
        qty, unit, line_total = item.get("quantity"), item.get("unit_price"), item.get("line_total")
        if not (_is_number(qty) and _is_number(unit) and _is_number(line_total)):
            issues.append(f"line {i}: a number is missing or not numeric")
        elif abs(qty * unit - line_total) > TOLERANCE:
            issues.append(
                f"line {i}: {qty} x {unit} = {qty * unit:.2f}, "
                f"but line_total reads {line_total:.2f}"
            )

    # 3. Line totals should sum to the stated subtotal.
    subtotal = data.get("subtotal")
    numeric_lines = [it.get("line_total") for it in line_items if _is_number(it.get("line_total"))]
    if _is_number(subtotal) and numeric_lines:
        line_sum = sum(numeric_lines)
        if abs(line_sum - subtotal) > TOLERANCE:
            issues.append(
                f"line totals sum to {line_sum:.2f}, but subtotal reads {subtotal:.2f}"
            )

    # 4. subtotal + tax should equal the stated total.
    tax, total = data.get("tax"), data.get("total")
    if _is_number(subtotal) and _is_number(tax) and _is_number(total):
        if abs(subtotal + tax - total) > TOLERANCE:
            issues.append(
                f"subtotal + tax = {subtotal + tax:.2f}, but total reads {total:.2f}"
            )

    status = "ok" if not issues else "needs_review"
    return ValidationResult(extraction.source_file, status, issues)


if __name__ == "__main__":
    # Smoke test: extract and validate the two invoices with seeded
    # problems -- INV-1003 (wrong total) and INV-1005 (missing date).
    from extractor import extract_invoice, get_client

    client = get_client()
    for name in ("invoices/INV-1003.pdf", "invoices/INV-1005.pdf"):
        result = validate(extract_invoice(name, client))
        print(f"{result.source_file}: {result.status}")
        for issue in result.issues:
            print(f"  - {issue}")
