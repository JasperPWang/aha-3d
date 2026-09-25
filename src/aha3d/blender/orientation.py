"""Declared asset frames and explicit scene-facing relationships in Blender."""
import json
import math
import time

import bpy
from mathutils import Matrix, Vector

from aha3d.orientation import AXES, normalize_orientation, unknown_orientation, validate_tolerance

PROPERTY = 'asset_orientation_json'
RELATION = 'facing_target_json'


def tag_orientation(root, orientation):
    """Record a reviewed/authored/unknown frame without rotating any geometry."""
    data = normalize_orientation(orientation)
    root[PROPERTY] = json.dumps(data, sort_keys=True)
    if data['front_axis'] is None:
        if 'asset_front_axis' in root:
            del root['asset_front_axis']
    else:
        root['asset_front_axis'] = data['front_axis']
    root['asset_up_axis'] = data['up_axis']
    root['asset_origin'] = data['origin']
    return root


def get_orientation(root, require_trusted=False):
    value = root.get(PROPERTY)
    data = json.loads(value) if value else unknown_orientation()
    return normalize_orientation(data, require_trusted=require_trusted)


def _check_uniform(matrix):
    basis = matrix.to_3x3()
    lengths = [basis.col[i].length for i in range(3)]
    if (not all(math.isfinite(v) for row in matrix for v in row) or
            min(lengths) <= 1e-8 or basis.determinant() <= 0 or
            max(lengths)-min(lengths) > 1e-5 * max(lengths) or
            any(abs(basis.col[i].dot(basis.col[j])) > 1e-5 * lengths[i]*lengths[j]
                for i in range(3) for j in range(i))):
        raise ValueError('Facing requires a positive uniform transform without reflection or shear')


def _placement(root, editable=False):
    bpy.context.view_layer.update()
    matrix = root.matrix_world.copy()
    _check_uniform(matrix)
    basis = matrix.to_3x3()
    data = get_orientation(root, require_trusted=True)
    up = (basis @ Vector(AXES[data['up_axis']])).normalized()
    if (up - Vector((0, 0, 1))).length > 1e-5:
        raise ValueError('Facing helper requires an upright asset; use an explicit reviewed transform for tilted mounts')
    if editable:
        obj = root
        while obj is not None:
            _check_uniform(obj.matrix_world)
            if obj.animation_data or len(obj.constraints):
                raise ValueError('Cannot change facing of animated/constrained roots or ancestors; update their placement animation explicitly')
            obj = obj.parent
    return matrix, data


def world_front(root):
    matrix, data = _placement(root)
    if data['front_axis'] is None:
        return None
    return (matrix.to_3x3() @ Vector(AXES[data['front_axis']])).normalized()


def _target(target, scene=None):
    if isinstance(target, bpy.types.Object):
        identity = target.get('instance_id')
        if not identity:
            raise ValueError('A facing target object needs a stable instance_id')
        matching = [obj for obj in (scene or bpy.context.scene).objects if obj.get('instance_id') == identity]
        if len(matching) != 1 or matching[0] != target:
            raise ValueError('Facing target must be a unique instance in the current scene')
        return target.matrix_world.translation.copy(), {'instance_id': identity}
    if not isinstance(target, (list, tuple, Vector)) or len(target) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in target):
        raise ValueError('Facing target must be a semantic object or three finite world coordinates')
    return Vector(target), {'point': list(target)}


def _direction(value):
    if not isinstance(value, (list, tuple, Vector)):
        raise ValueError('Facing direction must be a three-component vector')
    vector, _ = _target(value)
    if abs(vector.z) > 1e-8 or vector.length < 1e-8:
        raise ValueError('Facing direction must be a nonzero horizontal world vector')
    return vector.normalized()


