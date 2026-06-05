"""Facility dataset DQ — bbox + completeness/uniqueness."""
from __future__ import annotations

import facilities as facilities_mod
import quality


def test_within_london_bbox():
    """Every facility coordinate lies within the Greater-London bbox."""
    df = quality.facilities_dataframe(facilities_mod.build_facilities())
    inside = quality.within_london_bbox(df)
    assert inside.all(), (
        "facilities outside London bbox:\n"
        + df.loc[~inside, ["id", "name", "lat", "lng"]].to_string(index=False)
    )
    # ~25 real facilities expected
    assert len(df) >= 20


def test_required_fields_and_unique():
    """No missing required fields; ids are unique (pandera-enforced)."""
    facilities = facilities_mod.build_facilities()
    df = quality.facilities_dataframe(facilities)

    # pandera schema enforces presence, types, enum, bbox and uniqueness.
    validated = quality.validate_facilities(df)
    assert len(validated) == len(df)

    # explicit no-missing / unique-id checks for a readable failure message.
    required = ["id", "name", "type", "lat", "lng"]
    for col in required:
        assert col in df.columns, f"missing column {col}"
        assert df[col].notna().all(), f"null values in {col}"
    assert df["id"].is_unique, "duplicate facility ids"
