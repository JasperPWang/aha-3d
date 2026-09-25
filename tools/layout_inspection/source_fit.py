"""Compare reviewed source masks with projected object geometry using several diagnostics."""
import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .agent_review import digest
from .object_outline import camera_rays, clipped, silhouette


def bbox(mask):
    y, x = np.nonzero(mask)
    return np.array([x.min(), y.min(), x.max()+1, y.max()+1], float) if len(x) else None


def mask_iou(a, b):
    union = np.count_nonzero(a | b)
    return float(np.count_nonzero(a & b)/union) if union else None


def envelope(mask):
    """Convex support envelope for coarse extent checks, not a visible mask."""
    import cv2
    y,x=np.nonzero(mask)
    result=np.zeros(mask.shape,np.uint8)
    if len(x)>=3:
        cv2.fillConvexPoly(result,cv2.convexHull(np.c_[x,y].astype(np.int32)),1)
    else:
        result[mask]=1
    return result.astype(bool)


def triage(row, boundary_px=12):
    """Separate persistent coarse disagreement from prompt-sensitive evidence."""
    primary=row['support_envelope']['boundary_p95_px']
    alternative=row.get('alternative_prompt',{}).get('support_envelope',{}).get('boundary_p95_px')
    if primary is not None and alternative is not None:
        if primary>boundary_px and alternative>boundary_px:
            return 'needs_attention','outer_boundary_disagreement_under_both_prompts'
        if (primary>boundary_px)!=(alternative>boundary_px):
            return 'segmentation_review_required','coarse_fit_depends_on_prompt'
    return 'visual_review_required','inspect_raw_shape_and_visibility_evidence'


def metrics(reference, model):
    from scipy.ndimage import binary_erosion, distance_transform_edt
    reference, model = np.asarray(reference, bool), np.asarray(model, bool)
    if reference.shape != model.shape or reference.ndim != 2:
        raise ValueError('Reference and model must share the exact 2D pixel grid')
    a, b = bbox(reference), bbox(model)
    result = dict(mask_iou=mask_iou(reference, model), reference_pixels=int(reference.sum()), model_pixels=int(model.sum()),
                  bbox_iou=None, center_delta_px=None, width_ratio=None, height_ratio=None,
                  boundary_mean_px=None, boundary_p95_px=None)
    if a is None or b is None:
        return result
    intersection = np.maximum(0, np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2])).prod()
    result['bbox_iou'] = float(intersection / (np.prod(a[2:]-a[:2])+np.prod(b[2:]-b[:2])-intersection))
    result['center_delta_px'] = ((b[:2]+b[2:]-a[:2]-a[2:])/2).tolist()
    result['width_ratio'], result['height_ratio'] = ((b[2:]-b[:2])/(a[2:]-a[:2])).tolist()
    edge_a = reference & ~binary_erosion(reference); edge_b = model & ~binary_erosion(model)
    distances = np.r_[distance_transform_edt(~edge_a)[edge_b], distance_transform_edt(~edge_b)[edge_a]]
    result['boundary_mean_px'] = float(distances.mean())
    result['boundary_p95_px'] = float(np.percentile(distances,95))
    return result


def warp(mask, parameters):
    import cv2
    tx,ty,sx,sy = parameters
    box = bbox(mask)
    if box is None:
        return mask.copy()
    cx,cy = (box[:2]+box[2:])/2
    matrix = np.array([[sx,0,tx+cx*(1-sx)],[0,sy,ty+cy*(1-sy)]],np.float32)
    return cv2.warpAffine(mask.astype(np.uint8),matrix,(mask.shape[1],mask.shape[0]),flags=cv2.INTER_NEAREST).astype(bool)


def alignment_probe(reference, model):
    """A diagnostic 2D fit, never applied to the scene or cameras."""
    from scipy.optimize import differential_evolution
    a,b = bbox(reference),bbox(model)
    if a is None or b is None:
        return None, model
    delta=(a[:2]+a[2:]-b[:2]-b[2:])/2
    extent=a[2:]-a[:2]
    bounds=[(delta[0]-.3*extent[0],delta[0]+.3*extent[0]),
            (delta[1]-.3*extent[1],delta[1]+.3*extent[1]),(.5,1.6),(.5,1.6)]
    result=differential_evolution(lambda p: -mask_iou(reference,warp(model,p)),bounds,seed=19,
                                  popsize=6,maxiter=16,polish=False,workers=1)
    fitted=warp(model,result.x)
    return dict(parameters=dict(zip(('tx_px','ty_px','scale_x','scale_y'),result.x.tolist())),
                mask_iou=mask_iou(reference,fitted),evaluations=result.nfev,
                meaning='Independent 2D diagnostic search only; not a valid multi-view scene or camera correction.'),fitted


