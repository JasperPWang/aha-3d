"""Independent requirements-intake behavior.

The intake itself is standard-library planning and must neither inspect Blender
content nor dispatch execution, regardless of any inherited run identity.
"""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.workflow.intake import apply_answers, build_intake


def static_request():
    return {'schema_version': 1, 'scene': 'intake-fixture',
            'inputs': {'images': ['references/source.png']}, 'reuse': 'reuse_allowed',
            'fidelity': {'mode': 'approximate'},
            'appearance': 'whitebox', 'delivery': 'stills', 'camera': 'inspection',
            'people': 'none', 'cabinets': 'none', 'objects': 'none',
            'variants': {'models': False, 'materials': False}}


def video_request():
    request = static_request()
    request['inputs'] = {'video': 'references/source.mp4'}
    request['delivery'] = 'video'
    request['timing'] = {'mode': 'explicit', 'fps': '24000/1001', 'frames': 208, 'start': 1}
    return request


def question_fields(report):
    return {question['field'] for question in report['questions']}


class IntakeTests(unittest.TestCase):
    def assertPlanOnly(self, report):
        self.assertEqual(report['execution'], 'not_started')
        self.assertIn(report['status'], ('needs_input', 'ready_for_authoring'))
        self.assertIsInstance(report['stages'], list)
        for stage in report['stages']:
            for field in ('id', 'depends_on', 'owner', 'tool', 'output', 'checks'):
                self.assertIn(field, stage)
        json.dumps(report, allow_nan=False)

    def test_fidelity_requires_answer_and_selective_targets_before_authoring(self):
        request = video_request()
        del request['fidelity']
        report = build_intake(request)
        self.assertEqual(question_fields(report), {'fidelity.mode'})
        self.assertEqual(report['stages'], [])
        selected = apply_answers(request, {'fidelity': {'mode': 'selective'}})
        self.assertEqual(question_fields(build_intake(selected)), {'fidelity.targets'})
        selected = apply_answers(selected, {'fidelity': {'targets': ['bed', 'window wall']}})
        report = build_intake(selected)
        self.assertEqual(report['status'], 'ready_for_authoring')
        review = next(s for s in report['stages'] if s['id'] == 'room_review')
        self.assertEqual(review['fidelity'], selected['fidelity'])
        self.assertEqual(build_intake(json.loads(json.dumps(report['request'])))['questions'], [])

    def test_major_object_fidelity_requires_xray_before_bounded_repairs(self):
        request = video_request()
        request['fidelity'] = {'mode': 'major_objects'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        review = next(s for s in report['stages'] if s['id'] == 'room_review')
        self.assertEqual(review['fidelity'], {'mode': 'major_objects'})
        checks = ' '.join(review['checks'])
        self.assertIn('isolated matched X-ray/source', checks)
        self.assertIn('compare before/after', checks)
        self.assertIn('salient lamps', checks)
        self.assertIn('small surface decor may vary', checks)

    def test_fidelity_question_offers_major_object_alignment(self):
        request = video_request()
        del request['fidelity']
        report = build_intake(request)
        question = next(q for q in report['questions'] if q['field'] == 'fidelity.mode')
        self.assertEqual(question['options'], ['approximate', 'major_objects', 'precise', 'selective'])

    def test_video_default_preserves_static_override_and_optional_demo(self):
        request = video_request()
        del request['delivery']
        report = build_intake(request)
        self.assertEqual(report['request']['delivery'], 'video')
        self.assertFalse(report['request']['interactive_demo'])
        self.assertNotIn('delivery', question_fields(report))
        demo = build_intake(apply_answers(report['request'], {'interactive_demo': True}))
        self.assertIn('interactive_demo', {s['id'] for s in demo['stages']})
        self.assertEqual(build_intake(static_request())['request']['delivery'], 'stills')

    def test_bare_checkpoint_does_not_override_later_explicit_static_preset(self):
        saved = build_intake({'schema_version': 1})['request']
        static = build_intake(apply_answers(saved, {'preset': 'whitebox'}))
        self.assertEqual(static['request']['delivery'], 'stills')

    def test_invalid_fidelity_and_demo_choices_are_rejected(self):
        for patch in ({'fidelity': {'mode': 'exact'}},
                      {'fidelity': {'mode': 'selective', 'targets': ['']}},
                      {'fidelity': {'mode': 'selective', 'targets': 'bed'}},
                      {'interactive_demo': 'yes'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                build_intake(apply_answers(static_request(), patch))

    def test_complete_static_request_does_not_need_timing_or_motion_details(self):
        request = static_request()
        before = copy.deepcopy(request)
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        self.assertEqual(report['questions'], [])
        self.assertEqual(request, before)
        self.assertNotIn('timing', report['request'])
        self.assertPlanOnly(report)

    def test_only_missing_context_is_asked_and_known_none_is_preserved(self):
        request = static_request()
        del request['appearance']
        del request['variants']
        report = build_intake(request)
        self.assertEqual(report['status'], 'needs_input')
        fields = question_fields(report)
        self.assertIn('appearance', fields)
        self.assertTrue(any(field == 'variants' or field.startswith('variants.') for field in fields))
        self.assertTrue(all(field == 'appearance' or field == 'variants' or field.startswith('variants.') for field in fields), fields)
        for field in ('people', 'cabinets', 'objects'):
            self.assertEqual(report['request'][field], 'none')
            self.assertNotIn(field, fields)
        answers = {'appearance': 'materials', 'variants': {'models': False, 'materials': True}}
        merged = apply_answers(request, answers)
        self.assertEqual(build_intake(merged)['questions'], [])
        self.assertNotIn('appearance', request)
        self.assertNotIn('variants', request)

    def test_video_input_does_not_authorize_camera_or_people_motion(self):
        request = static_request()
        request['inputs'] = {'video': 'references/source.mp4'}
        report = build_intake(request)
        self.assertEqual(report['request']['camera'], 'inspection')
        self.assertEqual(report['request']['people'], 'none')
        self.assertEqual(report['request']['delivery'], 'stills')
        self.assertNotIn('timing', report['request'])
        self.assertEqual(report['questions'], [])
        del request['camera']
        unknown_camera = build_intake(request)
        self.assertNotIn(unknown_camera['request'].get('camera'), ('source_trajectory', 'custom'))

    def test_partial_variants_only_ask_for_the_missing_choice(self):
        for known, missing in (('models', 'materials'), ('materials', 'models')):
            for chosen in (False, True):
                with self.subTest(known=known, chosen=chosen):
                    request = static_request()
                    request['variants'] = {known: chosen}
                    report = build_intake(request)
                    self.assertEqual(question_fields(report), {'variants.' + missing})
                    self.assertEqual(report['request']['variants'], {known: chosen})
                    self.assertEqual(report['questions'][0]['options'], [False, True])
                    resolved = apply_answers(report['request'], {'variants': {missing: False}})
                    replay = build_intake(resolved)
                    self.assertEqual(replay['status'], 'ready_for_authoring')
                    self.assertEqual(replay['request']['variants'], {known: chosen, missing: False})

    def test_explicit_choices_override_presets(self):
        request = video_request()
        request.update(preset='whitebox', appearance='materials', camera='custom', people='approximate')
        request['details'] = {'camera': 'A slow left-to-right room pan.', 'people': 'One adult walks to the sofa.'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        for field in ('appearance', 'delivery', 'camera', 'people'):
            self.assertEqual(report['request'][field], request[field])
            self.assertNotIn(field, report['defaults'])
        self.assertPlanOnly(report)

    def test_static_presets_and_source_camera_preset_have_different_motion_defaults(self):
        common = {'fidelity': {'mode': 'approximate'}, 'schema_version': 1, 'scene': 'intake-fixture', 'inputs': {'video': 'references/source.mp4'},
                  'variants': {'models': False, 'materials': False}}
        for preset in ('whitebox', 'materials'):
            report = build_intake(dict(common, preset=preset))
            self.assertEqual(report['status'], 'ready_for_authoring')
            self.assertEqual(report['request']['delivery'], 'stills')
            self.assertEqual(report['request']['camera'], 'inspection')
            self.assertEqual([report['request'][key] for key in ('people', 'cabinets', 'objects')], ['none'] * 3)
            self.assertTrue(report['defaults'])
        report = build_intake(dict(common, preset='source_camera'))
        self.assertEqual(report['request']['camera'], 'source_trajectory')
        self.assertEqual(report['request']['delivery'], 'video')
        self.assertTrue({'people', 'cabinets', 'objects'} <= question_fields(report))
        self.assertNotEqual(report['status'], 'ready_for_authoring')

    def test_appearance_delivery_and_motion_axes_remain_independent(self):
        request = video_request()
        request.update(appearance='whitebox', camera='inspection', people='none', cabinets='animate', objects='none')
        request['details'] = {'cabinets': 'Open the left cabinet door from 2 to 4 seconds.'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        self.assertEqual(report['request']['appearance'], 'whitebox')
        self.assertEqual(report['request']['camera'], 'inspection')
        self.assertEqual(report['request']['people'], 'none')
        self.assertEqual(report['request']['objects'], 'none')
        self.assertEqual(report['request']['cabinets'], 'animate')
        self.assertPlanOnly(report)

    def test_exact_timing_survives_canonical_request_json_roundtrip(self):
        request = video_request()
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        canonical = json.loads(json.dumps(report['request']))
        replay = build_intake(canonical)
        self.assertEqual(replay['status'], 'ready_for_authoring')
        self.assertEqual(replay['request']['timing'], report['request']['timing'])
        self.assertEqual(replay['request']['timing']['fps'], '24000/1001')
        self.assertEqual(replay['request']['timing']['frames'], 208)
        self.assertEqual(replay['request']['timing'].get('start', 1), 1)
        self.assertNotIn('duration_seconds', replay['request']['timing'])
        self.assertNotIn('end', replay['request']['timing'])

    def test_source_timing_records_intent_without_fabricating_numbers(self):
        request = video_request()
        request['timing'] = {'mode': 'source'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        self.assertEqual(report['request']['timing'], {'mode': 'source'})
        self.assertPlanOnly(report)
        del request['timing']
        self.assertIn('timing', question_fields(build_intake(request)))

    def test_resume_switches_timing_mode_without_retaining_incompatible_fields(self):
        request = video_request()
        before = copy.deepcopy(request)
        source = apply_answers(request, {'timing': {'mode': 'source'}})
        self.assertEqual(source['timing'], {'mode': 'source'})
        self.assertEqual(build_intake(source)['status'], 'ready_for_authoring')
        explicit = apply_answers(source, {'timing': {'mode': 'explicit', 'fps': '24', 'duration_seconds': 5}})
        self.assertEqual(build_intake(explicit)['request']['timing'],
                         {'mode': 'explicit', 'fps': '24', 'frames': 120})
        incomplete = apply_answers(source, {'timing': {'mode': 'explicit'}})
        self.assertEqual(question_fields(build_intake(incomplete)), {'timing.fps', 'timing.frames'})
        self.assertEqual(request, before)

    def test_resume_new_duration_replaces_saved_frame_count_but_keeps_cadence_and_start(self):
        request = video_request()
        request['timing'] = {'mode': 'explicit', 'fps': '24', 'frames': 120, 'start': 7}
        saved = json.loads(json.dumps(build_intake(request)['request']))
        resumed = apply_answers(saved, {'timing': {'duration_seconds': 10}})
        self.assertNotIn('frames', resumed['timing'])
        self.assertEqual(build_intake(resumed)['request']['timing'],
                         {'mode': 'explicit', 'fps': '24', 'frames': 240, 'start': 7})
        self.assertEqual(saved['timing'], request['timing'])
        contradictory = apply_answers(saved, {'timing': {'duration_seconds': 10, 'frames': 120}})
        with self.assertRaisesRegex(ValueError, 'exact'):
            build_intake(contradictory)

    def test_resume_explicit_frame_answer_discards_old_duration(self):
        request = video_request()
        request['timing'] = {'mode': 'explicit', 'duration_seconds': 5, 'start': 3}
        resumed = apply_answers(request, {'timing': {'frames': 144, 'fps': '24'}})
        self.assertNotIn('duration_seconds', resumed['timing'])
        self.assertEqual(build_intake(resumed)['request']['timing'],
                         {'mode': 'explicit', 'fps': '24', 'frames': 144, 'start': 3})
        self.assertEqual(request['timing'], {'mode': 'explicit', 'duration_seconds': 5, 'start': 3})

    def test_answer_merge_preserves_other_context_and_replaces_lists(self):
        request = video_request()
        request['inputs']['images'] = ['old-a.png', 'old-b.png']
        request['details'] = {'appearance': 'Keep the original palette.', 'objects': 'An existing note.'}
        answers = {'inputs': {'images': ['new.png']}, 'details': {'objects': 'A replacement note.'},
                   'variants': {'models': True}}
        before, answers_before = copy.deepcopy(request), copy.deepcopy(answers)
        merged = apply_answers(request, answers)
        self.assertEqual(merged['inputs']['images'], ['new.png'])
        self.assertEqual(merged['inputs']['video'], request['inputs']['video'])
        self.assertEqual(merged['details']['appearance'], request['details']['appearance'])
        self.assertEqual(merged['details']['objects'], 'A replacement note.')
        self.assertEqual(merged['variants'], {'models': True, 'materials': False})
        self.assertEqual(request, before)
        self.assertEqual(answers, answers_before)
        with self.assertRaises(ValueError):
            apply_answers(request, {'unexpected': 'not silently retained'})

    def test_invalid_schema_timing_and_explicit_conflicts_fail(self):
        # New source/custom animated cameras + stills are intentionally outside
        # intake v1 scope; legacy still-frame recipes remain independently valid.
        invalid_updates = [
            {'unknown': True}, {'schema_version': True}, {'schema_version': 9},
            {'scene': '../escape'}, {'appearance': 'anything'}, {'people': 'tracking'},
            {'variants': {'models': 1, 'materials': False}},
            {'timing': {'mode': 'explicit', 'fps': True, 'frames': 120}},
            {'timing': {'mode': 'explicit', 'fps': '24', 'frames': True}},
            {'timing': {'mode': 'explicit', 'fps': float('nan'), 'frames': 120}},
            {'timing': {'mode': 'explicit', 'fps': '24', 'frames': 0}},
            {'timing': {'mode': 'explicit', 'fps': '24', 'frames': 120, 'start': 0}},
            {'timing': {'mode': 'explicit', 'fps': '24', 'frames': 121, 'duration_seconds': 5}},
            {'camera': 'source_trajectory', 'delivery': 'stills'},
            {'camera': 'custom', 'delivery': 'stills', 'details': {'camera': 'A short pan.'}},
            {'reuse': 'independent', 'people': 'existing', 'inputs': {'source_scene': 'existing.blend'}},
            {'reuse': 'independent', 'cabinets': 'existing', 'inputs': {'source_scene': 'existing.blend'}},
            {'reuse': 'independent', 'objects': 'existing', 'inputs': {'source_scene': 'existing.blend'}}]
        for updates in invalid_updates:
            with self.subTest(updates=updates):
                request = video_request()
                request.update(updates)
                with self.assertRaises(ValueError):
                    build_intake(request)

    def test_bare_request_collects_scene_and_inputs_without_fabricating_context(self):
        report = build_intake({'schema_version': 1})
        self.assertEqual(report['status'], 'needs_input')
        self.assertTrue({'scene', 'inputs', 'preset', 'variants'} <= question_fields(report))
        self.assertEqual(report['stages'], [])
        self.assertEqual(report['execution'], 'not_started')
        self.assertNotIn('scene', report['request'])
        self.assertNotIn('inputs', report['request'])

    def test_seconds_and_rational_fps_derive_exact_frames_then_roundtrip(self):
        cases = [('24', 5, 120), ('30000/1001', 15.015, 450), ('24000/1001', '13013/1500', 208)]
        for fps, duration, frames in cases:
            with self.subTest(fps=fps, duration=duration):
                request = video_request()
                request['timing'] = {'mode': 'explicit', 'fps': fps, 'duration_seconds': duration}
                report = build_intake(request)
                self.assertEqual(report['status'], 'ready_for_authoring')
                canonical = report['request']['timing']
                self.assertEqual(canonical, {'mode': 'explicit', 'fps': fps, 'frames': frames})
                self.assertIs(type(canonical['frames']), int)
                replay = build_intake(json.loads(json.dumps(report['request'])))
                self.assertEqual(replay['request']['timing'], canonical)
                self.assertEqual(request['timing']['duration_seconds'], duration)

    def test_nonintegral_duration_is_rejected_without_rounding(self):
        request = video_request()
        request['timing'] = {'mode': 'explicit', 'fps': '30000/1001', 'duration_seconds': 5}
        original = copy.deepcopy(request)
        with self.assertRaisesRegex(ValueError, 'exact'):
            build_intake(request)
        self.assertEqual(request, original)
        for duration in (True, 0, -1, float('nan'), '1/0'):
            with self.subTest(duration=duration):
                request['timing'] = {'mode': 'explicit', 'fps': '24', 'duration_seconds': duration}
                with self.assertRaises(ValueError):
                    build_intake(request)

    def test_partial_duration_questions_only_ask_for_missing_cadence(self):
        request = video_request()
        request['timing'] = {'mode': 'explicit', 'duration_seconds': 5}
        report = build_intake(request)
        self.assertEqual(question_fields(report), {'timing.fps'})
        resolved = apply_answers(request, {'timing': {'fps': '24'}})
        self.assertEqual(build_intake(resolved)['request']['timing']['frames'], 120)
        request['timing'] = {'mode': 'explicit'}
        self.assertEqual(question_fields(build_intake(request)), {'timing.fps', 'timing.frames'})

    def test_existing_camera_preserves_saved_scope_and_requires_a_source_scene(self):
        request = static_request()
        request.update(camera='existing', timing={'mode': 'source'})
        request['inputs'] = {'source_scene': 'scenes/source.blend'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        self.assertEqual(report['request']['camera'], 'existing')
        stages = {stage['id'] for stage in report['stages']}
        self.assertIn('existing_motion', stages)
        self.assertNotIn('camera', stages)
        self.assertEqual(report['request']['delivery'], 'stills')
        request['reuse'] = 'independent'
        with self.assertRaises(ValueError):
            build_intake(request)
        request['reuse'] = 'reuse_allowed'
        request['inputs'] = {'video': 'references/source.mp4'}
        self.assertIn('inputs.source_scene', question_fields(build_intake(request)))

    def test_parallel_groups_respect_dependencies_without_scheduling(self):
        request = video_request()
        request.update(camera='source_trajectory', people='approximate', cabinets='animate', objects='animate')
        request['details'] = {'people': 'One person sits.', 'cabinets': 'Open the left door.', 'objects': 'Move the cup.'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        stages = {stage['id']: stage for stage in report['stages']}
        completed = set()
        for group in report['parallel_groups']:
            self.assertFalse(completed.intersection(group))
            for stage_id in group:
                self.assertTrue(set(stages[stage_id]['depends_on']) <= completed)
            completed.update(group)
        self.assertEqual(completed, set(stages))
        self.assertTrue(any({'people', 'cabinets', 'objects'} <= set(group) for group in report['parallel_groups']))
        self.assertEqual(report['execution'], 'not_started')

    def test_requested_variants_are_recorded_but_execution_is_deferred(self):
        request = static_request()
        request['variants'] = {'models': True, 'materials': True, 'notes': 'All chairs, wall finish and floor finish.'}
        report = build_intake(request)
        self.assertEqual(report['status'], 'ready_for_authoring')
        self.assertEqual(report['request']['variants'], request['variants'])
        self.assertTrue(report['deferred'])
        self.assertIn('variant', json.dumps(report['deferred']).lower())
        self.assertTrue(all('scene_variant' not in str(stage['tool']) for stage in report['stages']))
        self.assertPlanOnly(report)


class IntakeCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.request = self.root / 'request-input.json'
        self.request.write_text(json.dumps(static_request()))

    def invoke(self, *arguments):
        # Importing the CLI may expose legacy runner functions. None is allowed
        # to run during intake, even when INDOOR_RUN_ID already exists.
        import aha3d.cli as cli
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ['indoor', '--root', str(self.root), 'intake'] + list(arguments)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, 'argv', argv))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            for name in ('prepare', 'execute', 'launch', 'submit', 'submit_recipes', 'load_runtime'):
                if hasattr(cli, name):
                    stack.enter_context(mock.patch.object(cli, name, side_effect=AssertionError('Intake dispatched ' + name)))
            stack.enter_context(mock.patch('subprocess.run', side_effect=AssertionError('Intake spawned subprocess.run')))
            stack.enter_context(mock.patch('subprocess.Popen', side_effect=AssertionError('Intake spawned subprocess.Popen')))
            try:
                result = cli.main()
            except SystemExit as error:
                result = error.code
        return result, stdout.getvalue(), stderr.getvalue()

    def test_stdout_intake_needs_no_runtime_or_jobs_with_or_without_run_identity(self):
        for job_id in ('', 'test-run'):
            with self.subTest(job_id=job_id), mock.patch.dict(os.environ, {'INDOOR_RUN_ID': job_id}):
                before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
                code, output, errors = self.invoke('--request', str(self.request))
                self.assertEqual(code, 0, errors)
                report = json.loads(output)
                self.assertEqual(report['status'], 'ready_for_authoring')
                self.assertEqual(report['execution'], 'not_started')
                self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), before)

    def test_save_and_resume_answers_keep_canonical_requirements_and_protect_existing_output(self):
        first = self.root / 'saved-intake'
        code, output, errors = self.invoke('--request', str(self.request), '--out', str(first))
        self.assertEqual(code, 0, errors)
        self.assertEqual({p.name for p in first.iterdir()}, {'request.json', 'intake.json', 'BRIEF.md'})
        saved = json.loads((first / 'request.json').read_text())
        self.assertEqual(saved, json.loads(output)['request'])
        self.assertEqual(json.loads((first / 'intake.json').read_text()), json.loads(output))
        brief = (first / 'BRIEF.md').read_text()
        self.assertTrue(brief.strip())
        before_bytes = {path.name: path.read_bytes() for path in first.iterdir()}
        code, output, errors = self.invoke('--request', str(self.request), '--out', str(first))
        self.assertNotEqual(code, 0)
        self.assertEqual({path.name: path.read_bytes() for path in first.iterdir()}, before_bytes)
        answers = self.root / 'answers.json'
        answers.write_text(json.dumps({'appearance': 'materials', 'variants': {'models': True}}))
        second = self.root / 'resumed-intake'
        code, output, errors = self.invoke('--request', str(first / 'request.json'), '--answers', str(answers), '--out', str(second))
        self.assertEqual(code, 0, errors)
        resumed = json.loads(output)
        self.assertEqual(resumed['execution'], 'not_started')
        self.assertEqual(resumed['request']['appearance'], 'materials')
        self.assertEqual(resumed['request']['variants'], {'models': True, 'materials': False})
        for field in ('inputs', 'camera', 'delivery', 'people', 'cabinets', 'objects'):
            self.assertEqual(resumed['request'][field], saved[field])
        self.assertEqual({path.name: path.read_bytes() for path in first.iterdir()}, before_bytes)

    def test_bare_cli_reports_missing_context_without_creating_files(self):
        before = sorted(path.name for path in self.root.iterdir())
        code, output, errors = self.invoke()
        self.assertEqual(code, 0, errors)
        report = json.loads(output)
        self.assertEqual(report['status'], 'needs_input')
        self.assertTrue({'scene', 'inputs'} <= question_fields(report))
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), before)

    def test_bad_answers_do_not_create_partial_output(self):
        answers = self.root / 'bad-answers.json'
        answers.write_text(json.dumps({'variants': {'models': 'yes'}}))
        output = self.root / 'bad-output'
        code, _, errors = self.invoke('--request', str(self.request), '--answers', str(answers), '--out', str(output))
        self.assertNotEqual(code, 0)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
