#!/usr/bin/env python3
"""One-employer application runner. Default: local-only dry run, no submissions."""
from __future__ import annotations
import argparse, hashlib, html, json, re, subprocess, sys, uuid
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
JOB_URL="https://www.allstarsit.com/job-posts/senior-linux-web-system-administrator-web-infrastructure-part-time-remote-pxsezf"
JOB_ID="PxSeZF"
FORM_ID="wf-form-Candidates-Form"
EXPECTED={"Full-name":"text","Email-6":"email","Phone-2":"text","Country-2":"text","File-7":"file","Message-2":"textarea","Transferring-Personal-Data-Confirmation":"checkbox"}
TECH_URL="https://techlumas.com/careers/devops-engineer/"
TECH_EXPECTED={"j-name":"text","j-email":"email","j-phone":"tel","j-exp":"text","j-portfolio":"url","j-cv":"url","j-cover":"textarea"}
CHECKS=("philippines_eligible","schedule_fits_existing_job","pay_meets_usd_40_hour","concurrent_work_accepted","data_transfer_consent")
class PreSubmissionError(ValueError):
 """A read-only prerequisite failed before any employer form was filled."""

class FormParser(HTMLParser):
 def __init__(self):
  super().__init__();self.forms=[];self.current=None
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=="form":self.current={"attrs":a,"controls":[]};self.forms.append(self.current)
  elif self.current is not None and tag in ("input","textarea","select","button"):
   self.current["controls"].append({"tag":tag,**a})
 def handle_endtag(self,tag):
  if tag=="form":self.current=None

def inspect_form(markup):
 p=FormParser();p.feed(markup);matches=[f for f in p.forms if f['attrs'].get('id')==FORM_ID]
 if len(matches)!=1:raise ValueError("Expected exactly one supported employer form")
 f=matches[0];controls=f['controls'];index={}
 for c in controls:
  if c.get('id'):
   if c['id'] in index:raise ValueError('Duplicate control ID')
   index[c['id']]=c
 for key,kind in EXPECTED.items():
  if key not in index or (index[key]['tag'] if kind=='textarea' else index[key].get('type','text'))!=kind:
   raise ValueError('Form schema changed: '+key)
 for c in controls:
  if 'required' in c and c.get('type') not in ('hidden','submit') and c.get('id') not in EXPECTED:
   raise ValueError('Unmapped required field: '+str(c.get('name')))
 ids=[c.get('value') for c in controls if c.get('name') in ('jb-id-position','vacancy_local_id')]
 if not ids or any(v!=JOB_ID for v in ids):raise ValueError('Wrong employer job ID')
 return f

def local_replica(form,job_title):
 # Rebuild only trusted mapped controls; no source JavaScript, URLs or event handlers.
 parts=['<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; form-action \'none\'; connect-src \'none\'"><style>body{font:16px sans-serif;max-width:850px;margin:30px auto;color:#18354b}label{display:block;margin:18px 0 5px}input,textarea{box-sizing:border-box;width:100%;padding:9px}input[type=checkbox]{width:auto}textarea{height:220px}.note{background:#fff0c9;padding:18px}</style></head><body><h1>Local application dry run</h1><p class="note">OFFLINE REPLICA. Nothing is uploaded or submitted. Consent remains unchecked.</p><h2>'+html.escape(job_title)+'</h2><form id="'+FORM_ID+'">']
 for key,kind in EXPECTED.items():
  label={'Full-name':'Full name','Email-6':'Email','Phone-2':'Phone','Country-2':'Country','File-7':'Resume (local attachment only)','Message-2':'Application message','Transferring-Personal-Data-Confirmation':'Data-transfer consent - pending applicant decision'}[key]
  parts.append('<label for="'+key+'">'+html.escape(label)+'</label>')
  if kind=='textarea':parts.append('<textarea id="'+key+'" maxlength="5000"></textarea>')
  else:parts.append('<input id="'+key+'" type="'+kind+'"'+(' required' if kind!='checkbox' else '')+'>')
 parts.append('<button type="submit" disabled>Submission disabled in dry run</button></form></body></html>')
 return ''.join(parts)

