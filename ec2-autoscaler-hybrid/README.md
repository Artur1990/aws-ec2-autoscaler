# ec2-autoscaler-hybrid

Hybrid architecture:
- n8n = UI + optional heartbeat workflow
- Python (boto3) = scaling decisions, AWS actions, audit logging, tests

No secrets in code. Secrets are injected from `.env`.

## Why this architecture

Chosen approach: autoscaler service runs continuously on its own 5-minute cycle.

Why:
- avoids `docker exec` from n8n (fragile and unsafe pattern),
- no need for extra HTTP trigger service,
- n8n stays as operator UI and config observer.

## Repository structure

```text
ec2-autoscaler-hybrid/
  docker-compose.yml
  Taskfile.yml
  README.md
  SECURITY.md
  .gitignore
  .env.example
  config/config.json.example
  config/config.json
  scripts/autoscale
  workflows/ec2-autoscaler.json
  autoscaler/
    Dockerfile
    requirements.txt
    src/autoscaler.py
    src/aws_client.py
    src/decision.py
    src/logging_audit.py
    tests/test_decision.py
  logs/
```

## Config format

`config/config.json`:

```json
{
  "enabled": true,
  "min_running": 2,
  "region": "eu-central-1",
  "tag_filter": {"AutoScale":"true","Role":"worker"},
  "scale_out": {"avg_cpu_threshold":65,"max_cpu_threshold":80,"window_minutes":15,"cooldown_minutes":15,"start_count":1},
  "scale_in": {"cpu_threshold":5,"window_minutes":60,"cooldown_minutes":60,"stop_count":1}
}
```

## Docker Compose services

- `postgres`: n8n storage backend.
- `n8n`: workflow UI, stores metadata in Postgres.
- `autoscaler`: Python worker loop (every 5 minutes).

Mounted volumes:
- `./config -> /opt/ec2-autoscaler/config` (read-only where possible)
- `./logs -> /opt/ec2-autoscaler/logs`

## IAM policy (minimal)

Use minimal permissions and tag-based condition for Start/Stop.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DescribeAndMetrics",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    },
    {
      "Sid": "StartStopTaggedOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:StartInstances",
        "ec2:StopInstances"
      ],
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "StringEquals": {
          "ec2:ResourceTag/AutoScale": "true",
          "ec2:ResourceTag/Role": "worker"
        }
      }
    }
  ]
}
```

## Tag rules on instances

Required:
- `AutoScale=true`
- `Role=worker`

Optional:
- `Priority=1|2|3` (missing => 999)
- `NeverStop=true` (never selected for STOP)

## Scaling logic

Scale-out:
- uses running instances CPU over `scale_out.window_minutes`.
- condition: avgCPU > `avg_cpu_threshold` OR maxCPU > `max_cpu_threshold`.
- checks start cooldown.
- starts up to 1 instance per cycle (default), lowest Priority first.

Scale-in:
- only if `running_count > min_running`.
- candidate must be running, tagged, not `NeverStop=true`.
- cpuAvg over `scale_in.window_minutes` must be below `cpu_threshold`.
- checks stop cooldown.
- stops up to 1 instance per cycle (default).

Anti-flap:
- separate in/out windows and thresholds,
- independent cooldowns,
- max one START and one STOP per cycle.

## Logs

- `logs/decisions.jsonl`: every cycle, even no-op.
- `logs/audit.jsonl`: only START/STOP actions.

JSONL fields include:
- `ts`, `action`, `instance_id`, `reason`, `evidence`, `thresholds`, `windows`,
- `min_running`, `running_count_before`, `running_count_after`, `tags`.

## n8n workflow role (simplified)

`workflows/ec2-autoscaler.json`:
- Cron every 5 minutes.
- Runs a simple heartbeat Code node.

All AWS scaling logic is executed only by the `autoscaler` service.
This removes file-access complexity from n8n and keeps the project simple and stable.

## scripts/autoscale usage

```bash
chmod +x scripts/autoscale
./scripts/autoscale status
./scripts/autoscale set-min 3
./scripts/autoscale pause
./scripts/autoscale resume
```

Requires `jq`:

```bash
sudo apt-get update && sudo apt-get install -y jq
```

## Run

1. Initialize files:
```bash
task init
```
2. Fill `.env` from `.env.example`.
3. Start stack:
```bash
task up
```
4. Check status/logs:
```bash
task status
task logs
```

## Tests

Run unit tests for decision engine:

```bash
task test
```

Lint/syntax check:

```bash
task lint
```

## Troubleshooting

- n8n file access errors:
  - not applicable in simplified mode (workflow does not read host files).
- AccessDenied:
  - verify IAM actions and tag conditions.
- No metrics:
  - ensure CloudWatch has CPU datapoints for selected window and region.
- Permission denied on logs/config:
  - verify host permissions on `config/` and `logs/`.
- No scaling actions:
  - inspect `logs/decisions.jsonl` reason and thresholds.
