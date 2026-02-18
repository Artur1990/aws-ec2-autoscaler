from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_epoch(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).timestamp()


def _cooldown_ok(last_ts: str | None, cooldown_minutes: int, now_ts: str) -> bool:
    if cooldown_minutes <= 0:
        return True
    last_epoch = _to_epoch(last_ts)
    if last_epoch is None:
        return True
    now_epoch = _to_epoch(now_ts)
    assert now_epoch is not None
    return (now_epoch - last_epoch) >= cooldown_minutes * 60


def _priority(instance: dict[str, Any]) -> int:
    raw = instance.get("tags", {}).get("Priority")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 999


def decide_actions(config: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    now_ts = snapshot.get("now_ts") or _iso_now()

    enabled = bool(config.get("enabled", True))
    min_running = int(config.get("min_running", 2))
    scale_out = config.get("scale_out", {})
    scale_in = config.get("scale_in", {})

    running = snapshot.get("running_instances", [])
    stopped = snapshot.get("stopped_instances", [])
    metrics_out = snapshot.get("metrics_scale_out", {})
    metrics_in = snapshot.get("metrics_scale_in", {})
    last_start = snapshot.get("last_action_times", {}).get("last_start_at")
    last_stop = snapshot.get("last_action_times", {}).get("last_stop_at")

    actions: list[dict[str, Any]] = []
    reasons: list[str] = []

    running_count = len(running)

    if not enabled:
        reasons.append("enabled=false")
        return {
            "now_ts": now_ts,
            "actions": actions,
            "summary": {
                "reason": "; ".join(reasons),
                "running_count_before": running_count,
                "running_count_after": running_count,
            },
        }

    out_values = [float(metrics_out[i["id"]]) for i in running if i["id"] in metrics_out]
    avg_cpu = sum(out_values) / len(out_values) if out_values else 0.0
    max_cpu = max(out_values) if out_values else 0.0

    out_cond = (
        avg_cpu > float(scale_out.get("avg_cpu_threshold", 65))
        or max_cpu > float(scale_out.get("max_cpu_threshold", 80))
    )
    out_cooldown_ok = _cooldown_ok(last_start, int(scale_out.get("cooldown_minutes", 15)), now_ts)

    if out_cond and out_cooldown_ok:
        start_count = min(int(scale_out.get("start_count", 1)), 1)
        sorted_stopped = sorted(stopped, key=lambda x: (_priority(x), x["id"]))
        for inst in sorted_stopped[:start_count]:
            actions.append(
                {
                    "type": "START",
                    "instance_id": inst["id"],
                    "reason": "scale_out_high_load",
                    "evidence": {"avg_cpu": avg_cpu, "max_cpu": max_cpu},
                    "thresholds": {
                        "avg_cpu_threshold": scale_out.get("avg_cpu_threshold", 65),
                        "max_cpu_threshold": scale_out.get("max_cpu_threshold", 80),
                    },
                    "windows": {"scale_out_window_minutes": scale_out.get("window_minutes", 15)},
                    "tags": inst.get("tags", {}),
                }
            )
    elif out_cond and not out_cooldown_ok:
        reasons.append("scale_out_cooldown")

    in_cooldown_ok = _cooldown_ok(last_stop, int(scale_in.get("cooldown_minutes", 60)), now_ts)
    if running_count <= min_running:
        reasons.append("min_running_guard")
    elif in_cooldown_ok:
        stop_count = min(int(scale_in.get("stop_count", 1)), 1)
        candidates = []
        for inst in running:
            tags = inst.get("tags", {})
            if str(tags.get("NeverStop", "")).lower() == "true":
                continue
            inst_cpu = metrics_in.get(inst["id"])
            if inst_cpu is None:
                continue
            if float(inst_cpu) < float(scale_in.get("cpu_threshold", 5)):
                candidates.append((float(inst_cpu), inst))

        candidates.sort(key=lambda x: (x[0], x[1]["id"]))
        max_allowed = max(0, running_count - min_running)
        to_stop = min(stop_count, max_allowed)
        for _, inst in candidates[:to_stop]:
            actions.append(
                {
                    "type": "STOP",
                    "instance_id": inst["id"],
                    "reason": "scale_in_idle",
                    "evidence": {"cpu_avg": float(metrics_in.get(inst["id"], 0.0))},
                    "thresholds": {"cpu_threshold": scale_in.get("cpu_threshold", 5)},
                    "windows": {"scale_in_window_minutes": scale_in.get("window_minutes", 60)},
                    "tags": inst.get("tags", {}),
                }
            )
    else:
        reasons.append("scale_in_cooldown")

    running_after = running_count + sum(1 for a in actions if a["type"] == "START") - sum(
        1 for a in actions if a["type"] == "STOP"
    )

    summary_reason = "; ".join(reasons) if reasons else "ok"
    return {
        "now_ts": now_ts,
        "actions": actions,
        "summary": {
            "reason": summary_reason,
            "running_count_before": running_count,
            "running_count_after": running_after,
            "avg_cpu": round(avg_cpu, 2),
            "max_cpu": round(max_cpu, 2),
        },
    }
