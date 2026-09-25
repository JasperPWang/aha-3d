"""Preview coverage and playback duration must not retime the final scene."""
from fractions import Fraction
from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aha3d.config import timing
from aha3d.workflow.preview_sampling import plan,validate_review

class PreviewSampling(unittest.TestCase):
    def test_fractional_source_reduces_work_preserves_duration_and_endpoints(self):
        source=timing(dict(fps='19001/317',frames=899,start=101));before=copy.deepcopy(source)
        p=plan(source)
        self.assertEqual(source,before)
        self.assertEqual(len(p['scene_frames']),75)
        self.assertEqual((p['scene_frames'][0],p['scene_frames'][-1]),(101,999))
        self.assertEqual(p['scene_frames'],sorted(set(p['scene_frames'])))
        self.assertLessEqual(max(b-a for a,b in zip(p['scene_frames'],p['scene_frames'][1:])),13)
        t=p['preview_timing']
        self.assertEqual(Fraction(t['frames'])/Fraction(t['fps']),Fraction(899)/Fraction('19001/317'))
        self.assertAlmostEqual(p['source_times_seconds'][-1],898/(19001/317))
        self.assertTrue(p['temporally_sampled'])

    def test_coarse_and_explicit_original_rate(self):
        t=timing(dict(fps=60,frames=900))
        self.assertEqual(plan(t,'1')['preview_timing']['frames'],15)
        for rate in ['source','120']:
            p=plan(t,rate)
            self.assertEqual(p['scene_frames'],list(range(1,901)))
            self.assertFalse(p['temporally_sampled'])
            self.assertEqual(p['preview_timing']['fps'],'60')

    def test_short_and_single_frame_clips_keep_available_endpoints(self):
        self.assertEqual(plan(timing(dict(fps=60,frames=1,start=9)))['scene_frames'],[9])
        self.assertEqual(plan(timing(dict(fps=60,frames=3,start=9)),'1')['scene_frames'],[9,11])

    def test_invalid_requested_rate(self):
        for rate in ['0','-1','nan','1/0','1001',None]:
            with self.subTest(rate=rate),self.assertRaises(ValueError):
                plan(timing(dict(fps=30,frames=30)),rate)

    def test_sampled_review_cannot_claim_original_frame_coverage(self):
        p=plan(timing(dict(fps=60,frames=900)))
        with self.assertRaises(ValueError):validate_review(dict(whole_clip_reviewed=True),p)
        review=dict(preview_reviewed=True,reviewed_scene_frames=p['scene_frames'],sampling_limitations='Five-FPS samples cannot rule out between-sample artifacts.')
        validate_review(review,p)
        for key,value in [('preview_reviewed',False),('reviewed_scene_frames',p['scene_frames'][:-1]),('sampling_limitations','')]:
            with self.subTest(key=key),self.assertRaises(ValueError):validate_review(dict(review,**{key:value}),p)

    def test_historical_full_rate_review_still_requires_whole_clip(self):
        validate_review(dict(whole_clip_reviewed=True),None)
        with self.assertRaises(ValueError):validate_review(dict(preview_reviewed=True),None)

if __name__=='__main__':unittest.main()