def load_application(plan_path):
 plan=json.loads(plan_path.read_text())
 allstars=plan.get('adapter')=='allstarsit-pxsezf' and plan.get('url')==JOB_URL and plan.get('job_id')==JOB_ID and plan.get('company')=='ALLSTARSIT'
 tech=plan.get('adapter')=='techlumas-devops' and plan.get('url')==TECH_URL and plan.get('job_id')=='devops-engineer' and plan.get('company')=='Techlumas Solutions'
 if not (allstars or tech):raise ValueError('Unsupported or mismatched employer/job')
 profile=json.loads((ROOT/plan['profile_source']).read_text())['fields']
 values={key:profile.get(field) for key,field in {'Full-name':'full_name','Email-6':'email','Phone-2':'phone_international','Country-2':'work_country'}.items()}
 if any(not isinstance(v,str) or not v.strip() for v in values.values()):raise ValueError('Missing confirmed identity/contact field')
 if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',values['Email-6']):raise ValueError('Invalid confirmed email')
 values['Message-2']=plan['message']
 if not values['Message-2'].strip() or len(values['Message-2'])>5000:raise ValueError('Invalid message length')
 resume=(ROOT/plan['resume']).resolve()
 if not resume.is_relative_to(ROOT) or resume.suffix.lower()!='.pdf' or not resume.is_file() or resume.stat().st_size>10_000_000:raise ValueError('Missing or invalid local PDF')
 digest=hashlib.sha256(resume.read_bytes()).hexdigest()
 if digest!=plan.get('resume_sha256'):raise ValueError('Resume changed after preparation; review and update its checksum')
 from pypdf import PdfReader
 reader=PdfReader(resume);text=' '.join(p.extract_text() or '' for p in reader.pages)
 for value in [profile['full_name'],profile['email'],'Tookitaki','July 2026 - Present']:
  if value.casefold() not in text.casefold():raise ValueError('Resume/profile mismatch: '+value)
 if len(reader.pages)!=2:raise ValueError('Resume must be exactly two pages')
 if tech:
  url=plan.get('resume_url','')
  if not re.fullmatch(r'https://media\.onlinejobs\.ph/jobseekers_resumes/[a-f0-9]+\.pdf',url):raise ValueError('Unverified public resume URL')
  values={'j-name':profile['full_name'],'j-email':profile['email'],'j-phone':profile['phone_international'],'j-exp':'4 years in cloud and DevOps; Senior SRE since July 2026','j-portfolio':profile.get('linkedin_url') or 'https://www.linkedin.com/in/catibag-ronald/','j-cv':url,'j-cover':plan['message']}
 return plan,values,resume

def submission_blockers(plan):
 if plan.get('adapter') in {'greenhouse-selected','ashby-selected','lever-selected'}:
  if plan.get('missing_fields'):return ['missing_confirmed_'+x for x in plan['missing_fields']]
  # This adapter validates every current required question against the prepared answers before fill.
  return [] if plan.get('answers') and plan.get('question_labels') else ['missing_prepared_answers']
 checks=plan.get('confirmed_checks',{})
 blockers = [name for name in CHECKS if checks.get(name) is not True]
 # Explicit user policy allows an honest application when geography is unknown.
 # A confirmed rejection of Philippines eligibility is never converted into acceptance.
 policy = plan.get('application_policy', {})
 if checks.get('philippines_eligible') is None and policy.get('allow_unconfirmed_country') is True and 'philippines' in plan.get('message', '').casefold():
  blockers.remove('philippines_eligible')
 # Applying is a request for consideration, not acceptance of unknown contract terms.
 # The user authorized negotiation with an honest disclosure of all availability/rate facts.
 if policy.get('apply_with_disclosed_terms') is True:
  message=plan.get('message','').casefold()
  disclosed=all(x in message for x in ('philippines','four hours','9 am-6 pm','usd 40','existing role'))
  if disclosed:
   for name in ('schedule_fits_existing_job','pay_meets_usd_40_hour','concurrent_work_accepted'):
    if checks.get(name) is None and name in blockers:blockers.remove(name)
 # Techlumas has no personal-data consent checkbox in this specific schema.
 if plan.get('adapter')=='techlumas-devops' and 'data_transfer_consent' in blockers:blockers.remove('data_transfer_consent')
 return blockers

