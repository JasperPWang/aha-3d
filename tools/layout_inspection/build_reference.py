"""One entry for Pi3X inference, full-frame semantics and reference meshing."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--video', type=Path)
    source.add_argument('--bundle', type=Path, help='Reuse a complete 32/64-frame Pi3X bundle')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--num-frames', type=int, choices=(32, 64), default=32)
    p.add_argument('--upstream', type=Path, default=Path(os.environ.get('PI3X_UPSTREAM', str(ROOT/'external/Pi3'))))
    p.add_argument('--checkpoint', type=Path)
    p.add_argument('--pi3x-python', type=Path, default=Path(os.environ.get('PI3X_PY', sys.executable)))
    p.add_argument('--semantic-runtime', type=Path, default=ROOT/'.runtime/sam3-segmentation')
    p.add_argument('--semantic-cache', type=Path, help='Reuse a source-matched cache covering every inference frame')
    p.add_argument('--mesh-python', type=Path, default=Path(os.environ.get('PI3X_MESH_PY', str(ROOT/'.runtime/pi3x-mesh/venv/bin/python'))), help='Python runtime with Open3D for default TSDF meshing')
    p.add_argument('--cameras', type=Path, help='Reviewed cameras matching the reused bundle; default bundle cameras.json')
    p.add_argument('--alignment', choices=('auto', 'structural', 'preserve'), default='auto',
                   help='auto fits floor/wall hypotheses unless explicit --cameras preserves an established basis')
    p.add_argument('--alignment-review', type=Path, help='Reviewed floor/wall mask frame selections')
    p.add_argument('--pixel-limit', type=int, default=255000)
    p.add_argument('--confidence', type=float, default=.5)
    p.add_argument('--max-edge', type=float, default=.15)
    p.add_argument('--mesh-method', choices=('tsdf-context', 'grid'), default='tsdf-context')
    p.add_argument('--fusion-confidence', type=float, default=.1,
                   help='Require sigmoid(raw Pi3X conf) > threshold for fusion and visible context')
    p.add_argument('--voxel-size', type=float, default=.03)
    p.add_argument('--human-mask-radius', type=int, default=3,
                   help='Per-frame human exclusion disk radius in processed-image pixels; 0 disables expansion')
    p.add_argument('--reference-views', type=int, choices=(3,4,5), default=5,
                   help='Native-camera source/geometry overlays; does not reduce inference or mesh frames')
    return p


def run(a, runner=subprocess.run):
    if a.human_mask_radius < 0:
        raise ValueError('Human mask radius must be a nonnegative integer')
    if a.video and not a.checkpoint:
        raise ValueError('--checkpoint is required for new video inference')
    if a.video and a.cameras:
        raise ValueError('Reviewed --cameras requires --bundle; new inference creates a new camera basis')
    structural = a.alignment == 'structural' or (a.alignment == 'auto' and not a.cameras)
    if a.cameras and structural:
        raise ValueError('Explicit --cameras preserves an established basis; run structural_alignment separately to propose a revision')
    if a.alignment_review and not structural:
        raise ValueError('--alignment-review requires structural alignment')
    out = a.out.resolve()
    bundle = a.bundle.resolve() if a.bundle else out/'pi3x'
    def call(command):
        runner([str(x) for x in command], cwd=ROOT, check=True)
    out.mkdir(parents=True, exist_ok=False)
    if a.video:
        call([a.pi3x_python, ROOT/'.agents/skills/pi3x-scene-reference/scripts/reconstruct.py',
              '--video', a.video.resolve(), '--upstream', a.upstream.resolve(),
              '--checkpoint', a.checkpoint.resolve(), '--output', bundle,
              '--num-frames', a.num_frames, '--pixel-limit', a.pixel_limit,
              '--confidence', a.confidence])
    inputs = json.loads((bundle/'inputs.json').read_text())
    ids = inputs['frame_indices']
    total = inputs['source_frame_count']
    if len(ids) != min(a.num_frames, total) or ids != sorted(set(ids)) or ids[0] != 0 or ids[-1] != total-1:
        raise ValueError('Bundle must match the selected 32/64 tier and cover both source endpoints')
    cameras = a.cameras.resolve() if a.cameras else bundle/'cameras.json'
    runtime = a.semantic_runtime.resolve()
    masks = a.semantic_cache.resolve() if a.semantic_cache else out/'masks'
    if not a.semantic_cache:
        call([runtime/'venv/bin/python', '-m', 'tools.layout_inspection.semantic',
              '--bundle', bundle, '--out', masks, '--runtime', runtime] +
             (['--structure'] if structural else []))
    mesh_python = a.mesh_python if a.mesh_method == 'tsdf-context' else a.pi3x_python
    if structural:
        call([mesh_python, '-m', 'tools.layout_inspection.structural_alignment',
              '--bundle', bundle, '--semantic-cache', masks, '--cameras', cameras,
              '--out', out/'alignment', '--confidence', a.confidence,
              '--human-mask-radius', a.human_mask_radius] +
             (['--review', a.alignment_review.resolve()] if a.alignment_review else []))
        cameras = out/'alignment/cameras.json'
    call([mesh_python, '-m', 'tools.layout_inspection.prepare',
          '--bundle', bundle, '--cameras', cameras, '--semantic-cache', masks,
          '--out', out/'mesh', '--confidence', a.confidence, '--max-edge', a.max_edge,
          '--mesh-method', a.mesh_method, '--fusion-confidence', a.fusion_confidence,
          '--voxel-size', a.voxel_size, '--human-mask-radius', a.human_mask_radius])
    mesh = json.loads((out/'mesh/manifest.json').read_text())
    if mesh['frame_indices'] != ids:
        raise ValueError('Mesh frame coverage differs from inference')
    if mesh.get('geometry_representation',{}).get('method') != a.mesh_method:
        raise ValueError('Mesh backend differs from requested method')
    call([a.mesh_python, '-m', 'tools.layout_inspection.reference_views',
          '--reference', out/'mesh/layers.npz', '--cameras', cameras,
          '--inputs', bundle/'inputs.npz', '--out', out/'source_views',
          '--view-count', a.reference_views])
    views = json.loads((out/'source_views/reference_views.json').read_text())
    selected = views['source_frame_indices']
    if (len(selected) != min(a.reference_views,len(ids)) or selected != sorted(set(selected))
            or selected[0] != ids[0] or selected[-1] != ids[-1] or any(f not in ids for f in selected)):
        raise ValueError('Source overlay views do not match the requested native coverage')
    report = dict(status='built; visual review required', frame_tier=a.num_frames,
                  frame_indices=ids, bundle=str(bundle), cameras=str(cameras),
                  mesh=str(out/'mesh/layers.npz'), mesh_method=a.mesh_method,
                  mesh_sha256=mesh.get('layers_sha256'), semantic_cache=str(masks),
                  geometry_representation=mesh['geometry_representation'],
                  source_views=str(out/'source_views/reference_views.json'),
                  source_view_frames=selected,
                  alignment=str(out/'alignment/alignment.json') if structural else None,
                  alignment_mode='structural hypothesis' if structural else 'preserved basis',
                  semantic_policy='Every frame processed; zero detections are valid empty masks')
    (out/'reference_build.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    a = parser().parse_args()
    print(json.dumps(run(a), indent=2))


if __name__ == '__main__':
    main()
