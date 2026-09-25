import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from tools.gvhmr.scene_ground import load_prior, ground_cameras, yaw_rotation_6d


class SceneGroundTests(unittest.TestCase):
    def test_tilted_offset_floor_and_camera_projection_roundtrip(self):
        normal = Rotation.from_euler('x', 13, degrees=True).apply([0., 0., 1.])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'prior.json'
            value = dict(source_video_sha256='a'*64, coordinate_frame='pi3x-aligned-world',
                         scale=1, accepted=True, evidence='reviewed patches',
                         plane=[*normal, -1.2], upright=normal.tolist())
            path.write_text(json.dumps(value))
            prior = load_prior(path, 'a'*64)
            transform = np.asarray(prior['world_to_ground'])
            np.testing.assert_allclose(transform[:3, :3]@normal, [0, 1, 0], atol=1e-8)
            np.testing.assert_allclose((transform@np.r_[1.2*normal, 1])[1], 0, atol=1e-8)
            camera = np.eye(4); camera[:3, 3] = [1, 2, 3]
            point = np.array([2., 4., 7., 1.])
            np.testing.assert_allclose(np.linalg.inv(ground_cameras(camera, prior))@transform@point,
                                       np.linalg.inv(camera)@point, atol=1e-8)
            np.testing.assert_allclose(np.asarray(prior['ground_to_world'])@transform, np.eye(4), atol=1e-8)
            with self.assertRaisesRegex(ValueError, 'different source'):
                load_prior(path, 'b'*64)
            value['accepted'] = False; path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'accepted'):
                load_prior(path, 'a'*64)

    def test_v2_yaw_parameter_cannot_tilt_upright(self):
        import torch
        x = torch.tensor([[.8, .3, .2, .1, .9, .4]], requires_grad=True)
        rotation = yaw_rotation_6d(x)
        np.testing.assert_allclose(rotation.detach().numpy()[0, :, 1], [0, 1, 0])
        rotation[0, 0, 2].backward()
        self.assertTrue(torch.isfinite(x.grad).all())
        self.assertGreater(float(x.grad.abs().sum()), 0)


if __name__ == '__main__':
    unittest.main()
