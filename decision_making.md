# Decisions & Findings

## Phase 0 — Viability

### The segments bug (2026-08-16)
First diff of 2022q1 vs 2024q1 showed 51.2% of facts materially changed.
Implausible — real restatement rates are low single digits.

Diagnostic: balance-sheet instants (qtrs=0) changed at 77.1% vs quarterly
durations at 12.2%. No economic mechanism explains that gap. 2,179 sign
flips out of 10,259 overlapping keys.

Root cause: `segments` was omitted from the natural key, so consolidated
totals collided with per-segment breakdowns. drop_duplicates() then picked
arbitrarily between them.

Fix: `segments` is part of the natural key. Consolidated series requires
blank segments AND blank coreg.
Result: 51.2% -> 5.97%; sign flips 2,179 -> 78.

Why it mattered: segment tagging has grown from 44% (2013) to 60% (2026)
of all facts, so the bug's severity increased over time. Uncorrected, it
would have produced a spurious upward trend in restatement rates — a
plausible-looking but entirely false finding.

### Ground truth fixtures
- AT&T (CIK 732717) FY2021 Revenues: $168.9B -> $134.0B (WarnerMedia
  separation, discontinued ops). Verified against both filings.
- Zillow (CIK 1617640) FY2021 OperatingIncomeLoss: -$327.7M -> +$239.0M.
  Sign crosses zero but this is REAL economics, not a presentation artefact.
  Classifier must not discard it as SIGN_FLIP.

### The 5.97% is not the population rate
Overlap sample is biased: ddate concentrated in 2020-21. Periods appearing
in filings two years apart are disproportionately late re-reports.
Population rate comes from Phase 4 over all 69 quarters.

## Phase 1 — Acquisition

### Scale
69 quarters, 181,351,169 facts, 426,003 submissions, 5.58 GB. Zero failures.

### XBRL phase-in coverage cliff
Facts/quarter: 3,999 (2009q2) -> 2.0M (2011q3) -> ~3.5M plateau.
Reflects the SEC's phased mandate (large accelerated filers 2009, all
filers by mid-2011). Pre-2011 data is NOT comparable to later periods.
Phase 4 experiment window should start 2012 or later.

2009q1 is a headers-only placeholder (0 rows). Expected, not a failure.

### Schema is stable
num.txt has the same 10 columns across 2013-2026. Checked 2013q1, 2020q1,
2025q1, 2025q4, 2026q1. rescuedDataColumn retained as insurance only.

### Filer count decline
Submissions peaked ~9,200 (2012q2), now ~6,200. Real trend — shrinking
count of US public companies. Not a data quality issue.