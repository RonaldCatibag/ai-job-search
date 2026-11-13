import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from tools.application_tracker import Store
from tools.application_controller import Controller
from tools.local_application_agents import LocalApplicationAgents

class LocalAgentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'repo';self.root.mkdir();self.store=Store(self.root,Path(self.tmp.name)/'data');self.controller=Controller(self.store);self.pool=LocalApplicationAgents(self.controller)
 def context(self):
  path=self.store.data/'context.json';path.write_text(json.dumps({'facts':{'tookitaki.0':{'label':'RCA','text':'Documented approximately 145 incidents.'}},'company':'Example','title':'SRE','approved_answers':{'work_country':'Philippines'},'posting':'SRE needed','base_message':'Based in Philippines; four hours/day.\n\nThank you for considering my application.','plan_path':str(self.root/'plan.json')}));return path
 def test_unknown_fact_id_is_quarantined(self):
  path=self.context();body=json.dumps({'message':{'content':json.dumps({'selected_fact_ids':['invented.99'],'summary':'Pretend achievement'})}}).encode()
  import io
  with patch('tools.local_application_agents.urllib.request.urlopen',return_value=io.BytesIO(body)),self.assertRaisesRegex(ValueError,'unknown fact ID'):self.pool.perform({'role':'tailorer','context_path':str(path),'dependency':None})
 def test_release_renders_trusted_fact_not_model_prose(self):
  path=self.context();context=json.loads(path.read_text());plan={'message':context['base_message'],'answers':{},'question_labels':{}};(self.root/'plan.json').write_text(json.dumps(plan));(path.parent/'tailorer-result.json').write_text(json.dumps({'selected_fact_ids':['tookitaki.0'],'summary':'Invented CEO claim'}))
  self.controller.snapshot=lambda:{'tasks':[{'id':'task','job_id':'job','state':'blocked','detail':{}}]};events=[];self.controller.event=lambda *args:events.append(args);self.controller.action=lambda *args:None
  self.pool.release({'context_path':str(path),'job_id':'job','revision':'one'})
  written=json.loads((self.root/'plan.json').read_text())['message'];self.assertIn('145 incidents',written);self.assertIn('Philippines',written);self.assertNotIn('CEO',written);self.assertTrue(events)
 def test_dependencies_prevent_tailoring_before_research(self):
  path=self.context()
  with self.store.connect() as db:
   db.execute("INSERT INTO local_agent_tasks(id,job_id,revision,role,state,created_at,updated_at,context_path) VALUES('a','job','r','researcher','queued','now','now',?)",(str(path),))
   db.execute("INSERT INTO local_agent_tasks(id,job_id,revision,role,state,dependency,created_at,updated_at,context_path) VALUES('b','job','r','tailorer','queued','a','now','now',?)",(str(path),))
  self.assertIsNone(self.pool.claim('tailorer'));self.assertEqual(self.pool.claim('researcher')['id'],'a');self.assertIsNone(self.pool.claim('researcher'))
 def test_long_instruction_is_rejected_before_file_access(self):
  with self.assertRaisesRegex(ValueError,'4,000'):self.pool.enqueue_prepared('x'*4001)

class AgentMemoryPhaseTests(unittest.TestCase):
 setUp=LocalAgentTests.setUp
 context=LocalAgentTests.context
 def test_pending_local_work_is_reported(self):
  self.assertFalse(self.pool.has_pending_work());path=self.context()
  with self.store.connect() as db:db.execute("INSERT INTO local_agent_tasks(id,job_id,revision,role,state,created_at,updated_at,context_path) VALUES('p','j','r','researcher','queued','now','now',?)",(str(path),))
  self.assertTrue(self.pool.has_pending_work())
 def test_failed_dependencies_are_blocked_instead_of_stalling_pipeline(self):
  path=self.context()
  with self.store.connect() as db:
   db.execute("INSERT INTO local_agent_tasks(id,job_id,revision,role,state,created_at,updated_at,context_path) VALUES('a','j','r','researcher','failed','now','now',?)",(str(path),))
   db.execute("INSERT INTO local_agent_tasks(id,job_id,revision,role,state,dependency,created_at,updated_at,context_path) VALUES('b','j','r','tailorer','queued','a','now','now',?)",(str(path),))
  self.assertIsNone(self.pool.claim('tailorer'));self.assertFalse(self.pool.has_pending_work())
