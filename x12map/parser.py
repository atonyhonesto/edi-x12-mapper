"""X12 interchange parsing and envelope validation.

An interchange announces its own delimiters: the ISA segment is fixed-width (106 chars),
so the element separator is character 3, the component separator is ISA16 (character 104)
and the segment terminator is character 105. Read them, never assume '*' and '~'.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class X12Error(ValueError):
    pass


@dataclass
class Issue:
    """One problem, at the level a 997 reports it.

    level 'transaction': AK5 code only (1-5), e.g. 4 = segment count mismatch
    level 'segment':     AK3 code (3 = mandatory segment missing, 8 = segment has element errors)
    level 'element':     AK3 code 8 plus AK4 element position and code
                         (1 = mandatory element missing, 6 = invalid character, 8 = invalid date)
    """
    level: str
    code: str
    text: str
    segment: str = ""
    position: int = 0
    element: int = 0


@dataclass
class Segment:
    id: str
    elements: list[str]
    position: int                      # 1-based position inside the transaction set (ST = 1)

    def get(self, n: int, default: str = "") -> str:
        """X12 numbering: element 1 is the first after the segment ID."""
        return self.elements[n - 1] if 0 < n <= len(self.elements) else default


@dataclass
class Transaction:
    set_id: str                        # ST01, e.g. 850
    control: str                       # ST02
    segments: list[Segment] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class Group:
    functional_id: str                 # GS01, e.g. PO
    control: str                       # GS06
    sender: str
    receiver: str
    version: str                       # GS08, e.g. 004010
    transactions: list[Transaction] = field(default_factory=list)


@dataclass
class Interchange:
    sender: str
    receiver: str
    control: str
    element_sep: str
    component_sep: str
    segment_term: str
    groups: list[Group] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def delimiters(raw: str) -> tuple[str, str, str]:
    raw = raw.lstrip()
    if not raw.startswith("ISA") or len(raw) < 106:
        raise X12Error("not an X12 interchange: must start with a 106-character ISA segment")
    return raw[3], raw[104], raw[105]


def parse(raw: str) -> Interchange:
    raw = raw.strip()
    el, comp, term = delimiters(raw)
    segs = [s.strip("\r\n ") for s in raw.split(term)]
    segs = [s.split(el) for s in segs if s]
    isa = segs[0]
    ic = Interchange(isa[6].strip(), isa[8].strip(), isa[13], el, comp, term)
    group = tx = None
    for parts in segs[1:]:
        sid, elems = parts[0], parts[1:]
        if sid == "GS":
            group = Group(elems[0], elems[5], elems[1], elems[2], elems[7])
            ic.groups.append(group)
        elif sid == "ST":
            tx = Transaction(elems[0], elems[1])
            tx.segments.append(Segment("ST", elems, 1))
            group.transactions.append(tx)
        elif sid == "SE":
            tx.segments.append(Segment("SE", elems, len(tx.segments) + 1))
            if int(elems[0]) != len(tx.segments):
                tx.issues.append(Issue("transaction", "4", f"SE01 says {elems[0]} segments, counted {len(tx.segments)}"))
            if elems[1] != tx.control:
                tx.issues.append(Issue("transaction", "3", f"SE02 {elems[1]} does not match ST02 {tx.control}"))
            tx = None
        elif sid == "GE":
            if int(elems[0]) != len(group.transactions):
                ic.errors.append(f"GE01 says {elems[0]} transactions, found {len(group.transactions)}")
            if elems[1] != group.control:
                ic.errors.append(f"GE02 {elems[1]} does not match GS06 {group.control}")
            group = None
        elif sid == "IEA":
            if elems[1] != ic.control:
                ic.errors.append(f"IEA02 {elems[1]} does not match ISA13 {ic.control}")
        elif tx is not None:
            tx.segments.append(Segment(sid, elems, len(tx.segments) + 1))
        else:
            ic.errors.append(f"segment {sid} outside a transaction set")
    return ic
