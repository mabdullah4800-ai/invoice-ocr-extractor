"""
extractor.py
------------
Reads an invoice PDF and asks a vision model to return its contents as
structured JSON: vendor, invoice number, date, line items and totals.

The model is reached through OpenRouter (an OpenAI-compatible gateway),
using a Gemini vision model. OpenRouter means the same code can switch
to a different model by changing one string.

Two things this module is deliberately careful about:

  * It never trusts the model to return clean JSON. The reply can arrive
    wrapped in ``` fences or with a stray sentence in front of it, so the
    JSON is extracted defensively and a parse failure is reported, not
    crashed on.
  * The prompt tells the model to return null for anything it cannot read
    confidently, rather than guess. A guessed value looks just as
    confident as a correct one -- a null can at least be flagged.

This module only extracts. Checking whether the numbers are *right* is
the validator's job.
"""

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI

# Model is routed through OpenRouter. Swapping providers is a one-line change.
MODEL = "google/gemini-2.0-flash-001"

# Top-level fields we expect on every invoice (line_items handled separately).
EXPECTED_FIELDS = [
    "vendor_name", "vendor_address", "invoice_number", "invoice_date",
    "currency", "subtotal", "tax", "total",
]

PROMPT = """You are reading a supplier invoice. Extract its contents and reply
with ONLY a JSON object -- no markdown, no code fences, no commentary.

Use exactly this structure:
{
  "vendor_name": string,
  "vendor_address": string,
  "invoice_number": string,
  "invoice_date": "YYYY-MM-DD",
  "currency": string,
  "line_items": [
    {"description": string, "quantity": number, "unit_price": number, "line_total": number}
  ],
  "subtotal": number,
  "tax": number,
  "total": number
}

Rules:
- All money and quantity fields must be numbers, not strings. No currency
  symbols, no thousands separators (write 1234.50, not "EUR 1,234.50").
- If a field is not on the invoice, or you cannot read it confidently, set
  it to null. Do not guess a value.
- Output the JSON object and nothing else.
"""


@dataclass
class Extraction:
    """The outcome of trying to extract one invoice.

    If `error` is set, extraction failed and `data` is empty. Callers
    must check `error` before using `data` -- a failure is a result to
    record, not an exception to ignore.
    """
    source_file: str
    data: dict = field(default_factory=dict)
    error: str | None = None


def get_client() -> OpenAI:
    """Build an OpenRouter client, or fail with a clear setup message."""
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env "
            "and add your OpenRouter key."
        )
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)


def pdf_to_images(pdf_path: Path) -> list[bytes]:
    """Render every page of the PDF to PNG bytes (200 dpi for legible text)."""
    images = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            images.append(page.get_pixmap(dpi=200).tobytes("png"))
    return images


def extract_json(text: str) -> dict:
    """Pull a JSON object out of the model's reply.

    Tolerates ``` fences and stray text by taking everything between the
    first '{' and the last '}'. Raises ValueError if that is not valid
    JSON, so the caller can record a clean failure.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop a leading ```json (or ```) fence and anything after the close.
        cleaned = cleaned.split("```")[1]
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in the model's response")
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"model returned malformed JSON: {exc}") from exc


def extract_invoice(pdf_path: str | Path, client: OpenAI) -> Extraction:
    """Extract one invoice PDF into an Extraction result.

    Any failure -- rendering, the API call, or JSON parsing -- is caught
    and returned as `error`, so a bad invoice never stops a batch run.
    """
    pdf_path = Path(pdf_path)
    try:
        images = pdf_to_images(pdf_path)

        # Build a multimodal message: the prompt followed by each page image.
        content: list[dict] = [{"type": "text", "text": PROMPT}]
        for img in images:
            b64 = base64.b64encode(img).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0,  # deterministic: same invoice -> same extraction
        )
        raw = response.choices[0].message.content or ""
        data = extract_json(raw)
    except Exception as exc:
        return Extraction(source_file=pdf_path.name, error=str(exc))

    # Normalise: guarantee every expected key exists so downstream code
    # can rely on the shape. A partial response just leaves Nones behind,
    # which the validator will flag.
    for key in EXPECTED_FIELDS:
        data.setdefault(key, None)
    if not isinstance(data.get("line_items"), list):
        data["line_items"] = []

    return Extraction(source_file=pdf_path.name, data=data, error=None)


if __name__ == "__main__":
    # Smoke test: extract a single invoice and print the JSON.
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "invoices/INV-1001.pdf"
    result = extract_invoice(target, get_client())
    if result.error:
        print(f"{result.source_file}: EXTRACTION FAILED -- {result.error}")
    else:
        print(f"{result.source_file}:")
        print(json.dumps(result.data, indent=2))
