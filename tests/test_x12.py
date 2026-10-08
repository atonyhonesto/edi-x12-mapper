import unittest
from datetime import datetime
from pathlib import Path

from x12map.ack997 import build_997
from x12map.map850 import map_850
from x12map.parser import X12Error, parse

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
NOW = datetime(2026, 10, 5, 9, 31)


def load(name):
    return parse((SAMPLES / name).read_text())


class ParserTests(unittest.TestCase):
    def test_delimiters_come_from_isa(self):
        raw = (SAMPLES / "850_good.edi").read_text().replace("*", "|").replace("~", "\n")
        ic = parse(raw)
        self.assertEqual((ic.element_sep, ic.component_sep, ic.segment_term), ("|", ">", "\n"))
        self.assertEqual(map_850(ic.groups[0].transactions[0])[0]["po_number"], "PO-48213")

    def test_rejects_non_x12(self):
        with self.assertRaises(X12Error):
            parse("UNA:+.? 'UNB+UNOC:3")

    def test_envelope_counts(self):
        ic = load("850_good.edi")
        self.assertEqual(ic.errors, [])
        self.assertEqual(len(ic.groups[0].transactions), 1)

    def test_se_count_mismatch_detected(self):
        tx = load("850_batch_with_errors.edi").groups[0].transactions[1]
        self.assertEqual([i.code for i in tx.issues if i.level == "transaction"], ["4"])


class MapperTests(unittest.TestCase):
    def setUp(self):
        self.order, self.issues = map_850(load("850_good.edi").groups[0].transactions[0])

    def test_header(self):
        self.assertEqual(self.issues, [])
        self.assertEqual((self.order["po_number"], self.order["po_date"]), ("PO-48213", "2026-10-05"))
        self.assertEqual(self.order["dates"]["delivery_requested"], "2026-10-12")

    def test_parties_and_lines(self):
        self.assertEqual(self.order["parties"]["ship_to"]["city"], "Indianapolis")
        self.assertEqual(len(self.order["lines"]), 3)
        self.assertEqual(self.order["lines"][2]["ids"], {"buyer_part": "RC-20017", "upc": "012345678905"})
        self.assertAlmostEqual(self.order["total"], 1252.80)

    def test_bad_order_issues(self):
        _, issues = map_850(load("850_batch_with_errors.edi").groups[0].transactions[1])
        found = {(i.segment, i.element, i.code) for i in issues if i.level == "element"}
        self.assertIn(("BEG", 3, "1"), found)
        self.assertIn(("BEG", 5, "8"), found)
        self.assertIn(("PO1", 2, "6"), found)
        self.assertIn(("CTT", 1, "7"), found)


class AckTests(unittest.TestCase):
    def ack(self, name):
        ic = load(name)
        g = ic.groups[0]
        return build_997(ic, g, {t.control: map_850(t)[1] for t in g.transactions}, now=NOW)

    def test_accepted(self):
        segs = self.ack("850_good.edi").split("~")
        self.assertIn("AK5*A", segs)
        self.assertIn("AK9*A*1*1*1", segs)
        isa = segs[0]
        self.assertEqual(len(isa) + 1, 106)
        self.assertIn("PARTSWAREHOUSE *ZZ*RETAILCO", isa)     # sender and receiver swapped

    def test_partial_with_grouped_errors(self):
        segs = self.ack("850_batch_with_errors.edi").split("~")
        self.assertIn("AK9*P*2*2*1", segs)
        self.assertEqual(segs.count("AK3*BEG*2**8"), 1)
        i = segs.index("AK3*BEG*2**8")
        self.assertEqual(segs[i + 1:i + 3], ["AK4*3**1", "AK4*5**8"])

    def test_997_se_count_is_right(self):
        segs = [s for s in self.ack("850_batch_with_errors.edi").split("~") if s]
        st, se = segs.index("ST*997*0001"), next(i for i, s in enumerate(segs) if s.startswith("SE*"))
        self.assertEqual(int(segs[se].split("*")[1]), se - st + 1)


if __name__ == "__main__":
    unittest.main()
