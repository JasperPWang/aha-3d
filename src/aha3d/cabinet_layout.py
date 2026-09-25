"""Validate and dimension cabinet recipes without importing Blender.

Columns run left to right; sections and drawer heights run bottom to top.
Widths/heights are positive relative weights, not metric dimensions. Shelves and
dividers accept a count or sorted positions strictly inside (0, 1).
"""
import copy
import math


PRESETS = {
    'default': {'columns': [{'sections': [
        {'height': 3, 'front': 'double_door', 'shelves': 1},
        {'height': 1, 'front': 'drawers', 'drawer_count': 1},
    ]}]},
    'three_drawers': {'columns': [{'sections': [
        {'front': 'drawers', 'drawer_count': 3},
    ]}]},
    'mixed': {'columns': [
        {'width': 2, 'sections': [{'front': 'door_left', 'shelves': [0.35, 0.7]}]},
        {'width': 1, 'sections': [{'front': 'drawers', 'drawer_heights': [2, 1, 1]}]},
    ]},
    'open_shelving': {'columns': [{'sections': [
        {'front': 'open', 'shelves': 2, 'dividers': 1},
    ]}]},
}


def cabinet_preset(name):
    """Return an independent editable recipe, never a shared preset object."""
    if name not in PRESETS:
        raise ValueError('Unknown cabinet preset: ' + str(name))
    return copy.deepcopy(PRESETS[name])


def _keys(value, allowed, path):
    if not isinstance(value, dict):
        raise ValueError(path + ' must be an object')
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(path + ': unknown keys ' + ', '.join(sorted(unknown)))