def fetch_public_form(run,url=JOB_URL):
 dest=run/'source.html'
 result=subprocess.run([sys.executable,str(ROOT/'tools/fetch_page.py'),url,'--out',str(dest)],capture_output=True,text=True,timeout=60)
 (run/'fetch.log').write_text(result.stdout+result.stderr)
 if result.returncode or not re.search(r'HTTP 200(?: |$)',result.stdout):raise ValueError('Public form fetch failed or returned non-200; inspect fetch.log')
 guard=subprocess.run([sys.executable,str(ROOT/'tools/posting_guard.py'),'--in',str(dest),'--html','--out',str(run/'posting-clean.txt'),'--json'],capture_output=True,text=True,timeout=20,check=True)
 (run/'posting-guard.log').write_text(guard.stdout)
 return dest.read_text()

def fill_form(page,values,resume):
 form=page.locator('#'+FORM_ID)
 for key,value in values.items():form.locator('#'+key).fill(value)
 form.locator('#File-7').set_input_files(str(resume))
 return form

def execute_browser(plan,values,resume,form,run,submit=False,headed=False):
 from playwright.sync_api import sync_playwright,expect
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=not headed)
  context=browser.new_context(service_workers='block',offline=not submit,viewport={'width':1100,'height':1200})
  network=[]
  if not submit:
   context.route('**/*',lambda route:route.abort())
  context.on('request',lambda req:network.append({'method':req.method,'origin':req.url.split('?')[0]}))
  page=context.new_page();page.set_default_timeout(15000)
  try:
   if not submit:
    markup=local_replica(form,plan['title']);(run/'replica.html').write_text(markup)
    page.set_content(markup)
   else:
    page.goto(JOB_URL,wait_until='domcontentloaded',timeout=45000)
    inspect_form(page.content())
    if page.locator('iframe[src*="captcha"]').count():raise ValueError('CAPTCHA present; manual action required')
    if page.locator('input[type=password]').count():raise ValueError('Login required; manual action required')
    if page.locator('.w-form-done').is_visible():raise ValueError('Success message already visible before submission')
   filled=fill_form(page,values,resume)
   for key,value in values.items():expect(filled.locator('#'+key)).to_have_value(value)
   filename=filled.locator('#File-7').evaluate('(el) => el.files[0]?.name')
   if filename!=resume.name:raise ValueError('File attachment mismatch')
   page.screenshot(path=str(run/'filled-form.png'),full_page=True)
   if not submit:
    if filled.locator('#Transferring-Personal-Data-Confirmation').is_checked():raise ValueError('Consent unexpectedly checked in dry run')
    if not filled.locator('[type=submit]').is_disabled():raise ValueError('Dry-run submit control is enabled')
    if network:raise ValueError('Offline replica unexpectedly attempted network traffic')
    return {'status':'dry_run_passed','submitted':False,'field_values_verified':True,'resume_attached_locally':True,'consent_checked':False,'outbound_browser_requests':0,'live_submission_verified':False}
   filled.locator('#Transferring-Personal-Data-Confirmation').check()
   filled.locator('[type=submit]').click()
   # HTTP 200, static hidden success HTML and a button click alone are not success.
   try:
    expect(page.locator('.w-form-done')).to_be_visible(timeout=25000)
    expect(filled).to_be_hidden(timeout=5000)
    message=page.locator('.w-form-done').inner_text().strip()
    if 'received' not in message.lower():raise ValueError('No explicit received confirmation')
    result={'status':'submission_confirmed','submitted':True,'confirmation':message,'confirmed_url':page.url}
   except Exception as error:
    result={'status':'submission_unconfirmed','submitted':False,'error':str(error),'note':'Do not retry automatically: duplicate application possible. Check email/employer portal.'}
   page.screenshot(path=str(run/'submission-result.png'),full_page=True)
   result['requests']=network
   return result
  finally:context.close();browser.close()