def _resolve_relation(root, scene=None):
    if not root.get(RELATION):
        return None, None
    relation = json.loads(root[RELATION])
    if not isinstance(relation, dict) or set(relation) - {'instance_id', 'point', 'direction', 'tolerance_degrees'}:
        raise ValueError('Invalid stored facing relation')
    if sum(key in relation for key in ('instance_id', 'point', 'direction')) != 1:
        raise ValueError('Stored facing relation requires one target')
    tolerance = validate_tolerance(relation.get('tolerance_degrees', 10))
    if 'direction' in relation:
        return root.matrix_world.translation + _direction(relation['direction']), tolerance
    if 'point' in relation:
        return _target(relation['point'])[0], tolerance
    matches = [obj for obj in (scene or bpy.context.scene).objects if obj.get('instance_id') == relation['instance_id']]
    if len(matches) != 1:
        raise ValueError('Stored facing target is missing or ambiguous: ' + str(relation['instance_id']))
    return matches[0].matrix_world.translation.copy(), tolerance


def facing_report(root, target=None, tolerance_degrees=None, *, scene=None):
    """Compare declared front against a stored/explicit target; no inferred intent."""
    data = get_orientation(root)
    result = dict(instance_id=root.get('instance_id', root.name), orientation=data,
                  status='unverified', reason='Orientation not authored or reviewed')
    if data['status'] not in ('authored', 'reviewed'):
        return result
    matrix, data = _placement(root)
    if data['symmetry'] == 'continuous_z':
        return dict(result, status='not_applicable', reason='Asset has no unique front')
    front = world_front(root)
    if target is None:
        point, saved_tolerance = _resolve_relation(root, scene)
    else:
        point, _ = _target(target, scene)
        saved_tolerance = None
    result['front_world'] = list(front)
    if point is None:
        return dict(result, status='no_target', reason='Frame known; no scene facing intent declared')
    tolerance = validate_tolerance(tolerance_degrees if tolerance_degrees is not None else
                                   (saved_tolerance if saved_tolerance is not None else 10))
    delta = point - matrix.translation
    delta.z = 0
    if delta.length < 1e-8:
        raise ValueError('Facing target has the same horizontal position as the asset')
    delta.normalize()
    angle = math.degrees(math.acos(max(-1, min(1, front.dot(delta)))))
    return dict(result, target_world=list(point), error_degrees=angle, tolerance_degrees=tolerance,
                status='pass' if angle <= tolerance else 'fail', reason='Declared front compared with explicit target')


def face_towards(root, target, *, tolerance_degrees=10, record=True):
    """Rotate an upright root around world Z; preserve location, size and rig locals."""
    tolerance = validate_tolerance(tolerance_degrees)
    matrix, data = _placement(root, editable=True)
    if data['front_axis'] is None:
        raise ValueError('Asset has no unique front; face_towards is not applicable')
    if isinstance(target, bpy.types.Object):
        ancestor = target
        while ancestor is not None:
            if ancestor == root:
                raise ValueError('Facing target cannot be the asset itself or its descendant')
            ancestor = ancestor.parent
    point, relation = _target(target)
    delta = point - matrix.translation
    delta.z = 0
    if delta.length < 1e-8:
        raise ValueError('Facing target has the same horizontal position as the asset')
    front = matrix.to_3x3() @ Vector(AXES[data['front_axis']])
    angle = math.atan2(delta.y, delta.x)-math.atan2(front.y, front.x)
    rotated = Matrix.Rotation(angle, 4, 'Z') @ matrix
    rotated.translation = matrix.translation
    root.matrix_world = rotated
    if record:
        relation['tolerance_degrees'] = tolerance
        root[RELATION] = json.dumps(relation, sort_keys=True)
    bpy.context.view_layer.update()
    return facing_report(root, target=target, tolerance_degrees=tolerance)


