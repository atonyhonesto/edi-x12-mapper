"""Receive two interchanges, map each 850 to JSON, and build the 997 that goes back."""
import json
from datetime import datetime
from pathlib import Path

from x12map.ack997 import build_997
from x12map.map850 import map_850
from x12map.parser import parse

NOW = datetime(2026, 10, 5, 9, 31)          # fixed so the output is repeatable

for name in ("850_good.edi", "850_batch_with_errors.edi"):
    ic = parse((Path(__file__).parent / "samples" / name).read_text())
    print(f"=== {name}: interchange {ic.control} from {ic.sender} to {ic.receiver}, "
          f"delimiters {ic.element_sep!r} {ic.component_sep!r} {ic.segment_term!r}")
    for group in ic.groups:
        results = {}
        for tx in group.transactions:
            order, issues = map_850(tx)
            results[tx.control] = issues
            if issues:
                print(f"--- 850 {tx.control}: REJECTED")
                for i in issues:
                    where = f"{i.segment}{i.element:02d}" if i.element else (i.segment or "SE")
                    print(f"    {where:<6} {i.text}")
            else:
                print(f"--- 850 {tx.control}: accepted, canonical JSON for the ERP:")
                print(json.dumps(order, indent=2) if name == "850_good.edi" else
                      f"    PO {order['po_number']}, {len(order['lines'])} lines, total {order['total']:.2f}")
        print("--- 997 sent back:")
        print("    " + build_997(ic, group, results, now=NOW).replace("~", "~\n    ").rstrip())
