import unittest
from tools.application_tracker import review_state

class ReviewStateTests(unittest.TestCase):
 def test_new_listing_still_needs_review(self):
  r=review_state({'status':'researching'})
  self.assertTrue(r['needs_review']);self.assertTrue(r['pending_submission'])
 def test_blocked_screening_is_complete_but_application_remains_pending(self):
  r=review_state({'status':'researching'},{'state':'blocked','stage':'prepare','detail':{'reason':'Required personal answer'}})
  self.assertFalse(r['needs_review']);self.assertTrue(r['pending_submission']);self.assertEqual(r['workflow_state'],'blocked')
 def test_unknown_outcome_is_not_reported_as_sent(self):
  job={'status':'researching'}
  r=review_state(job,{'state':'submission_unknown','stage':'verify','detail':{}})
  self.assertTrue(r['pending_submission']);self.assertEqual(r['workflow_state'],'verify_submission');self.assertEqual(job['status'],'researching')
 def test_failed_model_review_does_not_clear_review_queue(self):
  r=review_state({'status':'researching'},{'state':'failed','stage':'review','detail':{'reason':'Invalid model JSON'}})
  self.assertTrue(r['needs_review']);self.assertFalse(r['review_complete'])
 def test_applied_record_is_not_pending_even_with_stale_task(self):
  r=review_state({'status':'applied'},{'state':'blocked','stage':'prepare','detail':{}})
  self.assertFalse(r['pending_submission']);self.assertFalse(r['needs_review']);self.assertEqual(r['workflow_state'],'applied')
