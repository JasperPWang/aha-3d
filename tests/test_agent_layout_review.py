import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from tools.layout_inspection.agent_review import analyze, create, review_image


def fixture():
    objects=[dict(id='stool1',semantic_class='furniture/stool',grouping='instance',color=[255,0,0]),
             dict(id='wall',semantic_class='unknown',grouping='ungrouped component',color=[0,255,0])]
    views={'top':dict(size=[20,20],objects={i:dict(paths=[[[2,2],[15,2],[15,15],[2,15]]],mask_pixels=169) for i in ('stool1','wall')})}
    return dict(objects=objects,views=views,source_scene_sha256='scene')

class AgentReviewTests(unittest.TestCase):
    def test_counts_and_missing_source_fit_never_pass(self):
        report=analyze(fixture(),{'expected_counts':[dict(id='stools',semantic_class='furniture/stool',count=4,evidence='reviewed source')]})
        findings={f['id']:f for f in report['findings']}
        self.assertEqual(findings['count:stools']['modeled_count'],1)
        self.assertIn('source_fit_not_assessed',findings)
        self.assertEqual(report['source_fidelity'],'not_accepted')

    def test_stale_manual_observation_requires_recheck(self):
        report=analyze(fixture(),{'review_items':[dict(id='size',object_ids=['stool1'],evidence='user crop',source_scene_sha256='old',message='too large')]})
        self.assertEqual(next(f for f in report['findings'] if f['id']=='review:size')['state'],'requires_recheck')

    def test_stale_measured_fit_rejected(self):
        with self.assertRaises(ValueError): analyze(fixture(),source_fit={'source_scene_sha256':'other','rows':[]})
        report=analyze(fixture(),source_fit={'source_scene_sha256':'scene','rows':[]})
        self.assertIn('source_fit_coverage',[f['id'] for f in report['findings']])

    def test_wall_context_retained_without_semantic_relabel(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bg.png'; Image.new('RGB',(20,20),'black').save(p)
            data=fixture();image,present=review_image(p,data['views']['top'],data['objects'],set())
            self.assertIn('wall',present)
            self.assertNotEqual(image.getpixel((2,2)),(0,0,0))
            self.assertEqual(data['objects'][1]['semantic_class'],'unknown')

    def test_repeat_packet_reports_unchanged_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=fixture();data['source_inspection']=str(root)
            Image.new('RGB',(20,20),'black').save(root/'top_reference.png')
            (root/'objects.json').write_text(json.dumps(data))
            (root/'inventory.json').write_text(json.dumps({'expected_counts':[dict(id='stools',semantic_class='furniture/stool',count=4,evidence='source')]}))
            create(root/'objects.json',root/'first',inventory=root/'inventory.json')
            first=json.loads((root/'first/agent_review.json').read_text())
            overview=next(row for row in first['images'] if row['kind']=='overview')
            self.assertEqual(overview['highlighted_ids'],['stool1','wall'])
            with Image.open(root/'first'/overview['path']) as image:
                self.assertGreater(image.height,20)  # Embedded ID legend travels with actual reviewer image.
            report=create(root/'objects.json',root/'second',inventory=root/'inventory.json',previous=root/'first/agent_review.json')
            self.assertTrue(report['delta']['inputs_unchanged'])
            self.assertEqual(report['delta']['changed'],[])

if __name__=='__main__': unittest.main()
