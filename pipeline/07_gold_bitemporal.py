"""Gold: the bitemporal core.

Turns silver.num (facts attached to filings, unordered) into knowledge
intervals: for each natural key, the windows during which each value was
the most recently published one.

Mirrors src/hindsight/precedence.py. That module is the correctness oracle:
its 26 unit tests define the rules, and invariant I5 asserts this Spark
implementation agrees with it on real data.

Rule rationale, the segments bug, and the SIGN_FLIP tightening are all
documented in DECISIONS.md.
"""

import dlt
from pyspark.sql import functions as F, Window, SparkSession

spark = SparkSession.builder.getOrCreate()

OPEN_END = "9999-12-31 00:00:00"
MATERIALITY = 0.005
KEY = ["cik", "canonical_tag", "ddate", "qtrs", "uom"]


@dlt.table(
    name="hindsight_dev.gold.fact_fundamental_pit",
    comment=(
        "Bitemporal fact table. Grain: one row per (cik, canonical_tag, ddate, "
        "qtrs, uom) per distinct believed value, with the transaction-time "
        "window during which that value was the market's best information. "
        "valid time = ddate/qtrs; transaction time = known_from_ts/known_to_ts."
    ),
    table_properties={"quality": "gold"},
    cluster_by=["cik", "ddate"],
)
@dlt.expect_or_fail("known_from_before_known_to", "known_from_ts < known_to_ts")
@dlt.expect_or_fail("value_not_null", "value IS NOT NULL")
@dlt.expect("revision_seq_positive", "revision_seq >= 1")
def fact_fundamental_pit():
    facts = (
        dlt.read("hindsight_dev.silver.num").alias("n")
        .join(
            dlt.read("hindsight_dev.silver.sub").alias("s")
                .select("adsh", "cik", "accepted_ts", "form", "is_amendment"),
            on="adsh", how="inner",
        )
        .filter(F.col("value").isNotNull())
        .select(
            "cik", "canonical_tag", "ddate", "qtrs", "uom", "value",
            F.col("adsh").alias("source_adsh"),
            F.col("form").alias("source_form"),
            "is_amendment", "accepted_ts", "statement",
        )
    )

    per_filing = Window.partitionBy(*KEY, "source_adsh").orderBy(F.col("value").desc())
    facts = (
        facts.withColumn("_rn", F.row_number().over(per_filing))
             .filter(F.col("_rn") == 1)
             .drop("_rn")
    )

    per_ts = Window.partitionBy(*KEY, "accepted_ts").orderBy(F.col("source_adsh").desc())
    facts = (
        facts.withColumn("_rn2", F.row_number().over(per_ts))
             .filter(F.col("_rn2") == 1)
             .drop("_rn2")
    )

    w = Window.partitionBy(*KEY).orderBy(
        F.col("accepted_ts").asc(), F.col("source_adsh").asc()
    )

    seq = facts.withColumn("prev_value", F.lag("value").over(w))

    changes = seq.filter(
        F.col("prev_value").isNull() | (F.col("value") != F.col("prev_value"))
    )

    w2 = Window.partitionBy(*KEY).orderBy(
        F.col("accepted_ts").asc(), F.col("source_adsh").asc()
    )

    intervals = (
        changes
        .withColumn("revision_seq", F.row_number().over(w2))
        .withColumn("prev_value", F.lag("value").over(w2))
        .withColumn("known_from_ts", F.col("accepted_ts"))
        .withColumn(
            "known_to_ts",
            F.coalesce(F.lead("accepted_ts").over(w2), F.lit(OPEN_END).cast("timestamp")),
        )
    )

    pct = F.when(
        F.col("prev_value").isNotNull() & (F.col("prev_value") != 0),
        F.abs(F.col("value") - F.col("prev_value")) / F.abs(F.col("prev_value")),
    )

    ratio = F.when(
        F.col("prev_value").isNotNull() & (F.col("prev_value") != 0) & (F.col("value") != 0),
        F.abs(F.col("value") / F.col("prev_value")),
    )

    near_pow10 = F.lit(False)
    for k in (-3, -2, -1, 1, 2, 3):
        near_pow10 = near_pow10 | ratio.between(0.99 * (10 ** k), 1.01 * (10 ** k))

    mag_preserved = (
        F.abs(F.abs(F.col("value")) - F.abs(F.col("prev_value")))
        / F.abs(F.col("prev_value"))
    ) < 0.02

    change_class = (
        F.when(F.col("prev_value").isNull(), "FIRST_REPORT")
         .when(near_pow10, "UNIT_SCALE")
         .when(pct < MATERIALITY, "IMMATERIAL")
         .when((F.col("prev_value") * F.col("value") < 0) & mag_preserved, "SIGN_FLIP")
         .otherwise("RESTATEMENT")
    )

    return (
        intervals
        .withColumn("change_class", change_class)
        .withColumn("pct_change", pct.cast("double"))
        .withColumn("is_current", F.col("known_to_ts") == F.lit(OPEN_END).cast("timestamp"))
        .select(
            *KEY, "value",
            "known_from_ts", "known_to_ts", "is_current",
            "source_adsh", "source_form", "is_amendment",
            "revision_seq", "prev_value", "change_class", "pct_change",
            "statement",
        )
    )


@dlt.table(
    name="hindsight_dev.gold.fact_revision",
    comment="Material belief changes only. One row per genuine restatement, "
            "with prior value, revised value, magnitude, and the filing that "
            "made the change. Drives the restatement monitor.",
    table_properties={"quality": "gold"},
)
def fact_revision():
    return (
        dlt.read("hindsight_dev.gold.fact_fundamental_pit")
        .filter(F.col("change_class") == "RESTATEMENT")
        .select(
            *KEY, "prev_value",
            F.col("value").alias("revised_value"),
            "pct_change",
            F.col("known_from_ts").alias("revised_at_ts"),
            "source_adsh", "source_form", "revision_seq", "statement",
        )
    )