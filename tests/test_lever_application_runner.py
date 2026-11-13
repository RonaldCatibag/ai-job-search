import unittest
from tools.lever_application_runner import application_url, exact_application_post, normalize, receipt_confirmed, validate_plan, validate_schema


class LeverPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'answers': {'name': 'Ronald'}, 'question_labels': {'name': 'Full name'}}
        self.schema = [{'key': 'name', 'type': 'text', 'required': True, 'label': 'Full name', 'radio_values': []}]

    def test_new_required_question_blocks_submission(self):
        with self.assertRaisesRegex(ValueError, 'Unanswered required'):
            validate_schema(self.schema + [{'key': 'declaration', 'type': 'text', 'required': True, 'label': 'New declaration'}], self.plan)

    def test_changed_question_blocks_submission(self):
        self.schema[0]['label'] = 'Agree to relocation'
        with self.assertRaisesRegex(ValueError, 'wording changed'):
            validate_schema(self.schema, self.plan)

    def test_choice_must_be_offered(self):
        self.schema[0].update(type='radio', radio_values=['Other'])
        with self.assertRaisesRegex(ValueError, 'Invalid radio'):
            validate_schema(self.schema, self.plan)

    def test_destination_lookalike_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unapproved'):
            validate_plan({'adapter': 'lever-selected', 'url': 'https://jobs.lever.co.example.org/company/job', 'job_id': 'job'})

    def test_matching_reviewed_question_is_valid(self):
        self.assertTrue(validate_schema(self.schema, self.plan))

    def test_required_marker_is_only_formatting(self):
        self.assertEqual(normalize('Full name\n' + chr(10033)), 'Full name')

    def test_apply_url_is_not_appended_twice(self):
        identifier = 'f0f18ff1-bf64-4a24-8521-1030cd05adcd'
        url = 'https://jobs.lever.co/brightedge/' + identifier + '/apply'
        self.assertEqual(application_url({'url': url, 'job_id': identifier}), url)

    def test_wrong_domain_does_not_receive_candidate_data(self):
        with self.assertRaisesRegex(ValueError, 'jobs.lever.co'):
            application_url({'url': 'https://jobs.lever.com/brightedge/job', 'job_id': 'job'})

    def test_analytics_and_resume_parsing_are_not_application_posts(self):
        destination = 'https://jobs.lever.co/brightedge/job/apply'
        for url in ['https://jobs.lever.co/parseResume', 'https://jobs.lever.co/cdn-cgi/challenge-platform/test', 'https://jobs.lever.co/another/job/apply']:
            self.assertFalse(exact_application_post('POST', url, destination))
        self.assertTrue(exact_application_post('POST', destination, destination))
        self.assertFalse(exact_application_post('GET', destination, destination))

    def test_verification_rejection_cannot_count_as_success(self):
        self.assertFalse(receipt_confirmed(True, False, [{'status': 400}]))
        self.assertFalse(receipt_confirmed(True, False, [{'status': 302}]))
        self.assertFalse(receipt_confirmed(True, False, []))

    def test_success_requires_acknowledgment_and_closed_form(self):
        self.assertFalse(receipt_confirmed(False, False, [{'status': 200}]))
        self.assertFalse(receipt_confirmed(True, True, [{'status': 200}]))
        self.assertTrue(receipt_confirmed(True, False, [{'status': 200}]))
