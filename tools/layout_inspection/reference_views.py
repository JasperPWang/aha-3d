"""Native-camera Pi3X reference overlays on exact cached source RGB."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_dilation
from .reference_geometry import rays, rigid

CORE_COLOR = np.array([30, 205, 245], np.uint8)
CONTEXT_COLOR = np.array([255, 165, 40], np.uint8)


def select_views(ids, times, count=5, requested=None):
    """Select distinct native observations near evenly spaced source times."""
    ids = np.asarray(ids); times = np.asarray(times, float)
    if (ids.ndim != 1 or not np.issubdtype(ids.dtype, np.integer) or not len(ids)
            or len(set(ids.tolist())) != len(ids) or np.any(np.diff(ids) <= 0)
            or times.shape != ids.shape or not np.isfinite(times).all() or np.any(np.diff(times) <= 0)):
        raise ValueError('Need ordered distinct native frame IDs and timestamps')
    if count not in (3, 4, 5):
        raise ValueError('Reference views must number 3 to 5')
    if requested is not None:
        if (len(requested) not in (3, 4, 5) or list(requested) != sorted(set(requested))
                or any(f not in ids for f in requested)):
            raise ValueError('Select 3 to 5 distinct ordered cached source frames')
        slots = [ids.tolist().index(f) for f in requested]
        third = (times[-1]-times[0])/3
        selected = times[slots]
        if not ((selected <= times[0]+third).any()
                and ((selected >= times[0]+third) & (selected <= times[0]+2*third)).any()
                and (selected >= times[0]+2*third).any()):
            raise ValueError('Selected views must cover early, middle and late source times')
        return slots
    count = min(count, len(ids))
    if count == 1:
        return [0]
    selected = [0]
    for i, target in enumerate(np.linspace(times[0], times[-1], count)[1:-1], 1):
        start = selected[-1]+1
        stop = len(ids)-(count-i-1)
        selected.append(start+int(np.argmin(np.abs(times[start:stop]-target))))
    selected.append(len(ids)-1)
    return selected


def overlay(rgb, depth, roles, person, alpha=.32):
    """Cyan core / amber context; untouched pixels carry no overlay evidence."""
    if not np.isfinite(alpha) or not 0 < alpha <= 1:
        raise ValueError('Overlay opacity must be in (0, 1]')
    hit = np.isfinite(depth) & (depth > 0) & ~person
    colors = np.where((roles == 0)[...,None], CORE_COLOR, CONTEXT_COLOR)
    result = rgb.copy()
    result[hit] = np.rint((1-alpha)*rgb[hit]+alpha*colors[hit]).astype(np.uint8)
    # Surface silhouettes and camera-Z jumps, never every tiny triangle edge.
    edges = np.zeros(hit.shape, bool)
    for axis in (0, 1):
        a = [slice(None),slice(None)]; b = a.copy()
        a[axis] = slice(None,-1); b[axis] = slice(1,None)
        a,b = tuple(a),tuple(b)
        both = hit[a] & hit[b]
        jump = np.zeros(both.shape,bool)
        jump[both] = np.abs(depth[a][both]-depth[b][both]) > np.maximum(.05,.03*np.minimum(depth[a][both],depth[b][both]))
        change = (hit[a] != hit[b]) | jump
        edges[a] |= change; edges[b] |= change
    edges = binary_dilation(edges, iterations=1) & hit
    result[edges] = colors[edges]
    return result, hit, edges


def run(reference, cameras, inputs, out, count=5, requested=None, alpha=.32):
    import open3d as o3d
    reference, cameras, inputs, out = map(Path, (reference,cameras,inputs,out))
    meta = json.loads(reference.with_name('manifest.json').read_text())
    cam = json.loads(cameras.read_text())
    with np.load(inputs,allow_pickle=False) as z:
        rgb, ids, times = z['rgb'], z['frame_indices'], z['timestamps_seconds']
    slots = select_views(ids,times,count,requested)
    n,h,w,_ = rgb.shape
    records = cam['frames']
    if ([r['source_frame'] for r in records] != ids.tolist()
            or not np.allclose([r['timestamp_seconds'] for r in records],times,atol=1e-6,rtol=0)
            or cam['processed_size_wh'] != [w,h]):
        raise ValueError('Camera/RGB native frame, time or raster mismatch')
    hybrid = meta.get('geometry_representation',{}).get('method') == 'tsdf-context'
    prefix = 'display_' if hybrid else ''
    with np.load(reference,allow_pickle=False) as z:
        if (z['frame_indices'].tolist() != ids.tolist() or meta['frame_indices'] != ids.tolist()
                or not np.allclose(z['world_transform'],rigid(cam['world_transform']),atol=1e-6)):
            raise ValueError('Reference frame IDs or world basis differ')
        vertices, colors = z[prefix+'vertices'], z[prefix+'colors']
        faces = z[prefix+'faces']; layers = z[prefix+'face_layer']
        roles = z['display_face_role'] if hybrid else np.zeros(len(faces),np.uint8)
        selected = layers != 1 if hybrid else layers == 0
        faces, roles = faces[selected], roles[selected]
        person = z['layer'].reshape(n,h,w) == 1
        exclusion = z['human_exclusion'].reshape(n,h,w) if 'human_exclusion' in z else person
    mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices),o3d.utility.Vector3iVector(faces))
    scene = o3d.t.geometry.RaycastingScene(nthreads=8)
    if len(faces): scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    out.mkdir(parents=True,exist_ok=False)
    report = dict(schema_version=2,status='rendered; visual review required',
        reference=str(reference.resolve()),cameras=str(cameras.resolve()),inputs=str(inputs.resolve()),
        geometry_method=meta.get('geometry_representation',{}).get('method','grid'),
        all_geometry_frame_indices=ids.tolist(),source_frame_indices=ids[slots].tolist(),
        requested_view_count=count,actual_view_count=len(slots),alpha=alpha,
        selection='Explicit native frames' if requested else 'Nearest available observations at evenly spaced source times; no interpolated cameras',
        legend={'cyan':'TSDF core' if hybrid else 'Retained grid reference','amber':'Approximate retained background/context',
                'contours':'Mesh silhouettes and camera-Z discontinuities; not all triangle edges',
                'unchanged_source_rgb':'No triangle hit or a person-mask/exclusion-margin pixel; not proof of known empty space'},
        pixel_convention='Integer-index centers; native processed raster, exact source pose/K; no independent fit',
        limitations='Own-view projection of the aggregate estimate is a visual consistency check, not independent geometric accuracy. Point fallback glyphs are not rendered. Source-person pixels and their exclusion margin remain untouched in overlays.',
        views=[],artifacts=[])
    cellw = min(w,640); cellh = round(h*cellw/w); rowh = cellh+34
    sheet = Image.new('RGB',(3*cellw,rowh*len(slots)+60),(25,28,35)); draw = ImageDraw.Draw(sheet)
    for col,title in enumerate(('Exact source RGB','Projected reference RGB','Geometry overlay: cyan core / amber context')):
        draw.text((col*cellw+10,12),title,fill='white')
    for row,i in enumerate(slots):
        record = records[i]; pose=rigid(record['c2w']); k=np.asarray(record['intrinsics'],float)
        if k.shape != (3,3) or not np.isfinite(k).all() or min(k[0,0],k[1,1]) <= 0 or not np.allclose(k[2],[0,0,1]):
            raise ValueError('Invalid pinhole camera intrinsics')
        depth = np.full((h,w),np.inf,np.float32); role=np.full((h,w),255,np.uint8)
        rendered = np.full((h,w,3),[30,34,40],np.uint8)
        if len(faces):
            cast = scene.cast_rays(o3d.core.Tensor(rays(k,pose,h,w)))
            depth = cast['t_hit'].numpy(); hit=np.isfinite(depth)
            face = cast['primitive_ids'].numpy()[hit]; uv=cast['primitive_uvs'].numpy()[hit]
            weights = np.column_stack([1-uv.sum(-1),uv])
            rendered[hit] = np.clip((colors[faces[face]]*weights[...,None]).sum(1),0,255).round().astype(np.uint8)
            role[hit] = roles[face]
        combined,visible,edges = overlay(rgb[i],depth,role,exclusion[i],alpha)
        name = f'source_{int(ids[i]):06d}'
        for col,(suffix,pixels) in enumerate((('source',rgb[i]),('reference',rendered),('overlay',combined))):
            file = out/f'{name}_{suffix}.png'; Image.fromarray(pixels).save(file)
            report['artifacts'].append(file.name)
            sheet.paste(Image.fromarray(pixels).resize((cellw,cellh),Image.Resampling.LANCZOS),(col*cellw,60+row*rowh))
        raw = out/f'{name}_projection.npz'
        np.savez_compressed(raw,depth_camera_z=depth,role=role,overlay_visible=visible,contour=edges,
                            person_mask=person[i],human_exclusion=exclusion[i])
        report['artifacts'].append(raw.name)
        report['views'].append(dict(source_frame=int(ids[i]),timestamp_seconds=float(times[i]),
            c2w=record['c2w'],intrinsics=record['intrinsics'],image_size_wh=[w,h],
            mesh_hit_pixels=int(np.isfinite(depth).sum()),overlay_pixels=int(visible.sum()),person_pixels=int(person[i].sum()),
            human_exclusion_pixels=int(exclusion[i].sum())))
        draw.text((10,60+row*rowh+cellh+9),f'Frame {int(ids[i])} | {times[i]:.3f} s | exact cached camera; approximate geometry',fill='white')
    sheet.save(out/'source_overlays.jpg',quality=95)
    report['artifacts'].append('source_overlays.jpg')
    (out/'reference_views.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','cameras','inputs','out'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--view-count',type=int,choices=(3,4,5),default=5)
    p.add_argument('--source-frames',type=int,nargs='+')
    p.add_argument('--alpha',type=float,default=.32)
    a=p.parse_args()
    print(json.dumps(run(a.reference,a.cameras,a.inputs,a.out,a.view_count,a.source_frames,a.alpha),indent=2))


if __name__ == '__main__': main()
