"""Measure source-selected surfaces from retained triangles of a reference mesh."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from .semantic import digest


class SurfaceRejection(ValueError):
    """An unsupported surface request, never a fallback measurement."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def measurement_support(vertex_count, faces, face_layer, eligible=None):
    supported = np.zeros(vertex_count, bool)
    supported[faces[face_layer == 0].ravel()] = True
    if eligible is not None:
        if eligible.shape != supported.shape:
            raise ValueError('Measurement eligibility shape mismatch')
        supported &= eligible
    return supported


def fit_surface(points, threshold=.025, normal_hint=None, max_angle_degrees=25):
    points = np.asarray(points)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise SurfaceRejection('invalid_surface_points', 'Surface samples must be finite Nx3 coordinates')
    if len(points) < 20:
        code = 'no_eligible_surface_points' if not len(points) else 'insufficient_surface_points'
        raise SurfaceRejection(code, 'Insufficient retained mesh surface samples (at least 20 required)')
    rng = np.random.default_rng(42)
    hint=None
    if normal_hint is not None:
        hint=np.asarray(normal_hint,dtype=float)
        if hint.shape!=(3,) or not np.isfinite(hint).all() or np.linalg.norm(hint)<1e-8:
            raise ValueError('Invalid surface normal hint')
        hint/=np.linalg.norm(hint)
        if not 0 < max_angle_degrees < 90:raise ValueError('Invalid normal angle tolerance')
    sample = points if len(points) <= 15000 else points[rng.choice(len(points),15000,replace=False)]
    best = np.zeros(len(sample),bool)
    for _ in range(120):
        a,b,c = sample[rng.choice(len(sample),3,replace=False)]
        normal = np.cross(b-a,c-a); norm = np.linalg.norm(normal)
        if norm < 1e-8: continue
        normal /= norm
        if hint is not None and abs(normal@hint)<np.cos(np.deg2rad(max_angle_degrees)):continue
        inside = np.abs((sample-a)@normal)<threshold
        if inside.sum()>best.sum():best=inside
    if best.sum()<20 or best.mean()<.3:
        raise SurfaceRejection('unsupported_plane', 'No supported plane in selected mesh region')
    center=sample[best].mean(0)
    _,_,axes=np.linalg.svd(sample[best]-center,full_matrices=False)
    normal=axes[-1]
    if hint is not None and abs(normal@hint)<np.cos(np.deg2rad(max_angle_degrees)):
        raise SurfaceRejection('surface_orientation_mismatch', 'Fitted plane differs from requested surface orientation')
    if normal[np.argmax(np.abs(normal))]<0:normal=-normal
    residual=np.abs((points-center)@normal);good=residual<threshold
    return center,normal,good,residual


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('mesh','config','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    meta=json.loads(a.mesh.with_name('manifest.json').read_text());cfg=json.loads(a.config.read_text())
    mesh_hash=digest(a.mesh)
    if mesh_hash!=meta.get('layers_sha256'):raise ValueError('Mesh bytes differ from manifest')
    with np.load(a.mesh,allow_pickle=False) as z:
        vertices=z['vertices'];faces=z['faces'];face_layer=z['face_layer'];frame_ids=z['frame_indices'];pixel=z['pixel_yx'];source=z['source_frame']
        eligible=z['measurement_valid'] if 'measurement_valid' in z else None
    static=measurement_support(len(vertices),faces,face_layer,eligible)
    del faces,face_layer
    n,h,w=meta['processed_shape_nhw'];bundle=Path(meta['bundle'])
    with np.load(bundle/'inputs.npz') as z:rgb=z['rgb']
    out=a.out;out.mkdir(parents=True,exist_ok=False);results={};support={}
    for request in cfg['surfaces']:
        chosen=[];region_counts=[]
        for roi in request['regions']:
            mask=Image.new('1',(w,h));ImageDraw.Draw(mask).polygon([tuple(v) for v in roi['polygon_uv']],fill=1)
            mask=np.asarray(mask);row=np.flatnonzero(source==roi['source_frame']);inside=mask[pixel[row,0],pixel[row,1]]
            sel=row[inside & static[row]];chosen.extend(sel.tolist())
            region_counts.append(dict(source_frame=roi['source_frame'], polygon_uv=roi['polygon_uv'],
                                      region_vertices=int(inside.sum()), eligible_vertices=len(sel)))
            im=Image.fromarray(rgb[frame_ids.tolist().index(roi['source_frame'])]);draw=ImageDraw.Draw(im);draw.line([tuple(v) for v in roi['polygon_uv']]+[tuple(roi['polygon_uv'][0])],fill='red',width=2)
            im.save(out/f'{request["id"]}_{roi["source_frame"]}.png')
        # Empty selections must retain integer indexing and reach the explicit
        # support rejection, rather than failing with NumPy's float-index error.
        idx=np.unique(np.asarray(chosen,dtype=np.intp));xyz=vertices[idx]
        try:
            center,normal,good,residual=fit_surface(xyz,request.get('plane_threshold_m',.025),
                request.get('normal_hint_world'),request.get('max_normal_angle_degrees',25))
        except SurfaceRejection as error:
            rejection=dict(schema_version=1,status='rejected',code=error.code,reason=str(error),
                surface_id=request['id'],selection=request,selected_vertices=len(idx),
                minimum_surface_points=20,region_selection_counts=region_counts,
                mesh=str(a.mesh.resolve()),mesh_sha256=mesh_hash,config_sha256=digest(a.config),
                world_transform=meta['world_transform'],frame_indices=frame_ids.tolist(),
                processed_size_wh=[w,h],units='Pi3X predicted metres; no physical calibration',
                completed_surface_ids=list(results),measurement_written=False)
            (out/'rejection.json').write_text(json.dumps(rejection,indent=2)+'\n')
            print(json.dumps(rejection,indent=2))
            raise SystemExit(1) from None
        support[request['id']]=idx[good]
        results[request['id']]=dict(center_xyz_m=center.tolist(),normal_xyz=normal.tolist(),plane_offset_m=float(-center@normal),
            support_vertices=int(good.sum()),selected_vertices=len(idx),inlier_fraction=float(good.mean()),
            residual_median_m=float(np.median(residual[good])),residual_p90_m=float(np.percentile(residual[good],90)),
            inlier_bounds_xyz_m=np.percentile(xyz[good],[2,98],axis=0).tolist(),selection=request,
            status='Observed surface fit; bounds are visible support, not completed object dimensions')
    np.savez_compressed(out/'support_vertex_ids.npz',**support)
    report=dict(schema_version=1,mesh=str(a.mesh.resolve()),mesh_sha256=mesh_hash,world_transform=meta['world_transform'],
        frame_indices=frame_ids.tolist(),units='Pi3X predicted metres; no physical calibration',surfaces=results)
    (out/'measurements.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
