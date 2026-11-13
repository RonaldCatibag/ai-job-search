"""Application boundaries: schema drift, blocking and offline replica isolation."""
import contextlib,hashlib,io,json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from tools import application_runner as runner


def fixture(extra="",job_id="PxSeZF"):
 controls=[]
 for key,kind in runner.EXPECTED.items():
  if kind=='textarea':controls.append(f'<textarea id="{key}"></textarea>')
  else:controls.append(f'<input id="{key}" type="{kind}" required>')
 return '<form id="'+runner.FORM_ID+'">'+''.join(controls)+f'<input type="hidden" name="vacancy_local_id" value="{job_id}">'+extra+'</form>'

class ApplicationRunnerTests(unittest.TestCase):
 def test_schema_drift_missing_file_blocks(self):
  with self.assertRaisesRegex(ValueError,'File-7'):runner.inspect_form(fixture().replace('id="File-7"','id="Other-file"'))
 def test_unknown_required_declaration_blocks(self):
  with self.assertRaisesRegex(ValueError,'Unmapped required'):runner.inspect_form(fixture('<input id="legal-new" name="new_declaration" required type="checkbox">'))
 def test_wrong_job_blocks(self):
  with self.assertRaisesRegex(ValueError,'Wrong employer'):runner.inspect_form(fixture(job_id='another-role'))
 def test_duplicate_form_blocks(self):
  with self.assertRaisesRegex(ValueError,'exactly one'):runner.inspect_form(fixture()+fixture())
 def test_replica_strips_source_scripts_and_disables_submit(self):
  form=runner.inspect_form(fixture('<script>fetch("https://leak.example")</script><img src="https://tracker.example">'))
  result=runner.local_replica(form,'<script>untrusted</script>')
  self.assertNotIn('<script>',result);self.assertNotIn('tracker.example',result);self.assertIn('form-action',result)
  self.assertIn('type="submit" disabled',result);self.assertNotIn(' checked',result)
 def test_unknown_checks_block_but_all_true_clear(self):
  self.assertEqual(set(runner.submission_blockers({})),set(runner.CHECKS))
  self.assertEqual(runner.submission_blockers({'confirmed_checks':dict.fromkeys(runner.CHECKS,True)}),[])
  self.assertIn('data_transfer_consent',runner.submission_blockers({'confirmed_checks':{'data_transfer_consent':'yes'}}))
 def make_plan(self,tmp):
  root=Path(tmp)/'project';root.mkdir();pdf=root/'resume.pdf';pdf.write_bytes(b'%PDF-local-fixture')
  profile={'fields':{'full_name':'Test Applicant','email':'test@example.test','phone_international':'+630000000000','work_country':'Philippines'}}
  (root/'profile.json').write_text(json.dumps(profile))
  plan={'adapter':'allstarsit-pxsezf','company':'ALLSTARSIT','url':runner.JOB_URL,'job_id':runner.JOB_ID,'profile_source':'profile.json','message':'USD 40 per hour; four hours per day.','resume':'resume.pdf','resume_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'confirmed_checks':{}}
  path=root/'plan.json';path.write_text(json.dumps(plan));return root,path,plan
 def fake_reader(self):
  page=types.SimpleNamespace(extract_text=lambda:'Test Applicant test@example.test Tookitaki July 2026 - Present')
  return types.SimpleNamespace(PdfReader=lambda _:types.SimpleNamespace(pages=[page,page]))
 def test_confirmed_profile_maps_to_form(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,p,plan=self.make_plan(tmp)
   with patch.object(runner,'ROOT',root),patch.dict('sys.modules',{'pypdf':self.fake_reader()}):
    _,values,resume=runner.load_application(p)
   self.assertEqual(values['Country-2'],'Philippines');self.assertEqual(values['Full-name'],'Test Applicant');self.assertTrue(resume.is_file())
 def test_changed_resume_checksum_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,p,plan=self.make_plan(tmp);plan['resume_sha256']='0'*64;p.write_text(json.dumps(plan))
   with patch.object(runner,'ROOT',root),self.assertRaisesRegex(ValueError,'Resume changed'):runner.load_application(p)
 def test_submit_with_missing_facts_never_fetches_or_launches_browser(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,p,plan=self.make_plan(tmp)
   with patch.object(runner,'ROOT',root),patch.dict('sys.modules',{'pypdf':self.fake_reader()}),patch.object(Path,'home',return_value=Path(tmp)),patch.object(runner,'fetch_public_form') as fetch,patch.object(runner,'execute_browser') as browser,contextlib.redirect_stdout(io.StringIO()):
    code=runner.main(['--plan',str(p),'--submit','--confirm-job-id','PxSeZF','--log-root',str(Path(tmp)/'runs')])
   self.assertEqual(code,1);fetch.assert_not_called();browser.assert_not_called()
   d=json.loads(next((Path(tmp)/'runs').glob('*/result.json')).read_text())
   self.assertFalse(d['submitted']);self.assertEqual(d['status'],'blocked_or_failed')
 def test_explicit_job_confirmation_required(self):
  with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):runner.main(['--plan','unused.json','--submit'])

class DirectAdapterTests(unittest.TestCase):
 def tech_fixture(self,extra=""):
  controls=[]
  for key,kind in runner.TECH_EXPECTED.items():
   controls.append(f'<textarea id="{key}"></textarea>' if kind=='textarea' else f'<input id="{key}" type="{kind}">')
  return '<h1>DevOps Engineer</h1><div id="jobFormContent">'+''.join(controls)+extra+'</div><div id="jobSuccess"></div><script>submitJob</script>'
 def test_tech_schema_validates(self):self.assertTrue(runner.inspect_tech_form(self.tech_fixture()))
 def test_tech_unknown_declaration_blocks(self):
  with self.assertRaisesRegex(ValueError,'Unmapped Techlumas'):runner.inspect_tech_form(self.tech_fixture('<input id="work-rights" type="checkbox" required>'))
 def test_tech_missing_field_blocks(self):
  with self.assertRaisesRegex(ValueError,'schema changed'):runner.inspect_tech_form(self.tech_fixture().replace('id="j-cv"','id="other"').replace('<input id="other" type="url">',''))
 def test_disclosed_terms_are_not_fabricated_confirmations(self):
  plan={'message':'Philippines; four hours per day outside 9 AM-6 PM, USD 40 per hour, alongside my existing role','confirmed_checks':{'data_transfer_consent':True},'application_policy':{'allow_unconfirmed_country':True,'apply_with_disclosed_terms':True}}
  self.assertEqual(runner.submission_blockers(plan),[])
  self.assertNotIn('schedule_fits_existing_job',plan['confirmed_checks'])
  plan['confirmed_checks']['schedule_fits_existing_job']=False
  self.assertIn('schedule_fits_existing_job',runner.submission_blockers(plan))
 def test_disclosed_terms_policy_does_not_bypass_consent(self):
  plan={'message':'Philippines; four hours outside 9 AM-6 PM, USD 40, existing role','application_policy':{'allow_unconfirmed_country':True,'apply_with_disclosed_terms':True}}
  self.assertEqual(runner.submission_blockers(plan),['data_transfer_consent'])

if __name__=='__main__':unittest.main()
