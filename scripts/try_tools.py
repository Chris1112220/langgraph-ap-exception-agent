"""Quick manual check of the Day 2 tools. Run: python scripts/try_tools.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # let 'import app' work from scripts/

from app.tools import check_duplicate, get_invoice, lookup_vendor, three_way_match

for inv_id in ["EX-001", "EX-002", "EX-004", "EX-007", "EX-013", "EX-014", "EX-017", "EX-020"]:
    inv = get_invoice(inv_id)
    v = lookup_vendor(inv["vendor_id"], inv["vendor_name_on_invoice"])
    m = three_way_match(inv_id)
    d = check_duplicate(inv_id) if v.vendor_id else None
    issues = [f"{l.item}: {l.issue}" + (f" ({l.variance_pct}%)" if l.issue == "price_variance" else "") for l in m.lines]
    print(f"{inv_id} | vendor={v.name} [{v.match_type}{', ' + str(v.similarity) if v.similarity else ''}] status={v.status}"
          f" | PO={m.po_number}{' (fixed from ' + inv['po_number'] + ')' if m.suggested_po else ''}"
          f" | {issues} | duplicate={d.is_duplicate if d else 'n/a'}{' of ' + d.matched_invoice_number if d and d.is_duplicate else ''}")