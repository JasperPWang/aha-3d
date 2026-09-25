#!/usr/bin/env python3
"""Build one source/room/method review page from source-bound case manifests.

Artifact paths are repository-relative. No server-side code or model API is used.
The page keeps diagnostics visible and synchronizes all video panels in seconds.
"""
from pathlib import Path
import argparse,json,hashlib,os,math
if __package__:
    from .inspection_bundle import bundle_artifacts
else:
    from inspection_bundle import bundle_artifacts
ROOT=Path(__file__).resolve().parents[2]
TEMPLATE=Path(__file__).with_name('portal.html')

def validate_review(case):
    """Bind the three-panel comparison to explicit retained/new variants."""
    review = case.get('review')
    if review is None:
        return
    if not isinstance(review, dict):
        raise ValueError('review must be an object')
    variants = {v['id']: v for v in case['variants']}
    previous = review.get('previous_variant')
    new = review.get('new_variants')
    if not isinstance(previous, str) or previous not in variants or not isinstance(new, list) or not new:
        raise ValueError('Review requires a known previous variant and new variants')
    if any(not isinstance(x, str) or x not in variants for x in new) or len(new) != len(set(new)):
        raise ValueError('Review new variants must be unique known IDs')
    if previous in new or review.get('default_new_variant') not in new:
        raise ValueError('Review previous and new comparison roles must be distinct')
    old_video = (ROOT / variants[previous]['video']).resolve()
    source_video = (ROOT / case['source_video']).resolve()
    new_videos = [(ROOT / variants[x]['video']).resolve() for x in new]
    if old_video == source_video or any(v in (old_video, source_video) for v in new_videos) or len(set(new_videos)) != len(new_videos):
        raise ValueError('New comparison requires its own rendered video, not source/control reuse')
    for key in ('actor_hint','verdict','change','explanation','source_caption','previous_caption'):
        if not isinstance(review.get(key), str) or not review[key].strip():
            raise ValueError('Review requires plain-language ' + key)
    points = review.get('watch_points')
    if not isinstance(points, list) or not points:
        raise ValueError('Review requires useful watch points')
    for point in points:
        if (not isinstance(point, dict) or type(point.get('frame')) is not int
                or not 0 <= point['frame'] < case['frames']
                or any(not isinstance(point.get(k), str) or not point[k].strip() for k in ('label','explanation'))):
            raise ValueError('Watch point requires an in-range source frame and explanation')

def build(manifests, output):
    cases=[];missing=[]
    for path in manifests:
        case=json.loads(path.read_text());seen=set()
        for required in ('id','title','frames','fps','source_video','variants'):
            if required not in case:raise ValueError(f'{path}: missing {required}')
        if type(case['frames']) is not int or case['frames']<1 or type(case['fps']) not in (int,float) or not math.isfinite(case['fps']) or case['fps']<=0:raise ValueError('Invalid timing')
        exit_frame = case.get('track_exit_frame')
        if exit_frame is not None and (type(exit_frame) is not int or not 0 <= exit_frame < case['frames']):
            raise ValueError('Track exit must be a source-frame index within the clip')
        if not isinstance(case['variants'],list) or not case['variants']:
            raise ValueError('At least one variant including a GVHMR baseline is required')
        for v in case['variants']:
            if not isinstance(v,dict) or any(not isinstance(v.get(k),str) or not v[k].strip() for k in ('id','label','method','status','video')):
                raise ValueError('Variant requires id, label, method, status and video')
            if v['status'] not in ('accepted','diagnostic','rejected','pending'):
                raise ValueError('Unknown variant status')
            if v['id'] in seen:raise ValueError(f'Duplicate variant {v["id"]}')
            seen.add(v['id'])
        if 'baseline' not in seen:
            raise ValueError('A baseline variant is required; generated motion must not be presented as GVHMR')
        for key in ('default_left_variant', 'default_right_variant'):
            if key in case and case[key] not in seen:
                raise ValueError('Unknown default variant: ' + str(case[key]))
        validate_review(case)
        evidence = case.get('evidence', [])
        if not isinstance(evidence, list) or any(not isinstance(e, dict) or not isinstance(e.get('label'), str) or not e['label'].strip() or sum(bool(e.get(k)) for k in ('video', 'figure', 'report')) != 1 for e in evidence):
            raise ValueError('Evidence requires a label and one video, figure or report')
        for record in [case,*case['variants'],*evidence]:
            if record.get('bundle'):
                if not record.get('report'):
                    raise ValueError('An inspection bundle requires its entry report')
                bundle_artifacts(ROOT / record['bundle'], root=ROOT, entry=ROOT / record['report'])
            for key in ('source_video','source_original','room_blend','report','video','blend','motion','figure','attribution','bundle'):
                value=record.get(key)
                if not value:continue
                artifact=(ROOT/value).resolve()
                if not artifact.is_relative_to(ROOT):raise ValueError('Artifact outside repository')
                if not artifact.is_file():missing.append(str(artifact))
                record[key]=os.path.relpath(artifact,output.parent)
        case['manifest_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();cases.append(case)
    if missing:raise FileNotFoundError('\n'.join(missing))
    if len({c['id'] for c in cases})!=len(cases):raise ValueError('Duplicate case')
    output.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(cases,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    output.write_text(TEMPLATE.read_text().replace('__CASE_DATA__',data))
    report={'cases':len(cases),'featured_comparisons':sum(bool(c.get('review')) for c in cases),'variants':sum(len(c['variants']) for c in cases),'artifacts_exist':True,'manifest_files':[str(p) for p in manifests],'output':str(output),'html_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'validation_scope':'Artifact existence/schema and explicit previous/new roles; video full decoding and saved-scene checks are separate.'}
    output.with_name('portal_build.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,action='append',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.manifest,a.output.resolve())
