"""Immutable run preparation, stage execution, verified reuse and local background batches."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid

from aha3d import runtime as host
from aha3d.config import identifier, load_recipe, load_runtime, path
from aha3d.io import digest, files, intact, inventory, lock, now, read, signature, write
from aha3d.provenance import git_identity


def runtime_identity(runtime):
    result = {}
    for key in ('python', 'blender', 'skin_blender'):
        p = Path(runtime[key]); stat = p.stat()
        result[key] = {'path': str(p), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    result['environment_script'] = digest(runtime['env_script'])
    local_environment = Path(runtime['env_script']).with_name('env.local.sh')
    if local_environment.is_file():
        result['local_environment_script'] = digest(local_environment)
    upstream = Path(runtime['upstream'])
    result['upstream_python'] = signature({str(p.relative_to(upstream)): digest(p)
        for p in sorted((upstream / 'kimodo').rglob('*.py'))})
    result['skeleton_assets'] = {str(p.relative_to(upstream)): digest(p)
        for p in sorted((upstream / 'kimodo/assets/skeletons/smplx22').glob('*.npy'))}
    result['checkpoint'] = runtime['checkpoint']
    freeze = Path(runtime['env_script']).parent / 'environment.freeze.txt'
    result['environment_freeze'] = digest(freeze) if freeze.exists() else None
    return result


def prepare(root, scene, recipe_name, run_id=None, reuse=None, preview=False, motion_only=False):
    root = Path(root).resolve()
    from aha3d.workflow.submission_preflight import check
    preflight = check(root, scene, recipe_name, motion_only)
    recipe = load_recipe(root, scene, recipe_name)
    stages(recipe, motion_only)  # Reject unsupported scope before creating outputs.
    registered_reference = read(root / 'scenes' / scene / 'scene.json').get('reference')
    if not motion_only and registered_reference and not recipe.get('layout_inspection'):
        raise ValueError('Reference reconstruction requires layout_inspection inputs and agent review before assembly')
    layout = None if motion_only else recipe.get('layout_inspection')
    if layout:
        layout = dict(layout)
        layout.setdefault('source_scene', recipe['source'])
        if path(root, layout['source_scene']) != path(root, recipe['source']):
            raise ValueError('Layout source_scene must be the exact recipe source room')
        layout.setdefault('source_video', registered_reference)
        if not layout.get('source_video'):
            raise ValueError('Layout inspection requires the source video')
        if registered_reference and path(root, layout['source_video']) != path(root, registered_reference):
            raise ValueError('Layout source video differs from registered scene reference')
    if preview:
        scale = min(1., 640 / recipe['render']['width'], 360 / recipe['render']['height'])
        recipe['render'].update(width=max(2, int(recipe['render']['width'] * scale) // 2 * 2),
                                height=max(2, int(recipe['render']['height'] * scale) // 2 * 2), samples=8)
    runtime = load_runtime(root, recipe['runtime'])
    reference = None if motion_only or recipe['render']['kind'] != 'video' else read(root / 'scenes' / scene / 'scene.json').get('reference')
    reference_input = None
    if reference:
        refpath = path(root, reference)
        if not refpath.is_file():
            raise ValueError(f'Missing registered source reference: {refpath}')
        reference_input = {'source': str(refpath), 'sha256': digest(refpath)}
    inputs = {} if motion_only else {'source.blend': path(root, recipe['source'])}
    for field, filename in [('cache', 'body_cache.npz'), ('native', 'native_motion.npz'), ('constraints', 'constraints.json')]:
        if recipe['body'].get(field):
            inputs[filename] = path(root, recipe['body'][field])
    layout_names = {'source_scene': 'source.blend', 'reference': 'reference.npz',
        'cameras': 'cameras.json', 'inputs': 'inputs.npz', 'config': 'layout_config.json',
        'camera_cache': 'layout_camera.npz', 'source_video': 'layout_source_video.mp4',
        'scale_provenance': 'scale_provenance.json'}
    if layout:
        for field, filename in layout_names.items():
            if layout.get(field): inputs[filename] = path(root, layout[field])
        inputs['manifest.json'] = path(root, layout['reference']).with_name('manifest.json')
        inputs['inputs.json'] = path(root, layout['inputs']).with_name('inputs.json')
    for p in inputs.values():
        if not p.is_file():
            raise ValueError(f'Missing input: {p}')
    run_id = identifier(run_id or time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    run = root / 'runs' / scene / run_id
    run.parent.mkdir(parents=True, exist_ok=True)
    run.mkdir()  # Exclusive creation; a reused ID never overwrites another run.
    try:
        snapshot = run / 'snapshot'
        source_control = git_identity(root)
        code_before = inventory(root / 'src')
        shutil.copytree(root / 'src', snapshot / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if inventory(snapshot / 'src') != code_before or inventory(root / 'src') != code_before:
            raise ValueError('Shared code changed during snapshot; retry preparation')
        if layout:
            tools_before = inventory(root / 'tools/layout_inspection')
            shutil.copytree(root / 'tools/layout_inspection', snapshot / 'tools/layout_inspection',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            if inventory(snapshot / 'tools/layout_inspection') != tools_before or inventory(root / 'tools/layout_inspection') != tools_before:
                raise ValueError('Layout inspection tools changed during snapshot')
        write(snapshot / 'recipe.json', recipe)
        write(snapshot / 'runtime.json', runtime)
        (run / 'inputs').mkdir()
        source_hashes = {}
        for filename, source in inputs.items():
            before = digest(source)
            shutil.copy2(source, run / 'inputs' / filename)
            if digest(run / 'inputs' / filename) != before or digest(source) != before:
                raise ValueError(f'Input changed during snapshot: {source}')
            source_hashes[filename] = {'source': str(source), 'sha256': before}
        workflow_policy={'acceptance_policy':1,'scope':'motion_only' if motion_only else 'scene','diagnostic_only':bool(preview or motion_only)}
        scope_path = root / 'scenes' / scene / 'task_scope.json'
        if scope_path.exists():
            from aha3d.workflow.acceptance import consumer_scope
            ref = read(scope_path)
            _, _, scope_dir = consumer_scope(ref, scope_path)
            workflow_policy['task_scope'] = str(scope_dir / 'scope.json')

        if not motion_only and recipe['render']['kind']=='video':workflow_policy['preview_policy']='full_clip_v1'
        write(snapshot/'workflow_policy.json',workflow_policy)
        manifest = {'schema_version': 1, 'project_root': str(root), 'run_id': run_id,
            'scene': scene, 'recipe_id': recipe_name, 'created_at': now(), 'updated_at': now(),
            'status': 'prepared', 'scope': 'motion_only' if motion_only else 'scene',
            'inputs': source_hashes, 'snapshot': inventory(snapshot),
            'code_signature': signature(inventory(snapshot / 'src')), 'source_control': source_control,
            'runtime_identity': runtime_identity(runtime), 'stages': {},
            'reuse_run': str(Path(reuse).resolve()) if reuse else None,
            'visual_review': {'status': 'pending'}, 'jobs': [], 'submission_preflight': preflight, 'reference_input': reference_input}
        manifest.update(workflow_policy)
        if layout:
            spec = {field: str(run / 'inputs' / filename) for field, filename in layout_names.items() if layout.get(field)}
            if 'required_object_ids' in layout:
                spec['required_object_ids'] = layout['required_object_ids']
            spec['pipeline_context'] = {'assembly': recipe['assembly'], 'timing': recipe['timing'],
                'render': recipe['render'], 'inspection_tools': inventory(snapshot / 'tools/layout_inspection')}
            manifest['layout_inspection'] = {'spec': spec, 'evidence_dir': str(run / 'layout_evidence'),
                'reuse_evidence': str(path(root, layout['review_dir'])) if layout.get('review_dir') else None,
                'status': 'pending', 'diagnostic_only_until_reviewed': True}
        if not motion_only and recipe['render']['kind'] == 'video':
            manifest['preview_policy'] = 'full_clip_v1'
        write(run / 'run.json', manifest)
        return run
    except Exception as exc:
        write(run / 'preparation_error.json', {'at': now(), 'error': str(exc)})
        raise


def load(run):
    run = Path(run).resolve()
    manifest = read(run / 'run.json')
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported run schema')
    if inventory(run / 'snapshot') != manifest['snapshot']:
        raise ValueError('Run snapshot changed; create a new run from the updated code/recipe')
    if set(p.name for p in (run / 'inputs').iterdir()) != set(manifest['inputs']):
        raise ValueError('Frozen run input inventory changed')
    for filename, info in manifest['inputs'].items():
        if not (run / 'inputs' / filename).is_file() or digest(run / 'inputs' / filename) != info['sha256']:
            raise ValueError(f'Frozen run input changed: {filename}')
    policy_path=run/'snapshot/workflow_policy.json'
    if policy_path.exists():
        frozen_policy=read(policy_path)
        if any(manifest.get(k)!=v for k,v in frozen_policy.items()):
            raise ValueError('Persisted workflow policy was removed or changed in run manifest')
    recipe = read(run / 'snapshot/recipe.json')
    if recipe.get('layout_inspection') and manifest.get('scope') != 'motion_only':
        info = manifest.get('layout_inspection')
        if not info:
            raise ValueError('Frozen layout policy is missing from the run manifest')
        names = {'source_scene': 'source.blend', 'reference': 'reference.npz', 'cameras': 'cameras.json',
                 'inputs': 'inputs.npz', 'config': 'layout_config.json', 'camera_cache': 'layout_camera.npz',
                 'source_video': 'layout_source_video.mp4', 'scale_provenance': 'scale_provenance.json'}
        expected = {field: str(run / 'inputs' / filename) for field, filename in names.items() if filename in manifest['inputs']}
        if 'required_object_ids' in recipe['layout_inspection']:
            expected['required_object_ids'] = recipe['layout_inspection']['required_object_ids']
        expected['pipeline_context'] = {'assembly': recipe['assembly'], 'timing': recipe['timing'],
            'render': recipe['render'], 'inspection_tools': inventory(run / 'snapshot/tools/layout_inspection')}
        if info.get('spec') != expected:
            raise ValueError('Layout evidence inputs differ from the immutable recipe/input snapshot')
    return manifest, recipe, read(run / 'snapshot/runtime.json')


def stages(recipe, motion_only=False):
    mode = recipe['body']['mode']
    if motion_only:
        if mode not in ('generate', 'native'):
            raise ValueError('motion-only requires generate or native body mode')
        return (['motion'] if mode == 'generate' else []) + ['resample', 'skin']
    return (['layout_inspection'] if recipe.get('layout_inspection') else []) + (['motion'] if mode == 'generate' else []) + (['resample', 'skin'] if mode in ('generate', 'native') else []) + ['assemble', 'verify', 'render'] + (['video'] if recipe['render']['kind'] == 'video' else [])


def artifact(run, recipe, kind):
    if kind in ('video', 'scene'):
        return run / {'video': 'stages/video/video.mp4', 'scene': 'stages/assemble/scene.blend'}[kind]
    if kind == 'native':
        return run / ('stages/motion/motion.npz' if recipe['body']['mode'] == 'generate' else 'inputs/native_motion.npz')
    if kind == 'body':
        return run / ('stages/skin/body.npz' if recipe['body']['mode'] in ('generate', 'native') else 'inputs/body_cache.npz')
    raise ValueError(kind)


def completed_artifact(run, kind):
    """Resolve a recorded final artifact, checking just its stage and recipe.

    This does not assert visual review or validate other stages/ensemble members.
    It allows comparison-only recovery without hashing/copying a room or rerendering.
    """
    if kind not in ('video', 'scene'):
        raise ValueError('Expected final video or scene artifact')
    run = Path(run).resolve()
    if (run / '.execute.lock').exists():
        raise ValueError('Run has an execution lock; wait for its writer or documented recovery')
    manifest = read(run / 'run.json')
    recipe_path = run / 'snapshot/recipe.json'
    if manifest.get('schema_version') != 1 or digest(recipe_path) != manifest.get('snapshot', {}).get('recipe.json'):
        raise ValueError('Run recipe differs from its snapshot record')
    recipe = read(recipe_path)
    output = artifact(run, recipe, kind)
    stage = 'video' if kind == 'video' else 'assemble'
    entry = manifest.get('stages', {}).get(stage, {})
    checksum = entry.get('outputs', {}).get(output.name)
    if entry.get('status') != 'completed' or not checksum or not output.is_file() or digest(output) != checksum:
        raise ValueError(f'Completed {kind} artifact is missing, changed or unrecorded: {output}')
    return output, recipe


def fingerprint(run, manifest, recipe, stage):
    body = recipe['body']
    common = {'code': manifest['code_signature'], 'runtime': manifest['runtime_identity'], 'stage': stage}
    if stage == 'motion':
        common['config'] = {k: body.get(k) for k in ['prompt', 'durations', 'model', 'seed', 'transition_frames', 'diffusion_steps']}
        common['constraints'] = manifest['inputs'].get('constraints.json', {}).get('sha256')
    elif stage == 'resample':
        common.update(native=digest(artifact(run, recipe, 'native')), timing=recipe['timing'],
                      smoothing=body.get('smoothing'), max_root_step=body.get('max_root_step'), source_fps=body.get('source_fps', 30))
    elif stage == 'skin':
        common['motion'] = digest(run / 'stages/resample/motion.npz')
    elif stage == 'assemble':
        common.update(source=manifest['inputs']['source.blend']['sha256'], timing=recipe['timing'],
                      render=recipe['render'], assembly=recipe['assembly'], validation=recipe['validation'],
                      placement={k: body.get(k) for k in ['mode', 'offset', 'yaw', 'ground_clearance', 'object_name', 'cache_timing', 'anchor']})
        body_path = artifact(run, recipe, 'body')
        common['body'] = digest(body_path) if body_path.exists() else None
    elif stage in ('verify', 'render'):
        common.update(assembled=manifest['stages']['assemble']['outputs'], render=recipe['render'])
    elif stage == 'video':
        common.update(rendered=manifest['stages']['render']['outputs'], timing=recipe['timing'], render=recipe['render'])
    return signature(common)


def command(run, recipe, runtime, stage, frame_budget=None):
    package = run / 'snapshot/src/aha3d'
    out = run / 'stages' / stage
    python = runtime['python']
    if stage == 'motion':
        body = recipe['body']
        args = [python, '-m', 'kimodo.scripts.generate', body['prompt'], '--model', body.get('model', 'Kimodo-SMPLX-RP-v1'),
                '--duration', ' '.join(str(d) for d in body['durations']), '--seed', str(body.get('seed', 42)),
                '--num_transition_frames', str(body.get('transition_frames', 5)),
                '--diffusion_steps', str(body.get('diffusion_steps', 100)), '--output', str(out / 'motion')]
        if (run / 'inputs/constraints.json').exists():
            args += ['--constraints', str(run / 'inputs/constraints.json')]
        return args
    if stage == 'resample':
        return [python, '-m', 'aha3d.motion.prepare', '--motion', str(artifact(run, recipe, 'native')),
                '--out', str(out / 'motion.npz'), '--fps', recipe['timing']['fps'], '--frames', str(recipe['timing']['frames']),
                '--source-fps', str(recipe['body'].get('source_fps', 30)), '--recipe', str(run / 'snapshot/recipe.json')]
    if stage == 'video':
        return [python, '-m', 'aha3d.video', str(run)]
    base = [runtime['skin_blender' if stage == 'skin' else 'blender'], '-b', '-t', str(host.threads(runtime)), '--python-exit-code', '1']
    if stage == 'skin':
        return base + ['--python', str(package / 'blender/skin.py'), '--', '--motion', str(run / 'stages/resample/motion.npz'), '--out', str(out / 'body.npz')]
    source = run / ('inputs/source.blend' if stage == 'assemble' else 'stages/assemble/scene.blend')
    args = base + [str(source), '--python', str(package / 'blender/stage.py'), '--', '--run', str(run), '--stage', stage]
    if frame_budget and stage == 'render':
        args += ['--frame-budget', str(frame_budget)]
    return args


def ensure_layout(run, manifest, runtime):
    """Generate diagnostic evidence and pause for explicit agent review; never auto-pass."""
    from aha3d.workflow.layout_gate import prepare as prepare_layout, require_current
    info = manifest['layout_inspection']; spec = info['spec']
    candidate = info.get('selected_evidence') or info.get('reuse_evidence') or info['evidence_dir']
    evidence = Path(candidate)
    if evidence.exists():
        try:
            require_current(spec, evidence)
        except (ValueError, OSError) as exc:
            info.update(status='review_required', review_error=str(exc), selected_evidence=str(evidence))
            # A stale external review cannot authorize this model. Generate fresh local evidence.
            if evidence != Path(info['evidence_dir']):
                evidence = Path(info['evidence_dir'])
            else:
                return False
        else:
            info.update(status='reviewed', selected_evidence=str(evidence))
            return True
    if not evidence.exists():
        script = run / 'snapshot/tools/layout_inspection/render_blender.py'
        def render(spec, output):
            log = run / 'logs/layout_inspection.log'; log.parent.mkdir(exist_ok=True)
            cmd = [runtime['blender'], '-b', spec['source_scene'], '-t', str(host.threads(runtime)),
                   '--python-exit-code', '1', '--python', str(script), '--']
            for field in ('reference', 'cameras', 'inputs', 'config'):
                cmd += ['--' + field, str(spec[field])]
            cmd += ['--out', str(output)]
            with log.open('w') as stream:
                subprocess.run(cmd, cwd=run, stdout=stream, stderr=subprocess.STDOUT, check=True)
            return output
        from aha3d.workflow.object_review import generate
        def objects(spec, output):
            generate(spec, output, blender=runtime['blender'], python=os.environ.get('PI3X_MESH_PY') or runtime['python'],
                     tools_root=script.parent, threads=host.threads(runtime))
        prepare_layout(spec, evidence, runner=render, object_runner=objects)
    info.update(status='review_required', selected_evidence=str(evidence))
    return False


def review_layout(run, reviewer, notes, verdict, expected_views, visual_review=None):
    from aha3d.workflow.layout_gate import record_review
    run = Path(run).resolve()
    with lock(run / '.execute.lock'):
        manifest, _, _ = load(run)
        info = manifest.get('layout_inspection')
        if not info or not info.get('selected_evidence'):
            raise ValueError('Generate layout evidence before recording actual agent review')
        result = record_review(info['spec'], Path(info['selected_evidence']), reviewer=reviewer,
                               notes=notes, verdict=verdict, expected_views=expected_views, visual_review=visual_review)
        if visual_review and visual_review.get('findings') and manifest.get('task_scope'):
            from aha3d.workflow.acceptance import consumer_scope, add_finding
            scope,state,out=consumer_scope(manifest,run/'run.json')
            for finding in visual_review['findings']:
                add_finding(out.parents[3],scope['scene'],scope['task'],dict(finding,origin='reviewer',originating_revision=state['candidate']))
        info['status'] = 'review_recorded'; manifest['updated_at'] = now()
        write(run / 'run.json', manifest)
        return result


def execute(run, until=None, frame_budget=None):
    run = Path(run).resolve()
    with lock(run / '.execute.lock'):
        manifest, recipe, runtime = load(run)
        if runtime_identity(runtime) != manifest['runtime_identity']:
            raise ValueError('Installed runtime/code identity changed since preparation; prepare a new run')
        motion_only = manifest.get('scope') == 'motion_only'
        if not motion_only and manifest.get('reference_input') and not manifest.get('layout_inspection'):
            raise ValueError('Reference run lacks layout evidence policy; prepare a new reviewed run')
        selected = stages(recipe, motion_only)
        if until is not None and until not in selected:
            raise ValueError(f'Unknown stop stage; choose one of {selected}')
        env = os.environ.copy()
        env['PYTHONPATH'] = str(run / 'snapshot/src') + os.pathsep + str(runtime['upstream'])
        env['PYTHONUNBUFFERED'] = '1'
        env['TMPDIR'] = str(run / 'tmp'); (run / 'tmp').mkdir(exist_ok=True)
        env.setdefault('CUDA_VISIBLE_DEVICES', str(runtime.get('gpu', 0)))
        job_id = host.run_id()
        manifest.update(status='running', updated_at=now(), active_job=job_id)
        write(run / 'run.json', manifest)
        from aha3d.workflow.acceptance import record_job
        record_job(manifest,run/'run.json',job_id,'running')
        stage = None
        try:
            for stage in selected:
                if stage == 'layout_inspection':
                    ready = ensure_layout(run, manifest, runtime)
                    manifest['updated_at'] = now()
                    if not ready:
                        manifest['status'] = 'awaiting_review'
                        write(run / 'run.json', manifest)
                        record_job(manifest,run/'run.json',job_id,'completed')
                        return manifest
                    write(run / 'run.json', manifest)
                    if until == stage:
                        manifest['status'] = 'staged'; write(run / 'run.json', manifest); record_job(manifest,run/'run.json',job_id,'completed'); return manifest
                    continue
                if stage in ('assemble', 'render') and manifest.get('acceptance_policy'):
                    from aha3d.workflow.acceptance import consumer_prerequisite
                    prerequisite = 'people' if stage == 'assemble' else 'render'
                    try:
                        consumer_prerequisite(manifest, run/'run.json', prerequisite)
                    except (ValueError, OSError) as exc:
                        manifest.update(status='blocked', accepted=False, blockers=[str(exc)], updated_at=now())
                        write(run/'run.json',manifest); record_job(manifest,run/'run.json',job_id,'completed'); return manifest
                if stage in ('assemble', 'render') and manifest.get('layout_inspection'):
                    from aha3d.workflow.layout_gate import require_current
                    layout = manifest['layout_inspection']
                    require_current(layout['spec'], Path(layout['selected_evidence']))
                if stage == 'render' and manifest.get('preview_policy') == 'full_clip_v1':
                    from aha3d.workflow.preview_gate import applicable
                    if not applicable(run, manifest):
                        manifest.update(status='awaiting_review', updated_at=now())
                        write(run / 'run.json', manifest)
                        record_job(manifest,run/'run.json',job_id,'completed')
                        return manifest
                expected = fingerprint(run, manifest, recipe, stage)
                entry = manifest['stages'].get(stage, {})
                out = run / 'stages' / stage
                if entry.get('status') == 'completed' and entry.get('fingerprint') == expected and intact(out, entry.get('outputs', {})):
                    print('STAGE_REUSED', stage, flush=True)
                else:
                    if out.exists() and entry.get('fingerprint') != expected:
                        archive = run / 'superseded' / f'{stage}-{uuid.uuid4().hex[:8]}'
                        archive.parent.mkdir(exist_ok=True)
                        out.rename(archive)
                    out.mkdir(parents=True, exist_ok=True)
                    reused = False
                    if manifest.get('reuse_run') and stage in ('motion', 'resample', 'skin'):
                        source = Path(manifest['reuse_run'])
                        if not (source / '.execute.lock').exists():
                            old = read(source / 'run.json')['stages'].get(stage, {})
                            if old.get('status') == 'completed' and old.get('fingerprint') == expected and intact(source / 'stages' / stage, old.get('outputs', {})):
                                shutil.copytree(source / 'stages' / stage, out, dirs_exist_ok=True)
                                reused = True
                    if not reused and stage in ('motion', 'assemble', 'render'):
                        from aha3d.workflow.submission_preflight import device_check
                        device_check('gpu', stage)
                    attempt = entry.get('attempts', 0) + 1
                    log = run / 'logs' / f'{stage}-{attempt:03d}.log'; log.parent.mkdir(exist_ok=True)
                    entry = {'status': 'running', 'fingerprint': expected, 'started_at': now(), 'attempts': attempt, 'log': str(log.relative_to(run))}
                    manifest['stages'][stage] = entry
                    write(run / 'run.json', manifest)
                    started = time.monotonic()
                    print('STAGE_START', stage, flush=True)
                    if not reused:
                        with log.open('w') as stream:
                            completed = subprocess.run(command(run, recipe, runtime, stage, frame_budget), cwd=run,
                                env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
                        if completed.returncode != 0:
                            entry.update(status='interrupted' if completed.returncode == 75 else 'failed', exit_code=completed.returncode)
                            raise RuntimeError(f'{stage} exited {completed.returncode}; see {log}')
                    entry.update(status='completed', completed_at=now(), seconds=time.monotonic() - started,
                                 outputs=inventory(out), reused_from=manifest.get('reuse_run') if reused else None)
                    if not entry['outputs']:
                        raise RuntimeError(f'{stage} produced no recorded artifacts')
                    manifest['updated_at'] = now()
                    write(run / 'run.json', manifest)
                if stage == until:
                    manifest['status'] = 'staged' if motion_only or stage != selected[-1] else 'validated'
                    break
            else:
                manifest['status'] = 'staged' if motion_only else 'validated'
            manifest['accepted'] = False
            manifest['completion_status'] = 'awaiting_review'
            manifest['updated_at'] = now(); write(run / 'run.json', manifest)
            record_job(manifest,run/'run.json',job_id,'completed')
            return manifest
        except BaseException as exc:
            manifest.update(status='interrupted' if manifest['stages'].get(stage, {}).get('status') == 'interrupted' else 'failed', updated_at=now(), error=str(exc))
            write(run / 'run.json', manifest)
            record_job(manifest,run/'run.json',job_id,'failed')
            raise


def start_batch(batch, settings, commands, preamble=()):
    """Run batch tasks one after another in a detached local worker; one GPU, so never in parallel.

    Task i exports INDOOR_RUN_ID=<batch>_<i>, logs to <batch>/<i>.log and records <i>.log.exit.
    """
    job = batch.name
    logs = [batch / f'{i}.log' for i in range(len(commands))]
    tasks = [f'export INDOOR_RUN_ID={shlex.quote(f"{job}_{i}")}; {command}' for i, command in enumerate(commands)]
    script = batch / 'job.sh'; script.write_text(host.sequential_script(tasks, logs, settings['env_script'], preamble))
    return job, host.start_background(script, batch / 'batch.log')


def submit(run_paths, until=None, frame_budget=None):
    runs = [Path(p).resolve() for p in run_paths]
    if not runs or len(set(runs)) != len(runs):
        raise ValueError('A batch needs distinct prepared runs')
    # Submission only reads small metadata. Full hashes are checked by execute in the worker.
    loaded = [(read(p / 'run.json'), read(p / 'snapshot/recipe.json'), read(p / 'snapshot/runtime.json')) for p in runs]
    settings = loaded[0][2]
    if any(value[2] != settings for value in loaded):
        raise ValueError('Batch runs must use identical runtime profiles')
    batch = Path(loaded[0][0]['project_root']) / 'runs/batches' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    write(batch / 'runs.json', [str(p) for p in runs])
    commands = []
    for run in runs:
        args = [settings['python'], '-m', 'aha3d', 'execute', str(run)]
        if until:
            args += ['--until', until]
        if frame_budget:
            args += ['--frame-budget', str(frame_budget)]
        commands.append('export PYTHONPATH=' + shlex.quote(str(run / 'snapshot/src')) + '; ' + shlex.join(args))
    job, pid = start_batch(batch, settings, commands)
    write(batch / 'submission.json', {'job_id': job, 'pid': pid, 'submitted_at': now(), 'runs': [str(p) for p in runs]})
    for i, run in enumerate(runs):
        # Submission metadata is separate so a fast-starting worker cannot race a run.json update.
        from aha3d.workflow.acceptance import record_job
        record_job(loaded[i][0],run/'run.json',f'{job}_{i}','submitted')
        write(run / f'submission-{job}.json', {'job_id': f'{job}_{i}', 'batch': str(batch), 'submitted_at': now()})
    return {'status':'submitted', 'accepted':False, 'job_id': job, 'pid': pid, 'batch': str(batch), 'runs': [str(p) for p in runs]}


def submit_recipes(root, pairs, preview=False, run_id=None, reuse=None, motion_only=False):
    """Queue small requests; the worker snapshots large inputs when its task starts."""
    if not pairs:
        raise ValueError('Choose recipes')
    root = Path(root).resolve()
    requests = []
    for scene, name in pairs:
        from aha3d.workflow.submission_preflight import check
        check(root, scene, name, motion_only)
        recipe = load_recipe(root, scene, name)
        stages(recipe, motion_only)
        runtime = load_runtime(root, recipe['runtime'])
        requests.append(dict(root=str(root), scene=scene, recipe=name,
            run_id=identifier(run_id or time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]),
            preview=preview, motion_only=motion_only, reuse=str(Path(reuse).resolve()) if reuse else None,
            expected_recipe=recipe, expected_runtime=runtime))
        scope_pointer=root/'scenes'/scene/'task_scope.json'
        if scope_pointer.exists():
            from aha3d.workflow.acceptance import consumer_scope
            _,_,scope_dir=consumer_scope(read(scope_pointer),scope_pointer)
            requests[-1]['task_scope']=str(scope_dir/'scope.json')
    settings = requests[0]['expected_runtime']
    if any(r['expected_runtime'] != settings for r in requests):
        raise ValueError('Batch recipes must use identical runtime profiles')
    batch = root / 'runs/batches' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    runs, commands = [], []
    for i, request in enumerate(requests):
        target = batch / f'request-{i}.json'; write(target, request)
        runs.append(str(root / 'runs' / request['scene'] / request['run_id']))
        commands.append(shlex.join([settings['python'], '-m', 'aha3d', 'launch', str(target)]))
    job, pid = start_batch(batch, settings, commands, ['export PYTHONPATH=' + shlex.quote(str(root / 'src'))])
    from aha3d.workflow.acceptance import record_job
    for i,request in enumerate(requests):record_job(request,batch/f'request-{i}.json',f'{job}_{i}','submitted')
    result = {'status':'submitted','accepted':False,'job_id': job, 'pid': pid, 'batch': str(batch), 'runs': runs, 'submitted_at': now()}
    write(batch / 'submission.json', result)
    return result


def launch(request_path):
    request_path = Path(request_path).resolve()
    request = read(request_path); root = Path(request['root'])
    recipe = load_recipe(root, request['scene'], request['recipe'])
    if recipe != request['expected_recipe'] or load_runtime(root, recipe['runtime']) != request['expected_runtime']:
        raise ValueError('Recipe/runtime changed while queued; submit a new request')
    run = prepare(root, request['scene'], request['recipe'], request['run_id'], request['reuse'], request['preview'], request.get('motion_only', False))
    job = host.run_id()
    write(run / f'submission-{job}.json', {'job_id': job, 'batch': str(request_path.parent), 'submitted_at': now()})
    # Re-enter through the frozen code before any stage executes.
    env = os.environ.copy(); env['PYTHONPATH'] = str(run / 'snapshot/src')
    subprocess.run([request['expected_runtime']['python'], '-m', 'aha3d', 'execute', str(run)],
                   env=env, check=True)
    return {'run': str(run), 'status': read(run / 'run.json')['status']}
