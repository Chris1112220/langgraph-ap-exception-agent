"""app/tools.py - the agent's tools.

A 'tool' is just a normal, deterministic Python function the LLM is allowed to call.
Rule of thumb: let the LLM *decide*, let code *calculate*. Matching numbers and
querying databases is code's job - it's exact, testable, and never hallucinates.
"""
import re
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from app.db import get_conn
from app.models import DuplicateResult, LineCheck, MatchResult, VendorResult

PRICE_TOLERANCE_PCT = 2.0  # AP policy: unit-price variance within 2% is acceptable

_SUFFIXES = r"\b(llc|inc|co|corp|company|ltd)\b"


def _norm_name(name: str) -> str:
    """'ACME Office Supplies, LLC' -> 'acme office supplies'"""
    name = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return re.sub(r"\s+", " ", re.sub(_SUFFIXES, " ", name)).strip()


def _norm_invoice_no(num: str) -> str:
    """'INV-0045' and '45' -> '45' so formatting tricks don't hide duplicates."""
    digits = re.sub(r"\D", "", num)
    return digits.lstrip("0") or "0"


def get_invoice(invoice_id: str) -> Optional[dict]:
    """Fetch an exception invoice and its lines."""
    with get_conn() as conn:
        inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = %s", (invoice_id,)).fetchone()
        if not inv:
            return None
        inv["lines"] = conn.execute(
            "SELECT line_no, item, qty, unit_price FROM invoice_lines WHERE invoice_id = %s ORDER BY line_no",
            (invoice_id,),
        ).fetchall()
        return inv


def lookup_vendor(vendor_id: Optional[str] = None, vendor_name: Optional[str] = None) -> VendorResult:
    """Find a vendor by ID, or by (fuzzy) name if the ID is missing."""
    with get_conn() as conn:
        if vendor_id:
            v = conn.execute("SELECT * FROM vendors WHERE vendor_id = %s", (vendor_id,)).fetchone()
            if v:
                return VendorResult(found=True, vendor_id=v["vendor_id"], name=v["name"], status=v["status"], match_type="id")
        if not vendor_name:
            return VendorResult(found=False, note="No vendor ID or name provided")
        vendors = conn.execute("SELECT * FROM vendors").fetchall()

    target = _norm_name(vendor_name)
    best, best_score = None, 0.0
    for v in vendors:
        score = SequenceMatcher(None, target, _norm_name(v["name"])).ratio()
        if score > best_score:
            best, best_score = v, score
    if best and best_score == 1.0:
        return VendorResult(found=True, vendor_id=best["vendor_id"], name=best["name"], status=best["status"], match_type="exact_name", similarity=1.0)
    if best and best_score >= 0.85:
        return VendorResult(found=True, vendor_id=best["vendor_id"], name=best["name"], status=best["status"],
                            match_type="fuzzy_name", similarity=round(best_score, 3),
                            note="Fuzzy match - a human should confirm before posting")
    return VendorResult(found=False, similarity=round(best_score, 3), note="No vendor close enough to match")


