"""Scene requirements and authoring plans, without compute or runtime discovery."""
import copy
from fractions import Fraction
import json
from pathlib import Path

from ..config import identifier, keys, positive_int
from ..io import write


PRESETS = {
    'whitebox': dict(appearance='whitebox', delivery='stills', camera='inspection',
                     people='none', cabinets='none', objects='none'),
    'materials': dict(appearance='materials', delivery='stills', camera='inspection',
                      people='none', cabinets='none', objects='none'),
    'whitebox_people': dict(appearance='whitebox', delivery='video', camera='inspection',
                            people='approximate', cabinets='none', objects='none'),
    'source_camera': dict(appearance='whitebox', delivery='video', camera='source_trajectory'),
}
CHOICES = {
    'appearance': ('whitebox', 'materials'),
    'delivery': ('stills', 'video'),
    'camera': ('inspection', 'source_trajectory', 'custom', 'existing'),
    'people': ('none', 'approximate', 'existing'),
    'cabinets': ('none', 'animate', 'existing'),
    'objects': ('none', 'animate', 'existing'),
    'reuse': ('reuse_allowed', 'independent'),
}
PROMPTS = {
    'appearance': 'Use whitebox appearance or furnished materials?',
    'delivery': 'Video delivery includes the editable scene and preview stills; use stills-only for an explicitly static request.',
    'camera': 'Use inspection cameras, the source video trajectory, a custom animated camera, or the existing scene camera?',
    'people': 'Include no people, approximately generated actions, or existing scene people?',
    'cabinets': 'Keep cabinets closed, author door/drawer motion, or preserve existing motion?',
    'objects': 'Keep objects static, author object motion, or preserve existing motion?',
}
DETAILS = {
    'people': 'Describe the people and approximate actions/paths, or which source actions to follow.',
    'cabinets': 'Describe which doors/drawers move and the intended action or source events.',
    'objects': 'Describe which objects move and the intended action or source events.',
    'camera': 'Describe the custom camera path or desired views and motion.',
}
FIELDS = ('schema_version', 'preset', 'scene', 'inputs', 'reuse', 'appearance',
          'delivery', 'camera', 'people', 'cabinets', 'objects', 'timing', 'variants', 'details', 'fidelity', 'interactive_demo')


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be nonempty text')