def inspect_tech_form(markup):
 class Controls(HTMLParser):
  def __init__(self):super().__init__();self.controls={};self.depth=0
  def handle_starttag(self,tag,attrs):
   a=dict(attrs)
   if tag=='div':
    if a.get('id')=='jobFormContent':self.depth=1
    elif self.depth:self.depth+=1
   if self.depth and tag in ('input','textarea','select'):
    key=a.get('id')
    if key not in TECH_EXPECTED:raise ValueError('Unmapped Techlumas application field: '+str(key))
    if key in self.controls:raise ValueError('Duplicate Techlumas field')
    self.controls[key]=(tag,a)
  def handle_endtag(self,tag):
   if tag=='div' and self.depth:self.depth-=1
 p=Controls();p.feed(markup)
 for key,kind in TECH_EXPECTED.items():
  if key not in p.controls:raise ValueError('Techlumas schema changed: '+key)
  tag,a=p.controls[key]
  if (tag if tag=='textarea' else a.get('type','text'))!=kind:raise ValueError('Techlumas field type changed: '+key)
 if 'DevOps Engineer' not in markup or 'jobFormContent' not in markup or 'jobSuccess' not in markup or 'submitJob' not in markup:raise ValueError('Techlumas form handler changed')
 return True

def execute_tech_browser(plan,values,resume,run,submit=False,headed=False):
 from playwright.sync_api import sync_playwright,expect
 if submit:
  import urllib.request
  try:
   request=urllib.request.Request(plan['resume_url'],headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.onlinejobs.ph/'})
   with urllib.request.urlopen(request,timeout=30) as response:data=response.read(10_000_001)
   if hashlib.sha256(data).hexdigest()!=plan['resume_sha256']:raise ValueError('Public resume differs from reviewed PDF')
  except Exception as error:raise PreSubmissionError('Public resume verification failed before form fill: '+str(error)) from error
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=not headed)
  context=browser.new_context(service_workers='block',offline=not submit,viewport={'width':1200,'height':1000})
  if not submit:context.route('**/*',lambda route:route.abort())
  page=context.new_page();page.set_default_timeout(15000);network=[];dialogs=[]
  context.on('request',lambda r:network.append({'method':r.method,'url':r.url.split('?')[0]}))
  page.on('dialog',lambda dialog:(dialogs.append(dialog.message),dialog.dismiss()))
  try:
   if submit:
    page.goto(TECH_URL,wait_until='networkidle',timeout=45000);inspect_tech_form(page.content())
    if page.locator('#jobSuccess').is_visible():raise ValueError('Success already visible before submission')
    if not page.locator('#jobFormContent').is_visible():page.locator('a[href="#apply"]').first.click()
   else:
    controls=[]
    for key,kind in TECH_EXPECTED.items():
     controls.append('<label>'+key+'</label>'+('<textarea id="'+key+'"></textarea>' if kind=='textarea' else '<input id="'+key+'" type="'+kind+'">'))
    replica='<!doctype html><html><body><h1>OFFLINE Techlumas application dry run</h1><p>No data is sent.</p><div id="jobFormContent">'+''.join(controls)+'<button id="j-btn" disabled>Submission disabled</button></div></body></html>'
    (run/'replica.html').write_text(replica);page.set_content(replica)
   for key,value in values.items():
    page.locator('#'+key).fill(value);expect(page.locator('#'+key)).to_have_value(value)
   page.screenshot(path=str(run/'filled-form.png'),full_page=True)
   if not submit:
    expect(page.locator('#j-btn')).to_be_disabled()
    if network:raise ValueError('Offline browser attempted network requests')
    return {'status':'dry_run_passed','submitted':False,'field_values_verified':True,'outbound_browser_requests':0}
   try:
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.split('?')[0]=='https://techlumas.com/wp-admin/admin-ajax.php',timeout=45000) as pending:
     page.locator('#j-btn').click()
    response=pending.value;payload=response.json()
    (run/'employer-response.json').write_text(json.dumps({'http_status':response.status,'response':payload},indent=2))
    if response.status!=200 or payload.get('success') is not True:raise ValueError('Employer did not confirm receipt: '+str(payload)[:500])
    expect(page.locator('#jobSuccess')).to_be_visible(timeout=5000)
    expect(page.locator('#jobFormContent')).to_be_hidden()
    message=page.locator('#jobSuccess').inner_text()
    result={'status':'submission_confirmed','submitted':True,'confirmation':message,'confirmed_url':page.url}
   except Exception as error:
    result={'status':'submission_unconfirmed','submitted':False,'error':str(error),'dialogs':dialogs,'note':'Check employer/email; do not automatically resend.'}
   page.screenshot(path=str(run/'submission-result.png'),full_page=True);result['requests']=network;return result
  finally:context.close();browser.close()

