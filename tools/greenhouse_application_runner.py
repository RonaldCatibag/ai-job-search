#!/usr/bin/env python3
"""Submit one explicitly prepared Greenhouse plan using the public employer form."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
import sys
import urllib.request
import uuid
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]

def validate_questions(data,plan):
    answers=plan['answers']; labels=plan['question_labels']
    for question in data.get('questions',[]):
        fields=question.get('fields',[])
        provided=[f for f in fields if f.get('name') in answers or f.get('name')=='resume']
        if question.get('required') and not provided:raise ValueError('Unanswered required question: '+question.get('label',''))
        for f in provided:
            name=f['name']
            if name=='resume':continue
            if labels.get(name)!=question.get('label'):raise ValueError('Question wording changed: '+name)
            choices=f.get('values',[])
            if choices and answers[name] not in [v['label'] for v in choices]:raise ValueError('Invalid dropdown answer: '+name)
    return True

def choose(page,key,text,pattern=None):
    control=page.locator('[id="'+key+'"]')
    if not control.count():control=page.locator('[id="'+key.removesuffix('[]')+'"]')
    control.click();control.fill(text);control.press('ArrowDown')
    option=page.get_by_role('option').filter(has_text=re.compile(pattern or '^'+re.escape(text)+'$',re.I)).first
    option.wait_for(timeout=15000);selected=option.inner_text();option.click()
    return selected

def finish_email_verification(page,run,plan,acknowledgement):
    security=page.get_by_role('textbox',name='Security code',exact=True)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if acknowledgement.count() and acknowledgement.is_visible():return True
        if security.count() and security.is_visible():break
        page.wait_for_timeout(250)
    else:return True
    request_path=run/'verification-request.json';code_path=run/'verification-code.tmp'
    request_path.write_text(json.dumps({'company':plan['company'],'job_id':plan['job_id'],'email':plan['answers']['email'],'requested_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'state':'awaiting_code'},indent=2))
    page.screenshot(path=str(run/'verification-required.png'),full_page=True)
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline:
        if code_path.exists():
            code=code_path.read_text().strip();code_path.unlink()
            if not re.fullmatch(r'[A-Za-z0-9]{8}',code):raise ValueError('Invalid security-code format')
            group=page.get_by_role('group',name=re.compile('verification code was sent',re.I))
            controls=group.get_by_role('textbox')
            if controls.count()==8:
                for i,char in enumerate(code):controls.nth(i).fill(char)
            else:security.fill(code)
            code=None;request_path.unlink(missing_ok=True)
            page.get_by_role('button',name='Submit application',exact=True).click()
            return True
        page.wait_for_timeout(500)
    request_path.unlink(missing_ok=True)
    return False

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--submit',action='store_true');ap.add_argument('--dry-run',action='store_true');ap.add_argument('--confirm-job-id');ap.add_argument('--log-root',type=Path,default=Path.home()/'local-ai/logs/sessions');args=ap.parse_args(argv)
    run=args.log_root/('application-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
    result={'mode':'submit' if args.submit else 'dry-run','submitted':False,'run_directory':str(run),'started_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'submission_request_sent':False}
    try:
        plan=json.loads(args.plan.read_text());job_id=str(plan['job_id']);board=plan['board']
        if plan['adapter']!='greenhouse-selected' or not re.fullmatch('[a-z0-9-]+',board) or not job_id.isdigit():raise ValueError('Unsupported plan')
        url='https://job-boards.greenhouse.io/'+board+'/jobs/'+job_id
        if plan['url']!=url:raise ValueError('Job URL mismatch')
        if args.submit and args.confirm_job_id!=job_id:raise ValueError('Explicit job confirmation required')
        api='https://boards-api.greenhouse.io/v1/boards/'+board+'/jobs/'+job_id+'?questions=true'
        with urllib.request.urlopen(api,timeout=25) as response:data=json.load(response)
        (run/'questions.json').write_text(json.dumps(data,indent=2));validate_questions(data,plan)
        resume=(ROOT/plan['resume']).resolve()
        if not resume.is_relative_to(ROOT) or resume.suffix!='.pdf' or hashlib.sha256(resume.read_bytes()).hexdigest()!=plan['resume_sha256']:raise ValueError('Reviewed resume checksum mismatch')
        from pypdf import PdfReader
        resume_text='\n\n'.join(page.extract_text() or '' for page in PdfReader(resume).pages)
        if 'ronald' not in resume_text.casefold() or 'tookitaki' not in resume_text.casefold():raise ValueError('Reviewed resume text could not be extracted')
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);context=browser.new_context(service_workers='block',offline=not args.submit);page=context.new_page();page.set_default_timeout(15000)
            responses=[]
            if not args.submit:context.route('**/*',lambda route:route.abort())
            else:
                def capture(response):
                    if result['submission_request_sent'] and response.request.method=='POST' and response.url.split('/')[2] in ('boards.greenhouse.io','boards-api.greenhouse.io','job-boards.greenhouse.io','job-boards-api.greenhouse.io','api.greenhouse.io'):responses.append({'url':response.url.split('?')[0],'status':response.status})
                page.on('response',capture)
            try:
                if not args.submit:
                    import html
                    controls=''.join('<label>'+html.escape(k)+'</label><input id="'+html.escape(k)+'">' for k in plan['answers'])
                    page.set_content('<h1>OFFLINE application dry run</h1>'+controls+'<textarea id="cover_letter_text"></textarea><input type="file" id="resume"><button disabled>Submit disabled</button>')
                    for key,value in plan['answers'].items():page.locator('[id="'+key+'"]').fill(value)
                    page.locator('#cover_letter_text').fill(plan['message']);page.locator('#resume').set_input_files(str(resume))
                    page.screenshot(path=str(run/'filled-form.png'),full_page=True)
                    result.update(status='dry_run_passed',outbound_browser_requests=0,field_values_verified=True)
                else:
                    page.goto(url,wait_until='networkidle',timeout=45000)
                    mapped=set(plan['answers'])|{k.removesuffix('[]') for k in plan['answers']}|{'country','candidate-location','cover_letter_text','resume','cover_letter'}
                    for item in page.locator('[aria-required=true]').evaluate_all('(xs)=>xs.map(x=>({id:x.id,role:x.getAttribute("role")}))'):
                        if item['id'] and item['id'] not in mapped:raise ValueError('Unmapped required live field: '+item['id'])
                    for key,value in plan['answers'].items():
                        control=page.locator('[id="'+key+'"]')
                        if not control.count():control=page.locator('[id="'+key.removesuffix('[]')+'"]')
                        if key.endswith('[]') and (not control.count() or control.evaluate('(el)=>el.tagName')=='FIELDSET'):
                            fields=[f for q in data['questions'] for f in q['fields'] if f['name']==key]
                            choice=next(v for v in fields[0].get('values',[]) if v['label']==value)
                            control=page.locator('[id="'+key+'_'+str(choice['value'])+'"]')
                            control.check()
                        elif control.get_attribute('role')=='combobox':choose(page,key,value)
                        else:control.fill(value)
                    choose(page,'country','Philippines',r'^Philippines \+63$')
                    city=choose(page,'candidate-location','Caloocan',r'Caloocan.*Philippines') if page.locator('#candidate-location').count() else 'Not requested by this form'
                    # The optional cover letter carries the actual second-job terms.
                    manual=page.get_by_role('button',name='Enter manually',exact=True)
                    if not plan.get('message_in_answers'):
                        if manual.count()>1:manual.nth(1).click()
                        if page.locator('#cover_letter_text').count():
                            page.locator('#cover_letter_text').fill(plan['message'])
                        else:
                            # Forms without a cover-letter field receive the reviewed note with the CV.
                            resume_text += '\n\nAPPLICATION NOTE\n' + plan['message']
                    resume_manual=page.get_by_role('button',name='Enter manually',exact=True).first
                    resume_manual.click();page.locator('#resume_text').fill(resume_text)
                    expect(page.locator('#resume_text')).to_have_value(resume_text)
                    page.screenshot(path=str(run/'filled-form.png'),full_page=True)
                    result['submission_request_sent']=True
                    page.get_by_role('button',name='Submit application',exact=True).click()
                    acknowledgement=page.get_by_text(re.compile(r'thank you.*(?:applying|submitting)|application (?:has been )?(?:submitted|received)',re.I)).first
                    try:
                        if not finish_email_verification(page,run,plan,acknowledgement):raise ValueError('Email verification was not completed within thirty minutes')
                        expect(acknowledgement).to_be_visible(timeout=30000);expect(page.locator('#first_name')).not_to_be_visible()
                        if not any(200<=r['status']<300 for r in responses):raise ValueError('No successful employer POST response')
                        result.update(status='submission_confirmed',submitted=True,confirmation=acknowledgement.inner_text(),confirmed_url=page.url,city=city)
                    except Exception as error:result.update(status='email_verification_required' if page.get_by_role('textbox',name='Security code',exact=True).count() else 'submission_unconfirmed',error=str(error).split('Aria snapshot:')[0][:1200])
                    result['employer_responses']=responses
                    if result.get('submitted') or not page.get_by_role('textbox',name='Security code',exact=True).count():page.screenshot(path=str(run/'submission-result.png'),full_page=True)
            finally:context.close();browser.close()
    except Exception as error:result.update(status='blocked_or_failed',error=str(error),safe_to_retry=not result['submission_request_sent'])
    result['finished_at']=datetime.now(ZoneInfo('Asia/Manila')).isoformat()
    (run/'result.json').write_text(json.dumps(result,indent=2)+'\n');(run/'conversation.md').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return 0 if result['status'] in ('dry_run_passed','submission_confirmed') else 1
if __name__=='__main__':raise SystemExit(main())
