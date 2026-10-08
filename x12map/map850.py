"""Map an X12 850 purchase order to a canonical JSON document.

This is the job a BizTalk map (or a Logic Apps Liquid/XSLT map) does: the trading
partner's structure goes in, the shape your ERP expects comes out, and anything the
business can't accept is reported back rather than silently dropped.
"""
from __future__ import annotations

from datetime import datetime

from .parser import Issue, Segment, Transaction

PARTY_ROLES = {"ST": "ship_to", "BT": "bill_to", "BY": "buyer", "SE": "seller", "VN": "vendor"}
ID_QUALIFIERS = {"BP": "buyer_part", "VP": "vendor_part", "UP": "upc", "IN": "buyer_item", "VN": "vendor_item"}


def _date(yyyymmdd: str) -> str | None:
    try:
        return datetime.strptime(yyyymmdd, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def map_850(tx: Transaction) -> tuple[dict, list[Issue]]:
    """Returns (canonical order, issues). Issues carry the codes a 997 needs."""
    errors: list[Issue] = list(tx.issues)
    order: dict = {"document": "purchase_order", "control_number": tx.control, "purpose": None,
                   "po_number": None, "po_date": None, "parties": {}, "lines": []}
    party: dict | None = None
    line: dict | None = None
    ctt: Segment | None = None
    for s in tx.segments:
        if s.id == "BEG":
            order["purpose"] = {"00": "original", "01": "cancellation", "05": "replace"}.get(s.get(1), s.get(1))
            order["po_number"] = s.get(3)
            order["po_date"] = _date(s.get(5))
            if not s.get(3):
                errors.append(Issue("element", "1", "BEG03 (purchase order number) is required", "BEG", s.position, 3))
            if s.get(5) and not order["po_date"]:
                errors.append(Issue("element", "8", f"BEG05 '{s.get(5)}' is not a valid date", "BEG", s.position, 5))
        elif s.id == "REF":
            order.setdefault("references", {})[s.get(1)] = s.get(2)
        elif s.id == "DTM":
            order.setdefault("dates", {})[{"002": "delivery_requested", "010": "ship_requested"}.get(s.get(1), s.get(1))] = _date(s.get(2))
        elif s.id == "N1":
            party = {"name": s.get(2), "id": s.get(4)}
            order["parties"][PARTY_ROLES.get(s.get(1), s.get(1))] = party
        elif s.id == "N3" and party is not None:
            party["street"] = s.get(1)
        elif s.id == "N4" and party is not None:
            party.update(city=s.get(1), state=s.get(2), postal_code=s.get(3), country=s.get(4) or "US")
        elif s.id == "PO1":
            try:
                qty, price = float(s.get(2)), float(s.get(4) or 0)
            except ValueError:
                errors.append(Issue("element", "6", "PO102 quantity and PO104 price must be numeric", "PO1", s.position, 2))
                qty, price = 0.0, 0.0
            line = {"line": s.get(1), "quantity": qty, "uom": s.get(3), "unit_price": price,
                    "extended": round(qty * price, 2), "ids": {}}
            # PO106/PO107, PO108/PO109 ... are qualifier/value pairs
            for q in range(6, len(s.elements) + 1, 2):
                if s.get(q):
                    line["ids"][ID_QUALIFIERS.get(s.get(q), s.get(q))] = s.get(q + 1)
            order["lines"].append(line)
        elif s.id == "PID" and line is not None:
            line["description"] = s.get(5)
        elif s.id == "CTT":
            ctt = s
    order["total"] = round(sum(l["extended"] for l in order["lines"]), 2)
    if ctt is not None and ctt.get(1) and int(ctt.get(1)) != len(order["lines"]):
        errors.append(Issue("element", "7", f"CTT01 says {ctt.get(1)} lines, found {len(order['lines'])}", "CTT", ctt.position, 1))
    if "ship_to" not in order["parties"]:
        errors.append(Issue("segment", "3", "no ship-to party (N1*ST)", "N1"))
    return order, errors
