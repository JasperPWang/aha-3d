"""Hash-bound layout evidence and explicit agent review for reference reconstruction.

A technical pass never accepts geometry. Motion inputs are deliberately outside
this contract: bind the saved room-only source, reference and camera, not an
assembled scene containing animated people.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import uuid

ALIASES = {'reference_npz':'reference','cameras_json':'cameras','inputs_npz':'inputs',
           'inspection_config':'config'}
PATH_FIELDS = ('source_scene','reference','cameras','inputs','config','source_video',
               'camera_cache','reference_manifest','inputs_metadata','scale_provenance')
REQUIRED = ('source_scene','reference','cameras','inputs','config','source_video')
MODES = ('reference','model','overlay','uncertainty')
XRAY_MODES = ('overlay_depth','edges','overlay_xray')


def _view_outputs(name, row):
    """Accept the legacy or complete X-ray output set; bind every supplied image."""
    outputs = row.get('outputs', [])
    names = [Path(p).name for p in outputs]
    base = {f'{name}_{mode}.png' for mode in MODES}
    extended = base | {f'{name}_{mode}.png' for mode in XRAY_MODES}
    if len(names) != len(set(names)) or set(names) not in (base, extended):
        raise ValueError('Inspection comparison modes differ: '+name)
    return set(names)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _read(path):
    return json.loads(Path(path).read_text())


def _signature(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _write(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def normalize_spec(spec,base=None):
    """Resolve explicit paths. Identical immutable copies can reuse a review."""
    result=dict(spec);base=Path(base or '.').resolve()
    for old,new in ALIASES.items():
        if old in result:
            if new in result and result[new]!=result[old]:raise ValueError('Conflicting layout input aliases')
            result[new]=result.pop(old)
    for key in REQUIRED:
        if not result.get(key):raise ValueError('Missing layout input: '+key)
    for key in PATH_FIELDS+('review_dir',):
        if result.get(key):result[key]=str((base/Path(result[key])).resolve())
    result.setdefault('reference_manifest',str(Path(result['reference']).with_name('manifest.json')))
    result.setdefault('inputs_metadata',str(Path(result['inputs']).with_suffix('.json')))
    return result


def _binding(spec):
    result={key:digest(spec[key]) for key in PATH_FIELDS if spec.get(key)}
    result['pipeline_context']=_signature(spec.get('pipeline_context',{}))
    result['gate_implementation']=digest(__file__)
    result['camera_validator']=digest(Path(__file__).with_name('camera.py'))
    result['object_review_implementation']=digest(Path(__file__).with_name('object_review.py'))
    result['review_contract']=digest(Path(__file__).with_name('review_contract.py'))
    result['required_object_ids']=_signature(spec.get('required_object_ids',[]))
    return result


def _rigid(matrix,label):
    import numpy as np
    m=np.asarray(matrix,float)
    if m.shape!=(4,4) or not np.isfinite(m).all() or not np.allclose(m[3],[0,0,0,1],atol=1e-6) or not np.allclose(m[:3,:3].T@m[:3,:3],np.eye(3),atol=2e-4) or not np.isclose(np.linalg.det(m[:3,:3]),1,atol=2e-4):
        raise ValueError(label+' must be a proper rigid transform in common units')
    return m


def _technical_inputs(spec):
    import numpy as np
    from .camera import interpolate
    cfg=_read(spec['config']);cam=_read(spec['cameras']);meta=_read(spec['inputs_metadata']);manifest=_read(spec['reference_manifest'])
    hashes=_binding(spec)
    for name,key in (('cameras','cameras_sha256'),('inputs','inputs_sha256')):
        if manifest.get(key)!=hashes[name]:raise ValueError('Prepared reference mismatches '+name)
    if manifest.get('layers_sha256') and manifest['layers_sha256']!=hashes['reference']:raise ValueError('Prepared reference bytes changed')
    if meta.get('source_sha256')!=hashes['source_video']:raise ValueError('Reference RGB source identity differs from video')
    world=_rigid(cam['world_transform'],'Reference world transform')
    _rigid(cfg['model_to_world'],'Model-to-world transform')
    if not str(cfg.get('model_transform_reason','')).strip():raise ValueError('Model transform requires provenance')
    if not str(cam.get('units','')).strip():raise ValueError('Camera metric/scale status is missing')
    with np.load(spec['reference'],allow_pickle=False) as ref:
        if not np.allclose(ref['world_transform'],world,atol=1e-6):raise ValueError('Reference/camera world transforms differ')
        reference_ids=ref['frame_indices'].tolist() if 'frame_indices' in ref else None
    if not np.allclose(manifest['world_transform'],world,atol=1e-6):raise ValueError('Prepared manifest world transform differs')
    with np.load(spec['inputs'],allow_pickle=False) as z:
        ids=z['frame_indices'];times=z['timestamps_seconds']
    if reference_ids!=ids.tolist() or manifest.get('frame_indices')!=ids.tolist():
        raise ValueError('Reference mesh must include all cached inference frames; regenerate semantic masks and mesh without --frames')
    if ids.tolist()!=meta['frame_indices'] or not np.allclose(times,meta['timestamps_seconds'],atol=1e-6,rtol=0):raise ValueError('RGB metadata frame/time mismatch')
    if len(ids)<3 or len(set(ids.tolist()))!=len(ids) or not np.isfinite(times).all() or not (np.diff(times)>0).all():raise ValueError('Need at least three ordered native reference frames')
    frames=cam['frames']
    if [r['source_frame'] for r in frames]!=ids.tolist() or not np.allclose([r['timestamp_seconds'] for r in frames],times,atol=1e-6,rtol=0):raise ValueError('Camera/RGB source frame/time mismatch')
    if cam['processed_size_wh']!=meta['processed_size_wh']:raise ValueError('Camera/RGB raster mismatch')
    for row in frames:
        _rigid(row['c2w'],'Native camera');k=np.asarray(row['intrinsics'],float)
        if k.shape!=(3,3) or not np.isfinite(k).all() or min(k[0,0],k[1,1])<=0 or not np.allclose(k[2],[0,0,1]):raise ValueError('Invalid native camera intrinsics')
    selected=cfg.get('source_frames',[])
    if len(selected)<3 or len(set(selected))!=len(selected) or any(type(f)!=int or f not in ids for f in selected):raise ValueError('Inspection requires three distinct native source frames')
    st=np.array([times[ids.tolist().index(f)] for f in selected]);third=(times[-1]-times[0])/3
    if not ((st<=times[0]+third).any() and ((st>=times[0]+third)&(st<=times[0]+2*third)).any() and (st>=times[0]+2*third).any()):raise ValueError('Inspection must cover early, middle and late source times')
    for name in ('top','front','side'):
        view=cfg.get('views',{}).get(name,{})
        crop=np.asarray(view.get('crop_xyz_m'),float)
        if crop.shape!=(3,2) or not np.isfinite(crop).all() or np.any(crop[:,0]>=crop[:,1]):raise ValueError('Missing explicit shared crop: '+name)
        location=np.asarray(view.get('location'),float);target=np.asarray(view.get('target'),float)
        if location.shape!=(3,) or target.shape!=(3,) or not np.isfinite(location).all() or not np.isfinite(target).all() or np.linalg.norm(location-target)<1e-6 or not np.isfinite(view.get('ortho_scale',0)) or view.get('ortho_scale',0)<=0:raise ValueError('Invalid orthographic camera: '+name)
    cache_report=None
    if spec.get('camera_cache'):
        with np.load(spec['camera_cache'],allow_pickle=False) as z:
            cc=z['c2w'];kk=z['K'];tt=z['time_seconds'];size=z['image_size']
        expected,held=interpolate(cam,tt,cam['processed_size_wh'],size,endpoint='error')
        if cc.shape!=expected['c2w'].shape or kk.shape!=expected['K'].shape or not np.allclose(cc,expected['c2w'],atol=2e-4,rtol=0) or not np.allclose(kk,expected['K'],atol=.01,rtol=0):raise ValueError('Consumer camera cache differs from reviewed native camera/time/scale')
        cache_report=dict(frames=len(tt),held_samples=held,maximum_pose_error=float(np.max(np.abs(cc-expected['c2w']))),maximum_intrinsic_error_px=float(np.max(np.abs(kk-expected['K']))))
    expected_views=['top','front','side']+[f'source_{f:06d}' for f in selected]
    return dict(config=cfg,cameras=cam,input_metadata=meta,hashes=hashes,expected_views=expected_views,camera_cache_check=cache_report,world_transform=world.tolist(),scale_status=cam['units'])


def _inspection(spec,directory,technical):
    """Validate complete concrete evidence, not a producer's existence claim."""
    import numpy as np
    from PIL import Image
    directory=Path(directory).resolve();meta=_read(directory/'inspection.json');files={}
    with np.load(spec['inputs'],allow_pickle=False) as raw:source_rgb=raw['rgb'];source_ids=raw['frame_indices'].tolist()
    for field,key in (('source_scene_sha256','source_scene'),('reference_sha256','reference'),('cameras_sha256','cameras')):
        if meta.get(field)!=technical['hashes'][key]:raise ValueError('Inspection producer input mismatch: '+key)
    if meta.get('config')!=technical['config'] or not np.allclose(meta['world_transform'],technical['world_transform'],atol=1e-6):raise ValueError('Inspection config/world transform differs')
    views=meta.get('views',{});expected=technical['expected_views']
    if set(views)!=set(expected):raise ValueError('Inspection view set differs from required evidence')
    def add(path):
        path=Path(path).resolve()
        if not path.is_relative_to(directory):raise ValueError('Inspection artifact escapes evidence directory')
        if not path.is_file() or path.stat().st_size==0:raise ValueError('Missing or empty inspection artifact: '+str(path))
        files[str(path.relative_to(directory))]=digest(path)
    add(directory/'inspection.json');add(directory/'inspection.blend')
    if meta.get('placement_report'):
        if meta['placement_report']!='placement/report.json':raise ValueError('Invalid placement report path')
        for name in ('report.json','report.html','REPORT.md'):add(directory/'placement'/name)
        placement=_read(directory/'placement/report.json')
        if placement.get('schema_version')!=1 or placement.get('summary',{}).get('accepted') is not False:
            raise ValueError('Invalid placement diagnostic report')
    for name in expected:
        row=views[name];_rigid(row['camera_matrix_world'],'Inspection camera matrix')
        required=_view_outputs(name,row)
        # Renderer paths may be absolute or cwd-relative; only contained, named
        # files are accepted, and the manifest cannot redirect to a different row.
        for filename in required:
            path=directory/filename;add(path)
            with Image.open(path) as im:
                im.load()
                expected_size=technical['cameras']['processed_size_wh'] if name.startswith('source_') else [technical['config'].get('resolution',900)]*2
                if list(im.size)!=list(expected_size):raise ValueError('Inspection image raster differs from configured camera')
        if name.startswith('source_'):
            f=int(name.split('_')[1]);source=next(x for x in technical['cameras']['frames'] if x['source_frame']==f)
            if row.get('settings',{}).get('source_record')!=source:raise ValueError('Inspection native source camera/time differs')
            expected_pose=np.asarray(source['c2w'])@np.diag([1,-1,-1,1])
            if not np.allclose(row['camera_matrix_world'],expected_pose,atol=2e-4,rtol=0):raise ValueError('Native inspection pose differs')
            add(directory/f'{name}_source.png')
            with Image.open(directory/f'{name}_source.png') as im:
                im.load()
                if not np.array_equal(np.asarray(im.convert('RGB')),source_rgb[source_ids.index(f)]):raise ValueError('Inspection source RGB differs from exact native frame')
        else:
            if row.get('settings')!=technical['config']['views'][name]:raise ValueError('Inspection crop/camera settings differ')
            matrix=np.asarray(row['camera_matrix_world'])
            if not np.allclose(matrix[:3,3],row['settings']['location'],atol=1e-5,rtol=0):raise ValueError('Orthographic inspection camera location differs')
            if 'rotation_euler' in row['settings']:
                from scipy.spatial.transform import Rotation
                if not np.allclose(matrix[:3,:3],Rotation.from_euler('xyz',row['settings']['rotation_euler']).as_matrix(),atol=2e-4,rtol=0):raise ValueError('Orthographic inspection orientation differs')
            else:
                forward=np.asarray(row['settings']['target'])-matrix[:3,3];forward/=np.linalg.norm(forward)
                if not np.allclose(-matrix[:3,2],forward,atol=2e-4,rtol=0):raise ValueError('Orthographic inspection aim differs')
    return files