def method_experiment(reference):
    """Controlled source-mask perturbations compare sensitivity to known error types."""
    a=bbox(reference);w,h=a[2:]-a[:2]
    shape=reference.copy();x0,y0,x1,y1=a.astype(int)
    # Remove interior pixels while preserving all box extrema.
    shape[y0+int(h*.25):y0+int(h*.75),x0+int(w*.25):x0+int(w*.75)]=False
    variants={'identity':reference, 'shift':warp(reference,[w*.12,h*.08,1,1]),
              'width_error':warp(reference,[0,0,1.2,1]), 'same_box_shape_error':shape}
    return {name:metrics(reference,mask) for name,mask in variants.items()}


def overlay(rgb, reference, model):
    from scipy.ndimage import binary_erosion
    image=rgb.copy().astype(float)
    image[reference & ~model]=image[reference & ~model]*.55+np.array([45,220,130])*.45
    image[model & ~reference]=image[model & ~reference]*.55+np.array([240,75,160])*.45
    image[reference & ~binary_erosion(reference)]=[45,255,150]
    image[model & ~binary_erosion(model)]=[255,65,180]
    return Image.fromarray(image.astype(np.uint8))


def run(geometry, metadata, outlines, sam3, review, out):
    started=time.monotonic()
    import open3d as o3d
    geometry,metadata,outlines,sam3,review,out=map(Path,(geometry,metadata,outlines,sam3,review,out))
    exported=json.loads(metadata.read_text());data=json.loads(outlines.read_text())
    masks=json.loads(sam3.read_text());selections=json.loads(review.read_text())
    inspection_path=Path(data['source_inspection'],'inspection.json')
    for name,path in (('geometry',geometry),('metadata',metadata),('inspection',inspection_path)):
        if data['input_hashes'][name] != digest(path):
            raise ValueError('Outline input changed: '+name)
    if exported['source_scene_sha256']!=data['source_scene_sha256'] or exported['geometry_sha256']!=digest(geometry):
        raise ValueError('Geometry and outline provenance mismatch')
    if selections['manifest_sha256']!=digest(sam3):
        raise ValueError('Mask review is stale')
    with np.load(geometry) as z: vertices,faces,face_ids=z['vertices'],z['faces'],z['face_object_id']
    inspection=json.loads(inspection_path.read_text())
    transform=np.asarray(inspection['config']['model_to_world']);vertices=vertices@transform[:3,:3].T+transform[:3,3]
    triangles={o['id']:vertices[faces[np.isin(face_ids,o['components'])]] for o in data['objects']}
    out.mkdir(parents=True,exist_ok=False)
    report=dict(schema_version=1,status='requires_review',source_scene_sha256=data['source_scene_sha256'],
                implementation_sha256=digest(__file__),run_id=os.environ.get('INDOOR_RUN_ID'),
                inputs={str(p):digest(p) for p in (geometry,metadata,outlines,sam3,review)},rows=[],
                thresholds={'mask_iou_below':.65,'boundary_p95_above_px':12},
                limits=['SAM3 masks represent visible source pixels and require identity/quality review.',
                        'Low agreement can reflect model, camera, occlusion or mask errors; it does not identify the sole cause.',
                        'Thresholds are triage heuristics, not calibrated acceptance standards.',
                        'Independent 2D fits are diagnostic only and are never applied to scene/cameras.'])
    for record in masks['objects']:
        chosen=selections['selections'].get(record['id'])
        if not chosen:
            report['rows'].append(dict(id=record['id'],status='mask_review_missing'));continue
        variant=next(v for v in record['variants'] if v['variant']==chosen['variant'])
        identity=chosen['object_id'];name=f"source_{record['source_frame']:06d}";view=data['views'][name]
        image_path=Path(record['image'])
        expected_image=inspection_path.parent/f'{name}_source.png'
        if digest(image_path) != digest(expected_image):
            raise ValueError('Mask source does not match the recorded source view')
        if digest(image_path)!=record['image_sha256'] or digest(variant['mask'])!=chosen['mask_sha256']:
            raise ValueError('Reviewed source image or mask changed')
        rgb=np.asarray(Image.open(image_path).convert('RGB'));h,w=rgb.shape[:2]
        reference=np.asarray(Image.open(variant['mask']).convert('L'))>127
        if reference.shape!=(h,w) or [w,h]!=view['size'] or not reference.any():
            raise ValueError('Missing source mask or mismatched native pixel grid')
        isolated=silhouette(triangles[identity],view,w,h,4)
        scene=o3d.t.geometry.RaycastingScene(nthreads=4);target=None
        for key,tri in triangles.items():
            tri=clipped(tri,view['settings']['crop_xyz_m'])
            if not len(tri):continue
            xyz=tri.reshape(-1,3).astype(np.float32)
            gid=scene.add_triangles(o3d.core.Tensor(xyz),o3d.core.Tensor(np.arange(len(xyz),dtype=np.uint32).reshape(-1,3)))
            if key==identity:target=gid
        rays,pose=camera_rays(view,w,h)
        rays[...,:3]=rays[...,:3]@pose[:3,:3].T+pose[:3,3];rays[...,3:]=rays[...,3:]@pose[:3,:3].T
        hits=scene.cast_rays(o3d.core.Tensor(rays),nthreads=4)
        visible=hits['geometry_ids'].numpy()==target if target is not None else np.zeros((h,w),bool)
        direct=metrics(reference,isolated);visible_score=metrics(reference,visible)
        probe,fitted=alignment_probe(reference,isolated)
        reasons=[]
        if direct['mask_iou']<.65:reasons.append('low_isolated_mask_overlap')
        if visible_score['mask_iou'] is not None and visible_score['mask_iou']<.65:reasons.append('low_visible_mask_overlap')
        if direct['boundary_p95_px'] is not None and direct['boundary_p95_px']>12:reasons.append('large_boundary_disagreement')
        row=dict(id=record['id'],object_id=identity,source_frame=record['source_frame'],mask_variant=variant['variant'],
                 mask_review=chosen,isolated=direct,visible=visible_score,
                 model_visible_fraction=float(visible.sum()/max(1,isolated.sum())),alignment_probe=probe,
                 status='needs_attention' if reasons else 'visual_review_required',review_reasons=reasons,
                 source_bbox_xyxy=bbox(reference).tolist(),model_bbox_xyxy=bbox(isolated).tolist() if isolated.any() else None)
        row['method_experiment']=method_experiment(reference)
        ref_envelope, model_envelope=envelope(reference),envelope(isolated)
        row['support_envelope']=metrics(ref_envelope,model_envelope)
        overlay(rgb,ref_envelope,model_envelope).save(out/f'{record["id"]}_envelope.png')
        if chosen.get('alternative_variant'):
            alternative=next(v for v in record['variants'] if v['variant']==chosen['alternative_variant'])
            if digest(alternative['mask']) != chosen['alternative_mask_sha256']:
                raise ValueError('Alternative mask review is stale')
            alt=np.asarray(Image.open(alternative['mask']).convert('L'))>127
            row['alternative_prompt']=dict(variant=alternative['variant'],isolated=metrics(alt,isolated),
                                          support_envelope=metrics(envelope(alt),model_envelope),
                                          agreement_with_primary=mask_iou(alt,reference))
        from scipy.ndimage import binary_fill_holes
        row['filled_holes_sensitivity']=metrics(binary_fill_holes(reference),isolated)
        row['status'],row['primary_reason']=triage(row)
        row['review_reasons'].insert(0,row['primary_reason'])
        overlay(rgb,reference,isolated).save(out/f'{record["id"]}_comparison.png')
        overlay(rgb,reference,visible).save(out/f'{record["id"]}_visible.png')
        overlay(rgb,reference,fitted).save(out/f'{record["id"]}_probe.png')
        np.savez_compressed(out/f'{record["id"]}_masks.npz',reference=reference,isolated=isolated,visible=visible,fitted_probe=fitted)
        row['images']={key:f'{record["id"]}_{key}.png' for key in ('comparison','visible','probe','envelope')}
        report['rows'].append(row)
    report['recommendation']='Use box center/extent deltas and support-envelope boundaries for coarse layout triage when cushion semantics contaminate masks; retain raw mask overlap and paired visible/isolated masks for shape and occlusion review. Convex envelopes bridge concavities and cannot validate detailed geometry. Box IoU alone misses shape errors. Use 2D alignment search only to diagnose possible position/scale error. Choose methods from their sensitivity and source reliability, not one mandatory score.'
    report['status']='needs_attention' if any(r['status']=='needs_attention' for r in report['rows']) else 'requires_review'
    report['elapsed_seconds']=time.monotonic()-started
    (out/'source_fit.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('geometry','metadata','outlines','sam3','review','out'):parser.add_argument('--'+key,required=True)
    report=run(**vars(parser.parse_args()))
    print(json.dumps({'status':report['status'],'rows':[{k:r.get(k) for k in ('id','isolated','visible','alignment_probe','review_reasons')} for r in report['rows']]},indent=2))
