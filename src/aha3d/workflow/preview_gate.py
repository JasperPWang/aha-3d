"""Full-duration preview and agent technical acceptance bound to frozen inputs."""
from fractions import Fraction
import os
import math
from pathlib import Path
import subprocess
import uuid

from aha3d import runtime as host
from aha3d.io import digest, intact, inventory, lock, now, read, signature, write


def binding(run, manifest):
    """Bind actual scene bytes and all recipe/runtime/code/input snapshot identities."""
    for stage in ('assemble', 'verify'):
        entry = manifest['stages'].get(stage, {})
        if entry.get('status') != 'completed' or not intact(run / 'stages' / stage, entry.get('outputs', {})):
            raise ValueError(f'Preview requires intact completed {stage}')
    return signature(dict(snapshot=manifest['snapshot'], inputs=manifest['inputs'], reference=manifest.get('reference_input'),
        assembled=manifest['stages']['assemble']['outputs'], verified=manifest['stages']['verify']['outputs']))


def applicable(run, manifest):
    gate = manifest.get('preview_acceptance')
    if not gate or gate.get('status') != 'accepted' or gate.get('implementation_sha256') != digest(__file__):
        return False
    if gate['binding'] != binding(run, manifest):
        return False
    return all(Path(p).is_file() and digest(p) == h for p, h in gate['evidence_hashes'].items())


