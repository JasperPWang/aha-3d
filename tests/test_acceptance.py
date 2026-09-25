"""CPU fixtures exercise policy, not Blender output quality or actual visual judgment."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aha3d.io import digest, read, signature, write
from aha3d.workflow import acceptance as gate
from aha3d.workflow.review_contract import ASPECTS, image_records
from aha3d.results import registry


def visual_fixture(revision, images, subjects=('bed', 'nightstand', 'bed-nightstand')):
    return dict(schema_version=2,candidate_revision=revision,reviewer='mock-image-reviewer',verdict='accepted',
        reviewed_views=list(images),image_delivery=dict(method='codex_exec_images',images=image_records(images),request_sha256='fixture-request'),
        observations=[dict(aspect=a,subjects=list(subjects),views=list(images),
            observation='Fixture observation: bed headboard and nightstand share the measured wall baseline; unseen wall remains uncertain.') for a in ASPECTS],
        findings=[],uncertainties=[dict(observation='Rear wall occluded',impact='nonblocking')],unreviewed_areas=[])


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'scenes/room').mkdir(parents=True)
        self.scope=dict(scene='room',task='task',kind='reconstruction',reference_reconstruction=False,
                        human_motion=False,render='none',required_artifacts=['scene'],subjects=['bed','nightstand','bed-nightstand'],repair_budget=2)
        gate.init(self.root,self.scope);self.out=gate.folder(self.root,'room','task')
        for name in ('room.blend','final.blend','camera.json','config.json','validator.py','technical.json'):
            (self.root/name).write_text(name)
        self.context={k:str(self.root/v) for k,v in [('room_scene','room.blend'),('final_scene','final.blend'),('cameras','camera.json'),('configuration','config.json')]}
        self.images={}
        for key in ('plan','front','side'):
            path=self.root/(key+'.png');path.write_bytes(b'fixture-image-'+key.encode());self.images[key]=str(path)
        write(self.root/'views.json',dict(images=self.images,input_binding={k:digest(v) for k,v in self.context.items()}))
        self.spec=dict(context=self.context,artifacts=[dict(role='scene',path='final.blend')],purpose='delivery',completeness='complete',final_views='views.json')
        self.revision=gate.register_candidate(self.root,'room','task',self.spec)['candidate_revision']

    def report(self,name):
        data=gate.candidate(self.out,self.revision)
        report=dict(policy=gate.POLICY,status='passed',candidate_revision=self.revision,evidence=[gate.capture(self.root/'technical.json')],validator=gate.capture(self.root/'validator.py'))
        if name=='technical':report['artifacts']=data['artifacts']
        else:report.update(images=self.images,review=visual_fixture(self.revision,self.images))
        path=self.root/(name+'-report.json');write(path,report)
        gate.record_check(self.root,'room','task',self.revision,name,path)
        return path

    def complete(self):
        self.report('technical');self.report('final_review')
        return gate.evaluate(self.root,'room','task')

    def delivery(self):
        data=dict(schema_version=1,scene='room',id='v1',status='recorded_delivery',
            artifacts=self.spec['artifacts'],evidence=[dict(path='technical-report.json')],review=dict(by='fixture',note='Synthetic test review'),
            acceptance=dict(task='task',candidate_revision=self.revision))
        return registry.register(self.root,data)

    def codes(self):return {b['code'] for b in gate.evaluate(self.root,'room','task')['blockers']}

    def test_complete_room_only_passes_without_human_checks(self):
        result=self.complete();self.assertTrue(result['permitted'],result)
        self.assertEqual([c['name'] for c in result['required_checks']],['technical','final_review'])
        self.delivery();self.assertEqual(registry.select(self.root,'room','v1')['status'],'accepted')
        self.assertEqual(registry.selected(self.root,'room')['certification'],'accepted')

    def test_inspection_exists_without_review_blocks(self):
        self.report('technical')
        self.assertIn('CHECK_FINAL_REVIEW',self.codes())
        self.delivery()
        with self.assertRaisesRegex(ValueError,'CHECK_FINAL_REVIEW'):registry.select(self.root,'room','v1')

    def test_incomplete_required_views_and_coverage(self):
        self.complete();path=self.root/'final_review-report.json'
        for field in ('reviewed_views','observations'):
            report=read(path);original=copy.deepcopy(report)
            report['review'][field]=[];write(path,report)
            gate.record_check(self.root,'room','task',self.revision,'final_review',path)
            self.assertIn('CHECK_FINAL_REVIEW',self.codes());write(path,original)

    def test_scene_camera_configuration_and_validator_changes_invalidate(self):
        self.complete()
        for name in ('room.blend','final.blend','camera.json','config.json','validator.py'):
            p=self.root/name;original=p.read_bytes();p.write_bytes(b'changed')
            self.assertFalse(gate.evaluate(self.root,'room','task')['permitted'],name);p.write_bytes(original)

    def test_evidence_changes_after_registration_reject_selection(self):
        self.complete();self.delivery();(self.root/'technical.json').write_text('mutated subordinate evidence')
        with self.assertRaisesRegex(ValueError,'CHECK_TECHNICAL'):registry.select(self.root,'room','v1')
        self.assertFalse((self.root/'deliveries/room/selected.json').exists())

    def test_registered_top_level_evidence_changes_reject_selection(self):
        self.complete();self.delivery();(self.root/'technical-report.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'EVIDENCE_CHANGED'):registry.select(self.root,'room','v1')

    def finding(self):
        return dict(id='bed-offset',origin='user',severity='blocking',affected_ids=['bed','nightstand','bed-nightstand'],views=['plan'],originating_revision=self.revision,
                    observation='Bed and nightstand are misaligned',resolution_needed='Correct both baselines and compare matched plan and source views')

    def test_user_finding_survives_new_inspection_revision_and_restart(self):
        self.complete();gate.add_finding(self.root,'room','task',self.finding())
        self.assertIn('OPEN_FINDING',self.codes())
        self.spec['purpose']='candidate';gate.register_candidate(self.root,'room','task',self.spec)
        self.assertEqual(read(self.out/'findings.json')['findings'][0]['status'],'open')
        self.assertIn('OPEN_FINDING',self.codes())
        with self.assertRaisesRegex(ValueError,'already exists'):gate.add_finding(self.root,'room','task',self.finding())

    def test_resolution_requires_actual_before_after_and_current_revision(self):
        gate.add_finding(self.root,'room','task',self.finding())
        resolution=dict(candidate_revision=self.revision,disposition='corrected',rationale='Moved the nightstand baseline',images=self.images,review=str(self.root/'review.json'))
        with self.assertRaisesRegex(ValueError,'before/after'):gate.resolve_finding(self.root,'room','task','bed-offset',resolution)
        images={'before:plan':self.images['plan'],'after:plan':self.images['plan']}
        write(self.root/'review.json',visual_fixture(self.revision,images));resolution['images']=images
        resolution.update(disposition='false_positive',rationale='Matched before/after plan verifies both baselines were aligned; original report confused perspective')
        gate.resolve_finding(self.root,'room','task','bed-offset',resolution)
        self.assertTrue(self.complete()['permitted'])
        (self.root/'review.json').write_text('{}');self.assertIn('OPEN_FINDING',self.codes())

    def test_diagnostic_and_partial_can_register_but_never_accept(self):
        for change in (dict(purpose='diagnostic'),dict(completeness='partial')):
            self.revision=gate.register_candidate(self.root,'room','task',dict(self.spec,**change))['candidate_revision']
            self.complete();self.assertIn('NOT_DELIVERY',self.codes())

    def test_corrected_finding_requires_fresh_closure_on_delivery_revision(self):
        gate.add_finding(self.root,'room','task',self.finding())
        original=self.revision
        self.spec['completeness']='partial'
        self.revision=gate.register_candidate(self.root,'room','task',self.spec)['candidate_revision']
        images={'before:plan':self.images['plan'],'after:plan':self.images['plan']}
        review=self.root/'closure-preview.json'
        write(review,visual_fixture(self.revision,images))
        resolution=dict(candidate_revision=self.revision,disposition='corrected',
                        rationale='Fixture corrected preview baseline',images=images,review=str(review))
        gate.resolve_finding(self.root,'room','task','bed-offset',resolution)
        with self.assertRaisesRegex(ValueError,'already resolved'):
            gate.resolve_finding(self.root,'room','task','bed-offset',resolution)
        # A new delivery artifact must not inherit the preview closure.
        (self.root/'extra.json').write_text('delivery artifact')
        self.spec['completeness']='complete'
        self.spec['artifacts'].append(dict(role='camera',path='extra.json'))
        self.revision=gate.register_candidate(self.root,'room','task',self.spec)['candidate_revision']
        self.assertIn('OPEN_FINDING',self.codes())
        resolution['candidate_revision']=self.revision
        with self.assertRaisesRegex(ValueError,'stale'):
            gate.resolve_finding(self.root,'room','task','bed-offset',resolution)
        review=self.root/'closure-delivery.json'
        write(review,visual_fixture(self.revision,images))
        resolution['review']=str(review)
        gate.resolve_finding(self.root,'room','task','bed-offset',resolution)
        finding=read(self.out/'findings.json')['findings'][0]
        self.assertEqual(finding['originating_revision'],original)
        self.assertEqual(len(finding['history']),3)
        self.assertTrue(self.complete()['permitted'])

    def test_submitted_running_jobs_are_not_completion(self):
        self.complete()
        for status in ('submitted','running'):
            state=read(self.out/'state.json');state['jobs']=[dict(id='123',status=status)];write(self.out/'state.json',state)
            result=gate.evaluate(self.root,'room','task')
            self.assertEqual(result['status'],status);self.assertFalse(result['permitted'])

    def test_final_scene_artifact_must_correspond(self):
        self.complete();self.spec['artifacts']=[dict(role='scene',path='room.blend')]
        with self.assertRaisesRegex(ValueError,'Final assembled scene'):gate.register_candidate(self.root,'room','task',self.spec)
        data=self.delivery();data['artifacts'][0]['path']='room.blend'
        self.assertIn('DELIVERY_MISMATCH',{b['code'] for b in gate.evaluate(self.root,'room','task',delivery=data)['blockers']})

    def test_scope_is_immutable_and_omission_cannot_skip_layout(self):
        from aha3d.workflow.layout_gate import validate_layout
        with self.assertRaisesRegex(ValueError,'immutable'):gate.init(self.root,self.scope)
        with self.assertRaisesRegex(ValueError,'task_scope'):validate_layout({'render':{}},self.root/'manifest.json')
        spec=read(self.out/'scope.json');spec['human_motion']=True;write(self.out/'scope.json',spec)
        self.assertIn('STATE_INVALID',self.codes())

    def test_historical_record_readable_but_not_newly_certified(self):
        data=dict(schema_version=1,scene='room',id='old',status='recorded_delivery',artifacts=self.spec['artifacts'],
                  evidence=[dict(path='technical.json')],review=dict(by='old',note='Historical only'))
        registry.register(self.root,data);path=self.root/'deliveries/room/versions/old.json'
        write(self.root/'deliveries/room/selected.json',dict(schema_version=2,delivery='deliveries/room/versions/old.json',delivery_sha256=digest(path)))
        self.assertEqual(registry.selected(self.root,'room')['certification'],'historical_unverified')
        with self.assertRaisesRegex(ValueError,'SCOPE_REQUIRED'):registry.select(self.root,'room','old')

    def test_selection_holds_task_lock(self):
        self.complete();self.delivery()
        from aha3d.io import lock
        with lock(self.out/'.lock'):
            with self.assertRaisesRegex(ValueError,'Already owned'):registry.select(self.root,'room','v1')

    def test_preview_requires_real_coverage_and_alignment_binds_assembled_scene(self):
        # Policy requirements are derived from persisted scope, not optional consumer fields.
        scope=dict(self.scope,reference_reconstruction=True,human_motion=True,render='video')
        self.assertEqual(gate.requirements(scope),['layout','alignment','preview','technical','final_review'])
        self.assertEqual(gate.requirements(scope,'people'),['layout'])
        self.assertEqual(gate.requirements(scope,'render'),['layout','alignment','preview'])

    def test_diagnostic_validator_receipt_cannot_be_relabelled_by_candidate(self):
        self.complete();path=self.root/'technical-report.json';report=read(path)
        report['diagnostic_only']=True;write(path,report)
        gate.record_check(self.root,'room','task',self.revision,'technical',path)
        self.assertIn('CHECK_TECHNICAL',self.codes())

    def test_legacy_pipeline_cannot_promote_with_only_a_prose_review(self):
        run=self.root/'runs/room/old'
        write(run/'run.json',dict(scene='room',status='validated',visual_review=dict(status='reviewed',note='Looks good')))
        with self.assertRaisesRegex(ValueError,'SCOPE_REQUIRED'):registry.promote(self.root,run)

    def test_concurrent_evidence_mutation_between_check_and_select_is_rejected(self):
        self.complete();self.delivery();original=gate.evaluate
        def race(*args,**kwargs):
            result=original(*args,**kwargs)
            (self.root/'technical.json').write_text('concurrent writer')
            return result
        with patch.object(gate,'evaluate',side_effect=race):
            with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):registry.select(self.root,'room','v1')
        self.assertFalse((self.root/'deliveries/room/selected.json').exists())

    def test_review_findings_are_persisted_and_cannot_be_erased_by_new_report(self):
        path=self.report('final_review');report=read(path)
        finding=self.finding();finding.pop('origin');finding.pop('originating_revision')
        report['review'].update(verdict='rejected',findings=[finding]);write(path,report)
        gate.record_check(self.root,'room','task',self.revision,'final_review',path)
        self.report('final_review')
        self.assertIn('OPEN_FINDING',self.codes())

    def test_pipeline_job_metadata_cannot_make_pending_work_accepted(self):
        self.complete();manifest=dict(task_scope=str(self.out/'scope.json'))
        gate.record_job(manifest,self.root/'manifest.json','123','running')
        gate.record_job(manifest,self.root/'manifest.json','123','submitted')
        self.assertEqual(gate.evaluate(self.root,'room','task')['status'],'running')
        gate.record_job(manifest,self.root/'manifest.json','123','completed')
        self.assertTrue(gate.evaluate(self.root,'room','task')['permitted'])

    def test_cli_registration_check_findings_and_budget_are_real_commands(self):
        import contextlib,io
        from aha3d.workflow.acceptance_cli import main
        write(self.root/'candidate.json',self.spec)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['candidate','room','task',str(self.root/'candidate.json')],self.root),0)
            report=self.report('technical')
            self.assertEqual(main(['record-check','room','task',self.revision,'technical',str(report)],self.root),0)
            self.assertEqual(main(['check','room','task'],self.root),2)
            write(self.root/'finding.json',self.finding())
            self.assertEqual(main(['finding','room','task',str(self.root/'finding.json')],self.root),0)
            self.assertEqual(main(['state','room','task','active','--reason','Explicit repair resume','--repair-budget','1'],self.root),0)
        self.assertEqual(read(self.out/'state.json')['repair_budget'],1)


class ReferenceAcceptance(unittest.TestCase):
    def setUp(self):
        import test_layout_gate
        self.layout=test_layout_gate.LayoutGate();self.layout.setUp();self.addCleanup(self.layout.doCleanups)
        self.root=self.layout.root;self.layout.review()
        self.out=gate.folder(self.root,'room','layout')
        spec=self.layout.spec
        context=dict(room_scene=spec['source_scene'],final_scene=spec['source_scene'],cameras=spec['camera_cache'],configuration=spec['config'],source_video=spec['source_video'])
        inspection=self.layout.evidence/'inspection'
        images={k:str(inspection/(v+'.png')) for k,v in [('plan','top_model'),('front','front_model'),('side','side_model'),('early','source_000000_model'),('middle','source_000005_model'),('late','source_000010_model'),('source_early','source_000000_source'),('source_middle','source_000005_source'),('source_late','source_000010_source')]}
        write(self.root/'final-views.json',dict(images=images,input_binding={k:digest(v) for k,v in context.items()}))
        candidate=dict(context=context,artifacts=[dict(role='scene',path=spec['source_scene'])],purpose='delivery',completeness='complete',final_views='final-views.json',layout=dict(spec=spec,evidence_dir=str(self.layout.evidence)))
        self.revision=gate.register_candidate(self.root,'room','layout',candidate)['candidate_revision']
        data=gate.candidate(self.out,self.revision)
        for name in ('technical','final_review'):
            report=dict(policy=1,status='passed',candidate_revision=self.revision,validator=gate.capture(gate.__file__),evidence=[gate.capture(self.layout.evidence/'evidence.json')])
            if name=='technical':report['artifacts']=data['artifacts']
            else:report.update(images=images,review=visual_fixture(self.revision,images))
            path=self.root/(name+'.json');write(path,report);gate.record_check(self.root,'room','layout',self.revision,name,path)

    def test_current_reference_room_passes_and_real_layout_review_is_required(self):
        result=gate.evaluate(self.root,'room','layout');self.assertTrue(result['permitted'],result)
        (self.layout.evidence/'review.json').unlink()
        result=gate.evaluate(self.root,'room','layout');self.assertIn('CHECK_LAYOUT',{b['code'] for b in result['blockers']})

    def test_omitting_consumer_source_never_downgrades_reference_scope(self):
        from aha3d.workflow.layout_gate import validate_layout
        manifest=dict(task_scope=str(self.out/'scope.json'),layout_gate=dict(self.layout.spec,review_dir=str(self.layout.evidence)),render=dict(scene=self.layout.spec['source_scene'],camera_cache=self.layout.spec['camera_cache']))
        with self.assertRaisesRegex(ValueError,'source_video'):validate_layout(manifest,self.root/'consumer.json')

    def test_real_layout_camera_change_invalidates_acceptance(self):
        Path(self.layout.spec['cameras']).write_text('{}')
        result=gate.evaluate(self.root,'room','layout');self.assertFalse(result['permitted'])
        self.assertIn('CHECK_LAYOUT',{b['code'] for b in result['blockers']})

    def test_layout_request_cli_supplies_every_actual_image(self):
        import contextlib,io
        from aha3d.workflow.acceptance_cli import main
        write(self.root/'layout-spec.json',self.layout.spec)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['layout-request',str(self.root/'layout-spec.json'),str(self.layout.evidence),'--out',str(self.root/'request.json')],self.root),0)
        request=read(self.root/'request.json')
        self.assertEqual(sum(not key.startswith('object:') for key in request['images']),27)
        self.assertEqual(set(request['object_views']), {'bed', 'headwall'})
        self.assertTrue(all(set(views) <= set(request['images']) for views in request['object_views'].values()))
        self.assertTrue(all(Path(p).is_file() for p in request['images'].values()))

if __name__=='__main__':unittest.main()
