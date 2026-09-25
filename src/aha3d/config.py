"""Strict JSON recipes and rational output timing; no ML or Blender imports."""
from fractions import Fraction
import math
import os
from pathlib import Path
import re

from .io import read
from .paths import migrated_path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}', value):
        raise ValueError(f'Invalid identifier: {value!r}')
    return value


def keys(value, allowed, context):
    if not isinstance(value, dict):
        raise ValueError(f'{context} must be an object')
    unknown = value.keys() - set(allowed)
    if unknown:
        raise ValueError(f'Unknown {context} fields: {sorted(unknown)}')


def positive_int(value, field):
    if type(value) is not int or value <= 0:
        raise ValueError(f'{field} must be a positive integer')
    return value


def timing(value):
    keys(value, ['fps', 'frames', 'start', 'duration_seconds'], 'timing')
    rate = Fraction(str(value['fps']))
    if rate <= 0 or rate > 1000:
        raise ValueError('fps must be positive and at most 1000')
    count = positive_int(value['frames'], 'frames')
    start = positive_int(value.get('start', 1), 'start')
    duration = Fraction(count, 1) / rate
    if 'duration_seconds' in value and Fraction(str(value['duration_seconds'])) != duration:
        raise ValueError('duration_seconds must equal frames / fps exactly')
    return {'fps': str(rate), 'frames': count, 'start': start,
            'duration_seconds': float(duration), 'end': start + count - 1}


def path(root, value):
    candidate = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return migrated_path(root, (candidate if candidate.is_absolute() else Path(root) / candidate).resolve()).resolve()


def load_recipe(root, scene_id, recipe_id):
    scene_id, recipe_id = identifier(scene_id), identifier(recipe_id)
    scene = read(Path(root) / 'scenes' / scene_id / 'scene.json')
    keys(scene, ['schema_version', 'id', 'reference', 'source_directory', 'description'], 'scene')
    if scene.get('schema_version') != 1 or scene.get('id') != scene_id:
        raise ValueError('Scene schema/identity mismatch')
    recipe = read(Path(root) / 'scenes' / scene_id / 'recipes' / f'{recipe_id}.json')
    return validate_recipe(recipe, scene_id, recipe_id)