def prepare(spec,evidence_dir,*,runner,object_runner=None):
    """Generate reviewable evidence through runner(spec, new_inspection_dir)."""
    spec=normalize_spec(spec);technical=_technical_inputs(spec)
    out=Path(evidence_dir).resolve();out.mkdir(parents=True,exist_ok=False)
    generated=Path(runner(spec,out/'inspection')).resolve()
    if generated!=out/'inspection':raise ValueError('Runner must use the requested inspection directory')
    if _binding(spec)!=technical['hashes']:raise ValueError('Layout inputs changed during evidence generation')
    artifacts=_inspection(spec,generated,technical)
    from .object_review import generate, packet
    (object_runner or generate)(spec,out)
    objects=packet(spec,out,technical['expected_views'])
    if _binding(spec)!=technical['hashes']:raise ValueError('Layout inputs changed during object evidence generation')
    evidence=dict(schema_version=1,status='awaiting_agent_review',input_binding=technical['hashes'],spec=spec,expected_views=technical['expected_views'],artifacts=artifacts,
        object_artifacts=objects['artifacts'],
        technical=dict(world_transform=technical['world_transform'],scale_status=technical['scale_status'],camera_cache=technical['camera_cache_check']),created_at=datetime.now(timezone.utc).isoformat())
    _write(out/'evidence.json',evidence)
    return evidence


