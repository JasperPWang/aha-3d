"""Bounded planar chart packing for a diffuse bake, independent of Blender."""
import math


def pack_planar_charts(vertices, faces, mesh_ids, padding=3):
    """Group coplanar triangles per source mesh, then shelf-pack padded charts.

    Projection is shared only by triangles on the same oriented plane in the
    same source mesh. Separate planes cannot overlap in the atlas. Coincident
    source triangles remain coincident; geometry is never displaced or changed.
    Returns triangle-corner UVs and a report of pixel rectangles for verification.
    """
    charts, face_charts = {}, []
    for face_index, (face, mesh_id) in enumerate(zip(faces, mesh_ids)):
        a, b, c = [vertices[i] for i in face]
        ab, ac = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        normal = [ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]]
        length = math.sqrt(sum(v*v for v in normal))
        normal = [v / length for v in normal] if length > 1e-12 else [0., 0., 1.]
        distance = sum(normal[i]*a[i] for i in range(3))
        key = (mesh_id, *(round(v, 5) for v in normal), round(distance, 5))
        if length <= 1e-12:
            key += (face_index,)
        if key not in charts:
            axis = max(range(3), key=lambda i: abs(normal[i]))
            charts[key] = {'axes': [i for i in range(3) if i != axis], 'min': [math.inf]*2, 'max': [-math.inf]*2}
        chart = charts[key]
        for vertex in (a, b, c):
            for j, axis in enumerate(chart['axes']):
                chart['min'][j] = min(chart['min'][j], vertex[axis])
                chart['max'][j] = max(chart['max'][j], vertex[axis])
        face_charts.append(key)
    if not charts:
        raise ValueError('Cannot atlas an empty mesh')
    resolution = 1024
    while resolution*resolution < len(charts)*(2*padding+3)**2*1.5:
        resolution *= 2
    if resolution > 4096:
        raise ValueError('Too many planar charts for a bounded 4096 atlas')
    area = 0.
    for chart in charts.values():
        chart['extent'] = [max(.00001, chart['max'][i]-chart['min'][i]) for i in range(2)]
        area += chart['extent'][0]*chart['extent'][1]
    scale = math.sqrt(resolution*resolution*.65 / max(area, 1e-10))
    for attempt in range(64):
        for chart in charts.values():
            chart['size'] = [max(2, math.ceil(e*scale))+2*padding for e in chart['extent']]
        ordered = sorted(charts.values(), key=lambda c: (-c['size'][1], -c['size'][0]))
        x = y = row_height = 0
        fit = True
        for chart in ordered:
            w, h = chart['size']
            if x+w > resolution:
                y += row_height; x = row_height = 0
            if w > resolution or y+h > resolution:
                fit = False; break
            chart['origin'] = [x, y]; x += w; row_height = max(row_height, h)
        if fit:
            break
        scale *= .85
    else:
        raise ValueError('Planar atlas packing exceeded its bounded attempts')
    uvs = []
    for face, key in zip(faces, face_charts):
        chart = charts[key]
        corners = []
        for index in face:
            vertex = vertices[index]
            corners.append([(chart['origin'][j]+padding+.5+(vertex[axis]-chart['min'][j])/chart['extent'][j]*(chart['size'][j]-2*padding-1))/resolution for j, axis in enumerate(chart['axes'])])
        uvs.append(corners)
    return uvs, {'method': 'oriented coplanar charts with bounded shelf packing', 'resolution': resolution,
                 'charts': len(charts), 'packing_attempts': attempt+1, 'padding':padding,
                 'rectangles': [c['origin']+c['size'] for c in charts.values()]}
