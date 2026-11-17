"""Tests for the Day 2 AP tools. The database is faked, so no Postgres and no API keys."""
from contextlib import contextmanager
from decimal import Decimal

from app.models import DuplicateResult, MatchResult, VendorResult
from app.tools import (
    PRICE_TOLERANCE_PCT,
    check_duplicate,
    lookup_vendor,
    three_way_match,
    _norm_invoice_no,
    _norm_name,
)


class _Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        if self.value is None:
            return None
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value

    def fetchall(self):
        if self.value is None:
            return []
        if isinstance(self.value, list):
            return self.value
        return [self.value]


class FakeConn:
    """Pretends to be a psycopg connection. A handler decides what each query returns."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _Result(self.handler(sql, params))


def patch_conn(monkeypatch, handler):
    conn = FakeConn(handler)

    @contextmanager
    def fake_get_conn():
        yield conn

    monkeypatch.setattr("app.tools.get_conn", fake_get_conn)
    return conn


def _sql(sql: str) -> str:
    return " ".join(sql.lower().split())


# --- 1. Normalization helpers -------------------------------------------------

def test_name_and_invoice_normalization():
    assert _norm_name("ACME Office Supplies, LLC") == "acme office supplies"
    assert _norm_name("Acme Office Supplies Inc.") == "acme office supplies"
    assert _norm_invoice_no("INV-0045") == "45"
    assert _norm_invoice_no("45") == "45"
    assert _norm_invoice_no("000") == "0"


# --- 2. Vendor lookup ---------------------------------------------------------

VENDORS = [
    {"vendor_id": "V-001", "name": "ACME Office Supplies, LLC", "status": "active"},
    {"vendor_id": "V-002", "name": "Northwind Paper Co", "status": "on_hold"},
]


def test_lookup_vendor_id_exact_fuzzy_and_miss(monkeypatch):
    def handler(sql, params):
        s = _sql(sql)
        if "from vendors where vendor_id" in s:
            return next((v for v in VENDORS if v["vendor_id"] == params[0]), None)
        if "from vendors" in s:
            return list(VENDORS)
        raise AssertionError(f"unexpected SQL: {sql}")

    patch_conn(monkeypatch, handler)

    by_id = lookup_vendor(vendor_id="V-002")
    assert by_id == VendorResult(
        found=True, vendor_id="V-002", name="Northwind Paper Co",
        status="on_hold", match_type="id",
    )

    exact = lookup_vendor(vendor_name="ACME Office Supplies, LLC")
    assert exact.found and exact.match_type == "exact_name" and exact.similarity == 1.0
    assert exact.vendor_id == "V-001"

    # Suffixes and a dropped 's' still clear the 0.85 fuzzy threshold.
    fuzzy = lookup_vendor(vendor_name="Acme Office Supply")
    assert fuzzy.found and fuzzy.match_type == "fuzzy_name"
    assert fuzzy.vendor_id == "V-001"
    assert fuzzy.similarity >= 0.85
    assert "human should confirm" in fuzzy.note

    miss = lookup_vendor(vendor_name="Totally Unknown Vendor")
    assert not miss.found and miss.match_type == "none"
    assert miss.similarity is not None and miss.similarity < 0.85

    empty = lookup_vendor()
    assert not empty.found and empty.note == "No vendor ID or name provided"


# --- 3 & 4. Three-way match ---------------------------------------------------

def _invoice(po_number="PO-1001", total="105.00", lines=None, vendor_id="V-001"):
    if lines is None:
        lines = [{"line_no": 1, "item": "Copy paper", "qty": Decimal("10"), "unit_price": Decimal("10.50")}]
    return {
        "invoice_id": "EX-001",
        "vendor_id": vendor_id,
        "invoice_number": "INV-100",
        "po_number": po_number,
        "total": Decimal(total),
        "lines": lines,
    }


def _po(po_number="PO-1001", vendor_id="V-001", status="open"):
    return {"po_number": po_number, "vendor_id": vendor_id, "status": status}


def _po_line(item="Copy paper", qty="10", unit_price="10.00", line_no=1):
    return {"line_no": line_no, "item": item, "qty": Decimal(qty), "unit_price": Decimal(unit_price)}


def _receipt(line_no=1, qty="10"):
    return {"line_no": line_no, "qty": Decimal(qty)}


def _match_handler(invoice, po=None, po_lines=None, receipts=None, typo_map=None):
    """Route SELECT statements to the right fake rows. typo_map: invoice PO -> real PO number."""
    typo_map = typo_map or {}
    po_lines = po_lines or []
    receipts = receipts or []

    def handler(sql, params):
        s = _sql(sql)
        if "from invoices where invoice_id" in s:
            return dict({k: v for k, v in invoice.items() if k != "lines"}) if invoice else None
        if "from invoice_lines" in s:
            return list(invoice["lines"]) if invoice else []
        if "from purchase_orders" in s:
            requested = params[0]
            if po and requested == po["po_number"]:
                return po
            return None
        if "from po_lines" in s:
            return list(po_lines)
        if "from receipts" in s:
            return list(receipts)
        raise AssertionError(f"unexpected SQL: {sql}")

    return handler


def test_three_way_match_flags_price_variance_and_fixes_ocr_po(monkeypatch):
    # Invoice says P0-1001 (letter O / zero typo). Unit price is 5% over the PO, above the 2% tolerance.
    invoice = _invoice(po_number="P0-1001", total="105.00")
    po = _po("PO-1001")
    patch_conn(
        monkeypatch,
        _match_handler(
            invoice,
            po=po,
            po_lines=[_po_line(unit_price="10.00")],
            receipts=[_receipt(qty="10")],
        ),
    )

    result = three_way_match("EX-001")
    assert isinstance(result, MatchResult)
    assert result.po_found is True
    assert result.po_number == "PO-1001"
    assert result.suggested_po == "PO-1001"
    assert result.po_vendor_matches is True
    assert len(result.lines) == 1
    line = result.lines[0]
    assert line.issue == "price_variance"
    assert line.variance_pct == 5.0
    assert PRICE_TOLERANCE_PCT == 2.0
    assert result.total_matches_lines is True

    # Same setup but 1.5% variance is accepted.
    invoice_ok = _invoice(po_number="PO-1001", total="101.50",
                          lines=[{"line_no": 1, "item": "Copy paper", "qty": Decimal("10"),
                                  "unit_price": Decimal("10.15")}])
    patch_conn(
        monkeypatch,
        _match_handler(
            invoice_ok,
            po=_po("PO-1001"),
            po_lines=[_po_line(unit_price="10.00")],
            receipts=[_receipt(qty="10")],
        ),
    )
    ok = three_way_match("EX-001")
    assert ok.suggested_po is None
    assert ok.lines[0].issue == "ok"
    assert ok.lines[0].variance_pct == 1.5


def test_three_way_match_flags_overbill_missing_receipt_and_unknown_invoice(monkeypatch):
    invoice = _invoice(
        total="200.00",
        lines=[
            {"line_no": 1, "item": "Copy paper", "qty": Decimal("12"), "unit_price": Decimal("10.00")},
            {"line_no": 2, "item": "Toner", "qty": Decimal("2"), "unit_price": Decimal("40.00")},
        ],
    )
    patch_conn(
        monkeypatch,
        _match_handler(
            invoice,
            po=_po("PO-1001"),
            po_lines=[
                _po_line(item="Copy paper", qty="10", unit_price="10.00", line_no=1),
                _po_line(item="Toner", qty="2", unit_price="40.00", line_no=2),
            ],
            # Warehouse only booked the paper, and only 10 of 12 billed.
            receipts=[_receipt(line_no=1, qty="10")],
        ),
    )
    result = three_way_match("EX-001")
    issues = {line.item: line.issue for line in result.lines}
    assert issues["Copy paper"] == "over_billed_vs_received"
    assert issues["Toner"] == "no_receipt"

    patch_conn(monkeypatch, _match_handler(None))
    missing = three_way_match("EX-999")
    assert missing.po_found is False
    assert "not found" in missing.note


# --- 5. Duplicate check -------------------------------------------------------

def test_check_duplicate_ignores_invoice_number_formatting(monkeypatch):
    invoice = {
        "invoice_id": "EX-007",
        "vendor_id": "V-001",
        "invoice_number": "INV-0045",
        "po_number": "PO-9",
        "total": Decimal("200.00"),
        "lines": [],
    }
    posted = [{"invoice_number": "45", "total": Decimal("200.00"), "vendor_id": "V-001"}]

    def handler(sql, params):
        s = _sql(sql)
        if "from invoices where invoice_id" in s:
            return dict({k: v for k, v in invoice.items() if k != "lines"})
        if "from invoice_lines" in s:
            return []
        if "from posted_invoices" in s:
            return list(posted)
        if "from invoices where vendor_id" in s:
            return []
        raise AssertionError(f"unexpected SQL: {sql}")

    patch_conn(monkeypatch, handler)
    dup = check_duplicate("EX-007")
    assert isinstance(dup, DuplicateResult)
    assert dup.is_duplicate is True
    assert dup.matched_invoice_number == "45"
    assert dup.matched_total == Decimal("200.00")
    assert dup.source == "posted"
    assert "do not pay again" in dup.note.lower()

    # No posted match, but the same number is already sitting in the exception queue.
    def open_handler(sql, params):
        s = _sql(sql)
        if "from invoices where invoice_id" in s:
            return dict({k: v for k, v in invoice.items() if k != "lines"})
        if "from invoice_lines" in s:
            return []
        if "from posted_invoices" in s:
            return []
        if "from invoices where vendor_id" in s:
            return [{"invoice_number": "00045", "total": Decimal("200.00"), "invoice_id": "EX-006"}]
        raise AssertionError(f"unexpected SQL: {sql}")

    patch_conn(monkeypatch, open_handler)
    open_dup = check_duplicate("EX-007")
    assert open_dup.is_duplicate is True
    assert open_dup.source == "open_exception"
    assert open_dup.matched_invoice_number == "00045"

    def clean_handler(sql, params):
        s = _sql(sql)
        if "from invoices where invoice_id" in s:
            return dict({k: v for k, v in invoice.items() if k != "lines"})
        if "from invoice_lines" in s:
            return []
        if "from posted_invoices" in s:
            return []
        if "from invoices where vendor_id" in s:
            return []
        raise AssertionError(f"unexpected SQL: {sql}")

    patch_conn(monkeypatch, clean_handler)
    clean = check_duplicate("EX-007")
    assert clean.is_duplicate is False