def _current_evidence(spec,evidence_dir,*,recheck_technical=True):
    spec=normalize_spec(spec);out=Path(evidence_dir).resolve();evidence=_read(out/'evidence.json')
    if evidence.get('schema_version')!=1:raise ValueError('Unsupported layout evidence')
    # Consumers (including Blender Python) need only stdlib: unchanged bytes
    # preserve the technical checks performed at generation and agent review.
    technical=_technical_inputs(spec) if recheck_technical else dict(hashes=_binding(spec),expected_views=['top','front','side']+[f'source_{f:06d}' for f in _read(spec['config'])['source_frames']])
    if evidence.get('input_binding')!=technical['hashes']:raise ValueError('Layout inputs changed; regenerate evidence and review')
    if evidence.get('expected_views')!=technical['expected_views']:raise ValueError('Layout review view requirements changed')
    if recheck_technical:
        artifacts=_inspection(spec,out/'inspection',technical)
    else:
        directory=(out/'inspection').resolve()
        names={'inspection.json','inspection.blend'}
        meta=_read(directory/'inspection.json')
        if meta.get('placement_report'):
            if meta['placement_report']!='placement/report.json':raise ValueError('Invalid placement report path')
            names.update('placement/'+n for n in ('report.json','report.html','REPORT.md'))
        for name in technical['expected_views']:
            names.update(_view_outputs(name,meta['views'][name]))
            if name.startswith('source_'):names.add(f'{name}_source.png')
        if set(evidence.get('artifacts',{}))!=names:raise ValueError('Layout inspection artifact inventory differs')
        artifacts={}
        for name in sorted(names):
            path=(directory/name).resolve()
            if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size==0:raise ValueError('Missing or unsafe layout inspection artifact: '+name)
            artifacts[name]=digest(path)
    if evidence.get('artifacts')!=artifacts:raise ValueError('Layout inspection artifacts changed or are missing')
    from .object_review import packet
    objects=packet(spec,out,technical['expected_views'])
    if evidence.get('object_artifacts')!=objects['artifacts']:raise ValueError('Object evidence changed or is missing; regenerate review')
    return evidence,dict(evidence_sha256=digest(out/'evidence.json'),input_binding=technical['hashes'],artifacts=artifacts,object_artifacts=objects['artifacts'])


