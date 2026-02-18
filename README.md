# n8n-ec2-autoscaler

Self-hosted n8n in Docker Compose. A cron workflow (every 5 minutes) checks EC2 workers and automatically:
- scale-out: starts one stopped worker on high load,
- scale-in: stops one idle worker,
- respects min_running, cooldowns, and NeverStop=true.

## 1) Project contents

- `docker-compose.yml` - n8n + Postgres.
- `.env.example` - all secrets and runtime settings.
- `config/config.json.example` - autoscaler config template.
- `config/config.json` - active host config (gitignored).
- `workflows/ec2-autoscaler.json` - exported n8n workflow.
- `scripts/autoscale` - safe CLI for config updates.
- `logs/autoscaler.log` - autoscaler action log (created automatically).

## 2) AWS IAM (minimal permissions)

Create an IAM user with programmatic access and this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    }
  ]
}
```

Why: workflow must read EC2 inventory, read CPU metrics, and call start/stop.

## 3) EC2 tags

Required tags for managed instances:
- `AutoScale=true`
- `Role=worker`

Optional tags:
- `Priority=1|2|3` (smaller number starts first during scale-out)
- `NeverStop=true` (protected from scale-in)

Why: strict targeting and deterministic start order.

## 4) Environment setup

1. Copy `.env.example` to `.env`.
2. Fill values:
   - `N8N_ENCRYPTION_KEY`
   - `N8N_BASIC_AUTH_USER`, `N8N_BASIC_AUTH_PASSWORD`
   - `POSTGRES_PASSWORD`
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`

Chosen AWS auth method: environment variables in `.env`.

Why this method:
- portable across Linux hosts,
- no dependency on host user home (`~/.aws`) inside container,
- centralized secrets handling.

## 5) Autoscaler config

`config/config.json` already exists. Default shape:

```json
{
  "enabled": true,
  "min_running": 2,
  "region": "eu-central-1",
  "tag_filter": {"AutoScale": "true", "Role": "worker"},
  "scale_out": {"avg_cpu_threshold": 65, "max_cpu_threshold": 80, "window_minutes": 15, "cooldown_minutes": 15, "start_count": 1},
  "scale_in": {"cpu_threshold": 5, "window_minutes": 60, "cooldown_minutes": 60, "stop_count": 1}
}
```

## 6) Run Docker Compose

```bash
docker compose up -d
```

Check:

```bash
docker compose ps
docker compose logs -f n8n
```

Expected: both `n8n-ec2-autoscaler` and `n8n-postgres` are running.

## 7) Import workflow in n8n

1. Open `http://<host>:5678`.
2. Log in with Basic Auth from `.env`.
3. `Workflows` -> `Import from file` -> choose `workflows/ec2-autoscaler.json`.
4. Save and activate it.

How to verify cron:
- `Executions` shows a run every ~5 minutes.
- `logs/autoscaler.log` gets new report lines.

## 8) Workflow logic

Pipeline:
1. `Cron every 5m` - trigger.
2. `Read config file` - reads `/opt/ec2-autoscaler/config.json`.
3. `Parse config` - JSON parse + required keys validation.
4. `Scale logic + AWS actions` - Code node with AWS SDK:
   - scale-out first by avg/max CPU thresholds,
   - scale-in only if `running_count > min_running`,
   - skip instances with `NeverStop=true`,
   - cooldown tracking in `/opt/ec2-autoscaler/state.json`,
   - append report to `/opt/ec2-autoscaler/logs/autoscaler.log`.

Why Code nodes were used:
- multi-condition logic with cooldown and priority sorting is simpler and safer in one explicit code path,
- easier maintenance than many branch nodes.

## 9) Config CLI

Make script executable:

```bash
chmod +x scripts/autoscale
```

Commands:

```bash
./scripts/autoscale set-min 3
./scripts/autoscale pause
./scripts/autoscale resume
./scripts/autoscale status
```

Requires `jq`.

Install `jq` on Ubuntu/Debian:

```bash
sudo apt-get update && sudo apt-get install -y jq
```

Safety:
- input validation,
- temp file + atomic move update.

## 10) Troubleshooting

### AWS AccessDenied

Symptoms:
- execution fails with AccessDenied.

Check:
- AWS credentials in `.env`,
- IAM policy includes `ec2:DescribeInstances`, `ec2:StartInstances`, `ec2:StopInstances`, `cloudwatch:GetMetricStatistics`.

### Missing CloudWatch metrics

Symptoms:
- avg CPU is always 0 and scaling decisions look wrong.

Check:
- workers are running and producing CPU,
- metrics exist in selected region,
- time windows are not too short.

### Volume permissions

Symptoms:
- n8n cannot read config or append logs.

Check:
- host permissions on `./config` and `./logs`,
- `config/config.json` exists,
- restart n8n after permission fixes:

```bash
docker compose restart n8n
```

## 11) Quick smoke test

1. Keep at least 2 workers running and at least 1 stopped with required tags.
2. Temporarily lower scale-out thresholds in `config.json`.
3. Wait for cron, then check `logs/autoscaler.log` and EC2 states.
4. Restore production thresholds.

