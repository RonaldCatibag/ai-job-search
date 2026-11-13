"""Durable queue, restart safety and evidence-backed application transitions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.application_tracker import Store
from tools.application_controller import Controller
from tools.application_runner import submission_blockers, CHECKS

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"; self.root.mkdir()
        (self.root / "job_scraper").mkdir()
        self.source = self.root / "job_scraper/seen_jobs.json"
        self.write_job()
        self.store = Store(self.root, Path(self.tmp.name) / "data")
        self.controller = Controller(self.store, reviewer=lambda *_: {"summary": "Review only", "approved": True})
    def write_job(self, status="new", **fields):
        item = dict(company="Example", title="DevOps Engineer", url="https://example.test/jobs/1", status=status, location="Remote", review_notes="AWS, Kubernetes; salary unknown", **fields)
        self.source.write_text(json.dumps({"seen": {"example": item}}))
    def task(self):
        self.controller.enqueue(); return self.controller.claim()
    def test_persistent_unique_queue_skips_submitted(self):
        self.assertEqual(self.controller.enqueue()["queued"], 1)
        other = Controller(self.store)
        self.assertEqual(other.enqueue()["queued"], 0)
        self.assertEqual(len(other.snapshot()["tasks"]), 1)
        self.write_job(status="applied")
        self.assertEqual(other.enqueue()["queued"], 0)
    def test_atomic_claim_only_one_worker_gets_task(self):
        self.controller.enqueue()
        other = Controller(self.store)
        self.assertIsNotNone(self.controller.claim()); self.assertIsNone(other.claim())
    def test_restore_explicit_portal_placeholder_preserves_uncertainty(self):
        self.write_job(status="skipped"); data=json.loads(self.source.read_text())
        data["seen"]["example"]["location"]="Remote portal listing; country eligibility unconfirmed"
        self.source.write_text(json.dumps(data))
        self.assertEqual(self.controller.enqueue(restore=True)["restored"],1)
        job=self.store.list_jobs()[0]
        self.assertEqual(job["status"],"researching");self.assertIn("unconfirmed",job["location"])
    def test_explicit_restriction_not_restored(self):
        self.write_job(status="skipped",eligibility="Explicit other-country restriction")
        data=json.loads(self.source.read_text());data["seen"]["example"]["location"]="Remote portal listing; country eligibility unconfirmed";self.source.write_text(json.dumps(data))
        self.assertEqual(self.controller.enqueue(restore=True)["queued"],0)
    def test_selected_country_mismatch_can_be_reopened_honestly(self):
        self.write_job(status="skipped",eligibility="Explicit other-country restriction")
        key=self.store.list_jobs()[0]["id"]
        result=self.controller.enqueue([key],reopen_selected=True)
        self.assertEqual(result["restored"],1)
        self.assertIn(key,self.controller.settings()["country_mismatch_job_ids"])
        self.assertEqual(self.store.list_jobs()[0]["eligibility"],"Explicit other-country restriction")
        with self.assertRaises(ValueError):self.controller.enqueue(reopen_selected=True)
    def test_metadata_survives_import(self):
        self.write_job(evidence_file="/saved/posting",schedule="20 hours",eligibility="Unknown")
        job=self.store.list_jobs()[0]
        self.assertEqual(job["schedule"],"20 hours");self.assertIn("AWS",job["notes"])
    def test_model_approval_does_not_submit_unsupported_form(self):
        task=self.task();self.controller.process(*task)
        row=self.controller.snapshot()["tasks"][0]
        self.assertEqual(row["state"],"blocked")
        self.assertEqual(self.store.list_jobs()[0]["status"],"researching")
    def test_recover_local_stage_requeues(self):
        task,_=self.task();self.controller.recover()
        self.assertEqual(self.controller.snapshot()["tasks"][0]["state"],"queued")
    def test_recover_external_stage_never_requeues(self):
        task,_=self.task();self.controller.set_task(task,"running","submit",submission_attempted=True)
        self.controller.recover()
        self.assertEqual(self.controller.snapshot()["tasks"][0]["state"],"submission_unknown")
        with self.assertRaises(ValueError):self.controller.action({"action":"retry","task_id":task})
    def test_unconfirmed_result_cannot_mark_applied(self):
        task,_=self.task();self.controller.record_receipt(task,{"submitted":False,"status":"submission_unconfirmed"})
        self.assertEqual(self.store.list_jobs()[0]["status"],"researching")
        self.assertEqual(self.controller.snapshot()["tasks"][0]["state"],"submission_unknown")
    def test_verified_receipt_records_applied_and_restart_is_idempotent(self):
        task,_=self.task()
        receipt={"submitted":True,"status":"submission_confirmed","confirmation":"Application received", "run_directory":"/saved/receipt", "finished_at":"2026-11-09T12:00:00+08:00"}
        self.controller.set_task(task,"running","record",receipt=receipt)
        self.controller.recover()
        self.assertEqual(self.store.list_jobs()[0]["status"],"applied")
        self.assertEqual(self.controller.snapshot()["tasks"][0]["state"],"completed")
        self.controller.recover();self.assertEqual(len(self.store.history(self.store.list_jobs()[0]["id"])),1)
    def test_receipt_cannot_regress_later_status(self):
        task,job=self.task();self.store.update(job,{"status":"interview"})
        self.controller.record_receipt(task,{"submitted":True,"status":"submission_confirmed","confirmation":"received","run_directory":"/evidence"})
        self.assertEqual(self.store.list_jobs()[0]["status"],"interview")
    def test_country_override_allows_unknown_but_not_false_or_missing_disclosure(self):
        plan={"confirmed_checks":dict.fromkeys(CHECKS,True),"application_policy":{"allow_unconfirmed_country":True},"message":"Based in the Philippines"}
        plan["confirmed_checks"]["philippines_eligible"]=None
        self.assertEqual(submission_blockers(plan),[])
        plan["confirmed_checks"]["philippines_eligible"]=False
        self.assertIn("philippines_eligible",submission_blockers(plan))
        plan["confirmed_checks"]["philippines_eligible"]=None;plan["message"]="Remote"
        self.assertIn("philippines_eligible",submission_blockers(plan))
    def test_country_override_cannot_clear_other_checks(self):
        blockers=submission_blockers({"application_policy":{"allow_unconfirmed_country":True},"message":"Philippines"})
        self.assertNotIn("philippines_eligible",blockers)
        self.assertIn("data_transfer_consent",blockers);self.assertIn("schedule_fits_existing_job",blockers)
    def test_verification_code_is_private_ephemeral_and_not_logged(self):
        task,_=self.task();self.controller.set_task(task,"running","submit",submission_attempted=True)
        run=self.store.data/"controller-runs"/task/"attempt-1/submit/application-test";run.mkdir(parents=True)
        (run/"verification-request.json").write_text('{"company":"Example"}')
        code="TESTABCD";result=self.controller.action({"action":"provide_code","task_id":task,"code":code})
        self.assertTrue(result["delivered"]);self.assertEqual((run/"verification-code.tmp").stat().st_mode&0o777,0o600)
        self.assertNotIn(code,json.dumps(self.controller.events(task)))
    def test_verification_code_rejected_without_active_browser(self):
        task,_=self.task();self.controller.set_task(task,"blocked","verify")
        with self.assertRaises(ValueError):self.controller.action({"action":"provide_code","task_id":task,"code":"TESTABCD"})
    def test_uncertain_outcome_requires_owner_confirmation_before_requeue(self):
        task,_=self.task();self.controller.set_task(task,"submission_unknown","verify",submission_attempted=True)
        with self.assertRaises(ValueError):self.controller.action({"action":"resolve_unsent","task_id":task})
        self.controller.action({"action":"resolve_unsent","task_id":task,"confirmed_not_submitted":True})
        row=self.controller.snapshot()["tasks"][0];self.assertEqual(row["state"],"queued");self.assertFalse(row["detail"]["submission_attempted"])
        self.assertEqual(self.store.list_jobs()[0]["status"],"researching")
    def test_confirmed_application_cannot_be_requeued_as_unsent(self):
        task,_=self.task();self.controller.set_task(task,"completed","done",submission_attempted=True)
        with self.assertRaises(ValueError):self.controller.action({"action":"resolve_unsent","task_id":task,"confirmed_not_submitted":True})
    def test_pause_persists_and_invalid_action_rejected(self):
        self.controller.action({"action":"pause"});self.assertTrue(Controller(self.store).settings()["paused"])
        with self.assertRaises(ValueError):self.controller.action({"action":"shell","command":"anything"})
    def test_single_process_worker_lock(self):
        self.controller.action({"action":"pause"});self.controller.start();self.addCleanup(self.controller.close)
        with self.assertRaisesRegex(RuntimeError,"already running"):Controller(self.store).start()

if __name__ == "__main__": unittest.main()

class ControllerHttpTests(unittest.TestCase):
    def test_mutations_require_token_and_same_origin(self):
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        from tools.application_tracker import Handler, TOKEN
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"repo";root.mkdir()
            store=Store(root,Path(tmp)/"data")
            class LocalHandler(Handler): pass
            LocalHandler.store=store;LocalHandler.controller=Controller(store)
            server=ThreadingHTTPServer(("127.0.0.1",0),LocalHandler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base="http://127.0.0.1:"+str(server.server_port)
                with urllib.request.urlopen(base+"/api/controller") as response:
                    self.assertEqual(json.load(response)["counts"],{})
                for headers in [{}, {"X-Tracker-Token":TOKEN,"Origin":"https://external.test"}]:
                    req=urllib.request.Request(base+"/api/controller",data=b'{"action":"pause"}',headers=headers)
                    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
                    self.assertEqual(caught.exception.code,403)
                req=urllib.request.Request(base+"/api/controller",data=b'{"action":"pause"}',headers={"X-Tracker-Token":TOKEN,"Origin":base})
                with urllib.request.urlopen(req) as response:self.assertTrue(json.load(response)["paused"])
            finally:server.shutdown();server.server_close();thread.join()
