# Security Policy

## 1. Secrets handling
- Do not commit `.env`.
- Do not commit `config/config.json` if it contains sensitive values.
- Keep AWS credentials only in environment variables.

## 2. File permissions
- Set strict permissions on Linux:
  - `chmod 600 .env`
  - `chmod 600 config/config.json`

## 3. IAM least privilege
- Grant only required actions:
  - `ec2:DescribeInstances`
  - `ec2:StartInstances`
  - `ec2:StopInstances`
  - `cloudwatch:GetMetricStatistics`
- Restrict Start/Stop with resource tag conditions where possible.

## 4. Runtime hardening
- Keep Docker images updated.
- Rotate AWS keys regularly.
- Monitor `logs/audit.jsonl` for unauthorized or unexpected START/STOP actions.
