"""Export evaluated static Blender geometry once for native-view inspection.

Run with a saved scene open in background Blender. This never saves the scene.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def object_group(original, instance_parent=None):
    """Use authored semantic ownership, never a mesh-name guess.

    Prefer the placed instance's hierarchy for collection instances. The nearest
    tagged ancestor owns a component; a room-wide parent must not merge furniture.
    """
    candidates = [instance_parent, original] if instance_parent is not None else [original]
    for candidate in candidates:
        root = candidate
        while root is not None:
            if root.get('instance_id'):
                return {'id': str(root['instance_id']), 'name': root.name,
                        'semantic_class': str(root.get('semantic_class', 'unknown')),
                        'grouping': 'authored instance_id', 'root_name': root.name}
            root = root.parent
    root = instance_parent if instance_parent is not None else original
    return {'id': 'unassigned:' + root.name, 'name': root.name,
            'semantic_class': 'unknown', 'grouping': 'ungrouped component',
            'root_name': root.name}


def export(out, cameras, frame=1, exclude=()):
    start = time.monotonic()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    source = Path(bpy.data.filepath)
    if not source.is_file():
        raise ValueError('Open a saved scene before exporting')
    camera_data = json.loads(Path(cameras).read_text())
    basis = np.asarray(camera_data['world_transform'], dtype=float)
    if basis.shape != (4, 4) or not np.isfinite(basis).all():
        raise ValueError('Invalid reference world transform')
    scene = bpy.context.scene
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    excluded = set(exclude)
    allowed = set()

    def visit(layer):
        if layer.exclude or layer.collection.hide_render:
            return
        allowed.update(o.name for o in layer.collection.objects)
        for child in layer.children:
            visit(child)

    visit(bpy.context.view_layer.layer_collection)
    vertices, faces, ids, names, groups = [], [], [], [], []
    offset = 0
    for inst in dg.object_instances:
        obj = inst.object
        original = obj.original
        parent = inst.parent.original if inst.is_instance and inst.parent else original
        if parent.name not in allowed or parent.hide_render or original.hide_render:
            continue
        if original.name in excluded or parent.name in excluded:
            continue
        if obj.type in {'CAMERA', 'LIGHT', 'EMPTY', 'ARMATURE', 'LATTICE', 'SPEAKER', 'LIGHT_PROBE'}:
            continue
        if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
            raise ValueError('Unsupported visible geometry: '+obj.name+' ('+obj.type+')')
        mesh = obj.to_mesh()
        try:
            mesh.calc_loop_triangles()
            if not mesh.loop_triangles:
                continue
            xyz = np.empty((len(mesh.vertices), 3), np.float32)
            tri = np.empty((len(mesh.loop_triangles), 3), np.int32)
            mesh.vertices.foreach_get('co', xyz.ravel())
            mesh.loop_triangles.foreach_get('vertices', tri.ravel())
            matrix = np.asarray(inst.matrix_world, dtype=float)
            xyz = (xyz @ matrix[:3, :3].T + matrix[:3, 3]).astype(np.float32)
            if not np.isfinite(xyz).all():
                raise ValueError('Nonfinite evaluated vertices: '+obj.name)
            chain, root = [original.name], original.parent
            while root:
                chain.append(root.name)
                root = root.parent
            names.append(' / '.join(chain))
            groups.append(object_group(original, parent if inst.is_instance else None))
            vertices.append(xyz)
            faces.append(tri + offset)
            ids.append(np.full(len(tri), len(names)-1, np.int32))
            offset += len(xyz)
        finally:
            obj.to_mesh_clear()
    if not faces:
        raise ValueError('No visible triangle geometry')
    geometry = out / 'model.npz'
    np.savez_compressed(geometry, vertices=np.concatenate(vertices),
                        faces=np.concatenate(faces), face_object_id=np.concatenate(ids))
    report = dict(schema_version=1, source_scene=str(source.resolve()),
                  source_scene_sha256=digest(source), cameras_sha256=digest(cameras),
                  geometry_sha256=digest(geometry), world_transform=basis.tolist(),
                  coordinate_policy='Evaluated world coordinates; no extra alignment applied. Caller must author in the reviewed reference basis.',
                  object_names=names, object_groups=groups, frame=frame, excluded_objects=sorted(excluded),
                  vertices=offset, triangles=sum(len(f) for f in faces),
                  seconds=time.monotonic()-start,
                  visibility_policy='Opaque first-hit geometry; shader transparency is not represented.',
                  limits='Static geometry check at the selected frame; world basis is a declared input, not estimated by this exporter.')
    (out / 'model.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--cameras', required=True)
    parser.add_argument('--frame', type=int, default=1)
    parser.add_argument('--exclude', action='append', default=[])
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    export(args.out, args.cameras, args.frame, args.exclude)
