"""Constrained transport must retain attached images and rejected judgments."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch
import test_acceptance
from aha3d.io import read,write
from aha3d.workflow.review_contract import run_reviewer


class ConstrainedImageReview(test_acceptance.Acceptance):
    def test_schema_transport_keeps_images_and_does_not_turn_rejection_into_acceptance(self):
        request=dict(candidate_revision=self.revision,images=self.images,subjects=self.scope['subjects'])
        judgment=test_acceptance.visual_fixture(self.revision,self.images)
        judgment.pop('image_delivery')
        judgment.update(verdict='rejected',findings=[dict(id='offset',severity='blocking',affected_ids=['bed'],views=['plan'],observation='Visible offset',resolution_needed='Repair and inspect')])
        binary=self.root/'codex'
        binary.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:]
schema=json.loads(Path(a[a.index('--output-schema')+1]).read_text())
assert schema['properties']['observations']['items']['properties']['aspect']['enum']==['inventory','placement','dimensions','orientation','relationships','uncertainty']
assert schema['properties']['observations']['items']['properties']['subjects']['minItems']==1
request=json.loads(sys.stdin.read().split('Request: ',1)[1])
assert [a[i+1] for i,v in enumerate(a) if v=='--image']==list(request['images'].values())
Path(a[a.index('--output-last-message')+1]).write_text('''+repr(json.dumps(judgment))+''')
''')
        binary.chmod(0o755)
        output=self.root/'constrained.json'
        tool=Path(__file__).resolve().parents[1]/'tools/review_images.py'
        with patch.dict(os.environ,PATH=str(self.root)+os.pathsep+os.environ['PATH']):
            result=run_reviewer(request,output,executable=str(tool))
        self.assertEqual(result['status'],'blocked')
        self.assertFalse(result['accepted'])
        self.assertEqual(read(output)['findings'],judgment['findings'])

    def test_cli_returns_nonzero_on_rejected_judgment(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'tools/review_images.py'
        spec=importlib.util.spec_from_file_location('review_cli',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        request=self.root/'request.json';write(request,dict(images=self.images))
        with patch('aha3d.workflow.review_contract.run_reviewer',return_value=dict(verdict='rejected')) as invoke:
            self.assertEqual(module.main([str(request),'--out',str(self.root/'new.json')]),2)
        self.assertEqual(invoke.call_args.kwargs['executable'],str(path))
