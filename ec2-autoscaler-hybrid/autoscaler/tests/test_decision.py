from decision import decide_actions


def base_config() -> dict:
    return {
        "enabled": True,
        "min_running": 2,
        "scale_out": {
            "avg_cpu_threshold": 65,
            "max_cpu_threshold": 80,
            "window_minutes": 15,
            "cooldown_minutes": 15,
            "start_count": 1,
        },
        "scale_in": {
            "cpu_threshold": 5,
            "window_minutes": 60,
            "cooldown_minutes": 60,
            "stop_count": 1,
        },
    }


def test_min_running_blocks_stop() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T18:00:00+00:00",
        "running_instances": [{"id": "i-1", "tags": {}}, {"id": "i-2", "tags": {}}],
        "stopped_instances": [],
        "metrics_scale_out": {"i-1": 10.0, "i-2": 10.0},
        "metrics_scale_in": {"i-1": 1.0, "i-2": 1.0},
        "last_action_times": {"last_start_at": None, "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    assert [a for a in out["actions"] if a["type"] == "STOP"] == []


def test_cooldown_blocks_start() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T18:10:00+00:00",
        "running_instances": [{"id": "i-1", "tags": {}}, {"id": "i-2", "tags": {}}],
        "stopped_instances": [{"id": "i-3", "tags": {"Priority": "1"}}],
        "metrics_scale_out": {"i-1": 90.0, "i-2": 85.0},
        "metrics_scale_in": {"i-1": 90.0, "i-2": 85.0},
        "last_action_times": {"last_start_at": "2026-02-18T18:00:00+00:00", "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    assert [a for a in out["actions"] if a["type"] == "START"] == []


def test_priority_selection() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T19:00:00+00:00",
        "running_instances": [{"id": "i-1", "tags": {}}, {"id": "i-2", "tags": {}}],
        "stopped_instances": [
            {"id": "i-9", "tags": {}},
            {"id": "i-3", "tags": {"Priority": "2"}},
            {"id": "i-4", "tags": {"Priority": "1"}},
        ],
        "metrics_scale_out": {"i-1": 90.0, "i-2": 88.0},
        "metrics_scale_in": {"i-1": 90.0, "i-2": 88.0},
        "last_action_times": {"last_start_at": None, "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    starts = [a for a in out["actions"] if a["type"] == "START"]
    assert starts and starts[0]["instance_id"] == "i-4"


def test_neverstop_excluded() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T20:00:00+00:00",
        "running_instances": [
            {"id": "i-1", "tags": {"NeverStop": "true"}},
            {"id": "i-2", "tags": {}},
            {"id": "i-3", "tags": {}},
        ],
        "stopped_instances": [],
        "metrics_scale_out": {"i-1": 10.0, "i-2": 10.0, "i-3": 10.0},
        "metrics_scale_in": {"i-1": 1.0, "i-2": 1.0, "i-3": 4.0},
        "last_action_times": {"last_start_at": None, "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    stops = [a for a in out["actions"] if a["type"] == "STOP"]
    assert stops and stops[0]["instance_id"] != "i-1"


def test_high_load_start() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T21:00:00+00:00",
        "running_instances": [{"id": "i-1", "tags": {}}, {"id": "i-2", "tags": {}}],
        "stopped_instances": [{"id": "i-5", "tags": {"Priority": "1"}}],
        "metrics_scale_out": {"i-1": 70.0, "i-2": 72.0},
        "metrics_scale_in": {"i-1": 70.0, "i-2": 72.0},
        "last_action_times": {"last_start_at": None, "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    assert any(a["type"] == "START" for a in out["actions"])


def test_idle_stop() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T22:00:00+00:00",
        "running_instances": [
            {"id": "i-1", "tags": {}},
            {"id": "i-2", "tags": {}},
            {"id": "i-3", "tags": {}},
        ],
        "stopped_instances": [],
        "metrics_scale_out": {"i-1": 10.0, "i-2": 10.0, "i-3": 10.0},
        "metrics_scale_in": {"i-1": 2.0, "i-2": 8.0, "i-3": 3.0},
        "last_action_times": {"last_start_at": None, "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    stops = [a for a in out["actions"] if a["type"] == "STOP"]
    assert stops and stops[0]["instance_id"] == "i-1"


def test_no_stopped_available() -> None:
    cfg = base_config()
    snap = {
        "now_ts": "2026-02-18T23:00:00+00:00",
        "running_instances": [{"id": "i-1", "tags": {}}, {"id": "i-2", "tags": {}}],
        "stopped_instances": [],
        "metrics_scale_out": {"i-1": 90.0, "i-2": 90.0},
        "metrics_scale_in": {"i-1": 90.0, "i-2": 90.0},
        "last_action_times": {"last_start_at": None, "last_stop_at": None},
    }
    out = decide_actions(cfg, snap)
    assert [a for a in out["actions"] if a["type"] == "START"] == []
