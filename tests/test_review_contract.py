import copy
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
from aha3d.io import read, write
from aha3d.workflow.review_contract import run_reviewer, validate
import test_acceptance


class ReviewContract(test_acceptance.Acceptance):
    def test_viewed_boolean_and_path_only_review_do_not_pass(self):
        review=test_acceptance.visual_fixture(self.revision,self.images)
        review['image_delivery']={'viewed':True,'paths':self.images}
        with self.assertRaisesRegex(ValueError,'image delivery'):validate(review,self.revision,self.images)

    def test_actual_codex_image_arguments_and_rejected_verdict_are_preserved(self):
        request=dict(candidate_revision=self.revision,images=self.images,subjects=self.scope['subjects'])
        def process(cmd,**kw):
            self.assertEqual(cmd.count('--image'),len(self.images))
            supplied=json.loads(kw['input'].split('Request: ',1)[1])
            self.assertEqual([cmd[i+1] for i,x in enumerate(cmd) if x=='--image'],
                             list(supplied['images'].values()))
            self.assertIn('Request:',kw['input'])
            result=test_acceptance.visual_fixture(self.revision,self.images)
            result.update(verdict='rejected',findings=[dict(id='offset',severity='blocking',affected_ids=['bed','nightstand'],views=['plan'],observation='Nightstand offset persists',resolution_needed='Correct baseline and compare before/after')])
            result.pop('image_delivery');write(Path(cmd[cmd.index('--output-last-message')+1]),result)
            return subprocess.CompletedProcess(cmd,0)
        output=self.root/'review-output.json'
        with patch('subprocess.run',side_effect=process):result=run_reviewer(request,output)
        self.assertEqual(result['status'],'blocked');self.assertFalse(result['accepted'])
        self.assertEqual(read(output)['verdict'],'rejected')

    def test_reviewer_failure_and_missing_output_do_not_create_acceptance(self):
        request=dict(candidate_revision=self.revision,images=self.images)
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('codex',600)):
            with self.assertRaises(subprocess.TimeoutExpired):run_reviewer(request,self.root/'missing.json')
        self.assertFalse((self.root/'missing.json').exists())

    def test_unreviewed_regions_and_blocking_uncertainty_reject_superficial_acceptance(self):
        review=test_acceptance.visual_fixture(self.revision,self.images)
        for update in (dict(unreviewed_areas=['bed/nightstand relationship']),dict(uncertainties=[dict(observation='Bad mirror mask',impact='blocking')])):
            with self.assertRaisesRegex(ValueError,'Unresolved'):validate(dict(review,**update),self.revision,self.images)