def _number(value, path, positive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(path + ' must be a finite number')
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(path + ' must be a finite positive number')
    return value


def _count(value, path, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(path + ' must be an integer >= ' + str(minimum))
    return value


def _positions(value, path):
    if isinstance(value, int) and not isinstance(value, bool):
        count = _count(value, path)
        if count > 100:
            raise ValueError(path + ' exceeds 100 partitions')
        return [(i + 1) / (count + 1) for i in range(count)]
    if not isinstance(value, (list, tuple)):
        raise ValueError(path + ' must be a count or ordered fractional positions')
    result = [_number(v, path) for v in value]
    if any(v >= 1 for v in result) or any(b <= a for a, b in zip(result, result[1:])):
        raise ValueError(path + ' must strictly increase inside (0, 1)')
    if len(result) > 100:
        raise ValueError(path + ' exceeds 100 partitions')
    return result


def _weights(values, available, path):
    weights = [_number(v, path) for v in values]
    if not weights or not math.isfinite(sum(weights)):
        raise ValueError(path + ' needs finite positive weights')
    return [available * v / sum(weights) for v in weights]


def _partition_clearance(positions, extent, thickness, path):
    edges = [0] + list(positions) + [1]
    for i, (a, b) in enumerate(zip(edges, edges[1:])):
        occupied = thickness * ((i > 0) + (i < len(edges) - 2)) / 2
        if (b - a) * extent - occupied < .035:
            raise ValueError(path + ' leaves less than 35 mm clear space')


def normalize_layout(layout=None, size=(1.2, .55, 1.1)):
    """Compile a fully checked metric plan before any scene objects are created.

    A string selects a preset. A mapping is a recipe; unknown keys are rejected.
    The result is a JSON-compatible construction plan and provenance record.
    """
    if not isinstance(size, (tuple, list)) or len(size) != 3:
        raise ValueError('size must contain width, depth, height')
    width, depth, height = [_number(v, 'size') for v in size]
    if min(width, depth, height) < .2:
        raise ValueError('Cabinet dimensions must be at least 0.2 m')
    recipe = cabinet_preset('default' if layout is None else layout) if isinstance(layout, str) or layout is None else copy.deepcopy(layout)
    _keys(recipe, ['columns', 'panel_thickness', 'front_thickness', 'gap',
                   'door_angle_degrees', 'drawer_travel_fraction'], 'layout')
    thick = _number(recipe.get('panel_thickness', .024), 'panel_thickness')
    front = _number(recipe.get('front_thickness', .026), 'front_thickness')
    gap = _number(recipe.get('gap', .004), 'gap')
    angle = _number(recipe.get('door_angle_degrees', 95), 'door_angle_degrees')
    travel = _number(recipe.get('drawer_travel_fraction', .65), 'drawer_travel_fraction')
    if thick > min(width, depth, height) / 5 or front > depth / 5:
        raise ValueError('Panel thickness is too large for this cabinet')
    if gap > .02 or gap > thick:
        raise ValueError('gap must not exceed 20 mm or panel thickness')
    if angle > 120:
        raise ValueError('door_angle_degrees must be <= 120')
    if travel > .85:
        raise ValueError('drawer_travel_fraction must be <= 0.85')
    columns = recipe.get('columns')
    if not isinstance(columns, list) or not columns or len(columns) > 32:
        raise ValueError('columns must be a nonempty list of at most 32 columns')
    for i, col in enumerate(columns):
        _keys(col, ['width', 'sections'], 'column ' + str(i))
    widths = _weights([c.get('width', 1) for c in columns],
                      width - thick * (len(columns) + 1), 'column width')
    result = {'schema_version': 1, 'size_m': [width, depth, height],
              'panel_thickness': thick, 'front_thickness': front, 'gap': gap,
              'door_angle_degrees': angle, 'drawer_travel_fraction': travel,
              'recipe': recipe, 'columns': []}
    left = -width / 2 + thick
    inner_depth = depth - thick - 2 * gap
    if inner_depth < .1:
        raise ValueError('Cabinet leaves less than 100 mm internal depth')
    for ci, (col, col_width) in enumerate(zip(columns, widths)):
        path = 'column ' + str(ci)
        if col_width < .1:
            raise ValueError(path + ' leaves less than 100 mm internal width')
        sections = col.get('sections')
        if not isinstance(sections, list) or not sections or len(sections) > 32:
            raise ValueError(path + ' sections must be a nonempty list of at most 32')
        for si, section in enumerate(sections):
            _keys(section, ['height', 'front', 'shelves', 'dividers',
                            'drawer_count', 'drawer_heights'], path + ' section ' + str(si))
        heights = _weights([s.get('height', 1) for s in sections],
                           height - thick * (len(sections) + 1), path + ' section height')
        column_plan = {'index': ci, 'x': left + col_width / 2, 'width': col_width, 'sections': []}
        bottom = thick
        for si, (section, section_height) in enumerate(zip(sections, heights)):
            spath = path + ' section ' + str(si)
            if section_height < .085:
                raise ValueError(spath + ' leaves less than 85 mm internal height')
            kind = section.get('front', 'open')
            if kind not in ('open', 'door_left', 'door_right', 'double_door', 'drawers'):
                raise ValueError(spath + ': unsupported front ' + str(kind))
            shelves = _positions(section.get('shelves', 0), spath + ' shelves')
            dividers = _positions(section.get('dividers', 0), spath + ' dividers')
            _partition_clearance(shelves, section_height, thick, spath + ' shelves')
            _partition_clearance(dividers, col_width, thick, spath + ' dividers')
            drawers = []
            if kind == 'drawers':
                if shelves or dividers:
                    raise ValueError(spath + ': drawers cannot contain static shelves or dividers')
                if 'drawer_count' in section and 'drawer_heights' in section:
                    raise ValueError(spath + ': use drawer_count or drawer_heights, not both')
                if 'drawer_heights' in section:
                    weights = section['drawer_heights']
                    if not isinstance(weights, list) or not weights or len(weights) > 100:
                        raise ValueError(spath + ' drawer_heights must be a nonempty list of at most 100')
                else:
                    count = _count(section.get('drawer_count', 1), spath + ' drawer_count', 1)
                    if count > 100:
                        raise ValueError(spath + ' exceeds 100 drawers')
                    weights = [1] * count
                drawers = _weights(weights, section_height, spath + ' drawer heights')
                if min(drawers) < max(.075, 2 * thick + 3 * gap):
                    raise ValueError(spath + ': a drawer has insufficient height for a hollow box')
            elif 'drawer_count' in section or 'drawer_heights' in section:
                raise ValueError(spath + ': drawer settings require front=drawers')
            if kind == 'double_door' and col_width / 2 - gap < .055:
                raise ValueError(spath + ': double doors are too narrow')
            column_plan['sections'].append({'index': si, 'bottom': bottom,
                'height': section_height, 'front': kind, 'shelves': shelves,
                'dividers': dividers, 'drawer_heights': drawers})
            bottom += section_height + thick
        result['columns'].append(column_plan)
        left += col_width + thick
    return result