def record_review(spec,evidence_dir,*,reviewer,notes,verdict,expected_views,visual_review=None):
    """Record an explicit agent decision after inspecting every required view."""
    evidence,binding=_current_evidence(spec,evidence_dir)
    if not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(notes,str) or not notes.strip():raise ValueError('Concrete reviewer identity and layout review notes required')
    if verdict not in ('accepted','rejected'):raise ValueError('Review verdict must be accepted or rejected')
    if list(expected_views)!=evidence['expected_views']:raise ValueError('Agent must explicitly review all expected views in evidence order')
    from .review_contract import validate
    request=review_request(spec,evidence_dir)
    validate(visual_review or {},request['candidate_revision'],request['images'],subjects=request['subjects'],object_views=request['object_views'])
    if visual_review['verdict']!=verdict:raise ValueError('Structured visual verdict differs')
    review=dict(schema_version=2,visual_review=visual_review,reviewer=reviewer.strip(),notes=notes.strip(),verdict=verdict,reviewed_views=list(expected_views),binding=binding,reviewed_at=datetime.now(timezone.utc).isoformat(),scope='room layout/source camera only; not human motion or final delivery')
    target=Path(evidence_dir)/'review.json'
    if target.exists():
        history=Path(evidence_dir)/'review_history';history.mkdir(exist_ok=True)
        _write(history/(digest(target)+'.json'),_read(target))
    _write(target,review);return review


