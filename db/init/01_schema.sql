-- 01_schema.sql - runs automatically the first time the database container starts.
CREATE EXTENSION IF NOT EXISTS vector;   -- turns on pgvector (vector search) for later

CREATE TABLE vendors (
    vendor_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',   -- active | on_hold | inactive
    payment_terms  TEXT NOT NULL DEFAULT 'Net 30',
    tax_id         TEXT
);

CREATE TABLE purchase_orders (
    po_number   TEXT PRIMARY KEY,
    vendor_id   TEXT NOT NULL REFERENCES vendors(vendor_id),
    po_date     DATE NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'          -- open | closed
);

CREATE TABLE po_lines (
    po_number   TEXT REFERENCES purchase_orders(po_number),
    line_no     INT,
    item        TEXT NOT NULL,
    qty         NUMERIC(12,2) NOT NULL,
    unit_price  NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (po_number, line_no)
);

CREATE TABLE receipts (                                -- what the warehouse actually received
    receipt_id  SERIAL PRIMARY KEY,
    po_number   TEXT REFERENCES purchase_orders(po_number),
    line_no     INT,
    qty_received NUMERIC(12,2) NOT NULL,
    received_on DATE NOT NULL
);

CREATE TABLE invoices (                                -- invoices that FAILED validation in the Gemini tool
    invoice_id      TEXT PRIMARY KEY,
    vendor_id       TEXT,
    vendor_name_on_invoice TEXT,
    invoice_number  TEXT NOT NULL,
    po_number       TEXT,
    invoice_date    DATE,
    total           NUMERIC(12,2),
    raw_text        TEXT,                              -- extracted text, used later for guardrail tests
    failure_reason  TEXT,                              -- why validation failed
    status          TEXT NOT NULL DEFAULT 'exception'  -- exception | proposed | approved | rejected
);

CREATE TABLE invoice_lines (
    invoice_id  TEXT REFERENCES invoices(invoice_id),
    line_no     INT,
    item        TEXT,
    qty         NUMERIC(12,2),
    unit_price  NUMERIC(12,2),
    PRIMARY KEY (invoice_id, line_no)
);

CREATE TABLE posted_invoices (                         -- history, used for duplicate detection
    vendor_id      TEXT,
    invoice_number TEXT,
    total          NUMERIC(12,2),
    posted_on      DATE
);
