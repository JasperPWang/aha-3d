"""Small explicit override contract. Ordinary scenes need no configuration file."""
import math

DEFAULTS = dict(penetration_m=.005, support_gap_m=.02, simulation_seconds=2.,
                movement_m=.03, rotation_degrees=5., max_samples=1024,
                max_simulated_objects=40, frame=None, physics='auto', objects={})


def normalize(raw=None):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw)-set(DEFAULTS):
        raise ValueError('Unknown placement configuration fields')
    value = dict(DEFAULTS, **raw)
    for key in ('penetration_m', 'support_gap_m', 'simulation_seconds', 'movement_m', 'rotation_degrees'):
        n = value[key]
        if isinstance(n, bool) or not isinstance(n, (float,int)) or not math.isfinite(n) or n <= 0:
            raise ValueError(key+' must be finite and positive')
    for key in ('max_samples','max_simulated_objects'):
        if type(value[key]) is not int or value[key] < 1:
            raise ValueError(key+' must be a positive integer')
    if value['frame'] is not None and type(value['frame']) is not int:
        raise ValueError('frame must be an integer')
    if value['physics'] not in ('auto','off'):
        raise ValueError('physics must be auto or off')
    if not isinstance(value['objects'], dict):
        raise ValueError('objects must map exact IDs or Blender root names to overrides')
    for key, item in value['objects'].items():
        if not isinstance(key,str) or not key or not isinstance(item,dict) or set(item)-{'role','support','fixed','mass_kg','exclude_reason'}:
            raise ValueError('Invalid object override: '+str(key))
        if 'role' in item and item['role'] not in ('floor','wall','ceiling','structure','cover','furniture','prop','person','fixture'):
            raise ValueError('Invalid role: '+key)
        for field in ('support','exclude_reason'):
            if field in item and (not isinstance(item[field],str) or not item[field].strip()):
                raise ValueError(field+' must be nonempty text')
        if 'fixed' in item and type(item['fixed']) is not bool:
            raise ValueError('fixed must be boolean')
        if 'mass_kg' in item and (isinstance(item['mass_kg'],bool) or not isinstance(item['mass_kg'],(int,float)) or not math.isfinite(item['mass_kg']) or item['mass_kg']<=0):
            raise ValueError('mass_kg must be positive')
    return value