def require_current(spec,evidence_dir):
    evidence,binding=_current_evidence(spec,evidence_dir,recheck_technical=False);review=_read(Path(evidence_dir)/'review.json')
    if review.get('schema_version')!=2 or review.get('verdict')!='accepted':raise ValueError('Layout requires an explicit accepted agent review')
    if not review.get('reviewer') or not review.get('notes') or review.get('reviewed_views')!=evidence['expected_views'] or review.get('binding')!=binding:raise ValueError('Layout review is missing, stale, or incomplete')
    from .review_contract import validate
    request=review_request(spec,evidence_dir)
    validate(review.get('visual_review',{}),request['candidate_revision'],request['images'],subjects=request['subjects'],object_views=request['object_views'])
    return dict(status='accepted',scope=review['scope'],reviewer=review['reviewer'],review_sha256=digest(Path(evidence_dir)/'review.json'),evidence_sha256=binding['evidence_sha256'])


def validate_layout(manifest,manifest_path,*,diagnostic=False):
    """Validate or provide actionable agent workflow guidance; no user approval."""
    try:
        return _validate_layout(manifest,manifest_path,diagnostic=diagnostic)
    except (OSError,ValueError,KeyError) as exc:
        raise ValueError(str(exc)+'. Generate layout evidence with layout_gate.prepare() or the pipeline layout stage, inspect every required orthographic/overlay/source view, record the agent verdict with layout_gate.record_review() or tools/indoor review-layout, then resume. Missing or stale evidence requires regeneration; technical checks alone do not accept geometry.') from exc


def review_request(spec,evidence_dir):
    """Exact image packet for an image-capable reviewer; no inferred visual pass."""
    evidence,binding=_current_evidence(spec,evidence_dir,recheck_technical=False)
    directory=Path(evidence_dir)/'inspection'
    images={}
    metadata=_read(directory/'inspection.json')
    for view in evidence['expected_views']:
        outputs=_view_outputs(view,metadata['views'][view])
        modes=MODES + XRAY_MODES if f'{view}_overlay_xray.png' in outputs else MODES
        for mode in modes:
            images[view+':'+mode]=str(directory/f'{view}_{mode}.png')
        if view.startswith('source_'):
            images[view+':source']=str(directory/f'{view}_source.png')
    from .review_contract import ASPECTS
    from .object_review import packet
    objects=packet(normalize_spec(spec),evidence_dir,evidence['expected_views'])
    images.update(objects['images'])
    return dict(candidate_revision=_signature(binding),images=images,coverage=list(ASPECTS),
                subjects=sorted(objects['object_views']),object_views=objects['object_views'])


def _validate_layout(manifest,manifest_path,*,diagnostic=False):
    """Scope is authoritative even if a downstream manifest omits source_video."""
    if diagnostic:return dict(status='awaiting_review',accepted=False,purpose='diagnostic')
    from .acceptance import consumer_scope
    scope,state,out=consumer_scope(manifest,manifest_path)
    if not scope['reference_reconstruction']:
        return dict(status='not_applicable',accepted=False,reason='Explicit text-authored room scope')
    base=Path(manifest_path).resolve().parent;render=manifest.get('render',{});raw=manifest.get('layout_gate')
    if not isinstance(raw,dict):raise ValueError('Reference reconstruction requires layout_gate evidence and explicit agent review')
    spec=normalize_spec(raw,base)
    if not spec.get('review_dir') or not spec.get('camera_cache'):raise ValueError('Reference consumer requires review_dir and camera_cache')
    if digest(spec['source_video'])!=scope['source_video']['sha256']:raise ValueError('Layout source differs from persisted task scope')
    for key,field in (('source_video','source_video'),('scene','source_scene'),('camera_cache','camera_cache')):
        if not render.get(key) or Path(spec[field])!=(base/render[key]).resolve():raise ValueError('Consumer '+key+' differs from reviewed room inputs')
    result=require_current(spec,spec['review_dir'])
    for finding in _read(out/'findings.json')['findings']:
        if finding['severity']=='blocking' and (finding['status']!='resolved' or finding.get('resolution',{}).get('candidate_revision')!=state['candidate']):
            raise ValueError('OPEN_FINDING: '+finding['id'])
    return result
