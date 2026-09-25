# Rendering engines

Daily room, camera and motion review defaults to fast raster rendering:

| Requested appearance | Automatic engine | Quality policy |
| --- | --- | --- |
| Clay / white model | Workbench | Matcap, cavity, shadows, 16-sample AA; original materials retained |
| Material preview | EEVEE | Shader materials and scene lights, requested samples, Raytracing disabled |
| Explicit final quality | Cycles | Path tracing and denoising; explicitly select GPU or CPU |

This changes rendering, not authored geometry, camera timing or body motion.
EEVEE previews can differ from Cycles in indirect light, reflection, glass and
exposure. Review representative frames before a full video. Workbench does not
evaluate material shader nodes and is rejected for material-mode rendering.

For full-render preflight, job waiting and final review, follow
[render execution](RENDER_EXECUTION.md).

## Standalone clips and stills

Use the configured Blender executable on the workstation GPU:

```bash
"$BLENDER_BIN" -b /absolute/scene.blend --python-exit-code 1 \
  --python .agents/skills/blender-roomkit/scripts/render_clip.py -- \
  --out /absolute/new-preview --mode material --samples 32 --stills 1,60,120
```

Use `--mode clay` for white models. For final path-traced material output add
`--engine cycles --samples 48`. Explicit `--cycles-device CPU` allows CPU
Cycles. A missing GPU or graphics context must fail clearly; helpers do not
silently turn a fast preview into a slow CPU render. Omit `--stills` and supply
`--ffmpeg` for the complete configured timeline. The legacy clip helper's camera
export restrictions remain documented in the skill's workflow reference.

Task-specific scripts should call
`roomkit.configure_render(scene, mode, samples, engine='auto')` in each render
process. It returns the actual engine/settings for the run report. New material
renders clear clay overrides without modifying the source file. Source lighting
must already exist. Write distinct outputs and preserve the original blend.

## Pipeline recipes

```json
{"render": {"mode": "material", "engine": "auto", "samples": 32}}
```

New recipes default to material/auto (EEVEE). Explicit clay/auto uses Workbench.
Explicit `engine: cycles` selects path tracing. `mode: preserve` keeps source
material overrides and color settings, and auto keeps its saved engine; it is
an explicit preservation option, not the default. EEVEE raytracing remains off.
Assembly records the actual renderer. Rendering reopens and uses that saved
engine instead of forcing Cycles, configuring its process-local devices again.
Frame receipts bind engine settings and reject mixed configurations.

`indoor preview RUN` defaults to the GPU and fast engines; explicit
`--backend cpu` retains the CPU Cycles route for machines without a graphics
context. Explicit Cycles recipes retain their requested engine. Low-resolution
full-timeline previews and native-resolution keyframes report their settings.
Already prepared immutable snapshots keep their old renderer implementation;
prepare a new run to adopt this change. Active scene-specific scripts do not
change automatically and must adopt the shared helper for future renders.

## Performance boundaries

Keep scene, camera, frame IDs, resolution and hardware fixed for comparisons.
Report first-frame compilation/setup separately from subsequent frame timings.
The elapsed render operator includes synchronization and PNG output. It does
not isolate raster/trace time from CPU scene evaluation or file I/O.

No-RT rendering does not remove model import, dependency graph updates,
modifier/shape-key evaluation, reference clipping, edge-mesh construction,
PNG encoding or shared-filesystem writes. Pi3X layout inspection already uses
Workbench; its geometry preparation needs separate profiling. Frame output,
full video decoding and timing checks remain part of delivery.

## Validation baseline

On 2026-09-12, Blender 5.2.1 on one 96 GB RTX PRO 6000 rendered five native camera
views of an existing indoor room at 1280 x 720, with the same saved scene for
each recipe. Median render-operator times excluding each recipe's first frame:

| Preview recipe | Seconds/frame | Cycles comparison | Speed ratio |
| --- | --- | --- | --- |
| Workbench clay, 16 AA | 0.215 | Clay, 16 samples: 1.095 | 5.1x |
| EEVEE material, 32 samples, RT off | 0.232 | Material, 48 samples: 1.344 | 5.8x |

These compare preview recipes, including different shading and sampling, not
identical-quality engines. They are five-frame measurements, not full-video
throughput guarantees. First-frame times were 0.576/1.570 s for Workbench/EEVEE.
All five views were reviewed; EEVEE retained recognizable materials and layout,
with visible reflection/indirect-light differences. Workbench emphasizes shape.

Real Blender checks cover engine selection, shader retention, clay override
removal in material mode, saved Workbench reopening and frame receipt reuse.
Both fast engines also passed a 12-frame, one-second synthetic animation render
and complete MP4 decode. Pipeline preview renders and keyframes preserved an
explicit exposure setting. Headless EEVEE and Workbench succeeded on that GPU;
other Blender/driver combinations, including WSL2's OpenGL path and 24 GB cards,
still need a runtime check. If fast engines lack a graphics context, use
`--backend cpu` or an explicit Cycles recipe.
