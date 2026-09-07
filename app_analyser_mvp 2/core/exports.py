from __future__ import annotations

import json
from typing import Dict

import pandas as pd


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def object_to_json_bytes(obj) -> bytes:
    def default(o):
        if isinstance(o, pd.DataFrame):
            return o.to_dict(orient="records")
        try:
            return str(o)
        except Exception:
            return None
    return json.dumps(obj, default=default, indent=2).encode("utf-8")
