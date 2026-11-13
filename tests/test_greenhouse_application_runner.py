import unittest
from tools.greenhouse_application_runner import validate_questions

class GreenhouseQuestionTests(unittest.TestCase):
 def fixture(self):
  return {'questions':[{'label':'First Name','required':True,'fields':[{'name':'first_name','type':'input_text'}]},{'label':'Resume/CV','required':True,'fields':[{'name':'resume','type':'input_file'},{'name':'resume_text','type':'textarea'}]},{'label':'Currently in Philippines?','required':True,'fields':[{'name':'question_1','type':'multi_value_single_select','values':[{'label':'Yes'},{'label':'No'}]}]}]}, {'answers':{'first_name':'Ronald','question_1':'Yes'},'question_labels':{'first_name':'First Name','question_1':'Currently in Philippines?'}}
 def test_all_required_answers_and_resume_alternative(self):
  data,plan=self.fixture();self.assertTrue(validate_questions(data,plan))
 def test_new_required_question_blocks_before_browser(self):
  data,plan=self.fixture();data['questions'].append({'label':'New legal declaration','required':True,'fields':[{'name':'new_question','type':'input_text'}]})
  with self.assertRaisesRegex(ValueError,'Unanswered required'):validate_questions(data,plan)
 def test_changed_wording_blocks_reused_question_id(self):
  data,plan=self.fixture();data['questions'][2]['label']='Legally authorized overseas?'
  with self.assertRaisesRegex(ValueError,'wording changed'):validate_questions(data,plan)
 def test_invalid_option_blocks(self):
  data,plan=self.fixture();plan['answers']['question_1']='Maybe'
  with self.assertRaisesRegex(ValueError,'Invalid dropdown'):validate_questions(data,plan)
