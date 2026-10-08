"""Build a 997 functional acknowledgment for a received functional group.

AK1 names the group, AK2/AK5 report each transaction set, AK3/AK4 point at the segment
and element in trouble, and AK9 summarises the group: A = accepted, P = partially
accepted, R = rejected.
"""
from __future__ import annotations

from datetime import datetime

from .parser import Group, Interchange, Issue


def _tx_lines(set_id: str, control: str, issues: list[Issue]) -> list[list[str]]:
    out = [["AK2", set_id, control]]
    # Element errors are grouped: one AK3 per segment, with its AK4s beneath it.
    by_segment: dict[tuple[str, int], list[Issue]] = {}
    for i in issues:
        if i.level == "element":
            by_segment.setdefault((i.segment, i.position), []).append(i)
    for (seg, pos), errs in by_segment.items():
        out.append(["AK3", seg, str(pos), "", "8"])                 # 8 = segment has data element errors
        out += [["AK4", str(e.element), "", e.code] for e in errs]
    for i in issues:
        if i.level == "segment":
            out.append(["AK3", i.segment, str(i.position or ""), "", i.code])
    tx_codes = [i.code for i in issues if i.level == "transaction"]
    if not issues:
        out.append(["AK5", "A"])
    else:
        out.append(["AK5", "R", tx_codes[0] if tx_codes else "5"])   # 5 = one or more segments in error
    return out


def build_997(ic: Interchange, group: Group, results: dict[str, list[Issue]],
              control: int = 1, now: datetime | None = None) -> str:
    now = now or datetime.now()
    e, t = ic.element_sep, ic.segment_term
    body = [["ST", "997", f"{control:04d}"], ["AK1", group.functional_id, group.control]]
    accepted = 0
    for tx in group.transactions:
        issues = results.get(tx.control, [])
        body += _tx_lines(tx.set_id, tx.control, issues)
        accepted += not issues
    n = len(group.transactions)
    status = "A" if accepted == n else ("R" if accepted == 0 else "P")
    body.append(["AK9", status, str(n), str(n), str(accepted)])
    body.append(["SE", str(len(body) + 1), f"{control:04d}"])
    # The acknowledgment goes back the other way: sender and receiver swap.
    isa = ["ISA", "00", " " * 10, "00", " " * 10, "ZZ", ic.receiver.ljust(15), "ZZ", ic.sender.ljust(15),
           now.strftime("%y%m%d"), now.strftime("%H%M"), "U", "00401", f"{control:09d}", "0", "P", ic.component_sep]
    gs = ["GS", "FA", ic.receiver, ic.sender, now.strftime("%Y%m%d"), now.strftime("%H%M"), str(control), "X", group.version]
    tail = [["GE", "1", str(control)], ["IEA", "1", f"{control:09d}"]]
    return t.join(e.join(s) for s in [isa, gs, *body, *tail]) + t
