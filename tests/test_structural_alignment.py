import json
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import numpy as np

from tools.layout_inspection.structural_alignment import build, solve, reviewed_frames
from tools.layout_inspection.semantic import validate_cache


def room():
    """Three views of a floor and two walls, rotated and translated from room axes."""
    a, b = np.meshgrid(np.linspace(-2, 2, 24), np.linspace(-1.5, 1.5, 24))
    floor = np.stack([a, b, np.zeros_like(a)], -1).reshape(-1, 3)
    a, b = np.meshgrid(np.linspace(-2, 2, 24), np.linspace(.2, 2.8, 24))
    wall = np.stack([a, np.full_like(a, -1.5), b], -1).reshape(-1, 3)
    yaw, tilt = .61, .23
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0,0,1]])
    rx = np.array([[1,0,0], [0,np.cos(tilt),-np.sin(tilt)], [0,np.sin(tilt),np.cos(tilt)]])
    rotation = rx @ rz
    shift = np.array([3, -4, 2])
    cameras = np.repeat(np.eye(4)[None], 3, axis=0)
    camera_rotation = np.array([[1,0,0], [0,0,1], [0,-1,0]])
    for i in range(3):
        cameras[i,:3,:3] = rotation @ camera_rotation
        cameras[i,:3,3] = np.array([.2*i, 0, 1.6]) @ rotation.T + shift
    rng = np.random.default_rng(17)
    floor = np.tile(floor, (3,1)) @ rotation.T + shift + rng.normal(0,.002,(1728,3))
    wall = np.tile(wall, (3,1)) @ rotation.T + shift + rng.normal(0,.002,(1728,3))
    frames = np.repeat([0,5,10], 576)
    return floor, wall, frames, cameras, rotation


