import unittest
import numpy as np
from tools.layout_inspection.source_fit import metrics, warp, envelope, alignment_probe, triage

class SourceFitTests(unittest.TestCase):
    def setUp(self):
        self.mask = np.zeros((100,120),bool)
        self.mask[25:65,30:90] = True

    def test_empty_is_unassessed_not_perfect(self):
        blank=np.zeros_like(self.mask)
        self.assertIsNone(metrics(blank,blank)['mask_iou'])
        self.assertEqual(metrics(self.mask,blank)['mask_iou'],0)
        with self.assertRaises(ValueError): metrics(self.mask,blank[:2])

    def test_box_cannot_detect_internal_shape_error(self):
        changed=self.mask.copy(); changed[35:55,40:80]=False
        result=metrics(self.mask,changed)
        self.assertEqual(result['bbox_iou'],1)
        self.assertLess(result['mask_iou'],.7)
        self.assertGreater(result['boundary_p95_px'],0)
        np.testing.assert_array_equal(envelope(changed),self.mask)

    def test_translation_and_scale_are_model_minus_source(self):
        changed=warp(self.mask,[10,-5,1.2,1])
        result=metrics(self.mask,changed)
        self.assertAlmostEqual(result['center_delta_px'][0],10,delta=1)
        self.assertAlmostEqual(result['center_delta_px'][1],-5,delta=1)
        self.assertAlmostEqual(result['width_ratio'],1.2,delta=.02)

    def test_diagnostic_search_recovers_known_offset(self):
        changed=warp(self.mask,[12,-8,1.15,.85])
        result,fitted=alignment_probe(self.mask,changed)
        self.assertGreater(result['mask_iou'],.9)
        self.assertGreater(result['mask_iou'],metrics(self.mask,changed)['mask_iou'])
        self.assertLess(result['parameters']['tx_px'],0)
        np.testing.assert_array_equal(changed,warp(self.mask,[12,-8,1.15,.85]))

    def test_prompt_disagreement_is_not_confirmed_layout_failure(self):
        row={'support_envelope':{'boundary_p95_px':6},'alternative_prompt':{'support_envelope':{'boundary_p95_px':44}}}
        self.assertEqual(triage(row)[0],'segmentation_review_required')
        row['support_envelope']['boundary_p95_px']=24
        self.assertEqual(triage(row)[0],'needs_attention')

if __name__=='__main__': unittest.main()
