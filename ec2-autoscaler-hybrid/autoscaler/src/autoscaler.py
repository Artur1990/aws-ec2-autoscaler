from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aws_client import AwsClient
from decision import decide_actions
from logging_audit import write_audit, write_decision


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: str, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_snapshot(config: dict[str, Any], aws: AwsClient, state: dict[str, Any]) -> dict[str, Any]:
    running = aws.list_running_instances(config["tag_filter"])
    stopped = aws.list_stopped_instances(config["tag_filter"])

    metrics_scale_out: dict[str, float] = {}
    metrics_scale_in: dict[str, float] = {}

    out_window = int(config["scale_out"]["window_minutes"])
    in_window = int(config["scale_in"]["window_minutes"])

    for inst in running:
        out_cpu = aws.get_cpu_avg(inst["id"], out_window, 300)
        if out_cpu is not None:
            metrics_scale_out[inst["id"]] = out_cpu

        in_cpu = aws.get_cpu_avg(inst["id"], in_window, 300)
        if in_cpu is not None:
            metrics_scale_in[inst["id"]] = in_cpu

    return {
        "now_ts": iso_now(),
        "running_instances": running,
        "stopped_instances": stopped,
        "metrics_scale_out": metrics_scale_out,
        "metrics_scale_in": metrics_scale_in,
        "last_action_times": {
            "last_start_at": state.get("last_start_at"),
            "last_stop_at": state.get("last_stop_at"),
        },
    }


def run_once() -> dict[str, Any]:
    config_path = os.environ.get("AUTOSCALER_CONFIG", "/opt/ec2-autoscaler/config/config.json")
    state_path = os.environ.get("AUTOSCALER_STATE", "/opt/ec2-autoscaler/logs/state.json")
    decision_log = os.environ.get("AUTOSCALER_DECISIONS_LOG", "/opt/ec2-autoscaler/logs/decisions.jsonl")
    audit_log = os.environ.get("AUTOSCALER_AUDIT_LOG", "/opt/ec2-autoscaler/logs/audit.jsonl")

    config = load_json(config_path, {})
    state = load_json(state_path, {"last_start_at": None, "last_stop_at": None})

    region = str(config.get("region") or os.environ.get("AWS_REGION") or "")
    if not region:
        raise RuntimeError("Region is required in config.region or AWS_REGION")

    aws = AwsClient(region=region)
    snapshot = build_snapshot(config, aws, state)
    decision_result = decide_actions(config=config, snapshot=snapshot)

    running_before = decision_result["summary"]["running_count_before"]
    running_after = decision_result["summary"]["running_count_after"]

    start_ids = [a["instance_id"] for a in decision_result["actions"] if a["type"] == "START"]
    stop_ids = [a["instance_id"] for a in decision_result["actions"] if a["type"] == "STOP"]

    aws.start_instances(start_ids[:1])
    aws.stop_instances(stop_ids[:1])

    now_ts = decision_result["now_ts"]
    if start_ids:
        state["last_start_at"] = now_ts
    if stop_ids:
        state["last_stop_at"] = now_ts
    save_json(state_path, state)

    decision_record = {
        "ts": now_ts,
        "action": "DECISION",
        "instance_id": None,
        "reason": decision_result["summary"].get("reason", "ok"),
        "evidence": {
            "avg_cpu": decision_result["summary"].get("avg_cpu", 0),
            "max_cpu": decision_result["summary"].get("max_cpu", 0),
        },
        "thresholds": {
            "scale_out": config.get("scale_out", {}),
            "scale_in": config.get("scale_in", {}),
        },
        "windows": {
            "scale_out_window_minutes": config.get("scale_out", {}).get("window_minutes"),
            "scale_in_window_minutes": config.get("scale_in", {}).get("window_minutes"),
        },
        "min_running": config.get("min_running"),
        "running_count_before": running_before,
        "running_count_after": running_after,
        "tags": config.get("tag_filter", {}),
        "planned_actions": decision_result["actions"],
    }
    write_decision(decision_log, decision_record)

    for action in decision_result["actions"]:
        if action["type"] not in {"START", "STOP"}:
            continue
        audit_record = {
            "ts": now_ts,
            "action": action["type"],
            "instance_id": action["instance_id"],
            "reason": action["reason"],
            "evidence": action["evidence"],
            "thresholds": action["thresholds"],
            "windows": action["windows"],
            "min_running": config.get("min_running"),
            "running_count_before": running_before,
            "running_count_after": running_after,
            "tags": action.get("tags", {}),
        }
        write_audit(audit_log, audit_record)

    return decision_record


def run_loop(interval_seconds: int) -> None:
    while True:
        run_once()
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="EC2 autoscaler hybrid service")
    parser.add_argument("mode", choices=["run-once", "run-loop"], help="Execution mode")
    args = parser.parse_args()

    interval = int(os.environ.get("AUTOSCALER_INTERVAL_SECONDS", "300"))

    if args.mode == "run-once":
        run_once()
    else:
        run_loop(interval)


if __name__ == "__main__":
    main()
