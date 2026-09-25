"""Extract a reviewed faucet or build a facing-target demonstration in background Blender."""
import argparse
import json
import math
from pathlib import Path
import runpy
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from aha3d.io import digest
from aha3d.blender import roomkit as rk
from aha3d.blender.orientation import face_towards, facing_report, get_orientation
from aha3d.blender.semantics import descendants, export_semantics, tag_root
from aha3d.blender.variants import apply_variant

ASSET = ROOT / 'assets/fixtures/v1/simple_faucet'
AUDIT = ROOT / 'runs/asset_orientation_audit/20260910/review_v2/audit.json'


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def extract(out):
    row = next(item for item in json.loads(AUDIT.read_text())['items'] if item['id'] == 'scene/g0055/gooseneck-faucet')
    source = ROOT / row['source_blend']
    original_hash = digest(source)
    assert original_hash == row['source_sha256_verified']
    bpy.ops.wm.open_mainfile(filepath=str(source))
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    mount = Vector(row['mount_world'])
    sink = bpy.data.objects['Island sink inset']
    center = sum((sink.matrix_world @ Vector(corner) for corner in sink.bound_box), Vector()) / 8
    to_sink = center - mount
    to_sink.z = 0
    source_front = Vector(row['likely_front_world'])
    source_dot = source_front.dot(to_sink.normalized())
    parent = bpy.data.objects.new('Reviewed faucet mounting root', None)
    bpy.context.scene.collection.objects.link(parent)
    parent.matrix_world = Matrix.Translation(mount)
    source_names = [record['name'] for record in row['source_parts']]
    for name in source_names:
        original = bpy.data.objects[name]
        obj = original.copy()
        if obj.data:
            obj.data = obj.data.copy()
        bpy.context.scene.collection.objects.link(obj)
        obj.parent = None
        obj.matrix_world = original.matrix_world.copy()
        rk.parent_keep_world(obj, parent)
    orientation = dict(schema_version=1, front_axis='-Y', up_axis='Z', symmetry='none',
        origin='mount_center', semantic_front='spout', status='reviewed',
        evidence='runs/asset_orientation_audit/20260910/review_v2/scene__g0055__gooseneck-faucet/audit.json; mounting-to-spout direction and oblique preview reviewed')
    selection = {'source_frame': 1, 'register_materials': False, 'material_prefix': '__none__',
                 'furniture': [{'root': parent.name, 'name': 'RK Faucet - Simple Gooseneck',
                                'catalog': 'Fixtures/Faucets', 'orientation': orientation,
                                'description': 'Approximate continuous gooseneck spout from g0055; mounting origin; no handle or internal plumbing mechanism.'}]}
    config_path = out / 'faucet_selection.json'
    write(config_path, selection)
    sys.argv = ['export_assets.py', '--', '--config', str(config_path), '--out', str(ASSET)]
    runpy.run_path(str(ROOT / '.agents/skills/blender-roomkit/scripts/export_assets.py'), run_name='__main__')
    assert digest(source) == original_hash
    write(ASSET / 'provenance.json', dict(source=row['source_blend'], source_sha256=original_hash,
        source_parts=source_names, source_mount_world=list(mount), source_front_world=list(source_front),
        source_sink_center_world=list(center), source_toward_sink_dot=source_dot,
        interpretation='Source spout points away from the inset center when dot is negative; this is scene placement, separate from the correct -Y source frame.',
        adaptations=['Copied complete continuous spout', 'Moved placement root to reviewed mounting point', 'Canonical orientation declared; shape unchanged'],
        source_unchanged=True, limitations=['Simplified white-model spout, no handle or internal plumbing']))
    print('FAUCET_EXTRACTED', str(ASSET), 'source_toward_sink_dot', source_dot)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (*color, 1)
    mat.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = .6
    return mat


