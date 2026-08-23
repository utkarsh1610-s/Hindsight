"""Shared Bronze ingestion helper.

Bronze rule: read everything as STRING, alter nothing, add provenance only.
All typing, filtering, and cleaning happens in Silver.
"""

import dlt
from pyspark.sql import functions as F, types as T , SparkSession

spark = SparkSession.builder.getOrCreate()
VOLUME = "/Volumes/hindsight_dev/bronze/raw"

# Schemas are declared explicitly rather than inferred: inference on 69
# quarters would sample inconsistently and can reorder columns. Verified
# stable across 2013q1 - 2026q1 (10 cols for num.txt).
SCHEMAS = {
    "sub": [
        "adsh", "cik", "name", "sic", "countryba", "stprba", "cityba", "zipba",
        "bas1", "bas2", "baph", "countryma", "stprma", "cityma", "zipma",
        "mas1", "mas2", "countryinc", "stprinc", "ein", "former", "changed",
        "afs", "wksi", "fye", "form", "period", "fy", "fp", "filed", "accepted",
        "prevrpt", "detail", "instance", "nciks", "aciks",
    ],
    "num": [
        "adsh", "tag", "version", "ddate", "qtrs", "uom",
        "segments", "coreg", "value", "footnote",
    ],
    "tag": [
        "tag", "version", "custom", "abstract", "datatype",
        "iord", "crdr", "tlabel", "doc",
    ],
    "pre": [
        "adsh", "report", "line", "stmt", "inpth",
        "rfile", "tag", "version", "plabel", "negating",
    ],
}


def bronze_reader(source: str):
    """Auto Loader stream over one SEC file type across all quarters."""
    schema = T.StructType([T.StructField(c, T.StringType()) for c in SCHEMAS[source]])

    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", f"{VOLUME}/_schema/{source}")
        .option("delimiter", "\t")
        .option("header", "true")
        .option("quote", "")
        .option("escape", "")
        .option("multiLine", "false")
        .option("mode", "PERMISSIVE")
        .option("rescuedDataColumn", "_rescued_data")
        .schema(schema)
        .load(f"{VOLUME}/quarter=*/{source}.txt")
        .select(
            "*",
            F.current_timestamp().alias("_ingested_at"),
            F.col("_metadata.file_path").alias("_source_file"),
            F.regexp_extract(F.col("_metadata.file_path"),
                             r"quarter=(\d{4}q[1-4])", 1).alias("quarter"),
        )
    )