def three_way_match(invoice_id: str) -> MatchResult:
    """Compare invoice vs. PO vs. goods receipt, line by line."""
    inv = get_invoice(invoice_id)
    if not inv:
        return MatchResult(po_found=False, note=f"Invoice {invoice_id} not found")

    lines_sum = sum((Decimal(l["qty"]) * Decimal(l["unit_price"]) for l in inv["lines"]), Decimal("0"))
    base = dict(invoice_total=inv["total"], lines_sum=lines_sum, total_matches_lines=(lines_sum == inv["total"]))

    if not inv["po_number"]:
        return MatchResult(po_found=False, note="Invoice has no PO number", **base)

    with get_conn() as conn:
        po = conn.execute("SELECT * FROM purchase_orders WHERE po_number = %s", (inv["po_number"],)).fetchone()
        suggested = None
        if not po:
            # Common OCR/typing error: letter O instead of zero
            fixed = inv["po_number"].upper().replace("O", "0").replace("P0-", "PO-")
            alt = conn.execute("SELECT * FROM purchase_orders WHERE po_number = %s", (fixed,)).fetchone()
            if alt:
                po, suggested = alt, fixed
            else:
                return MatchResult(po_found=False, po_number=inv["po_number"], note="PO not found", **base)
        po_lines = conn.execute("SELECT * FROM po_lines WHERE po_number = %s", (po["po_number"],)).fetchall()
        receipts = conn.execute(
            "SELECT line_no, SUM(qty_received) AS qty FROM receipts WHERE po_number = %s GROUP BY line_no",
            (po["po_number"],),
        ).fetchall()
    received = {r["line_no"]: r["qty"] for r in receipts}

    checks: list[LineCheck] = []
    for line in inv["lines"]:
        po_line = next((p for p in po_lines if p["item"].lower() == line["item"].lower()), None)
        if po_line is None:
            # Same product, different unit of measure? e.g. 'slides (each)' vs 'slides (case of 12)'
            stem = line["item"].split("(")[0].strip().lower()
            uom = next((p for p in po_lines if p["item"].split("(")[0].strip().lower() == stem), None)
            if uom:
                checks.append(LineCheck(line_no=line["line_no"], item=line["item"], issue="uom_mismatch",
                                        po_unit_price=uom["unit_price"], invoice_unit_price=line["unit_price"],
                                        po_qty=uom["qty"], billed_qty=line["qty"]))
            else:
                checks.append(LineCheck(line_no=line["line_no"], item=line["item"], issue="not_on_po",
                                        invoice_unit_price=line["unit_price"], billed_qty=line["qty"]))
            continue

        got = received.get(po_line["line_no"])
        variance = float((line["unit_price"] - po_line["unit_price"]) / po_line["unit_price"] * 100)
        common = dict(line_no=line["line_no"], item=line["item"], po_unit_price=po_line["unit_price"],
                      invoice_unit_price=line["unit_price"], variance_pct=round(variance, 2),
                      po_qty=po_line["qty"], received_qty=got, billed_qty=line["qty"])
        if got is None:
            issue = "no_receipt"
        elif line["qty"] > got:
            issue = "over_billed_vs_received"
        elif abs(variance) > PRICE_TOLERANCE_PCT:
            issue = "price_variance"
        elif line["qty"] != po_line["qty"]:
            issue = "qty_differs_from_po"
        else:
            issue = "ok"
        checks.append(LineCheck(issue=issue, **common))

    return MatchResult(po_found=True, po_number=po["po_number"], suggested_po=suggested, po_status=po["status"],
                       po_vendor_matches=(inv["vendor_id"] is None or po["vendor_id"] == inv["vendor_id"]),
                       lines=checks, **base)


def check_duplicate(invoice_id: str) -> DuplicateResult:
    """Has this vendor already billed us this invoice number (ignoring formatting)?"""
    inv = get_invoice(invoice_id)
    if not inv or not inv["vendor_id"]:
        return DuplicateResult(is_duplicate=False, note="Need a known vendor to check duplicates")
    key = _norm_invoice_no(inv["invoice_number"])
    with get_conn() as conn:
        posted = conn.execute("SELECT * FROM posted_invoices WHERE vendor_id = %s", (inv["vendor_id"],)).fetchall()
        others = conn.execute("SELECT * FROM invoices WHERE vendor_id = %s AND invoice_id <> %s",
                              (inv["vendor_id"], invoice_id)).fetchall()
    for p in posted:
        if _norm_invoice_no(p["invoice_number"]) == key:
            return DuplicateResult(is_duplicate=True, matched_invoice_number=p["invoice_number"], matched_total=p["total"],
                                   source="posted", note="Already paid - do not pay again")
    for o in others:
        if _norm_invoice_no(o["invoice_number"]) == key:
            return DuplicateResult(is_duplicate=True, matched_invoice_number=o["invoice_number"], matched_total=o["total"],
                                   source="open_exception")
    return DuplicateResult(is_duplicate=False)