def render(run, backend='gpu', max_width=320, source_frames=None, preview_fps='5'):
    if backend not in ('cpu', 'gpu') or type(max_width) is not int or max_width < 16:
        raise ValueError('Choose cpu/gpu and an integer width >=16')
    from aha3d.workflow.submission_preflight import device_check
    device_check(backend, 'preview')
    from aha3d.pipeline.runner import load, runtime_identity
    from aha3d.video import main as encode
    run = Path(run).resolve()
    with lock(run / '.execute.lock'):
        data, recipe, runtime = load(run)
        if runtime_identity(runtime) != data['runtime_identity']:
            raise ValueError('Installed runtime changed since preparation')
        if data.get('acceptance_policy'):
            from .acceptance import consumer_prerequisite
            consumer_prerequisite(data,run/'run.json','preview')
        if recipe['render']['kind'] != 'video':
            raise ValueError('Full-clip preview applies to video recipes')
        current = binding(run, data)
        # Integer divisor preserves the exact raster ratio and even H.264 dimensions.
        w, h = recipe['render']['width'], recipe['render']['height']
        divisors = [d for d in range(1, min(w,h)+1) if w % (2*d) == 0 and h % (2*d) == 0]
        divisor = next((d for d in divisors if w//d <= max_width), divisors[-1])
        from .preview_sampling import plan
        sampling = plan(recipe['timing'], preview_fps)
        script = run / 'snapshot/src/aha3d/blender/preview.py'
        if not script.exists():
            raise ValueError('This historical snapshot predates preview support; existing delivery remains valid')
        supports_sampling = 'sampling.json' in script.read_text()
        if sampling['temporally_sampled'] and not supports_sampling:
            raise ValueError('Frozen preview implementation predates sampling; prepare a new run or explicitly use --preview-fps source. Do not edit its snapshot.')
        reduced = dict(recipe, timing=sampling['preview_timing'] if supports_sampling else recipe['timing'],
                       render=dict(recipe['render'], width=w//divisor, height=h//divisor, samples=4))
        out = run / 'previews' / uuid.uuid4().hex[:12]; out.mkdir(parents=True)
        write(out / 'snapshot/recipe.json', reduced)
        if supports_sampling:
            write(out / 'sampling.json', sampling)
        env = os.environ.copy(); env['PYTHONPATH'] = str(run / 'snapshot/src')
        env.setdefault('CUDA_VISIBLE_DEVICES', str(runtime.get('gpu', 0)))
        source_reference = None
        if data.get('reference_input'):
            import imageio_ffmpeg
            source = Path(data['reference_input']['source'])
            if digest(source) != data['reference_input']['sha256']:
                raise ValueError('Registered source changed since preparation')
            reader = imageio_ffmpeg.read_frames(str(source)); metadata = next(reader); reader.close()
            t = recipe['timing']
            keyframes = sorted(set([t['start'], (t['start']+t['end'])//2, t['end']]))
            if source_frames is None:
                from aha3d.workflow.compare import validate_video
                try:
                    validate_video(source, recipe['timing'])
                except ValueError as exc:
                    raise ValueError('Source timing differs: supply explicit --source-frames for output keyframes') from exc
                source_frames = [f-recipe['timing']['start'] for f in keyframes]
            if len(source_frames) != len(keyframes) or any(type(f) is not int or f < 0 for f in source_frames):
                raise ValueError('Supply one nonnegative source frame index per output keyframe')
            source_folder = out / 'source_keyframes'; source_folder.mkdir()
            mapping = []
            for frame, source_index in zip(keyframes, source_frames):
                target = source_folder / f'frame_{frame:06d}.png'
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-i', str(source),
                    '-vf', f"select='eq(n,{source_index})'", '-vsync', '0', '-frames:v', '1', '-threads', '1', str(target)], check=True)
                if not target.is_file():
                    raise ValueError('Source keyframe mapping exceeds available source video')
                mapping.append(dict(frame=frame, source_frame=source_index, image=str(target), sha256=digest(target)))
            source_reference = dict(data['reference_input'],
                original_size=list(metadata['size']), keyframes=mapping,
                mapping='Zero-based decoded source frame indices; default direct mapping only after matching full clip count/rate/duration. Explicit indices required otherwise; review cuts/retiming.')
        with (out / 'render.log').open('w') as log:
            subprocess.run([runtime['blender'], '-b', '-t', str(host.threads(runtime)),
                str(run / 'stages/assemble/scene.blend'), '--python-exit-code', '1', '--python', str(script),
                '--', '--run', str(run), '--out', str(out), '--backend', backend], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        encode(out)
        if binding(run, data) != current:
            raise ValueError('Inputs changed during preview')
        receipt = dict(status='validated', binding=current, directory=str(out), at=now(),
            artifacts=inventory(out), timing=reduced['timing'], source_timing=recipe['timing'],
            sampling=sampling if supports_sampling else None, source_reference=source_reference,
            implementation_sha256=digest(__file__))
        write(out / 'preview.json', receipt)
        data['preview'] = str(out / 'preview.json'); data.pop('preview_acceptance', None)
        write(run / 'run.json', data)
        return receipt


def accept(run, evidence):
    from aha3d.pipeline.runner import load
    import imageio_ffmpeg
    from PIL import Image
    run = Path(run).resolve(); evidence = Path(evidence).resolve()
    with lock(run / '.execute.lock'):
        data, recipe, _ = load(run)
        receipt_path = Path(data['preview']); receipt = read(receipt_path); out = receipt_path.parent
        current = binding(run, data)
        if receipt.get('status') != 'validated' or receipt['binding'] != current or not intact(out, receipt['artifacts']):
            raise ValueError('Preview is stale or changed; regenerate it')
        review = read(evidence)
        if not review.get('reviewer', '').strip() or not review.get('note', '').strip():
            raise ValueError('Record agent reviewer and concrete visual observations')
        from .preview_sampling import validate_review
        validate_review(review, receipt.get('sampling'))
        hashes = {str(evidence): digest(evidence), str(receipt_path): digest(receipt_path)}
        for relative, h in receipt['artifacts'].items():
            hashes[str(out / relative)] = h
        reference = data.get('reference_input')
        metadata = None
        if reference:
            source = Path(review.get('source_video', reference['source'])).resolve()
            if digest(source) != reference['sha256']:
                raise ValueError('Reviewed source video differs from frozen reference provenance')
            metadata = {'size': receipt['source_reference']['original_size']}
            hashes[str(source)] = reference['sha256']
        elif not review.get('no_reference_rationale', '').strip():
            raise ValueError('Text-authored scene requires explicit no-reference rationale')
        comparisons = review.get('source_comparisons' if reference else 'render_keyframes', [])
        required = set(read(out / 'render_report.json')['keyframes'])
        if not required <= {item['frame'] for item in comparisons}:
            raise ValueError('Review start/middle/end full-resolution keyframes; source comparisons required for reference scenes')
        for item in comparisons:
            if not item.get('note', '').strip():
                raise ValueError('Each comparison needs concrete proportion/framing observations')
            rendered = out / 'keyframes' / f"frame_{item['frame']:06d}.png"
            if reference:
                src = out / 'source_keyframes' / f"frame_{item['frame']:06d}.png"
                if item.get('source_image') and digest(Path(item['source_image']).resolve()) != digest(src):
                    raise ValueError('Source comparison image differs from receipt-extracted exact source frame')
                with Image.open(src) as im:
                    if im.size != tuple(metadata['size']):
                        raise ValueError('Source comparison must use original video raster, not a thumbnail')
                hashes[str(src)] = digest(src)
            with Image.open(rendered) as im:
                if im.size != (recipe['render']['width'], recipe['render']['height']):
                    raise ValueError('Comparison render must use final recipe resolution')
        actors = {p['id'] for p in read(out / 'render_report.json')['people']}
        reviews = review.get('people', [])
        if {p['id'] for p in reviews} != actors or any(not p.get('placement_contact_note', '').strip() for p in reviews):
            raise ValueError('Explicit placement/contact review required for every enumerated person_id')
        if actors:
            report = Path(review.get('people_report', out / 'people_report.json')).resolve(); checked = read(report)
            if checked.get('source_sha256') != digest(run / 'stages/assemble/scene.blend'):
                raise ValueError('All-person report must reference the actual assembled scene hash')
            if checked.get('status') != 'passed' or {int(i) for i in checked.get('people', {})} != actors:
                raise ValueError('Passed all-person report must enumerate exactly the preview person IDs')
            if any(p.get('sampled_frames') != list(range(recipe['timing']['start'], recipe['timing']['end']+1)) for p in checked['people'].values()):
                raise ValueError('All-person placement/contact report must sample the complete timeline')
            if not review.get('people_report_limitations', '').strip():
                raise ValueError('Describe report coverage and remaining contacts; singlebody verification is insufficient for an ensemble')
            hashes[str(report)] = digest(report)
        from .review_contract import validate
        images = {f'render:{frame}': str(out/'keyframes'/f'frame_{frame:06d}.png') for frame in sorted(required)}
        if reference:
            images.update({f'source:{frame}': str(out/'source_keyframes'/f'frame_{frame:06d}.png') for frame in sorted(required)})
        validate(review.get('visual_review', {}), current, images)
        if review['visual_review']['verdict'] != 'accepted':
            raise ValueError('Preview visual judgment rejected')
        gate = dict(status='accepted', implementation_sha256=digest(__file__), binding=current, evidence_hashes=hashes, reviewer=review['reviewer'], at=now())
        data['preview_acceptance'] = gate
        if data.get('status') != 'validated':
            data['status'] = 'preview_accepted'
        write(run / 'run.json', data)
        return gate
