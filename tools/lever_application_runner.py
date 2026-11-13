#!/usr/bin/env python3
"""Fill one reviewed Lever application plan and require an employer receipt."""
import argparse,hashlib,html,json,re,uuid,os,time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def normalize(value):return ' '.join(value.replace(chr(10033),'').replace('*','').split())
def application_url(plan):
 u=urlsplit(plan['url']);parts=u.path.strip('/').split('/')
 if u.hostname=='jobs.lever.com':raise ValueError('Use the reviewed jobs.lever.co URL; jobs.lever.com is not approved')
 if u.scheme!='https' or u.netloc!='jobs.lever.co' or u.query or u.fragment or len(parts) not in [2,3] or (len(parts)==3 and parts[2]!='apply') or parts[1]!=plan['job_id'] or not re.fullmatch(r'[a-zA-Z0-9_-]+',parts[0]) or not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}',parts[1]):raise ValueError('Unapproved employer/job URL')
 return 'https://jobs.lever.co/'+'/'.join(parts[:2])+'/apply'
def exact_application_post(method,url,destination):
 u,t=urlsplit(url),urlsplit(destination)
 return method=='POST' and u.scheme==t.scheme and u.netloc==t.netloc and u.path.rstrip('/')==t.path.rstrip('/')
def receipt_confirmed(ack_visible,form_visible,responses):
 return bool(ack_visible and not form_visible and any(200<=r['status']<300 for r in responses))
def write_json(path,value):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)
def validate_plan(plan):
 if plan.get('adapter')!='lever-selected':raise ValueError('Unapproved employer/job URL')
 application_url(plan)
 resume=(ROOT/plan['resume']).resolve()
 if not resume.is_relative_to(ROOT) or resume.suffix!='.pdf' or hashlib.sha256(resume.read_bytes()).hexdigest()!=plan['resume_sha256']:raise ValueError('Reviewed resume checksum mismatch')
 if not plan.get('answers') or not plan.get('question_labels'):raise ValueError('Missing reviewed answers')
 return resume

def read_schema(page):
 fields=page.locator('input:not([type=hidden]),select,textarea').evaluate_all("""xs=>xs.filter(e=>e.name).map(e=>({key:e.name,type:e.type,required:e.required,label:e.closest('li')?.querySelector('.application-label')?.innerText||e.closest('.application-question')?.querySelector('.application-label')?.innerText||e.labels?.[0]?.innerText||'',value:['radio','checkbox'].includes(e.type)?e.value:undefined,options:e.options?Array.from(e.options).map(o=>({value:o.value,label:o.text})):undefined}))""")
 result={}
 for f in fields:
  k=f['key']
  if k not in result:result[k]={**f,'radio_values':[]}
  if f['type']=='radio':result[k]['radio_values'].append(f['value'])
  if chr(10033) in f.get('label','') or '*' in f.get('label',''):result[k]['required']=True
 return list(result.values())

def validate_schema(schema,plan):
 observed={f['key']:f for f in schema}
 for key,value in plan['answers'].items():
  field=observed.get(key)
  if not field or normalize(field['label'])!=normalize(plan['question_labels'][key]):raise ValueError('Question wording changed: '+key)
  if field['type']=='radio' and value not in field['radio_values']:raise ValueError('Invalid radio choice: '+key)
  if field['type']=='select-one' and value not in [v['value'] for v in field.get('options',[])]:raise ValueError('Invalid select choice: '+key)
 missing=[f['label'] for f in schema if f['required'] and f['key']!='resume' and f['key'] not in plan['answers']]
 if missing:raise ValueError('Unanswered required questions: '+', '.join(missing))
 return True

