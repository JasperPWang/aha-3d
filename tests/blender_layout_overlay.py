"""Render an edge behind an opaque plane: depth must hide it, X-ray must show it.

Run in background Blender with --python-exit-code 1, followed by -- OUT_DIR.
"""
import json
from pathlib import Path
import sys
import bpy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/layout_inspection'))
from render_blender import color, collection, feature_edges
from overlay import composite_xray

out = Path(sys.argv[sys.argv.index('--') + 1])
out.mkdir(parents=True, exist_ok=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = scene.render.resolution_y = 128
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.image_settings.color_depth = '8'
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new('Test world')
scene.world.color = (.07, .07, .07)
scene.display.shading.background_type = 'WORLD'
scene.display.render_aa = '16'
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
scene.display.shading.color_type = 'VERTEX'
scene.display.shading.light = 'FLAT'
scene.display.shading.show_shadows = False
scene.display.shading.show_cavity = False
scene.display.shading.show_specular_highlight = False
bpy.ops.object.camera_add(location=(0, 0, 8))
scene.camera = bpy.context.object
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 6
bpy.ops.mesh.primitive_cube_add(size=2)
cube = bpy.context.object
edges = collection('edges')
feature_edges(cube.data, edges, 'hidden cube edges', .16, np.deg2rad(35))
cube.hide_render = True
bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, 2))
plane = bpy.context.object
color(plane.data, [.2, .5, .7])

def render(name):
    path = out / (name + '.png')
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return path

edges.hide_render = True
reference = render('reference')
edges.hide_render = False
depth = render('depth')
plane.hide_render = True
scene.render.film_transparent = True
edge_pass = render('edges')
scene.render.film_transparent = False
xray = out / 'xray.png'
composite_xray(reference, edge_pass, xray, scene)

def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    values = np.array(image.pixels[:]).reshape(128, 128, 4)
    bpy.data.images.remove(image)
    return values

r, d, e, x = map(pixels, [reference, depth, edge_pass, xray])
mask = e[..., 3] > .98
empty = e[..., 3] == 0
assert mask.sum() > 100, 'Edge-only pass is empty or lacks opaque edges'
assert empty.sum() > 100, 'Edge pass does not have a transparent background'
assert np.max(np.abs(r - d)) < 2 / 255, 'Foreground plane did not fully occlude the cube edges'
assert np.max(np.abs(x[empty] - r[empty])) < 2 / 255, 'Compositing changed reference pixels outside edges'
assert np.mean(x[mask, 0]) > .8, 'Hidden orange edges did not survive compositing'
assert np.mean(x[mask, 0] - r[mask, 0]) > .4, 'X-ray is still occluded'
report = {'passed': True, 'opaque_edge_pixels': int(mask.sum()),
          'max_background_error': float(np.max(np.abs(x[empty] - r[empty]))),
          'max_depth_reference_error': float(np.max(np.abs(r - d)))}
(out / 'validation.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
