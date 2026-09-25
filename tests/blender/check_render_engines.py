"""Real Blender engine routing, saved-scene preservation and frame receipt checks."""
import json
from pathlib import Path
import sys
import tempfile
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
from aha3d.blender.rendering import configure_render
from aha3d.blender.stage import render
s = bpy.context.scene
s.render.resolution_x = s.render.resolution_y = 64
s.render.resolution_percentage = 100
material = bpy.data.materials.new('Preserved material'); material.use_nodes = True
bpy.data.objects['Cube'].data.materials.append(material)
before = material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value[:]
for mode, engine, expected in [('clay','auto','BLENDER_WORKBENCH'),
                               ('material','auto','EEVEE'),
                               ('clay','cycles','CYCLES'), ('material','cycles','CYCLES')]:
    info = configure_render(s, mode, 2, engine)
    assert s.render.engine in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT') if expected == 'EEVEE' else s.render.engine == expected, info
    if expected == 'EEVEE': assert not s.eevee.use_raytracing
    if mode == 'material': assert s.view_layers[0].material_override is None
    assert material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value[:] == before
    bpy.ops.render.render()
# The pipeline must respect the reopened raster engine and refuse mixed receipts.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); (root/'stages/assemble').mkdir(parents=True)
    configure_render(s, 'clay', 2)
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'stages/assemble/scene.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(root/'stages/assemble/scene.blend'))
    recipe = dict(render=dict(kind='stills', stills=[1], samples=2, engine='auto', mode='clay'),
                  timing=dict(start=1, end=1, fps='24'))
    render(root, recipe, None)
    result = json.loads((root/'stages/render/validation.json').read_text())
    assert result['renderer']['engine'] == 'BLENDER_WORKBENCH'
    render(root, recipe, None)
    assert json.loads((root/'stages/render/validation.json').read_text())['reused_frames'] == 1
    recipe['render']['engine'] = 'cycles'
    try: render(root, recipe, None)
    except ValueError as e: assert 'another scene/render configuration' in str(e)
    else: raise AssertionError('Mixed engine receipts were accepted')
print('RENDER_ENGINES_OK', flush=True)
