from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3


class AwsClient:
    def __init__(self, region: str):
        self.region = region
        self.ec2 = boto3.client("ec2", region_name=region)
        self.cloudwatch = boto3.client("cloudwatch", region_name=region)

    @staticmethod
    def _tags_to_map(tags: list[dict[str, str]] | None) -> dict[str, str]:
        result: dict[str, str] = {}
        for tag in tags or []:
            if "Key" in tag and "Value" in tag:
                result[tag["Key"]] = tag["Value"]
        return result

    def _describe_instances(self, state_name: str, tag_filter: dict[str, str]) -> list[dict[str, Any]]:
        filters = [{"Name": "instance-state-name", "Values": [state_name]}]
        for key, value in tag_filter.items():
            filters.append({"Name": f"tag:{key}", "Values": [str(value)]})

        paginator = self.ec2.get_paginator("describe_instances")
        instances: list[dict[str, Any]] = []
        for page in paginator.paginate(Filters=filters):
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    instances.append({"id": inst["InstanceId"], "tags": self._tags_to_map(inst.get("Tags"))})
        return instances

    def list_running_instances(self, tag_filter: dict[str, str]) -> list[dict[str, Any]]:
        return self._describe_instances("running", tag_filter)

    def list_stopped_instances(self, tag_filter: dict[str, str]) -> list[dict[str, Any]]:
        return self._describe_instances("stopped", tag_filter)

    def get_cpu_avg(self, instance_id: str, window_minutes: int, period_seconds: int = 300) -> float | None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=window_minutes)
        response = self.cloudwatch.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start,
            EndTime=end,
            Period=period_seconds,
            Statistics=["Average"],
        )
        datapoints = response.get("Datapoints", [])
        values = [point["Average"] for point in datapoints if "Average" in point]
        if not values:
            return None
        return float(sum(values) / len(values))

    def start_instances(self, instance_ids: list[str]) -> None:
        if instance_ids:
            self.ec2.start_instances(InstanceIds=instance_ids)

    def stop_instances(self, instance_ids: list[str]) -> None:
        if instance_ids:
            self.ec2.stop_instances(InstanceIds=instance_ids)