def build(out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 48
    scene.render.fps = 24
    gray = material('Warm neutral', (.57, .54, .49))
    pale = material('Blue gray', (.38, .56, .61))
    dark = material('Sink inside', (.12, .15, .17))
    rk.box('Ground', (0, 0, -.06), (8, 8, .12), gray)
    table = tag_root(rk.box('Table top', (0, 0, .74), (1.5, 1.5, .08), pale),
                     'furniture/tables', instance_id='table')
    for x in (-.56, .56):
        for y in (-.56, .56):
            rk.box('Table leg', (x, y, .35), (.09, .09, .7), pale)
    chairs = []
    for identity, location in [('east', (1.4, 0, 0)), ('north', (0, 1.4, 0)),
                                ('west', (-1.4, 0, 0)), ('south', (0, -1.4, 0))]:
        chairs.append(rk.place_asset('dining-chair-v1/chair-open-frame-dining', location=location,
            facing_target=table, instance_id='chair-' + identity, project_root=ROOT))
    sofa = rk.place_asset('roomkit-v1/sofa-linen-three-seat', location=(-.1, 2.75, 0),
        facing_target=table, instance_id='sofa', scale=.7, project_root=ROOT)
    sink = tag_root(rk.box('Sink inset', (2.75, .4, .92), (.56, .46, .035), dark),
                    'fixtures/plumbing/sinks', instance_id='sink')
    rk.box('Counter base', (2.75, .4, .44), (.95, .85, .88), pale)
    rk.box('Countertop', (2.75, .4, .90), (1.0, .9, .04), gray)
    # Mount sits behind the basin; the target controls its front independently of yaw conventions.
    faucet = rk.place_asset('faucet-simple-v1/faucet-simple-gooseneck', location=(2.75, .7, .92),
        facing_target=sink, instance_id='faucet', project_root=ROOT)
    cab_a, _ = rk.cabinet('Cabinet A', location=(-2.6, 1.7, 0), size=(.8, .5, .9),
                         layout='mixed', material=pale, interior=gray, instance_id='cabinet-a')
    cab_b, _ = rk.cabinet('Cabinet B', location=(-2.6, .4, 0), size=(.8, .5, .9),
                         layout='three_drawers', material=pale, interior=gray, instance_id='cabinet-b')
    face_towards(cab_a, table)
    face_towards(cab_b, table)
    saved_closed = [obj.matrix_basis.copy() for obj in rk.cabinet_controls(cab_b)]
    rk.set_open(cab_a, .5)
    assert all(obj.matrix_basis == previous for obj, previous in zip(rk.cabinet_controls(cab_b), saved_closed))
    reports = [facing_report(root) for root in chairs + [sofa, faucet, cab_a, cab_b]]
    assert all(report['status'] == 'pass' for report in reports), reports
    scene.world = bpy.data.worlds.new('Demo world')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value = (.7, .7, .7, 1)
    scene.world.node_tree.nodes.get('Background').inputs[1].default_value = .45
    rk.area_light('Key', (1, -5, 7), (0, 0, 0), 1500, 6)
    rk.area_light('Fill', (-4, 1, 5), (0, 0, 1), 900, 5)
    data = bpy.data.cameras.new('Orientation overview')
    camera = bpy.data.objects.new('Orientation overview', data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.location = (7, -9, 9)
    camera.rotation_euler = (Vector((0, .6, .5))-camera.location).to_track_quat('-Z', 'Y').to_euler()
    data.type = 'ORTHO'
    data.ortho_scale = 10.0
    rk.configure_render(scene, 'material', samples=24)
    scene.view_settings.view_transform = 'AgX'
    scene.render.resolution_x, scene.render.resolution_y = 1200, 900
    scene.render.resolution_percentage = 100
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'facing_demo.blend'))
    export_semantics(out / 'facing_demo.semantics.json')
    before = chairs[0].matrix_world.copy()
    recipe = {'schema_version': 1, 'models': [{'selector': {'instance_ids': ['chair-east']},
        'asset_id': 'roomkit-v1/chair-walnut-lounge', 'fit': 'native'}]}
    replacement = apply_variant(recipe, project_root=ROOT)
    matrix_error = max(abs(chairs[0].matrix_world[i][j]-before[i][j]) for i in range(4) for j in range(4))
    assert matrix_error < 1e-6 and facing_report(chairs[0])['status'] == 'pass', (matrix_error, facing_report(chairs[0]))
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'facing_replacement.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(out / 'facing_replacement.blend'))
    reopened = [facing_report(obj) for obj in bpy.context.scene.objects if obj.get('facing_target_json')]
    assert len(reopened) == 8 and all(r['status'] == 'pass' for r in reopened)
    scene = bpy.context.scene
    scene.render.filepath = str(out / 'facing_overview.png')
    bpy.ops.render.render(write_still=True)
    scene.camera.location = (0, .6, 11)
    scene.camera.rotation_euler = (0, 0, 0)
    scene.render.filepath = str(out / 'facing_top.png')
    bpy.ops.render.render(write_still=True)
    scene.camera.location = (3.9, -1.0, 2.0)
    scene.camera.rotation_euler = (Vector((2.75, .46, 1.02))-scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera.data.ortho_scale = 1.45
    scene.render.filepath = str(out / 'faucet_mount.png')
    bpy.ops.render.render(write_still=True)
    write(out / 'integration.json', dict(status='passed', facing_checks=reports,
        replacement=replacement, reopened_facing_checks=reopened,
        independent_cabinet_controls=True, replacement_matrix_max_error=matrix_error,
        render_engine=scene.render.engine, render_device=scene.cycles.device,
        scope='Static synthetic facing fixture; no source camera or human motion requested'))
    print('FACING_DEMO_PASSED', len(reopened))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['extract', 'build'], required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (extract if args.phase == 'extract' else build)(out)


if __name__ == '__main__':
    main()
