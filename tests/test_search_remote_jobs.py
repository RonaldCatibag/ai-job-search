"""Offline regression checks for remote infrastructure discovery filters."""
from datetime import datetime, timezone
import unittest
from tools.search_remote_jobs import select_jobs


class SearchRemoteJobsTests(unittest.TestCase):
    cutoff = datetime(2026, 10, 24, tzinfo=timezone.utc)

    def job(self, title="DevOps Engineer", location="Remote - Worldwide", **extra):
        return dict(title=title, location=dict(name=location), absolute_url="https://example.test/jobs/1", id=1, **extra)

    def test_all_three_role_families_are_discovered(self):
        jobs = [self.job(title=t) for t in ["DevOps Engineer", "Site Reliability Engineer", "Platform Engineer"]]
        selected, excluded = select_jobs("Example", "greenhouse", "example", jobs, self.cutoff)
        self.assertEqual(len(selected), 3)
        self.assertEqual(excluded, [])

    def test_home_based_worldwide_is_a_remote_location(self):
        selected, excluded = select_jobs("Canonical", "greenhouse", "canonical", [self.job(location="Home based - Worldwide")], self.cutoff)
        self.assertEqual(len(selected), 1)
        self.assertEqual(excluded, [])

    def test_remote_country_restriction_is_not_worldwide(self):
        selected, excluded = select_jobs("Example", "greenhouse", "example", [self.job(location="Remote - Poland")], self.cutoff)
        self.assertEqual(selected, [])
        self.assertIn("eligibility", excluded[0]["exclusion_reason"])

    def test_known_old_posting_requires_explicit_broader_search(self):
        jobs = [self.job(publishedAt="2026-09-01T00:00:00Z")]
        self.assertEqual(select_jobs("Example", "ashby", "example", jobs, self.cutoff)[0], [])
        self.assertEqual(len(select_jobs("Example", "ashby", "example", jobs, self.cutoff, True)[0]), 1)

    def test_update_date_does_not_become_publication_date(self):
        selected, _ = select_jobs("Example", "greenhouse", "example", [self.job(updated_at="2026-11-07")], self.cutoff)
        self.assertIsNone(selected[0]["posted_date"])
        self.assertEqual(selected[0]["salary_status"], "unverified")

    def test_current_employer_is_excluded_case_insensitively(self):
        selected, excluded = select_jobs("TOOKITAKI", "greenhouse", "example", [self.job()], self.cutoff)
        self.assertEqual((selected, excluded), ([], []))


if __name__ == "__main__":
    unittest.main()
