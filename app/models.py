"""app/models.py - Pydantic models: the typed 'shape' of what each tool returns.

Why bother? The LLM and our code both depend on these shapes. Pydantic validates
them at runtime, so a bad value fails loudly here instead of silently later.
"""
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class VendorResult(BaseModel):
    found: bool
    vendor_id: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    match_type: Literal["id", "exact_name", "fuzzy_name", "none"] = "none"
    similarity: Optional[float] = Field(None, description="0-1 name similarity for fuzzy matches")
    note: str = ""


class LineCheck(BaseModel):
    line_no: int
    item: str
    issue: Literal["ok", "price_variance", "over_billed_vs_received", "qty_differs_from_po",
                   "not_on_po", "no_receipt", "uom_mismatch"]
    po_unit_price: Optional[Decimal] = None
    invoice_unit_price: Optional[Decimal] = None
    variance_pct: Optional[float] = None
    po_qty: Optional[Decimal] = None
    received_qty: Optional[Decimal] = None
    billed_qty: Optional[Decimal] = None


class MatchResult(BaseModel):
    po_found: bool
    po_number: Optional[str] = None
    suggested_po: Optional[str] = None
    po_status: Optional[str] = None
    po_vendor_matches: Optional[bool] = None
    lines: list[LineCheck] = []
    lines_sum: Optional[Decimal] = None
    invoice_total: Optional[Decimal] = None
    total_matches_lines: Optional[bool] = None
    note: str = ""


class DuplicateResult(BaseModel):
    is_duplicate: bool
    matched_invoice_number: Optional[str] = None
    matched_total: Optional[Decimal] = None
    source: Optional[Literal["posted", "open_exception"]] = None
    note: str = ""