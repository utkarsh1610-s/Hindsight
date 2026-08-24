"""Bitemporal precedence resolution.

Turns an unordered set of reported facts into knowledge intervals: for each
natural key, the windows during which each value was the most recently
published one.

Pure Python -- no Spark, no dlt. Testable against small fixtures.
See DECISIONS.md and the project spec for rule rationale.
"""

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


# ---------------------------------------------------------------- ordering

def sort_key(f: Fact):
    """P1: order by acceptance time.
    P2: ties break deterministically by accession number, descending.

    Acceptance time is when the document became public. Filing date lacks
    time granularity; fiscal period is valid time and says nothing about
    when anything was known.
    """
    return (f.accepted_ts, f.adsh)


def is_amendment(form: str) -> bool:
    return form.endswith("/A")


# ---------------------------------------------------------- classification

def _pct_change(prev: Decimal, curr: Decimal) -> Optional[float]:
    if prev is None or prev == 0:
        return None
    return float(abs(curr - prev) / abs(prev))


def _near_power_of_ten(prev: Decimal, curr: Decimal) -> bool:
    """Reporting-scale change, e.g. thousands -> millions."""
    if prev == 0 or curr == 0:
        return False
    ratio = abs(float(curr) / float(prev))
    for k in (-3, -2, -1, 1, 2, 3):
        if 0.99 * (10 ** k) <= ratio <= 1.01 * (10 ** k):
            return True
    return False


def classify_revision(prev: Optional[Decimal], curr: Decimal) -> str:
    """Separate genuine restatements from artefacts.

    NOTE on SIGN_FLIP: a sign reversal is only an artefact when magnitude is
    roughly preserved. Zillow FY2021 OperatingIncomeLoss went -327.7M -> +239.0M,
    which crosses zero but is real economics (Zillow Offers wind-down). A naive
    sign-flip rule would discard one of the most consequential restatements in
    the dataset. See tests/fixtures.py.
    """
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


# ------------------------------------------------------- interval building

def build_intervals(facts: Iterable[Fact]) -> List[Interval]:
    """Collapse one natural key's facts into knowledge intervals.

    All facts must share the same key. Rules applied:
      P1/P2  order by (accepted_ts, adsh)
      P4     an identical re-report extends the current interval rather than
             opening a new one -- without this, most keys accumulate dozens
             of meaningless intervals and the revision feed is mostly noise
      P6     a null value never supersedes a real number
    """
    ordered = sorted((f for f in facts if f.value is not None), key=sort_key)
    if not ordered:
        return []

    keys = {f.key for f in ordered}
    if len(keys) > 1:
        raise ValueError(f"build_intervals expects one natural key, got {len(keys)}")

    out: List[Interval] = []
    seq = 0
    prev_value: Optional[Decimal] = None

    for f in ordered:
        # P4: same value re-reported -- extend, don't open a new interval
        if out and f.value == out[-1].value:
            continue

        if out:  # close the previous interval at this filing's acceptance
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


# ----------------------------------------------------------- as-of lookup

def as_of(intervals: Iterable[Interval], ts: datetime) -> Optional[Interval]:
    """Reference implementation of the as-of contract.

    Returns the interval covering ts, or None if nothing was known yet.
    Absence is meaningful: a fact not yet filed is UNKNOWN, not zero and not
    its eventual value. Coalescing that to a default is how future
    information leaks into a backtest.

    This is the oracle for invariant I5 -- the materialised Gold table must
    agree with this for any (key, timestamp).
    """
    for iv in intervals:
        if iv.known_from_ts <= ts < iv.known_to_ts:
            return iv
    return None