def main(argv=None):
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True)
 mode=ap.add_mutually_exclusive_group();mode.add_argument('--dry-run',action='store_true');mode.add_argument('--submit',action='store_true')
 ap.add_argument('--confirm-job-id');ap.add_argument('--headed',action='store_true');ap.add_argument('--log-root',type=Path,default=Path.home()/'local-ai/logs/sessions')
 args=ap.parse_args(argv)
 if args.submit and not args.confirm_job_id:ap.error('--submit requires --confirm-job-id')
 log_root=args.log_root.expanduser().resolve()
 if log_root.is_relative_to(ROOT):ap.error('Keep execution evidence outside the repository')
 stamp=datetime.now(ZoneInfo('Asia/Manila'));run=log_root/('application-'+stamp.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
 result={'started_at':stamp.isoformat(),'mode':'submit' if args.submit else 'dry-run','submitted':False,'run_directory':str(run)}
 try:
  plan,values,resume=load_application(args.plan.resolve());blockers=submission_blockers(plan)
  if args.submit and args.confirm_job_id!=plan['job_id']:raise ValueError('Explicit job confirmation does not match plan')
  result.update(company=plan['company'],job_id=plan['job_id'],submission_blockers=blockers)
  if args.submit and blockers:raise ValueError('Submission blocked by unconfirmed fields: '+', '.join(blockers))
  markup=fetch_public_form(run,plan['url'])
  if plan['adapter']=='techlumas-devops':
   inspect_tech_form(markup)
   result.update(execute_tech_browser(plan,values,resume,run,args.submit,args.headed))
  else:
   form=inspect_form(markup)
   result.update(execute_browser(plan,values,resume,form,run,args.submit,args.headed))
 except Exception as error:result.update(status='blocked_or_failed',error=str(error),safe_to_retry=isinstance(error,PreSubmissionError))
 result['finished_at']=datetime.now(ZoneInfo('Asia/Manila')).isoformat()
 (run/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 (run/'conversation.md').write_text('# Application runner\n\n'+json.dumps(result,indent=2)+'\n')
 base=Path.home()/'local-ai';base.mkdir(exist_ok=True)
 with (base/'PROMPT_LOG.md').open('a') as f:f.write('\n## Application runner '+result['finished_at']+'\n\nMode: '+result['mode']+'. Result: '+result['status']+'. [Evidence]('+str(run/'result.json')+').\n')
 (base/'logs').mkdir(parents=True,exist_ok=True)
 with (base/'logs/interactions.jsonl').open('a') as f:f.write(json.dumps({'event':'application_runner_result',**result})+'\n')
 print(json.dumps(result,indent=2))
 return 0 if result['status'] in ('dry_run_passed','submission_confirmed') else 1
if __name__=='__main__':raise SystemExit(main())
