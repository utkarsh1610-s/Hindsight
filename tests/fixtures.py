GROUND_TRUTH = [
    {
        "company": "AT&T INC.", "cik": 732717,
        "canonical_tag": "REVENUE", "ddate": "2021-12-31", "qtrs": 4,
        "original": 168_864_000_000, "revised": 134_038_000_000,
        "original_adsh": "0000732717-22-000015",
        "original_known_from": "2022-02-16T06:30:00",
        "revised_adsh": "0000732717-23-000011",
        "revised_known_from": "2023-02-13T16:12:00",
        "expected_class": "RESTATEMENT", "expected_pct": 0.2062,
        "cause": "WarnerMedia separation -> discontinued ops. Restated in the "
                 "FY2022 10-K, the first annual report after the April 2022 spin-off.",
    },
    {
        "company": "ZILLOW GROUP, INC.", "cik": 1617640,
        "canonical_tag": "OperatingIncomeLoss", "ddate": "2021-12-31", "qtrs": 4,
        "original": -327_673_000, "revised": 239_000_000,
        "original_adsh": "0001617640-22-000013",
        "original_known_from": "2022-02-10T16:36:00",
        "revised_adsh": "0001617640-23-000010",
        "revised_known_from": "2023-02-15T16:44:00",
        "expected_class": "RESTATEMENT", "expected_pct": 1.7294,
        "cause": "Zillow Offers wind-down. Sign crosses zero but magnitude is "
                 "NOT preserved -- real economics, not a presentation artefact.",
    },
]