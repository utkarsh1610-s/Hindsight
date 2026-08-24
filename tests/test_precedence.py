from datetime import datetime
from decimal import Decimal

import pytest

from src.hindsight.precedence import (
    Fact, Interval, OPEN_END, build_intervals, classify_revision, as_of, sort_key,
)


def mk(value, accepted, adsh=None, form="10-K", cik=1, tag="REVENUE",
       ddate="2021-12-31", qtrs=4):
    """Terse Fact builder. accepted is 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM'."""
    fmt = "%Y-%m-%d %H:%M" if " " in accepted else "%Y-%m-%d"
    return Fact(
        cik=cik, canonical_tag=tag, ddate=ddate, qtrs=qtrs, uom="USD",
        value=None if value is None else Decimal(str(value)),
        adsh=adsh or f"000000000-00-{abs(hash(accepted)) % 1000000:06d}",
        accepted_ts=datetime.strptime(accepted, fmt), form=form,
    )


# ------------------------------------------------------------------ P1, P2

def test_p1_orders_by_acceptance_not_insertion():
    """Later-accepted wins regardless of input order."""
    ivs = build_intervals([mk(200, "2024-01-01"), mk(100, "2022-01-01")])
    assert [i.value for i in ivs] == [Decimal("100"), Decimal("200")]
    assert ivs[0].known_to_ts == datetime(2024, 1, 1)
    assert ivs[1].known_to_ts == OPEN_END


def test_p1_ignores_fiscal_period_ordering():
    """Valid time must not influence transaction-time ordering."""
    a = mk(100, "2022-01-01", ddate="2021-12-31")
    b = mk(200, "2023-01-01", ddate="2021-12-31")
    assert [f.value for f in sorted([b, a], key=sort_key)] == [Decimal("100"), Decimal("200")]


def test_p2_identical_timestamps_break_deterministically():
    """Same acceptance time must always resolve the same way."""
    a = mk(100, "2022-01-01 09:00", adsh="000000000-22-000001")
    b = mk(200, "2022-01-01 09:00", adsh="000000000-22-000002")
    assert build_intervals([a, b]) == build_intervals([b, a])


# ---------------------------------------------------------------------- P4

def test_p4_identical_reports_do_not_open_new_intervals():
    """The same value re-reported three times is ONE belief, not three."""
    ivs = build_intervals([
        mk(100, "2022-01-01"), mk(100, "2023-01-01"), mk(100, "2024-01-01"),
    ])
    assert len(ivs) == 1
    assert ivs[0].known_to_ts == OPEN_END
    assert ivs[0].revision_seq == 1


def test_p4_value_returning_to_prior_opens_a_new_interval():
    """100 -> 200 -> 100 is three beliefs. The third is not a duplicate of
    the first because a genuine change of mind happened in between."""
    ivs = build_intervals([
        mk(100, "2022-01-01"), mk(200, "2023-01-01"), mk(100, "2024-01-01"),
    ])
    assert [i.value for i in ivs] == [Decimal("100"), Decimal("200"), Decimal("100")]
    assert [i.revision_seq for i in ivs] == [1, 2, 3]


# ---------------------------------------------------------------------- P6

def test_p6_nulls_never_supersede_a_real_value():
    ivs = build_intervals([mk(100, "2022-01-01"), mk(None, "2023-01-01")])
    assert len(ivs) == 1
    assert ivs[0].value == Decimal("100")
    assert ivs[0].known_to_ts == OPEN_END


def test_all_null_yields_nothing():
    assert build_intervals([mk(None, "2022-01-01")]) == []


def test_empty_input():
    assert build_intervals([]) == []


# --------------------------------------------------------------- invariants

def _assert_invariants(ivs):
    """I1 no overlaps, I2 exactly one open, I3 contiguous, I4 monotonic."""
    assert sum(1 for i in ivs if i.known_to_ts == OPEN_END) == 1, "I2"
    ordered = sorted(ivs, key=lambda i: i.known_from_ts)
    for a, b in zip(ordered, ordered[1:]):
        assert a.known_to_ts <= b.known_from_ts, "I1 overlap"
        assert a.known_to_ts == b.known_from_ts, "I3 gap"
    assert [i.revision_seq for i in ordered] == list(range(1, len(ordered) + 1))