def validate_recipe(recipe, scene_id=None, recipe_id=None):
    keys(recipe, ['schema_version', 'scene', 'id', 'description', 'source', 'timing',
                  'render', 'body', 'assembly', 'validation', 'runtime', 'layout_inspection'], 'recipe')
    if recipe.get('schema_version') != 1:
        raise ValueError('Unsupported recipe schema')
    identifier(recipe['scene']); identifier(recipe['id'])
    if scene_id is not None and recipe['scene'] != scene_id or recipe_id is not None and recipe['id'] != recipe_id:
        raise ValueError('Recipe identity mismatch')
    if not isinstance(recipe['source'], str) or not recipe['source'].endswith('.blend'):
        raise ValueError('source must identify a saved .blend')
    recipe = dict(recipe)
    recipe['timing'] = timing(recipe['timing'])
    render = dict(recipe.get('render', {}))
    keys(render, ['kind', 'mode', 'engine', 'width', 'height', 'samples', 'stills', 'seed', 'view_transform', 'look', 'exposure'], 'render')
    render = dict(kind='video', mode='material', engine='auto', width=1280, height=720, samples=24, seed=0) | render
    if render['kind'] not in ('video', 'stills') or render['mode'] not in ('preserve', 'clay', 'material'):
        raise ValueError('Unsupported render kind or mode')
    if render['engine'] not in ('auto', 'workbench', 'eevee', 'cycles'):
        raise ValueError('Unsupported render engine')
    if render['mode'] == 'material' and render['engine'] == 'workbench':
        raise ValueError('Material rendering requires eevee or cycles')
    for field in ('width', 'height', 'samples'):
        positive_int(render[field], field)
    if 'exposure' in render and not math.isfinite(float(render['exposure'])):
        raise ValueError('Exposure must be finite')
    if render['kind'] == 'video' and (render['width'] % 2 or render['height'] % 2):
        raise ValueError('H.264 output dimensions must be even')
    if render['kind'] == 'stills':
        selected = render.get('stills', [recipe['timing']['start']])
        if not isinstance(selected, list) or not selected or any(type(f) is not int or not recipe['timing']['start'] <= f <= recipe['timing']['end'] for f in selected):
            raise ValueError('Still frames must lie within the configured timeline')
        render['stills'] = sorted(set(selected))
    recipe['render'] = render
    if 'layout_inspection' in recipe:
        layout = dict(recipe['layout_inspection'])
        keys(layout, ['source_scene', 'reference', 'cameras', 'inputs', 'config',
                     'camera_cache', 'source_video', 'scale_provenance', 'review_dir',
                     'required_object_ids'], 'layout_inspection')
        identities = layout.get('required_object_ids', [])
        if (not isinstance(identities, list) or any(not isinstance(i, str) or not i.strip() for i in identities)
                or len(identities) != len(set(identities))):
            raise ValueError('layout_inspection.required_object_ids needs unique nonempty exact IDs')
        for field in ('reference', 'cameras', 'inputs', 'config', 'camera_cache'):
            if not isinstance(layout.get(field), str) or not layout[field]:
                raise ValueError(f'layout_inspection.{field} requires an explicit input path')
        for field, value in layout.items():
            if field != 'required_object_ids' and (not isinstance(value, str) or not value):
                raise ValueError(f'layout_inspection.{field} must be a nonempty path')
        recipe['layout_inspection'] = layout
    body = dict(recipe.get('body', {'mode': 'keep'}))
    keys(body, ['mode', 'cache', 'native', 'source_fps', 'prompt', 'durations', 'seed',
                'model', 'constraints', 'transition_frames', 'diffusion_steps',
                'offset', 'yaw', 'ground_clearance', 'object_name', 'smoothing',
                'cache_timing', 'max_root_step', 'anchor'], 'body')
    if body.get('mode') not in ('keep', 'cache', 'native', 'generate'):
        raise ValueError('body.mode must be keep, cache, native or generate')
    for mode, field in [('cache', 'cache'), ('native', 'native')]:
        if body['mode'] == mode and not body.get(field):
            raise ValueError(f'{mode} mode requires {field}')
    if body['mode'] == 'generate':
        if not body.get('prompt') or not isinstance(body.get('durations'), list) or not body['durations']:
            raise ValueError('Generation requires prompt and durations')
        if any(not isinstance(d, (int, float)) or not math.isfinite(d) or d <= 0 for d in body['durations']):
            raise ValueError('Generation durations must be finite and positive')
        if any(d > 10 for d in body['durations']):
            raise ValueError('Kimodo supports at most 10 seconds per prompt; split longer actions into native prompt segments')
        if not isinstance(body['prompt'], str) or len([p for p in body['prompt'].split('.') if p.strip()]) != len(body['durations']):
            raise ValueError('Provide one duration per period-separated Kimodo prompt segment')
        if abs(sum(body['durations']) - recipe['timing']['duration_seconds']) > 1 / 30 + 1e-6:
            raise ValueError('Generation duration and output duration differ by more than one native frame')
    if 'offset' in body and (len(body['offset']) != 3 or not all(math.isfinite(float(x)) for x in body['offset'])):
        raise ValueError('Body offset must contain three finite coordinates')
    recipe['body'] = body
    if body.get('anchor', 'cache_origin') not in ('cache_origin', 'first_pelvis_xy'):
        raise ValueError('Unsupported placement anchor')
    if body.get('cache_timing', 'exact') not in ('exact', 'match_scene_frames'):
        raise ValueError('Unsupported cache timing policy')
    assembly = recipe.get('assembly', {})
    keys(assembly, ['camera', 'hide_collections', 'close_cabinets'], 'assembly')
    if 'camera' in assembly:
        keys(assembly['camera'], ['location', 'target', 'lens'], 'camera')
    recipe['assembly'] = assembly
    if recipe.get('layout_inspection') and (assembly.get('camera') or assembly.get('hide_collections') or assembly.get('close_cabinets')):
        raise ValueError('Reference layout evidence requires an authored room source; save camera, collection and cabinet changes into source before inspection')
    validation = dict(recipe.get('validation', {}))
    keys(validation, ['collisions', 'minimum_in_frame', 'floor_min', 'sample_frames'], 'validation')
    validation.setdefault('collisions', 'report')
    if validation['collisions'] not in ('report', 'error', 'off'):
        raise ValueError('Invalid collision policy')
    if not 0 <= validation.get('minimum_in_frame', 0) <= 1:
        raise ValueError('minimum_in_frame must lie in [0,1]')
    samples = validation.get('sample_frames')
    if samples is not None and samples != 'all':
        if not isinstance(samples, list) or not samples or any(type(f) is not int or not recipe['timing']['start'] <= f <= recipe['timing']['end'] for f in samples):
            raise ValueError('Validation sample frames must lie within the configured timeline')
    recipe['validation'] = validation
    recipe.setdefault('runtime', 'local')
    identifier(recipe['runtime'])
    return recipe


def load_runtime(root, name):
    folder = Path(root) / 'configs' / 'runtimes'
    name = identifier(name)
    local = folder / f'{name}.local.json'
    source = local if local.is_file() else folder / f'{name}.json'
    config = read(source)
    if not isinstance(config, dict) or config.get('schema_version') != 2:
        raise ValueError(f'{source} has an unsupported runtime schema; regenerate it with: '
                         f'python tools/configure_runtime.py --out {source} ...')
    keys(config, ['schema_version', 'python', 'blender', 'skin_blender', 'env_script',
                  'upstream', 'checkpoint', 'threads', 'gpu'], 'runtime')
    config.setdefault('threads', None); config.setdefault('gpu', 0)
    if config['threads'] is not None and (type(config['threads']) is not int or config['threads'] < 1):
        raise ValueError('Runtime threads must be null (all cores) or a positive integer')
    if type(config['gpu']) is not int or config['gpu'] < 0:
        raise ValueError('Runtime gpu must be a nonnegative CUDA device index')
    for field in ('python', 'blender', 'skin_blender', 'env_script', 'upstream', 'checkpoint'):
        config[field] = str(path(root, config[field]))
        if not Path(config[field]).exists():
            raise ValueError(f'Missing runtime {field}: {config[field]}')
    return config
