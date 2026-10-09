import unittest
from datetime import UTC, datetime, timedelta

from app.connectors.azure_devops import (
    evaluate_pipeline,
    is_stale_branch,
    parse_organization,
    short_ref,
    thresholds,
)


def _run(result: str, hours_ago: int = 0, status: str = "completed") -> dict:
    when = datetime.now(UTC) - timedelta(hours=hours_ago)
    return {
        "id": hours_ago,
        "result": result,
        "status": status,
        "finishTime": when.isoformat(),
        "buildNumber": str(hours_ago),
    }


class OrganizationParseTests(unittest.TestCase):
    def test_name_only(self):
        org, base = parse_organization({"organization": "contoso"})
        self.assertEqual(org, "contoso")
        self.assertEqual(base, "https://dev.azure.com/contoso")

    def test_url(self):
        org, base = parse_organization({"organization_url": "https://dev.azure.com/fabrikam/"})
        self.assertEqual(org, "fabrikam")
        self.assertEqual(base, "https://dev.azure.com/fabrikam")

    def test_org_field_is_url(self):
        org, base = parse_organization({"organization": "https://dev.azure.com/contoso"})
        self.assertEqual(org, "contoso")
        self.assertEqual(base, "https://dev.azure.com/contoso")

    def test_missing(self):
        with self.assertRaises(Exception):
            parse_organization({})


class ThresholdTests(unittest.TestCase):
    def test_defaults(self):
        values = thresholds({})
        self.assertEqual(values["stale_days"], 30)
        self.assertEqual(values["fail_consecutive"], 3)
        self.assertEqual(values["fail_rate"], 0.75)

    def test_percent_rate(self):
        self.assertEqual(thresholds({"fail_rate": 80})["fail_rate"], 0.8)


class StaleBranchTests(unittest.TestCase):
    def test_default_branch_is_never_stale(self):
        now = datetime.now(UTC)
        self.assertFalse(
            is_stale_branch(
                last_commit_at=now - timedelta(days=400),
                now=now,
                stale_days=30,
                is_default=True,
            )
        )

    def test_old_topic_branch(self):
        now = datetime.now(UTC)
        self.assertTrue(
            is_stale_branch(
                last_commit_at=now - timedelta(days=45),
                now=now,
                stale_days=30,
                is_default=False,
            )
        )

    def test_recent_topic_branch(self):
        now = datetime.now(UTC)
        self.assertFalse(
            is_stale_branch(
                last_commit_at=now - timedelta(days=3),
                now=now,
                stale_days=30,
                is_default=False,
            )
        )


class PipelineAlertTests(unittest.TestCase):
    def test_consecutive_failures(self):
        runs = [_run("failed", i) for i in range(5)] + [_run("succeeded", 10)]
        alert = evaluate_pipeline(runs, consecutive_threshold=3, fail_rate=0.75, lookback=8)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["reason"], "consecutive")
        self.assertEqual(alert["consecutive_failures"], 5)

    def test_high_failure_rate(self):
        runs = [
            _run("failed"),
            _run("failed"),
            _run("succeeded"),
            _run("failed"),
            _run("failed"),
            _run("failed"),
            _run("succeeded"),
            _run("failed"),
        ]
        alert = evaluate_pipeline(runs, consecutive_threshold=3, fail_rate=0.75, lookback=8)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["reason"], "rate")
        self.assertEqual(alert["failure_count"], 6)

    def test_healthy_pipeline(self):
        runs = [_run("succeeded", i) for i in range(8)]
        self.assertIsNone(evaluate_pipeline(runs, consecutive_threshold=3, fail_rate=0.75, lookback=8))

    def test_ignores_in_progress_and_canceled(self):
        runs = [
            _run("failed", 0, status="inProgress"),
            _run("canceled", 1),
            _run("failed", 2),
            _run("failed", 3),
            _run("failed", 4),
            _run("succeeded", 5),
        ]
        alert = evaluate_pipeline(runs, consecutive_threshold=3, fail_rate=0.75, lookback=8)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["consecutive_failures"], 3)

    def test_not_enough_history(self):
        runs = [_run("failed"), _run("failed")]
        self.assertIsNone(evaluate_pipeline(runs, consecutive_threshold=3, fail_rate=0.75, lookback=8))


class RefTests(unittest.TestCase):
    def test_short_ref(self):
        self.assertEqual(short_ref("refs/heads/main"), "main")
        self.assertEqual(short_ref("feature/x"), "feature/x")


if __name__ == "__main__":
    unittest.main()
