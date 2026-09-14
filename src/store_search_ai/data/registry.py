from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd


REGISTRY_COLUMNS = [
    "entity_fingerprint",
    "store_id",
    "business_no",
    "created_dataset_version",
]


def assign_store_ids(
    df: pd.DataFrame,
    registry_path: str | Path,
    dataset_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    registry_path = Path(
        registry_path
    )

    if registry_path.exists():

        registry = pd.read_parquet(
            registry_path
        )

    else:

        registry = pd.DataFrame(
            columns=REGISTRY_COLUMNS
        )

    existing = dict(
        zip(
            registry["entity_fingerprint"],
            registry["store_id"],
        )
    )

    unique_entities = (
        df[
            [
                "entity_fingerprint",
                "business_no",
            ]
        ]
        .drop_duplicates(
            "entity_fingerprint"
        )
    )

    new_rows = []

    for row in unique_entities.itertuples(
        index=False
    ):

        fingerprint = (
            row.entity_fingerprint
        )

        if fingerprint in existing:
            continue

        store_id = str(
            uuid4()
        )

        existing[
            fingerprint
        ] = store_id

        new_rows.append(
            {
                "entity_fingerprint":
                    fingerprint,

                "store_id":
                    store_id,

                "business_no":
                    row.business_no,

                "created_dataset_version":
                    dataset_version,
            }
        )

    if new_rows:

        registry = pd.concat(
            [
                registry,
                pd.DataFrame(
                    new_rows
                ),
            ],
            ignore_index=True,
        )

    result = df.copy()

    result["store_id"] = (
        result[
            "entity_fingerprint"
        ]
        .map(existing)
    )

    registry_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    registry.to_parquet(
        registry_path,
        index=False,
    )

    return result, registry