def main(argv=None):
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--submit',action='store_true');ap.add_argument('--dry-run',action='store_true');ap.add_argument('--confirm-job-id');ap.add_argument('--log-root',type=Path,required=True);a=ap.parse_args(argv)
 run=a.log_root/('application-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
 result={'mode':'submit' if a.submit else 'dry-run','submitted':False,'submission_request_sent':False,'run_directory':str(run)}
 try:
  plan=json.loads(a.plan.read_text());resume=validate_plan(plan);destination=application_url(plan)
  if a.submit and a.confirm_job_id!=plan['job_id']:raise ValueError('Explicit job confirmation required')
  if a.submit and plan.get('missing_fields'):raise ValueError('Missing confirmed facts: '+', '.join(plan['missing_fields']))
  from playwright.sync_api import sync_playwright,expect
  with sync_playwright() as pw:
   interactive=a.submit and plan.get('interactive_verification') is True
   env=os.environ.copy()
   if interactive:env.update(DISPLAY=':0',WAYLAND_DISPLAY='wayland-0',XDG_RUNTIME_DIR='/run/user/1000')
   browser=pw.chromium.launch(headless=not interactive,args=['--disable-gpu'],env=env);context=browser.new_context(offline=not a.submit,service_workers='allow' if a.submit else 'block');page=context.new_page();page.set_default_timeout(15000);responses=[];requests=[]
   try:
    if not a.submit:
     context.route('**/*',lambda r:r.abort());page.set_content(''.join('<label>'+html.escape(plan['question_labels'][k])+'</label><textarea id="f'+str(i)+'"></textarea>' for i,k in enumerate(plan['answers']))+'<input id="resume" type="file"><button disabled>Submit disabled</button>')
     for i,value in enumerate(plan['answers'].values()):page.locator('#f'+str(i)).fill(value)
     page.locator('#resume').set_input_files(str(resume));page.screenshot(path=str(run/'filled-form.png'),full_page=True);result.update(status='dry_run_passed',outbound_browser_requests=0,field_values_verified=True,pending_required_answers=plan.get('missing_fields',[]))
    else:
     def note_request(req):
      if exact_application_post(req.method,req.url,destination):
       requests.append({'method':'POST','url':destination});result['submission_request_sent']=True;save_network()
     def note_response(r):
      if exact_application_post(r.request.method,r.url,destination):
       responses.append({'url':destination,'status':r.status});save_network()
     def save_network():write_json(run/'network-events.json',{'application_requests':requests,'application_responses':responses,'updated_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat()})
     page.on('request',note_request);page.on('response',note_response);save_network();page.goto(destination,wait_until='domcontentloaded',timeout=45000);page.locator('input[name=email]').wait_for()
     schema=read_schema(page);(run/'observed-schema.json').write_text(json.dumps(schema,indent=2));validate_schema(schema,plan)
     page.locator('input[name=resume]').set_input_files(str(resume))
     page.get_by_text('Success!',exact=True).first.wait_for(timeout=45000)
     observed={f['key']:f for f in schema}
     for key,value in plan['answers'].items():
      control=page.locator('[name='+json.dumps(key)+']');kind=observed[key]['type']
      if kind=='radio':
       target=next(c for c in control.all() if c.get_attribute('value')==value);target.check()
      elif kind=='select-one':control.select_option(value=value)
      elif kind=='checkbox':
       if value in ['Yes','No']:control.set_checked(value=='Yes')
       else:
        target=next(c for c in control.all() if c.get_attribute('value')==value);target.check()
      elif key=='location':
       current=control.input_value().lower()
       if 'caloocan' in current and 'philippines' in current:continue
       control.fill('');control.press_sequentially('Caloocan',delay=50)
       options=page.locator('.dropdown-results').get_by_text(re.compile(r'Caloocan.*Philippines',re.I)).first
       try:options.wait_for(timeout=15000);options.click()
       except Exception:pass  # The user can complete this field in the visible browser.
      else:control.fill(value)
     invalid=page.locator('input,select,textarea').evaluate_all("xs=>xs.filter(e=>!e.validity.valid).map(e=>({name:e.name,type:e.type,message:e.validationMessage}))")
     interactive_deadline=time.monotonic()+1800
     user_has_control=bool(invalid and interactive)
     if invalid and interactive:
      request_file=run/'human-verification-request.json'
      write_json(request_file,{'company':plan['company'],'title':plan['title'],'requested_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'kind':'form_review','message':'Complete the highlighted fields in the visible browser, review the application, then click Submit application once and complete any provider challenge yourself. The controller will not race your Submit click.','url':destination,'invalid_fields':invalid})
     if invalid and not interactive:raise ValueError('Browser validation prevents submission: '+json.dumps(invalid))
     page.screenshot(path=str(run/'filled-form.png'),full_page=True)
     submit=page.get_by_role('button',name=re.compile('^Submit application$',re.I)).first
     if not submit.count():submit=page.locator('#btn-submit')
     if not user_has_control:submit.click()
     ack=page.get_by_text(re.compile('thank you|thanks for applying|application (received|submitted)',re.I)).first
     if interactive:
      request_file=run/'human-verification-request.json';deadline=interactive_deadline;announced=user_has_control;error_reported=False
      while time.monotonic()<deadline:
       if receipt_confirmed(ack.count() and ack.is_visible(),page.locator('input[name=email]').is_visible(),responses):break
       verification_error=page.get_by_text(re.compile('there was an error verifying your application',re.I)).first
       if not error_reported and verification_error.count() and verification_error.is_visible():
        result['provider_verification_error']='There was an error verifying your application. Please try again.'
        write_json(run/'verification-error.json',{'error':result['provider_verification_error'],'application_responses':responses})
        write_json(request_file,{'company':plan['company'],'title':plan['title'],'requested_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'kind':'verification_failed','message':'Lever rejected verification. Complete a fresh provider challenge yourself and submit once in the visible browser. No receipt is confirmed. The script will not repeatedly click Submit.','url':destination})
        error_reported=True;announced=True
       if not announced:
        request_file.write_text(json.dumps({'company':plan['company'],'title':plan['title'],'requested_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'kind':'browser_verification','message':'Use the visible Chromium window. Review the filled application and complete any provider challenge yourself. Click Submit application if needed.','url':plan['url']},indent=2));announced=True
       page.wait_for_timeout(500)
      else:raise ValueError('Visible-browser verification was not completed within thirty minutes')
      request_file.unlink(missing_ok=True)
     else:expect(ack).to_be_visible(timeout=45000)
     expect(page.locator('input[name=email]')).not_to_be_visible()
     if not any(200<=r['status']<300 for r in responses):raise ValueError('No successful employer application POST')
     result.update(status='submission_confirmed',submitted=True,confirmation=ack.inner_text(),confirmed_url=page.url);page.screenshot(path=str(run/'submission-result.png'),full_page=True)
   except Exception:
    if result['submission_request_sent'] and not requests:result['submission_request_sent']=False
    try:
     result['invalid_fields']=page.locator('input,select,textarea').evaluate_all("xs=>xs.filter(e=>!e.validity.valid).map(e=>({name:e.name,type:e.type,message:e.validationMessage}))")
     result['verification_frames']=page.locator('iframe').evaluate_all("xs=>xs.map(e=>({title:e.title,src:e.src.split('?')[0],visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)}))")
    except Exception:pass
    try:(run/'form-result.txt').write_text(page.locator('body').inner_text());page.screenshot(path=str(run/'form-result.png'),full_page=True,timeout=10000)
    except Exception:pass
    raise
   finally:
    result.update(employer_requests=requests,employer_responses=responses);context.close();browser.close()
 except Exception as e:result.update(status='submission_unconfirmed' if result['submission_request_sent'] else 'blocked_or_failed',error=str(e).split('Aria snapshot:')[0][:1500],safe_to_retry=not result['submission_request_sent'])
 result['finished_at']=datetime.now(ZoneInfo('Asia/Manila')).isoformat();(run/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return 0 if result.get('status') in ['submission_confirmed','dry_run_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
