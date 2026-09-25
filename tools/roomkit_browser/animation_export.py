"""Sample an existing baked mesh animation without regenerating or retiming it."""
import base64
import hashlib

import bpy
import numpy as np


def export_actor(obj, material_id, owner):
    scene = bpy.context.scene
    frames = range(scene.frame_start, scene.frame_end + 1)
    samples, bounds, triangles, checks = [], [], None, []
    ids = None
    for frame in frames:
        scene.frame_set(frame)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            faces = np.array([t.vertices[:] for t in mesh.loop_triangles], dtype=np.uint32)
            if triangles is None:
                triangles = faces
                vertex_count = len(mesh.vertices)
                ids = sorted(set([0, vertex_count // 4, vertex_count // 2, vertex_count - 1]))
            elif len(mesh.vertices) != vertex_count or not np.array_equal(faces, triangles):
                raise ValueError('Animated mesh topology changed: ' + obj.name)
            positions = np.empty((len(mesh.vertices), 3), dtype=np.float32)
            mesh.vertices.foreach_get('co', positions.ravel())
            matrix = np.array(evaluated.matrix_world, dtype=np.float64)
            world = (positions @ matrix[:3, :3].T + matrix[:3, 3]).astype('<f4')
            if not np.isfinite(world).all():
                raise ValueError('Non-finite animated geometry')
            samples.append(world)
            bounds.append([world.min(axis=0).tolist(), world.max(axis=0).tolist()])
            checks.append({'frame': frame, 'vertices': world[ids].tolist(),
                           'sha256': hashlib.sha256(world.tobytes()).hexdigest()})
        finally:
            evaluated.to_mesh_clear()
    array = np.stack(samples)
    fps = scene.render.fps / scene.render.fps_base
    initial = {'name': obj.name, 'owner': owner, 'joint': None,
               'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
               'positions': array[0].ravel().tolist(), 'normals': None,
               'groups': [{'material': material_id, 'indices': triangles.ravel().tolist()}]}
    actor = {'owner': owner, 'mesh_name': obj.name, 'vertex_count': array.shape[1],
             'positions_base64': base64.b64encode(array.tobytes()).decode('ascii'),
             'encoding': 'float32-le-world-xyz', 'bounds': bounds,
             'sample_vertex_ids': ids, 'checks': checks,
             'first_last_max_difference_m': float(np.abs(array[-1] - array[0]).max())}
    scene.frame_set(scene.frame_start)
    return initial, actor, {'frames': len(samples), 'fps': fps,
                            'start_frame': scene.frame_start, 'duration_seconds': len(samples) / fps}
