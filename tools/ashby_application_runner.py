#!/usr/bin/env python3
"""Run a reviewed Ashby application plan; never infer answers from a live form."""
import argparse,hashlib,html,json,re,sys,time,uuid,os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]

def validate_plan(plan):
    u=urlsplit(plan['url']);parts=u.path.strip('/').split('/')
    if plan.get('adapter')!='ashby-selected' or u.scheme!='https' or u.netloc!='jobs.ashbyhq.com' or len(parts)!=2 or parts[1]!=plan['job_id'] or u.query or u.fragment:
        raise ValueError('Unapproved application URL')
    if not re.fullmatch(r'[a-zA-Z0-9._-]+',parts[0]) or not re.fullmatch(r'[a-f0-9-]{36}',parts[1]):raise ValueError('Invalid employer/job identity')
    resume=(ROOT/plan['resume']).resolve()
    if not resume.is_relative_to(ROOT) or resume.suffix!='.pdf' or hashlib.sha256(resume.read_bytes()).hexdigest()!=plan['resume_sha256']:raise ValueError('Reviewed resume checksum mismatch')
    if not plan.get('answers') or not plan.get('question_labels'):raise ValueError('Missing approved answers')
    for key in set(plan['answers'])|set(plan.get('files',{})):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',key) or key not in plan['question_labels']:raise ValueError('Unreviewed field: '+key)
    for key,item in plan.get('files',{}).items():
        file=(ROOT/item['path']).resolve()
        if not file.is_relative_to(ROOT) or file.suffix!='.pdf' or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Reviewed extra-file checksum mismatch')
    return resume

def validate_schema(schema,plan):
    observed={x['key']:x for x in schema}
    for key in set(plan['answers'])|set(plan.get('files',{})):
        if key not in observed or observed[key]['label'].strip()!=plan['question_labels'][key].strip():raise ValueError('Question wording changed or missing: '+key)
    missing=[x['label'] for x in schema if x['required'] and x['key']!='_systemfield_resume' and x['key'] not in plan['answers'] and x['key'] not in plan.get('files',{})]
    if missing:raise ValueError('Unanswered required questions: '+', '.join(missing))
    return True

def read_schema(page):
    return page.locator('[data-field-path]').evaluate_all("""xs=>xs.map(e=>({key:e.getAttribute('data-field-path'),label:e.querySelector('.ashby-application-form-question-title')?.innerText?.trim()||'',required:!!e.querySelector('input[required],textarea[required],select[required]')||!!Array.from(e.querySelectorAll('label')).find(l=>l.className.includes('_required_'))})).filter(x=>x.label)""")

