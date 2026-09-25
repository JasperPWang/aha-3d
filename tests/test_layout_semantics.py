import unittest
import tempfile
import json
from pathlib import Path
from tools.layout_inspection.semantic import validate_cache
import numpy as np
from tools.layout_inspection.prepare import classify, triangulate

class SemanticsTests(unittest.TestCase):
    def test_missing_frames_unknown_and_people_priority(self):
        valid=np.ones((2,2,2),bool)
        masks={k:np.zeros_like(valid) for k in ('person','glass','mirror')}
        masks['person'][0,0,0]=True
        masks['glass'][0,0,0]=True
        out=classify(masks,np.array([True,False]),valid)
        self.assertEqual(out[0,0,0],1)
        self.assertTrue((out[1]==5).all())
        self.assertEqual(out[0,1,1],0)

    def test_triangles_exclude_invalid_and_dynamic_static_leak(self):
        vertices=np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,0]],float)
        layer=np.array([[[1,0],[0,0]]],np.uint8)
        valid=np.ones((1,2,2),bool)
        faces, labels=triangulate(layer,valid,2,vertices)
        self.assertEqual(labels.tolist(),[1,0])
        valid[0,0,1]=False
        self.assertEqual(len(triangulate(layer,valid,2,vertices)[0]),0)
        self.assertEqual(len(triangulate(layer,np.ones_like(valid),.5,vertices)[0]),0)

    def test_cache_provenance_and_missing_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bundle=root/'bundle'; cache=root/'cache'
            bundle.mkdir(); cache.mkdir()
            np.savez(bundle/'inputs.npz', rgb=np.zeros((2,2,2,3),np.uint8))
            masks={k:np.zeros((1,2,2),bool) for k in ('person','glass','mirror')}
            masks['person'][0,1,1]=True
            np.savez(cache/'masks.npz',frame_indices=np.array([7]),**masks)
            meta={'status':'complete','bundle':str(bundle.resolve())}
            (cache/'manifest.json').write_text(json.dumps(meta))
            out,known,_=validate_cache(cache,bundle,np.array([3,7]),(2,2))
            self.assertEqual(known.tolist(),[False,True])
            self.assertTrue(out['person'][1,1,1])
            with self.assertRaises(ValueError): validate_cache(cache,bundle,np.array([3,7]),(3,3))
            meta['bundle']=str(root/'different-bundle')
            (cache/'manifest.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError): validate_cache(cache,bundle,np.array([3,7]),(2,2))

if __name__=='__main__': unittest.main()
