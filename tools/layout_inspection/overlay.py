"""Depth-independent overlay compositing and a portable inspection contact sheet."""
import base64
import html
import json
from pathlib import Path

import numpy as np


def alpha_over(reference, edges):
    """Composite straight-alpha edge pixels over an opaque reference, without depth."""
    reference = np.asarray(reference)
    edges = np.asarray(edges)
    if reference.shape != edges.shape or reference.ndim != 3 or reference.shape[-1] != 4:
        raise ValueError('Matching H x W x 4 reference and edge passes required')
    alpha = edges[..., 3:4]
    result = np.ones_like(reference)
    result[..., :3] = edges[..., :3] * alpha + reference[..., :3] * (1 - alpha)
    return result


def composite_xray(reference_path, edges_path, output_path, scene):
    """Load matching Blender PNG passes, composite, and save through its image API."""
    import bpy
    images = []
    try:
        arrays = []
        for path in (reference_path, edges_path):
            image = bpy.data.images.load(str(path), check_existing=False)
            images.append(image)
            image.alpha_mode = 'STRAIGHT'
            width, height = image.size
            pixels = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            arrays.append(pixels.reshape(height, width, 4))
        pixels = alpha_over(*arrays)
        result = bpy.data.images.new('Layout X-ray composite', width=width, height=height, alpha=True)
        images.append(result)
        result.alpha_mode = 'STRAIGHT'
        result.colorspace_settings.name = images[0].colorspace_settings.name
        result.pixels.foreach_set(pixels.ravel())
        result.filepath_raw = str(output_path)
        result.file_format = 'PNG'
        result.save()
    finally:
        for image in images:
            bpy.data.images.remove(image)


def write_report(out, metadata, overview_dir=None, report_path=None):
    """Embed panels so the report works both locally and in Gallery's allowlist."""
    out = Path(out)
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Layout inspection: X-ray and depth</title>',
             '<style>body{font:16px system-ui;margin:24px;background:#202328;color:#eee}'
             '.panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}'
             'figure{margin:0}img{width:100%;height:auto}figcaption{padding:8px 0}'
             'code{overflow-wrap:anywhere}section{margin:32px 0}summary{cursor:pointer}'
             '@media(max-width:650px){.panels{grid-template-columns:1fr}}</style>',
             '<h1>Layout inspection: X-ray and depth</h1>',
             '<p>Start with the numbered object overview when available. It uses one '
             'color per authored ID and faint architecture, omitting internal tile/trim '
             'edges. Open the detailed passes for openings, internal construction and depth.</p>',
             '<p><b>Detailed X-ray</b> puts all retained orange feature edges above the reference '
             'for footprint and proportion review. <b>Depth</b> retains reference-mesh '
             'occlusion. X-ray visibility does not establish correct depth or source fidelity.</p>',
             '<p>Both modes use identical cameras, transforms and crops. Cropped geometry '
             'and filtered feature edges are still absent. Uncertain reference geometry '
             'can occlude in the depth view. Scale follows the input calibration status.</p>',
             '<p>Source scene: <code>' + html.escape(metadata['source_scene']) + '</code></p>']

    def panel(path, label):
        data = base64.b64encode(path.read_bytes()).decode('ascii')
        return '<figure><figcaption>' + html.escape(label) + '</figcaption><img alt="' + html.escape(label, quote=True) + '" src="data:image/png;base64,' + data + '"></figure>'

    for name, view in metadata['views'].items():
        parts.append('<section><h2>' + html.escape(name) + '</h2><p>Common crop XYZ: <code>' +
                     html.escape(json.dumps(view['settings']['crop_xyz_m'])) + '</code></p><div class="panels">')
        if overview_dir is not None:
            for mode,label in [('reference','Object overview on Pi3X reference'),('source','Object overview on original source')]:
                overview=Path(overview_dir)/f'{name}_overview_{mode}.png'
                if overview.exists():parts.append(panel(overview,label))
            parts.append('</div><details><summary>Detailed feature edges and depth comparison</summary><div class="panels">')
        for mode, label in [('overlay_xray', 'X-ray: orange model edges always on top'),
                            ('overlay_depth', 'Depth: reference can occlude model edges')]:
            parts.append(panel(out / f'{name}_{mode}.png', label))
        parts.append('</div>'+('</details>' if overview_dir is not None else '')+'<details><summary>Reference, model and uncertainty</summary><div class="panels">')
        for mode, label in [('reference', 'Rendered Pi3X reference'), ('model', 'Authored model'),
                            ('uncertainty', 'Uncertain reference layers'), ('source', 'Original cached source RGB')]:
            path = out / f'{name}_{mode}.png'
            if path.exists():
                parts.append(panel(path, label))
        parts.append('</div></details></section>')
    parts.append('</html>')
    Path(report_path or out / 'report.html').write_text('\n'.join(parts))
