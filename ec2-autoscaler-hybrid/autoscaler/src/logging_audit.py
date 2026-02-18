from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_jsonl(path: str, record: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def write_decision(path: str, payload: dict[str, Any]) -> None:
    append_jsonl(path, payload)


def write_audit(path: str, payload: dict[str, Any]) -> None:
    append_jsonl(path, payload)
