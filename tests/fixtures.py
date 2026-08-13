GROUND_TRUTH = [
    {
        "company": "AT&T INC.", "cik": 732717,
        "tag": "Revenues", "ddate": "20211231", "qtrs": 4,
        "original": 168_864_000_000, "revised": 134_038_000_000,
        "adsh_original": "0000732717-22-000015",
        "adsh_revised":  "0000732717-24-000009",
        "expected_class": "RESTATEMENT",
        "cause": "WarnerMedia separation -> discontinued ops",
    },
    {
        "company": "ZILLOW GROUP, INC.", "cik": 1617640,
        "tag": "OperatingIncomeLoss", "ddate": "20211231", "qtrs": 4,
        "original": -327_673_000, "revised": 239_000_000,
        "expected_class": "RESTATEMENT",  
        "cause": "Zillow Offers wind-down; sign crosses zero",
    },
]