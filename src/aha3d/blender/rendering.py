"""Explicit preview engines; no implicit ray tracing or CPU fallback."""
import bpy
import json


def configure_render(scene, mode='clay', samples=32, engine='auto', *, cycles_device='GPU'):
    if mode not in ('clay', 'material', 'preserve'):
        raise ValueError('Render mode must be clay, material or preserve')
    if engine not in ('auto', 'workbench', 'eevee', 'cycles'):
        raise ValueError('Render engine must be auto, workbench, eevee or cycles')
    if type(samples) is not int or samples < 1:
        raise ValueError('Samples must be a positive integer')
    if cycles_device not in ('GPU', 'CPU'):
        raise ValueError('Cycles device must be GPU or CPU')
    engines = {'workbench': 'BLENDER_WORKBENCH', 'eevee': 'BLENDER_EEVEE', 'cycles': 'CYCLES'}
    if engine == 'auto':
        engine = (dict({v: k for k, v in engines.items()}, BLENDER_EEVEE_NEXT='eevee').get(scene.render.engine)
                  if mode == 'preserve' else 'workbench' if mode == 'clay' else 'eevee')
        if engine is None:
            raise ValueError('Unsupported saved engine; choose an explicit engine')
    if engine == 'workbench' and mode == 'material':
        raise ValueError('Workbench cannot reproduce shader materials; choose eevee or cycles')
    try:
        scene.render.engine = engines[engine]
    except TypeError:
        if engine != 'eevee': raise
        # Blender 4.2-4.5 names the rewritten engine EEVEE_NEXT; 5.2 uses EEVEE.
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    devices = []
    if engine == 'workbench':
        if mode != 'preserve':
            shade = scene.display.shading
            shade.light = 'MATCAP'; shade.studio_light = 'basic_bright.exr'
            shade.color_type = 'SINGLE'; shade.single_color = (.82, .82, .82)
            shade.show_shadows = shade.show_cavity = True
            shade.cavity_type = 'BOTH'
            shade.curvature_ridge_factor, shade.curvature_valley_factor = .35, .5
            shade.cavity_ridge_factor, shade.cavity_valley_factor = .6, .85
            shade.show_specular_highlight = shade.show_object_outline = False
            scene.view_settings.view_transform = 'Standard'
            scene.view_settings.look = 'None'; scene.view_settings.exposure = .65
        scene.display.render_aa = '16'
    else:
        if mode != 'preserve':
            scene.view_settings.view_transform = 'AgX'
            scene.view_settings.look = 'None'; scene.view_settings.exposure = 0.
        if engine == 'eevee':
            scene.eevee.taa_render_samples = samples
            scene.eevee.use_raytracing = False
        else:
            scene.cycles.samples = samples; scene.cycles.use_denoising = True
            scene.cycles.device = cycles_device
            if cycles_device == 'GPU':
                prefs = bpy.context.preferences.addons['cycles'].preferences
                for backend in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
                    try:
                        prefs.compute_device_type = backend; prefs.get_devices()
                        selected = [d for d in prefs.devices if d.type == backend]
                        if selected:
                            for d in prefs.devices: d.use = d.type == backend
                            devices = [d.name for d in selected]
                            break
                    except (TypeError, RuntimeError):
                        continue
                if not devices:
                    raise RuntimeError('No Cycles GPU found; explicitly choose CPU or allocate a GPU')
            scene.render.use_persistent_data = True
    if mode == 'material':
        for layer in scene.view_layers: layer.material_override = None
    elif mode == 'clay' and engine != 'workbench':
        material = bpy.data.materials.new('Render clay override'); material.use_nodes = True
        shader = material.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = (.72, .72, .72, 1)
        shader.inputs['Roughness'].default_value = .8
        for layer in scene.view_layers: layer.material_override = material
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'; scene.render.image_settings.color_depth = '8'
    scene.render.use_motion_blur = False; scene.render.film_transparent = False
    from .orientation import scene_facing_report
    facing = scene_facing_report(scene)
    scene['facing_preflight_json'] = json.dumps(facing, sort_keys=True)
    if facing['issues']:
        print('FACING_REVIEW ' + json.dumps(facing['issues'], ensure_ascii=True))
    return dict(engine=scene.render.engine, mode=mode, samples=16 if engine == 'workbench' else samples,
                raytracing=False if engine != 'cycles' else True,
                cycles_device=cycles_device if engine == 'cycles' else None, gpu_devices=devices)
