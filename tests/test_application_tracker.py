"""Offline tests for durable local application tracking and submission boundaries."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from tools.application_tracker import Store, identity, normalize_url


class ApplicationTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/"project"
        (self.root/"job_scraper").mkdir(parents=True)
        (self.root/"documents/applications").mkdir(parents=True)
        queue={"seen":{"example":{"company":"Example","title":"DevOps Engineer","url":"https://example.test/jobs/123","location":"Remote - Worldwide","status":"new","fit":"high"}}}
        (self.root/"job_scraper/seen_jobs.json").write_text(json.dumps(queue))
        self.store=Store(self.root,Path(self.temp.name)/"data")
        self.key=identity("Example","DevOps Engineer","https://example.test/jobs/123")

    def test_country_stays_unverified_without_source_evidence(self):
        job=self.store.list_jobs()[0]
        self.assertEqual(job["employer_country"],"Unverified")
        self.assertEqual(job["job_country"],"Worldwide")
        self.assertEqual(job["status"],"researching")

    def test_existing_application_readme_overrides_discovery_and_deduplicates(self):
        (self.root/"documents/applications/README.md").write_text("## Current leads\n\n| Company / role | Link | Location | Compensation | Status | Next action |\n| --- | --- | --- | --- | --- | --- |\n| Example - DevOps Engineer | https://www.example.test/jobs/123/ | Remote, worldwide | Not listed | Applied (user reported) | Confirmed previously |\n")
        jobs=self.store.list_jobs()
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]["status"],"applied")
        self.assertIn("not reverified",jobs[0]["source_record_note"])
        self.assertFalse((self.root/"job_search_tracker.csv").exists())

    def test_research_update_persists_without_creating_application(self):
        self.store.update(self.key,{"status":"ready_to_apply","note":"Check country eligibility"})
        loaded=Store(self.root,self.store.data)
        self.assertEqual(loaded.list_jobs()[0]["status"],"ready_to_apply")
        self.assertFalse((self.root/"job_search_tracker.csv").exists())
        self.assertEqual(loaded.history(self.key)[0]["to_status"],"ready_to_apply")

    def test_applied_requires_real_submission_confirmation_and_date(self):
        for values in ({"status":"applied"},{"status":"applied","confirmed_submitted":True},{"status":"applied","confirmed_submitted":False,"applied_date":"2026-11-07"}):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError,"Confirm"):
                self.store.update(self.key,values)
        self.assertEqual(self.store.history(self.key),[])
        self.assertFalse((self.root/"job_search_tracker.csv").exists())

    def test_confirmed_status_is_written_to_canonical_csv_and_history(self):
        self.store.update(self.key,{"status":"applied","confirmed_submitted":True,"applied_date":"2026-11-07","note":"I submitted via the employer portal"})
        with (self.root/"job_search_tracker.csv").open(newline="") as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["status"],"applied")
        self.assertEqual(rows[0]["date"],"2026-11-07")
        self.assertEqual(rows[0]["source"],"https://example.test/jobs/123")
        self.assertEqual(self.store.history(self.key)[0]["from_status"],"researching")

    def test_other_tracker_rows_and_extra_columns_are_preserved(self):
        (self.root/"job_search_tracker.csv").write_text("date,company,role,status,source,custom\n2026-10-01,Other,Engineer,interview,https://other.test/job,keep\n")
        self.store.update(self.key,{"status":"drafted","note":"Draft prepared locally"})
        with (self.root/"job_search_tracker.csv").open(newline="") as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(rows[0]["company"],"Other")
        self.assertEqual(rows[0]["status"],"interview")
        self.assertEqual(rows[0]["custom"],"keep")
        self.assertEqual(rows[1]["status"],"drafted")

    def test_document_paths_cannot_escape_project(self):
        secret=Path(self.temp.name)/"secret.txt";secret.write_text("private")
        self.assertIsNone(self.store.file_path({"cv_file":str(secret)},"cv"))

    def test_unknown_status_and_invalid_dates_do_not_mutate(self):
        for values in ({"status":"sent_maybe"},{"status":"applied","confirmed_submitted":True,"applied_date":"bad"}):
            with self.assertRaises(ValueError):self.store.update(self.key,values)
        self.assertEqual(self.store.list_jobs()[0]["status"],"researching")


class EmailMonitoringTests(unittest.TestCase):
    setUp = ApplicationTrackerTests.setUp
    def snapshot(self, **changes):
        item=dict(message_id="message-123",company="Example",role="DevOps Engineer",signal="rejection",proposed_status="rejected",date="2026-11-03",subject="Application update",evidence="We will not proceed",full_body_read=True)
        item.update(changes)
        (self.store.data/"email_snapshot.json").write_text(json.dumps(dict(last_checked="2026-11-07",items=[item],continuous_polling=False)))

    def test_email_monitor_proposes_without_changing_status(self):
        self.snapshot()
        self.assertTrue(self.store.email_items()["items"][0]["can_apply"])
        self.assertEqual(self.store.list_jobs()[0]["status"],"researching")
        self.assertFalse((self.root/"job_search_tracker.csv").exists())

    def test_approval_is_explicit_and_idempotent(self):
        self.snapshot()
        self.store.email_action("message-123","apply")
        self.assertEqual(self.store.list_jobs()[0]["status"],"rejected")
        self.assertFalse(self.store.email_items()["items"][0]["can_apply"])
        with self.assertRaises(ValueError):self.store.email_action("message-123","apply")
        self.assertEqual(len(self.store.history(self.key)),1)

    def test_delivery_failure_and_unmatched_email_do_not_write(self):
        for changes in [dict(signal="delivery_failed",proposed_status=None),dict(company="Unknown")]:
            self.snapshot(**changes)
            self.assertFalse(self.store.email_items()["items"][0]["can_apply"])
            with self.assertRaises(ValueError):self.store.email_action("message-123","apply")
        self.assertFalse((self.root/"job_search_tracker.csv").exists())

    def test_dismiss_keeps_application_unchanged(self):
        self.snapshot();self.store.email_action("message-123","dismiss")
        self.assertEqual(self.store.list_jobs()[0]["status"],"researching")
        self.assertEqual(self.store.email_items()["items"][0]["action"],"dismiss")


class ReviewPacketImportTests(unittest.TestCase):
    setUp = ApplicationTrackerTests.setUp
    def test_review_packet_enriches_metadata_without_claiming_submission(self):
        folder=self.root/"documents/applications/test";folder.mkdir()
        (folder/"review.md").write_text("Review only")
        manifest={"roles":[{"company":"Example","title":"DevOps Engineer","url":"https://example.test/jobs/123","review_file":"documents/applications/test/review.md","employer_country":"India (HQ)","preparation_status":"Draft for review","blockers":["Dates unknown"]}]}
        (self.root/"documents/applications/review_batch_test.json").write_text(json.dumps(manifest))
        job=self.store.list_jobs()[0]
        self.assertEqual(job["status"],"researching")
        self.assertTrue(job["review_available"])
        self.assertEqual(job["employer_country"],"India (HQ)")
        self.assertFalse((self.root/"job_search_tracker.csv").exists())


if __name__=="__main__":unittest.main()