def test_invariants_hold_on_a_messy_sequence():
    ivs = build_intervals([
        mk(100, "2020-03-01"), mk(100, "2020-08-01"), mk(150, "2021-03-01"),
        mk(150, "2021-08-01"), mk(90, "2022-03-01"), mk(None, "2022-08-01"),
        mk(90, "2023-03-01"), mk(200, "2024-03-01"),
    ])
    _assert_invariants(ivs)
    assert [i.value for i in ivs] == [Decimal(x) for x in (100, 150, 90, 200)]


def test_mixed_keys_are_rejected():
    """Guard against silently merging two different facts' timelines."""
    with pytest.raises(ValueError):
        build_intervals([mk(100, "2022-01-01", tag="REVENUE"),
                         mk(200, "2023-01-01", tag="ASSETS")])


# ------------------------------------------------------------ as-of contract

@pytest.fixture
def timeline():
    return build_intervals([mk(100, "2022-02-16"), mk(70, "2024-02-23")])


@pytest.mark.parametrize("when,expected", [
    ("2021-01-01", None),            # nothing filed yet -- UNKNOWN, not zero
    ("2022-02-15", None),            # day before acceptance
    ("2022-02-16", Decimal("100")),  # boundary is inclusive at known_from
    ("2023-06-01", Decimal("100")),
    ("2024-02-23", Decimal("70")),   # boundary is exclusive at known_to
    ("2026-01-01", Decimal("70")),
])
def test_as_of_returns_what_was_knowable(timeline, when, expected):
    got = as_of(timeline, datetime.fromisoformat(when))
    assert (got.value if got else None) == expected


def test_absence_is_not_zero(timeline):
    """The single most important property. A fact not yet filed must be
    UNKNOWN. Coalescing to zero or to the eventual value is how future
    information leaks into a backtest."""
    assert as_of(timeline, datetime(2020, 1, 1)) is None


# ------------------------------------------------------------ classification

@pytest.mark.parametrize("prev,curr,expected", [
    (None,        100,        "FIRST_REPORT"),
    (100,         100,        "IDENTICAL"),
    (1000,        1002,       "IMMATERIAL"),     # 0.2%
    (1000,        1_000_000,  "UNIT_SCALE"),     # thousands -> billions
    (1000,        -1000,      "SIGN_FLIP"),      # magnitude preserved
    (1000,        1500,       "RESTATEMENT"),    # 50%
    (168_864,     134_038,    "RESTATEMENT"),    # AT&T, 20.6%
])
def test_classify_revision(prev, curr, expected):
    p = None if prev is None else Decimal(str(prev))
    assert classify_revision(p, Decimal(str(curr))) == expected


def test_zillow_sign_change_is_a_restatement_not_an_artefact():
    """Regression guard. FY2021 OperatingIncomeLoss went -327.7M -> +239.0M.
    The sign flips, but magnitude is NOT preserved -- this is the Zillow
    Offers wind-down, genuine economics. A naive sign-flip rule would
    discard one of the largest real restatements in the dataset."""
    assert classify_revision(Decimal("-327673000"), Decimal("239000000")) == "RESTATEMENT"


# --------------------------------------------------- real-data regressions

def test_att_fy2021_revenue_timeline():
    """Ground truth, verified against both filings on EDGAR."""
    ivs = build_intervals([
        mk(168_864_000_000, "2022-02-16 06:30", adsh="0000732717-22-000015", cik=732717),
        mk(134_038_000_000, "2024-02-23 16:45", adsh="0000732717-24-000009", cik=732717),
    ])
    _assert_invariants(ivs)
    assert len(ivs) == 2
    assert ivs[1].change_class == "RESTATEMENT"
    assert round(ivs[1].pct_change, 3) == 0.206

    # What a mid-2023 backtest must see
    assert as_of(ivs, datetime(2023, 6, 1)).value == Decimal("168864000000")
    # What is true today
    assert as_of(ivs, datetime(2026, 8, 1)).value == Decimal("134038000000")