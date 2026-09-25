"""Object evidence contract: real focus PNGs, synthetic saved-scene provenance."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from aha3d.io import digest, read, write
from aha3d.workflow.object_review import generate, packet
from tools.layout_inspection.agent_review import create


def object_fixture(spec, out):
    out = Path(out)
    (out/'export').mkdir(); (out/'outlines').mkdir()
    (out/'export/model.npz').write_bytes(b'geometry fixture')
    scene_hash = digest(spec['source_scene'])
    objects = [dict(id=i, name=i, root_name=i, semantic_class=c, grouping='authored instance_id', color=color)
               for i, c, color in [('bed', 'furniture/bed', [255, 150, 0]),
                                    ('headwall', 'structure/wall', [0, 200, 255])]]
    write(out/'export/model.json', dict(source_scene_sha256=scene_hash,
          cameras_sha256=digest(spec['cameras']), geometry_sha256=digest(out/'export/model.npz'), object_groups=objects))
    views = read(out/'inspection/inspection.json')['views']
    data = dict(source_scene_sha256=scene_hash, source_inspection=str(out/'inspection'), objects=objects,
                input_hashes=dict(geometry=digest(out/'export/model.npz'), metadata=digest(out/'export/model.json'),
                                  inspection=digest(out/'inspection/inspection.json')),
                views={v: dict(objects={o['id']: dict(paths=[[[1,1],[6,1],[6,6],[1,6]]], mask_pixels=36)
                                       for o in objects}) for v in views})
    write(out/'outlines/objects.json', data)
    create(out/'outlines/objects.json', out/'objects', all_objects=True)


class ObjectPacket(unittest.TestCase):
    def setUp(self):
        from test_layout_gate import LayoutGate
        self.layout = LayoutGate()
        self.layout.setUp(); self.addCleanup(self.layout.doCleanups)
        self.layout.prepare()
        self.out, self.spec = self.layout.evidence, self.layout.spec
        self.views = read(self.out/'evidence.json')['expected_views']

    def check(self):
        return packet(self.spec, self.out, self.views)

    def change_report(self, change):
        path = self.out/'objects/agent_review.json'; data = read(path)
        change(data); write(path, data)

    def test_bed_and_architecture_get_individual_source_and_orthographic_views(self):
        result = self.check()
        self.assertEqual(set(result['object_views']), {'bed', 'headwall'})
        self.assertEqual(len(read(self.out/'objects/summary.json')['next_images']), 6)
        for images in result['object_views'].values():
            self.assertEqual(len(images), 3)
            self.assertTrue(any('_top.png' in i for i in images))
            self.assertEqual(sum('_source_' in i for i in images), 2)

    def test_missing_packet_and_empty_inventory_fail(self):
        path = self.out/'objects/agent_review.json'; original = path.read_bytes(); path.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'): self.check()
        path.write_bytes(original)
        data = read(self.out/'outlines/objects.json'); data['objects'] = []
        write(self.out/'outlines/objects.json', data)
        self.change_report(lambda r: r['inputs'].update(outlines_sha256=digest(self.out/'outlines/objects.json')))
        with self.assertRaisesRegex(ValueError, 'inventory'): self.check()

    def test_wall_cannot_be_omitted_from_focus_packet(self):
        self.change_report(lambda r: r.update(images=[i for i in r['images'] if i.get('object_id') != 'headwall']))
        with self.assertRaisesRegex(ValueError, 'focus evidence: headwall'): self.check()

    def test_wrong_highlight_and_empty_contour_fail(self):
        data = read(self.out/'objects/agent_review.json')
        row = next(i for i in data['images'] if i.get('object_id') == 'bed')
        row['highlighted_ids'] = ['headwall']; write(self.out/'objects/agent_review.json', data)
        with self.assertRaisesRegex(ValueError, 'wrong object'): self.check()
        row['highlighted_ids'] = ['bed']; write(self.out/'objects/agent_review.json', data)
        outlines = read(self.out/'outlines/objects.json')
        outlines['views'][row['view']]['objects']['bed']['paths'] = []
        write(self.out/'outlines/objects.json', outlines)
        self.change_report(lambda r: r['inputs'].update(outlines_sha256=digest(self.out/'outlines/objects.json')))
        with self.assertRaisesRegex(ValueError, 'no object contour'): self.check()

    def test_changed_image_and_required_inventory_fail(self):
        self.spec['required_object_ids'] = ['missing-wall']
        with self.assertRaisesRegex(ValueError, 'absent from export'): self.check()
        self.spec.pop('required_object_ids')
        report = read(self.out/'objects/agent_review.json')
        (self.out/'objects'/report['images'][-1]['path']).write_bytes(b'changed image')
        with self.assertRaisesRegex(ValueError, 'image changed'): self.check()

    def test_generation_composes_tools_once_with_exact_frame_and_exclusions(self):
        config = read(self.spec['config']); config.update(model_frame=7, exclude_objects=['person'])
        write(self.spec['config'], config)
        with patch('subprocess.run') as run:
            generate(self.spec, self.out, blender='/bin/blender', python='/bin/python', threads=2)
        self.assertEqual(run.call_count, 3)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][-4:], ['--frame', '7', '--exclude', 'person'])
        self.assertIn('tools.layout_inspection.object_outline', commands[1])
        self.assertIn('--all-objects', commands[2])

    def test_general_prose_does_not_replace_object_observations(self):
        from aha3d.workflow import layout_gate as gate
        from aha3d.workflow.review_contract import validate
        from test_acceptance import visual_fixture
        request = gate.review_request(self.spec, self.out)
        review = visual_fixture(request['candidate_revision'], request['images'], subjects=request['subjects'])
        with self.assertRaisesRegex(ValueError, 'Object-focused'):
            validate(review, request['candidate_revision'], request['images'], object_views=request['object_views'])

    def test_packet_manifest_cannot_be_rewritten_after_preparation(self):
        from aha3d.workflow import layout_gate as gate
        self.change_report(lambda r: r.update(status='cosmetic rewrite'))
        with self.assertRaisesRegex(ValueError, 'Object evidence changed'):
            gate.review_request(self.spec, self.out)


if __name__ == '__main__': unittest.main()