def fill_answer(page,key,value,kind):
    entry=page.locator('[data-field-path="'+key+'"]')
    if kind=='yesno':
        if value not in ['Yes','No']:raise ValueError('Invalid yes/no answer')
        entry.locator('button[data-option="'+value.lower()+'"]').click()
    elif kind=='radio':entry.get_by_role('radio',name=value,exact=True).check()
    elif kind=='dropdown':
        entry.get_by_role('combobox').fill(value)
        option=page.get_by_role('option',name=value,exact=True);option.wait_for(timeout=15000);option.click()
    elif kind=='location':
        control=entry.get_by_role('combobox');control.fill(value)
        option=page.get_by_role('option').filter(has_text=re.compile(r'Caloocan.*Philippines',re.I)).first
        option.wait_for(timeout=15000);option.click()
    else:
        control=entry.locator('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]),textarea').first
        control.fill(value)
        if control.input_value()!=value:raise ValueError('Field verification failed: '+key)

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--submit',action='store_true');ap.add_argument('--dry-run',action='store_true');ap.add_argument('--confirm-job-id');ap.add_argument('--log-root',type=Path,required=True);a=ap.parse_args(argv)
    run=a.log_root/('application-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
    result={'mode':'submit' if a.submit else 'dry-run','submitted':False,'submission_request_sent':False,'run_directory':str(run)}
    try:
        plan=json.loads(a.plan.read_text());resume=validate_plan(plan)
        if a.submit and a.confirm_job_id!=plan['job_id']:raise ValueError('Explicit job confirmation required')
        if a.submit and plan.get('missing_fields'):raise ValueError('Missing confirmed facts: '+', '.join(plan['missing_fields']))
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            interactive=a.submit and plan.get('interactive_verification') is True
            env=os.environ.copy()
            if interactive:env.update(DISPLAY=':0',WAYLAND_DISPLAY='wayland-0',XDG_RUNTIME_DIR='/run/user/1000')
            browser=pw.chromium.launch(headless=not interactive,args=['--disable-gpu'],env=env);context=browser.new_context(offline=not a.submit,service_workers='block');page=context.new_page();page.set_default_timeout(15000)
            responses=[];requests=[];browser_errors=[]
            try:
                if not a.submit:
                    context.route('**/*',lambda r:r.abort())
                    page.set_content(''.join('<label>'+html.escape(plan['question_labels'][k])+'</label><textarea id="'+k+'"></textarea>' for k in plan['answers'])+'<input type="file" id="resume"><button disabled>Submit disabled</button>')
                    for key,value in plan['answers'].items():page.locator('[id="'+key+'"]').fill(value)
                    page.locator('#resume').set_input_files(str(resume));page.screenshot(path=str(run/'filled-form.png'),full_page=True)
                    result.update(status='dry_run_passed',outbound_browser_requests=0,field_values_verified=True,pending_required_answers=plan.get('missing_fields',[]))
                else:
                    def capture(r):
                        host=urlsplit(r.url).hostname or ''
                        if result['submission_request_sent'] and r.request.method=='POST' and (host=='ashbyhq.com' or host.endswith('.ashbyhq.com')):responses.append({'url':r.url.split('?')[0],'status':r.status})
                    page.on('response',capture)
                    page.on('pageerror',lambda error:browser_errors.append(str(error)[:300]))
                    def note_request(req):
                        host=urlsplit(req.url).hostname or ''
                        if result['submission_request_sent'] and req.method=='POST' and (host=='ashbyhq.com' or host.endswith('.ashbyhq.com')):
                            try:operation=(req.post_data_json or {}).get('operationName')
                            except Exception:operation=None
                            requests.append({'host':host,'path':urlsplit(req.url).path,'operation':operation})
                    page.on('request',note_request)
                    page.goto(plan['url'],wait_until='networkidle',timeout=45000)
                    button=page.get_by_role('button',name=re.compile('^Apply|Apply for',re.I)).first
                    if button.count():button.click()
                    elif page.get_by_role('link',name='Application',exact=True).count():page.get_by_role('link',name='Application',exact=True).click()
                    page.locator('[data-field-path="_systemfield_resume"]').wait_for()
                    schema=read_schema(page);(run/'observed-schema.json').write_text(json.dumps(schema,indent=2));validate_schema(schema,plan)
                    page.locator('[data-field-path="_systemfield_resume"] input[type=file]').set_input_files(str(resume))
                    for key,item in plan.get('files',{}).items():
                        page.locator('[data-field-path="'+key+'"] input[type=file]').set_input_files(str(ROOT/item['path']))
                    page.wait_for_timeout(1500)
                    for key,value in plan['answers'].items():fill_answer(page,key,value,plan.get('kinds',{}).get(key,'text'))
                    page.wait_for_load_state('networkidle',timeout=20000)
                    page.wait_for_timeout(1000)
                    page.screenshot(path=str(run/'filled-form.png'),full_page=True)
                    result['submission_request_sent']=True
                    page.get_by_role('button',name='Submit Application',exact=True).click()
                    confirmation=page.get_by_text(re.compile(r'(application (has been |was )?(received|submitted)|thank you for applying|thanks for applying)',re.I)).first
                    if interactive:
                        request_file=run/'human-verification-request.json'
                        deadline=time.monotonic()+1800
                        announced=False
                        while time.monotonic()<deadline:
                            if confirmation.count() and confirmation.is_visible() and not page.locator('[data-field-path="_systemfield_resume"]').is_visible():break
                            if not announced:
                                challenge=page.locator('iframe[src*="/bframe"]')
                                captcha=any(frame.is_visible() for frame in challenge.all())
                                request_file.write_text(json.dumps({'company':plan['company'],'title':plan['title'],'requested_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'kind':'captcha' if captcha else 'form_review','message':'Use the visible Chromium window. Review the filled form, complete any provider verification yourself, and click Submit Application if needed.','url':plan['url']},indent=2))
                                announced=True
                            page.wait_for_timeout(500)
                        else:raise ValueError('Visible-browser verification was not completed within thirty minutes')
                        request_file.unlink(missing_ok=True)
                    else:expect(confirmation).to_be_visible(timeout=45000)
                    expect(page.locator('[data-field-path="_systemfield_resume"]')).not_to_be_visible()
                    if not any(200<=r['status']<300 for r in responses):raise ValueError('No successful employer POST response')
                    result.update(status='submission_confirmed',submitted=True,confirmation=confirmation.inner_text(),confirmed_url=page.url,employer_responses=responses)
                    page.screenshot(path=str(run/'submission-result.png'),full_page=True)
            except Exception:
                result['employer_responses']=responses;result['employer_requests']=requests;result['browser_errors']=browser_errors
                try:
                    result['verification_frames']=page.locator('iframe').evaluate_all("xs=>xs.map(e=>({title:e.title,src:e.src.split('?')[0],width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,hidden:e.getAttribute('aria-hidden')}))")
                    result['recaptcha_loaded']=page.evaluate("typeof window.grecaptcha!=='undefined'")
                    result['recaptcha_response_present']=page.locator('textarea[name="g-recaptcha-response"]').evaluate_all("xs=>xs.some(e=>e.value.length>0)")
                except Exception:pass
                if result['submission_request_sent'] and not requests:result['submission_request_sent']=False
                try:
                    (run/'form-result.txt').write_text(page.locator('body').inner_text())
                    page.screenshot(path=str(run/'form-result.png'),full_page=True,timeout=10000)
                except Exception:pass
                raise
            finally:context.close();browser.close()
    except Exception as e:result.update(status='blocked_or_failed' if not result['submission_request_sent'] else 'submission_unconfirmed',error=str(e)[:1500],safe_to_retry=not result['submission_request_sent'])
    result['finished_at']=datetime.now(ZoneInfo('Asia/Manila')).isoformat();(run/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return 0 if result.get('status') in ['dry_run_passed','submission_confirmed'] else 1
if __name__=='__main__':raise SystemExit(main())