def _rational(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(name + ' must be a positive rational value')
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(name + ' must be finite and rational') from exc
    if result <= 0:
        raise ValueError(name + ' must be positive')
    return result


def apply_answers(request, answers):
    """Explicit new answers override earlier values; untouched context survives."""
    keys(request, FIELDS, 'scene request')
    keys(answers, FIELDS, 'answers')
    def merge(old, new):
        result = copy.deepcopy(old)
        for name, value in new.items():
            if isinstance(value, dict) and isinstance(result.get(name), dict):
                result[name] = merge(result[name], value)
            else:
                result[name] = copy.deepcopy(value)
        return result
    base = copy.deepcopy(request)
    patch = answers.get('timing')
    previous = base.get('timing')
    if isinstance(patch, dict) and isinstance(previous, dict):
        if 'mode' in patch and patch['mode'] != previous.get('mode'):
            # These are alternative timing sources, not cumulative settings.
            base['timing'] = {}
        elif 'duration_seconds' in patch and 'frames' not in patch:
            previous.pop('frames', None)
        elif 'frames' in patch and 'duration_seconds' not in patch:
            previous.pop('duration_seconds', None)
    return merge(base, answers)


def _validate(request):
    keys(request, FIELDS, 'scene request')
    if type(request.get('schema_version')) is not int or request['schema_version'] != 1:
        raise ValueError('scene request schema_version must be 1')
    if 'preset' in request and (not isinstance(request['preset'], str) or request['preset'] not in PRESETS):
        raise ValueError('Unsupported scene request preset')
    if 'scene' in request:
        identifier(request['scene'])
    for name, options in CHOICES.items():
        if name in request and request[name] not in options:
            raise ValueError('Unsupported ' + name + ': ' + repr(request[name]))
    inputs = request.get('inputs', {})
    keys(inputs, ('video', 'images', 'source_scene'), 'inputs')
    for name, value in inputs.items():
        if name == 'images':
            if not isinstance(value, list) or not value:
                raise ValueError('inputs.images must be a nonempty list')
            for item in value:
                _text(item, 'inputs.images item')
        else:
            _text(value, 'inputs.' + name)
    details = request.get('details', {})
    keys(details, ('appearance', 'people', 'cabinets', 'objects', 'camera'), 'details')
    for name, value in details.items():
        _text(value, 'details.' + name)
    if 'variants' in request:
        variants = request['variants']
        keys(variants, ('models', 'materials', 'notes'), 'variants')
        for name in ('models', 'materials'):
            if name in variants and type(variants[name]) is not bool:
                raise ValueError('variants.' + name + ' must be a boolean')
        if 'notes' in variants:
            _text(variants['notes'], 'variants.notes')
    if 'interactive_demo' in request and type(request['interactive_demo']) is not bool:
        raise ValueError('interactive_demo must be a boolean')
    if 'fidelity' in request:
        fidelity = request['fidelity']
        keys(fidelity, ('mode', 'targets'), 'fidelity')
        if 'mode' in fidelity and fidelity['mode'] not in ('approximate', 'major_objects', 'precise', 'selective'):
            raise ValueError('Unsupported fidelity.mode')
        if 'targets' in fidelity:
            if not isinstance(fidelity['targets'], list):
                raise ValueError('fidelity.targets must be a list')
            for target in fidelity['targets']:
                _text(target, 'fidelity.targets item')
    if 'timing' in request:
        value = request['timing']
        keys(value, ('mode', 'fps', 'frames', 'start', 'duration_seconds'), 'request timing')
        if value.get('mode') not in ('source', 'explicit'):
            raise ValueError('timing.mode must be source or explicit')
        if value['mode'] == 'source' and set(value) != {'mode'}:
            raise ValueError('Source timing must be resolved from media; do not supply guessed fps/frames')
        if 'fps' in value:
            rate = _rational(value['fps'], 'timing.fps')
            if rate > 1000:
                raise ValueError('timing.fps must be positive and at most 1000')
        if 'duration_seconds' in value:
            duration = _rational(value['duration_seconds'], 'timing.duration_seconds')
            if 'fps' in value:
                count = duration * rate
                if count.denominator != 1:
                    raise ValueError('Duration does not contain an exact number of output frames; choose frames explicitly')
                if 'frames' in value and count != value['frames']:
                    raise ValueError('duration_seconds must equal frames / fps exactly')
        for field in ('frames', 'start'):
            if field in value:
                positive_int(value[field], 'timing.' + field)


def _stages(request):
    stages = []
    def add(name, after, owner, tool, output, checks):
        stages.append(dict(id=name, depends_on=after, owner=owner, tool=tool,
                           output=output, checks=checks))
    video = bool(request['inputs'].get('video'))
    independent = request['reuse'] == 'independent'
    add('source', [], 'reference', 'pi3x-scene-reference' if video else 'blender-roomkit',
        'reference/', ['Inspect source identity, availability and requested content',
        'Infer a fresh source-based basis; exclude earlier scene-specific outputs' if independent else
        'Reuse compatible reviewed inputs; retain their provenance',
        'Resolve exact source timing before downstream animation; never assume 24 fps'])
    if video:
        add('reference', ['source'], 'reference', 'pi3x-scene-reference', 'reference/aligned/',
            ['Review floor, scale, dimensions and common geometry/camera transform'])
    basis = 'reference' if video else 'source'
    add('room', [basis], 'room', 'blender-roomkit', 'room/room.blend',
        ['Match major layout, proportions, support and circulation',
         'Use semantic roots and verified source orientation; declare facing targets',
         'Preserve embedded materials; whitebox is an output appearance',
         'Explicitly implement people/cabinet/object exclusions in any reused source'])
    ready = ['room']
    if request['camera'] in ('source_trajectory', 'custom'):
        add('camera', ['room', basis], 'camera', 'workflow.camera' if request['camera'] == 'source_trajectory' else 'blender-roomkit',
            'camera/camera.blend', ['Match requested timing and shot cuts',
            'Run CPU preflight and evaluated Blender camera checks before full rendering'])
        ready.append('camera')
    add('room_review', ready, 'review', 'blender-roomkit', 'review/room/',
        ['Inspect room renders against source; verify facing, scale, support and requested camera'])
    fidelity = request['fidelity']
    review = stages[-1]
    review['fidelity'] = copy.deepcopy(fidelity)
    review['checks'].append('Keep user-reported mismatches open until actual before/after source-view review supports closure')
    if fidelity['mode'] in ('major_objects', 'precise', 'selective'):
        review['checks'].append('Inspect each correction target in isolated matched X-ray/source and plan/side views before editing; correct only a recorded mismatch and compare before/after')
        if fidelity['mode'] == 'major_objects':
            review['checks'].append('Lock structure, scene-defining furniture and salient lamps; small surface decor may vary unless user-flagged')
        if fidelity['mode'] == 'selective':
            review['checks'].append('Apply precise correction to named targets and affected neighbors; retain basic review elsewhere')
    else:
        review['checks'].append('Compare representative source/whitebox views and correct obvious defects; detailed X-ray is optional')
    components = ['room_review']
    if request['people'] == 'approximate':
        add('people_plan', [basis], 'people', 'kimodo-body-motion',
            'people/plan/', ['Stable actor IDs and approximate actions; establish routes and required contacts',
            'For source-video people, review the root route; use sparse SAM 3D Body hand/foot guidance only when explicitly requested',
            'Resolve contact-sensitive replacement assets before final motion generation; do not change a contacted chair blindly'])
        add('people', ['people_plan', 'room_review'], 'people', 'kimodo-body-motion', 'people/<actor-id>/',
            ['Separate caches per actor; resample rotations before skinning',
             'Review every actor; these are approximate generated actions'])
        components.append('people')
    for kind in ('cabinets', 'objects'):
        if request[kind] == 'animate':
            add(kind, ['room_review'], kind, 'blender-roomkit', kind + '/motion.blend',
                ['Use separate component output; preserve stable identities and native controls',
                 'Check requested timing, evaluated transforms, clearance and contact'])
            components.append(kind)
    if any(request[kind] == 'existing' for kind in ('camera', 'people', 'cabinets', 'objects')):
        add('existing_motion', ['source', 'room_review'], 'review', 'blender-roomkit', 'review/existing_motion/',
            ['Verify saved-source camera, actors/actions and timing; preserve only the requested existing components'])
        components.append('existing_motion')
    add('integrate', components, 'integrator', 'workflow.people + blender-roomkit', 'integrated/scene.blend',
        ['One writer combines component copies; preserve all semantic/facing IDs',
         'Reopen and check every requested person, camera, cabinet and moving object',
         'If a separately applied asset variant changes contact/support geometry, revalidate affected motion before delivery'])
    add('delivery', ['integrate'], 'delivery', 'indoor pipeline', 'delivery/',
        ['Author a matching executable recipe; do not forward this request as a legacy recipe',
         'Deliver editable scene and representative preview stills alongside the requested video' if request['delivery'] == 'video' else 'Inspect representative actual renders',
         'Validate exact frames, cadence, duration and full video decoding' if request['delivery'] == 'video'
         else 'Deliver editable scene and useful inspection stills'])
    if request.get('interactive_demo'):
        add('interactive_demo', ['integrate'], 'delivery', 'blender-browser-demo', 'delivery/demo/',
            ['Export the requested integrated scene and verify browser controls and preserved animation'])
    return stages


def build_intake(request):
    """Validate partial context, ask missing questions, and route complete requests."""
    _validate(request)
    resolved = copy.deepcopy(request)
    defaults = {}
    seed = dict(PRESETS.get(request.get('preset'), {}))
    seed['reuse'] = 'reuse_allowed'
    if any(name in request for name in ('preset', 'appearance', 'camera', 'people', 'cabinets', 'objects')):
        seed.setdefault('delivery', 'video')
    seed['interactive_demo'] = False
    for name, value in seed.items():
        if name not in resolved:
            resolved[name] = value
            defaults[name] = value
    if 'timing' in resolved and 'fps' in resolved['timing']:
        resolved['timing']['fps'] = str(Fraction(str(resolved['timing']['fps'])))
        if 'duration_seconds' in resolved['timing']:
            resolved['timing']['frames'] = int(Fraction(str(resolved['timing'].pop('duration_seconds'))) *
                                              Fraction(resolved['timing']['fps']))
    questions = []
    def ask(field, prompt, options=None):
        item = dict(field=field, prompt=prompt)
        if options is not None:
            item['options'] = list(options)
        questions.append(item)
    if 'scene' not in resolved:
        ask('scene', 'Which scene should this task create or revise? Use its stable scene ID.')
    inputs = resolved.get('inputs', {})
    if not inputs:
        ask('inputs', 'Which source video, reference images or saved scene should be used?')
    # Offer one coarse choice before opening all individual output questions.
    if not any(field in request for field in ('preset', 'appearance', 'delivery', 'camera', 'people', 'cabinets', 'objects')):
        ask('preset', 'Choose a starting scope; detailed choices remain independently editable.', PRESETS)
    else:
        for name in PROMPTS:
            if name not in resolved:
                ask(name, PROMPTS[name], CHOICES[name])
    fidelity = resolved.get('fidelity', {})
    if 'mode' not in fidelity:
        ask('fidelity.mode', 'Choose approximate, major-object, all-object precise, or named-target alignment.',
            ('approximate', 'major_objects', 'precise', 'selective'))
    elif fidelity['mode'] == 'selective' and not fidelity.get('targets'):
        ask('fidelity.targets', 'Which objects or areas need precise matching?')
    variants = resolved.get('variants', {})
    missing_variants = [key for key in ('models', 'materials') if key not in variants]
    if len(missing_variants) == 2:
        ask('variants', 'After the base scene, replace models, materials, both, or neither?',
            [dict(models=False, materials=False), dict(models=True, materials=False),
             dict(models=False, materials=True), dict(models=True, materials=True)])
    elif missing_variants:
        key = missing_variants[0]
        ask('variants.' + key, 'After the base scene, also replace ' + key + '?', [False, True])
    camera = resolved.get('camera')
    if camera in ('source_trajectory', 'custom') and resolved.get('delivery') == 'stills':
        raise ValueError('Animated camera choices require video delivery; use inspection for static comparison cameras')
    if camera == 'source_trajectory' and inputs and not inputs.get('video'):
        ask('inputs.video', 'Which video supplies the requested source camera trajectory?')
    existing = [kind for kind in ('camera', 'people', 'cabinets', 'objects') if resolved.get(kind) == 'existing']
    if existing and not inputs.get('source_scene'):
        ask('inputs.source_scene', 'Which saved scene contains the requested existing camera, people or motion?')
    if resolved['reuse'] == 'independent' and (existing or inputs.get('source_scene')):
        raise ValueError('Independent rebuild excludes existing scene implementations/motion; use original video or images')
    details = resolved.get('details', {})
    for name, selected in [('people', 'approximate'), ('cabinets', 'animate'), ('objects', 'animate'), ('camera', 'custom')]:
        if resolved.get(name) == selected and name not in details:
            ask('details.' + name, DETAILS[name])
    animated = resolved.get('delivery') == 'video' or any(
        resolved.get(kind) not in (None, 'none') for kind in ('people', 'cabinets', 'objects'))
    if animated and 'timing' not in resolved:
        ask('timing', 'Follow source timing, or specify duration and fps (an exact frame count also works)?')
    value = resolved.get('timing', {})
    if value.get('mode') == 'explicit':
        for name in ('fps', 'frames'):
            if name not in value and not (name == 'frames' and 'duration_seconds' in value):
                ask('timing.' + name, 'Specify output ' + name + ' without rounding the duration.')
    if value.get('mode') == 'source' and not (inputs.get('video') or inputs.get('source_scene')):
        raise ValueError('Source timing requires a source video or saved scene')
    deferred = []
    if any(resolved.get('variants', {}).get(key) for key in ('models', 'materials')):
        deferred.append(dict(id='asset_variants', status='deferred_phase_3',
            request=copy.deepcopy(resolved['variants']), after='integrate',
            reason='Automatic complete-workflow variant integration is phase 3; the existing standalone interface remains available',
            manual_route='Use aha3d.blender.variants.apply_variant under its existing preflight, claims and validation rules',
            delivery_obligation='The base-scene delivery does not fulfill these requested variants'))
    stages = [] if questions else _stages(resolved)
    completed, parallel_groups = set(), []
    while len(completed) < len(stages):
        ready = [stage['id'] for stage in stages if stage['id'] not in completed and
                 set(stage['depends_on']) <= completed]
        if not ready:
            raise RuntimeError('Intake stage dependencies contain a cycle')
        parallel_groups.append(ready)
        completed.update(ready)
    return dict(schema_version=1, request=resolved, defaults=defaults, questions=questions,
        status='needs_input' if questions else 'ready_for_authoring',
        stages=stages, parallel_groups=parallel_groups, deferred=deferred, execution='not_started',
        coordination=dict(policy='One writer per file or Blender scene; independent outputs per component',
            parallelism='Stages with satisfied dependencies may be delegated; this is not an automatic scheduler'),
        limits=['This request is not an executable legacy pipeline recipe',
                'Input availability, source timing and artifact reuse are checked during authoring',
                'No jobs, models, Blender processes or asset variants are launched by intake'])


def save_intake(report, folder):
    """Write a new reviewable checkpoint, never overwrite a previous intake."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / 'request.json', report['request'])
    write(folder / 'intake.json', report)
    lines = ['# Scene requirements', '', 'Status: ' + report['status'] + '.', '',
             'This checkpoint records scope and an authoring plan; execution has not started.', '',
             '```json', json.dumps(report['request'], indent=2, ensure_ascii=True), '```', '']
    if report['questions']:
        lines += ['## Missing information', '']
        lines += ['- `' + q['field'] + '`: ' + q['prompt'] for q in report['questions']]
    if report['stages']:
        lines += ['## Stage dependencies', '', '| Stage | Depends on | Owner | Output |', '| --- | --- | --- | --- |']
        for stage in report['stages']:
            lines.append('| {id} | {deps} | {owner} | `{output}` |'.format(deps=', '.join(stage['depends_on']) or 'none', **stage))
        lines += ['', 'Output paths are relative to a new claimed run directory. Only the integrator writes the combined scene.', '']
    if report['deferred']:
        lines += ['## Deferred requested work', '',
                  'Asset variants are recorded for phase 3. A base-scene delivery does not fulfill them.', '']
    (folder / 'BRIEF.md').write_text('\n'.join(lines) + '\n')


def command(args):
    request = json.loads(args.request.read_text()) if args.request else {'schema_version': 1}
    if args.preset:
        request = apply_answers(request, {'preset': args.preset})
    if args.answers:
        request = apply_answers(request, json.loads(args.answers.read_text()))
    report = build_intake(request)
    report['project_root'] = str(args.root.resolve())
    if args.out:
        save_intake(report, args.out)
    return report
