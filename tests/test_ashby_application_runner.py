import unittest
from tools.ashby_application_runner import CONFIRMATION,validate_schema,validate_plan

class AshbyPlanTests(unittest.TestCase):
 def setUp(self):
  self.plan={'answers':{'name':'Ronald'},'question_labels':{'name':'Full name'}}
 def test_required_question_must_have_reviewed_answer(self):
  with self.assertRaisesRegex(ValueError,'Unanswered required'):
   validate_schema([{'key':'name','label':'Full name','required':True},{'key':'new','label':'New legal declaration','required':True}],self.plan)
 def test_changed_question_text_stops_submission(self):
  with self.assertRaisesRegex(ValueError,'wording changed'):
   validate_schema([{'key':'name','label':'Consent to relocation','required':True}],self.plan)
 def test_resume_is_handled_separately_and_optional_fields_need_not_be_filled(self):
  self.assertTrue(validate_schema([{'key':'name','label':'Full name','required':True},{'key':'_systemfield_resume','label':'Resume','required':True},{'key':'eeo','label':'Optional demographic','required':False}],self.plan))
 def test_lookalike_host_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'Unapproved'):
   validate_plan({'adapter':'ashby-selected','url':'https://jobs.ashbyhq.com.example.org/acme/123','job_id':'123'})
 def test_job_identity_mismatch_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'Unapproved'):
   validate_plan({'adapter':'ashby-selected','url':'https://jobs.ashbyhq.com/acme/00000000-0000-0000-0000-000000000000','job_id':'11111111-1111-1111-1111-111111111111'})
 def test_xero_success_screen_and_existing_receipts_are_recognized(self):
  for message in ['Thank you - Your application was successfully submitted.','Your application has been received','Thanks for applying!']:
   with self.subTest(message=message):self.assertIsNotNone(CONFIRMATION.search(message))
 def test_instruction_to_apply_is_not_a_receipt(self):
  self.assertIsNone(CONFIRMATION.search('Review your application and click Submit Application.'))

if __name__=='__main__':unittest.main()