def place_root(root, location=None, *, facing_target=None, facing_direction=None,
               tolerance_degrees=10):
    """Place an authored directional root in world space and retain its intent.

    Exactly one target or horizontal direction is required. A direction preserves
    source-observed skew without assuming a chair faces the table center. This
    does not declare or infer the root's actual front. Call after room parenting.
    """
    if (facing_target is None) == (facing_direction is None):
        raise ValueError('Choose exactly one facing_target or facing_direction')
    tolerance = validate_tolerance(tolerance_degrees)
    matrix, data = _placement(root, editable=True)
    if data['front_axis'] is None:
        raise ValueError('A symmetric root has no facing to place')
    if location is not None and not isinstance(location, (list, tuple, Vector)):
        raise ValueError('Location must be three finite world coordinates')
    point = _target(location)[0] if location is not None else matrix.translation.copy()
    direction = _direction(facing_direction) if facing_direction is not None else None
    target = facing_target if direction is None else point + direction
    if direction is None:
        target_point, _ = _target(target)
        if math.hypot(target_point.x-point.x, target_point.y-point.y) < 1e-8:
            raise ValueError('Facing target has the same horizontal position as the asset')
        if isinstance(target, bpy.types.Object):
            ancestor = target
            while ancestor is not None:
                if ancestor == root:
                    raise ValueError('Facing target cannot be the asset itself or its descendant')
                ancestor = ancestor.parent
    previous_relation = root.get(RELATION)
    try:
        moved = matrix.copy(); moved.translation = point
        root.matrix_world = moved
        face_towards(root, target, tolerance_degrees=tolerance)
        if direction is not None:
            root[RELATION] = json.dumps({'direction': list(direction),
                                        'tolerance_degrees': tolerance}, sort_keys=True)
    except Exception:
        root.matrix_world = matrix
        if previous_relation is None:
            if RELATION in root:
                del root[RELATION]
        else:
            root[RELATION] = previous_relation
        bpy.context.view_layer.update()
        raise
    return root


# Semantic classes identify missing metadata, never infer the actual front.
_DIRECTIONAL_CLASSES = {'chair', 'chairs', 'seating', 'sofa', 'sofas', 'stool',
                        'stools', 'cabinet', 'cabinets', 'faucet', 'faucets',
                        'door', 'doors'}


def scene_facing_report(scene):
    """Cheap current-frame exception list; no mesh extraction or source inference.

    Inspect directional semantic roots and explicit orientation/intent metadata.
    Nested imported geometry is covered by its outer placement root. Untagged
    geometry cannot be classified and is not claimed to have passed this check.
    """
    start = time.perf_counter()
    counts = {key: 0 for key in ('pass', 'not_applicable', 'fail', 'no_target',
                                'unverified', 'invalid')}
    issues = []
    checked = 0
    for root in sorted(scene.objects, key=lambda obj: obj.name):
        category = set(str(root.get('semantic_class', '')).lower().split('/'))
        explicit = PROPERTY in root or RELATION in root
        if not explicit and not (category & _DIRECTIONAL_CLASSES):
            continue
        ancestor = root.parent
        nested = False
        while ancestor is not None:
            if ancestor.get('instance_id') or PROPERTY in ancestor or RELATION in ancestor:
                nested = not root.get('instance_id') and RELATION not in root
                break
            ancestor = ancestor.parent
        if nested:
            continue
        checked += 1
        try:
            item = facing_report(root, scene=scene)
        except (ValueError, TypeError, RuntimeError) as error:
            item = {'status': 'invalid', 'reason': str(error)}
        counts[item['status']] += 1
        if item['status'] not in ('pass', 'not_applicable'):
            issues.append(dict(object=root.name, instance_id=root.get('instance_id'),
                               **{key: item[key] for key in ('status', 'reason', 'error_degrees')
                                  if key in item}))
    return dict(schema_version=1, frame=scene.frame_current, checked=checked,
                counts=counts, issues=issues,
                status='needs_review' if issues else 'no_reported_issues',
                elapsed_seconds=time.perf_counter()-start,
                scope='Current-frame declared facing; untagged geometry and source visual correctness are not verified')
