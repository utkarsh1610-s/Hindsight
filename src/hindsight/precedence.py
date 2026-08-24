from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List, Optional

OPEN_END = datetime(9999, 12, 31)

# Below this relative change, a revision is rounding or minor reclassification
# rather than a genuine restatement.
MATERIALITY = Decimal("0.005")   # 0.5%


@dataclass(frozen=True)
class Fact:
    """One fact as reported by one filing."""
    cik: int
    canonical_tag: str
    ddate: str                  # fiscal period end, 'YYYY-MM-DD'
    qtrs: int
    uom: str
    value: Optional[Decimal]
    adsh: str
    accepted_ts: datetime       # transaction time
    form: str = "10-K"

    @property
    def key(self):
        return (self.cik, self.canonical_tag, self.ddate, self.qtrs, self.uom)


@dataclass(frozen=True)
class Interval:
    """One believed value and the window during which it was public."""
    cik: int
    canonical_tag: str
    ddate: str
    qtrs: int
    uom: str
    value: Decimal
    known_from_ts: datetime
    known_to_ts: datetime
    source_adsh: str
    source_form: str
    revision_seq: int
    prev_value: Optional[Decimal]
    change_class: str
    pct_change: Optional[float]

    @property
    def is_current(self) -> bool:
        return self.known_to_ts == OPEN_END


# ordering

def sort_key(f: Fact):
    return (f.accepted_ts, f.adsh)


def is_amendment(form: str) -> bool:
    return form.endswith("/A")


# classification

def _pct_change(prev: Decimal, curr: Decimal) -> Optional[float]:
    if prev is None or prev == 0:
        return None
    return float(abs(curr - prev) / abs(prev))


def _near_power_of_ten(prev: Decimal, curr: Decimal) -> bool:
    if prev == 0 or curr == 0:
        return False
    ratio = abs(float(curr) / float(prev))
    for k in (-3, -2, -1, 1, 2, 3):
        if 0.99 * (10 ** k) <= ratio <= 1.01 * (10 ** k):
            return True
    return False


def classify_revision(prev: Optional[Decimal], curr: Decimal) -> str:
    if prev is None:
        return "FIRST_REPORT"
    if prev == curr:
        return "IDENTICAL"
    if _near_power_of_ten(prev, curr):
        return "UNIT_SCALE"

    pct = _pct_change(prev, curr)
    if pct is not None and pct < float(MATERIALITY):
        return "IMMATERIAL"

    # magnitude preserved within 2% AND sign reversed -> presentation artefact
    if prev * curr < 0:
        mag = abs(abs(float(curr)) - abs(float(prev))) / abs(float(prev))
        if mag < 0.02:
            return "SIGN_FLIP"

    return "RESTATEMENT"


# interval building

def build_intervals(facts: Iterable[Fact]) -> List[Interval]:
    ordered = sorted((f for f in facts if f.value is not None), key=sort_key)
    if not ordered:
        return []

    keys = {f.key for f in ordered}
    if len(keys) > 1:
        raise ValueError(f"build_intervals expects one natural key, got {len(keys)}")

    per_filing = {}
    for f in ordered:
        cur = per_filing.get(f.adsh)
        if cur is None or f.value > cur.value:
            per_filing[f.adsh] = f
    ordered = sorted(per_filing.values(), key=sort_key)

    collapsed: List[Fact] = []
    for f in ordered:
        if collapsed and collapsed[-1].accepted_ts == f.accepted_ts:
            collapsed[-1] = f
        else:
            collapsed.append(f)

    out: List[Interval] = []
    seq = 0
    prev_value: Optional[Decimal] = None

    for f in ordered:
        if out and f.value == out[-1].value:
            continue

        if out:  
            out[-1] = _replace_end(out[-1], f.accepted_ts)

        seq += 1
        cls = classify_revision(prev_value, f.value)
        out.append(Interval(
            cik=f.cik, canonical_tag=f.canonical_tag, ddate=f.ddate,
            qtrs=f.qtrs, uom=f.uom, value=f.value,
            known_from_ts=f.accepted_ts, known_to_ts=OPEN_END,
            source_adsh=f.adsh, source_form=f.form,
            revision_seq=seq, prev_value=prev_value,
            change_class=cls,
            pct_change=_pct_change(prev_value, f.value) if prev_value is not None else None,
        ))
        prev_value = f.value

    return out


def _replace_end(iv: Interval, end: datetime) -> Interval:
    return Interval(**{**iv.__dict__, "known_to_ts": end})


# as-of lookup

def as_of(intervals: Iterable[Interval], ts: datetime) -> Optional[Interval]:
    for iv in intervals:
        if iv.known_from_ts <= ts < iv.known_to_ts:
            return iv
    return None