class StructuralAlignment(unittest.TestCase):
    def test_floor_wall_axes_and_projection_invariance(self):
        floor, wall, frames, cameras, rotation = room()
        transform, report, fitted, walls = solve(floor, frames, wall, frames, cameras)
        self.assertIsNotNone(fitted)
        self.assertEqual(len(walls), 1)
        aligned_floor = floor @ transform[:3,:3].T + transform[:3,3]
        aligned_wall = wall @ transform[:3,:3].T + transform[:3,3]
        self.assertLess(np.std(aligned_floor[:,2]), .004)
        self.assertLess(abs(np.median(aligned_floor[:,2])), .004)
        self.assertLess(np.std(aligned_wall[:,1]), .004)
        self.assertTrue(np.allclose(transform[:3,:3] @ transform[:3,:3].T, np.eye(3)))
        self.assertAlmostEqual(np.linalg.det(transform[:3,:3]), 1)
        p = np.column_stack([floor[:10], np.ones(10)])
        before = (np.linalg.inv(cameras[0]) @ p.T).T
        after = (np.linalg.inv(transform @ cameras[0]) @ transform @ p.T).T
        np.testing.assert_allclose(before, after, atol=1e-10)
        np.testing.assert_allclose(np.linalg.norm(floor[0]-floor[500]),
                                   np.linalg.norm(aligned_floor[0]-aligned_floor[500]))
        self.assertTrue(report['visual_review_required'])

    def test_outliers_do_not_define_floor(self):
        floor, wall, frames, cameras, _ = room()
        floor[:200] += np.array([0,0,1.2])
        _, report, fitted, _ = solve(floor, frames, wall, frames, cameras)
        self.assertIsNotNone(fitted)
        self.assertLess(report['floor']['residual_p90_predicted_m'], .01)
        self.assertLess(report['floor']['inlier_fraction'], .95)

    def test_single_view_or_narrow_support_cannot_establish_floor(self):
        floor, wall, frames, cameras, _ = room()
        for points, ids in [(floor, np.zeros_like(frames)),
                            (np.tile(np.column_stack([np.linspace(0,3,576),np.zeros(576),np.zeros(576)]),(3,1)), frames)]:
            _, report, fitted, walls = solve(points, ids, wall, frames, cameras)
            self.assertIsNone(fitted)
            self.assertEqual(report['status'], 'camera-up only; no floor accepted')
            self.assertFalse(walls)

    def test_missing_walls_preserves_floor_and_camera_yaw(self):
        floor, _, frames, cameras, _ = room()
        _, report, fitted, walls = solve(floor, frames, np.empty((0,3)), np.empty(0,int), cameras)
        self.assertIsNotNone(fitted)
        self.assertEqual(report['yaw_status'], 'camera-right fallback')
        self.assertTrue(report['blockers'])

    def test_ceiling_is_rejected_even_when_flat(self):
        floor, wall, frames, cameras, rotation = room()
        floor += 3 * rotation[:,2]
        _, report, fitted, _ = solve(floor, frames, wall, frames, cameras)
        self.assertIsNone(fitted)
        self.assertIn('above', report['blockers'][0])

    def test_nonorthogonal_walls_are_reported_without_snapping(self):
        floor, wall, frames, cameras, rotation = room()
        # A second wall rotated 60 degrees about the true vertical.
        center = np.array([3,-4,2])
        theta = np.deg2rad(60)
        turn = np.array([[np.cos(theta),-np.sin(theta),0],[np.sin(theta),np.cos(theta),0],[0,0,1]])
        second = (wall-center) @ rotation @ turn.T @ rotation.T + center
        _, report, _, walls = solve(floor, frames, np.concatenate([wall,second]), np.tile(frames,2), cameras)
        self.assertGreaterEqual(len(walls), 2)
        angles = [w['angle_to_x_degrees'] for w in report['walls']]
        self.assertTrue(any(abs(a-60) < 1 for a in angles), angles)

    def test_source_bound_review_selection(self):
        meta = dict(bundle='/source/bundle')
        review = dict(**meta, semantic_cache='/source/masks', reviewer='reviewer', floor=[dict(source_frame=5, observation='Exposed floor patch')], wall=[])
        selected, status = reviewed_frames(review, meta, np.array([0,5,10]), '/source/masks')
        self.assertEqual(selected, {'floor': {5}, 'wall': set()})
        review['semantic_cache'] = '/other/masks'
        with self.assertRaisesRegex(ValueError, 'differs'):
            reviewed_frames(review, meta, np.array([0,5,10]), '/source/masks')

    def fixture(self, root):
        floor, wall, frames, poses, _ = room()
        bundle, cache = root/'bundle', root/'masks'
        bundle.mkdir(); cache.mkdir()
        points = np.concatenate([floor.reshape(3,24,24,3),wall.reshape(3,24,24,3)],axis=2)
        ids = np.array([0,5,10]); shape = points.shape[:-1]
        rgb = np.full(points.shape, 100, np.uint8)
        np.savez(bundle/'inputs.npz',rgb=rgb,frame_indices=ids)
        (bundle/'inputs.json').write_text(json.dumps(dict(frame_indices=ids.tolist(), timestamps_seconds=[0,.5,1],processed_size_wh=[48,24])))
        indices=np.arange(points.size//3)
        np.savez(bundle/'reference_samples.npz',points=points.reshape(-1,3),colors=rgb.reshape(-1,3),source_flat_indices=indices)
        k = np.repeat(np.eye(3)[None],3,axis=0)
        local = np.ones_like(points)
        np.savez(bundle/'predictions.npz',points=points,local_points=local,conf=np.full((*shape,1),5.),
                 non_edge=np.ones(shape,bool),camera_poses=poses,intrinsics=k)
        masks = {name:np.zeros(shape,bool) for name in ('person','glass','mirror','floor','wall')}
        masks['floor'][:,:,:24] = True; masks['wall'][:,:,24:] = True
        np.savez(cache/'masks.npz',frame_indices=ids,**masks)
        meta = dict(status='complete',bundle=str(bundle.resolve()))
        (cache/'manifest.json').write_text(json.dumps(meta))
        camera = dict(world_transform=np.eye(4).tolist(),frames=[dict(source_frame=int(fid),timestamp_seconds=float(i*.5),
                         c2w=poses[i].tolist(),intrinsics=k[i].tolist()) for i,fid in enumerate(ids)])
        path = bundle/'cameras.json'; path.write_text(json.dumps(camera))
        return bundle, cache, path, masks, ids

    def test_cli_build_exports_evidence_preserves_inputs_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bundle, cache, path, _, ids = self.fixture(root)
            original = path.read_text()
            report = build(bundle, cache, path, root/'out')
            self.assertEqual(path.read_text(),original)
            self.assertEqual(report['mask_review_status'],'pending_visual_review')
            self.assertIn('floor and wall',report['status'])
            self.assertEqual(len(report['evidence']),6)
            output=json.loads((root/'out/cameras.json').read_text())
            source=json.loads(path.read_text())
            for a,b in zip(source['frames'],output['frames']):
                self.assertEqual(a['intrinsics'],b['intrinsics'])
                self.assertEqual(a['timestamp_seconds'],b['timestamp_seconds'])
            with self.assertRaises(FileExistsError):
                build(bundle,cache,path,root/'out')

    def test_people_and_reflections_are_excluded_from_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bundle,cache,path,masks,ids=self.fixture(root)
            masks['mirror'] = masks['floor'].copy()
            np.savez(cache/'masks.npz',frame_indices=ids,**masks)
            meta=json.loads((cache/'manifest.json').read_text())
            (cache/'manifest.json').write_text(json.dumps(meta))
            report=build(bundle,cache,path,root/'out')
            self.assertIsNone(report['floor'])
            self.assertNotIn('plane_normal_raw',json.loads((root/'out/cameras.json').read_text())['floor_alignment'])

    def test_legacy_cache_requires_explicit_preservation_or_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,cache,path,masks,ids=self.fixture(root)
            np.savez(cache/'masks.npz',frame_indices=ids,**{k:masks[k] for k in ('person','glass','mirror')})
            meta=json.loads((cache/'manifest.json').read_text())
            (cache/'manifest.json').write_text(json.dumps(meta))
            validate_cache(cache,bundle,ids,(24,48))
            with self.assertRaisesRegex(ValueError,'floor and wall'):
                validate_cache(cache,bundle,ids,(24,48),require_structure=True)

    def test_changed_camera_timing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,cache,path,_,_=self.fixture(root)
            camera=json.loads(path.read_text());camera['frames'][1]['timestamp_seconds']=.7
            path.write_text(json.dumps(camera))
            with self.assertRaisesRegex(ValueError,'timing'):
                build(bundle,cache,path,root/'out')
            self.assertFalse((root/'out').exists())

    def test_measurements_and_display_samples_use_final_basis(self):
        scripts=Path(__file__).resolve().parents[1]/'.agents/skills/pi3x-scene-reference/scripts'
        spec=importlib.util.spec_from_file_location('structural_measure_test',scripts/'measure.py')
        module=importlib.util.module_from_spec(spec)
        with patch.object(sys,'path',[str(scripts),*sys.path]):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,cache,path,_,_=self.fixture(root)
            build(bundle,cache,path,root/'out')
            result=module.load_reference(bundle,{},root/'out/cameras.json')
            camera,cloud=result[1],result[4]
            transform=np.asarray(camera['world_transform'])
            with np.load(bundle/'predictions.npz') as data:
                expected=data['points'].reshape(-1,3)@transform[:3,:3].T+transform[:3,3]
            np.testing.assert_allclose(cloud,expected)


if __name__ == '__main__':
    unittest.main()
