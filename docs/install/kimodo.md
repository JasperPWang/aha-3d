# Install Kimodo for native G1 robotics motion

Level 3 Robotics extends [Level 1 Static](../INSTALLATION.md#installation-levels).
Kimodo generates native G1 motion with its G1 checkpoint and rigid-link meshes.
It can also generate approximate human actions with its separate SMPL-X checkpoint.
GVHMR and PMPose belong to Level 2 Human reconstruction. Keep model files
outside the source bundle.

## Shared environment and pinned code

Choose Level 3 from the checkout root. The selector prepares
[Static](../PI3X_GEOMETRY_REFERENCE.md#runtime) and adds
[the shared core](core.md) to its Pi3X inference environment:

```bash
bash tools/setup.sh --level robotics --plan
bash tools/setup.sh --level robotics
export KIMODO_ENV="$PWD/.runtime/pi3x-inference/venv"
source kimodo_blender/env.sh
```

This uses Python 3.11 / Torch 2.7.1 cu128 and pins Kimodo source to
`1aece8c124d73d255ceff5086d983b844c9f4e94`. A compatible NVIDIA driver and C++ compiler
are prerequisites (on Ubuntu, `build-essential` or `gcc-12 g++-12`). The common installer
handles CMake's native executable and protects the shared Torch/Transformers versions.
The Robotics core also installs `trimesh` and `fast-simplification` for native
G1 rigid-link mesh processing. Interactive Viser/SOMA extras are not required by
the batch routes. See the
[pinned upstream instructions](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/docs/source/getting_started/installation_virtual_env.md).

## Authorized G1 and text weights

Obtain access with your own account to [Kimodo G1](https://huggingface.co/nvidia/Kimodo-G1-RP-v1)
and [Llama 3 8B Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct).
Authenticate interactively with `hf auth login`; keep its token outside the
checkout and logs. Acquisition and use remain subject to each upstream's terms.
Then, in the environment above:

```bash
python kimodo_blender/download_models.py --model g1
test -f "$CHECKPOINT_DIR/Kimodo-G1-RP-v1/config.yaml"
```

The download helper uses `KIMODO_ROOT` and `HF_HUB_CACHE` from
`kimodo_blender/env.sh`. It places the native G1 snapshot
at `kimodo_blender/checkpoints/Kimodo-G1-RP-v1` and downloads these text assets
to the configured Hugging Face cache:

| Model | Source-deployment snapshot revision |
| --- | --- |
| `meta-llama/Meta-Llama-3-8B-Instruct` | `8afb486c1db24fe5011ec46dfbe5b5dccdb575c2` |
| `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp` | `31474e395ada192e8ed1586db6be79fb3b70c9c0` |
| `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised` | `baa8ebf04a1c2500e61288e7dad65e8ae42601a7` |

The helper downloads current model revisions rather than enforcing those historical
pins. Record the resulting snapshot revisions and checkpoint file paths in your own
installation report before treating a deployment as reproduced. A failed model
access/download is not resolved by a successful Python import.

To add generated human motion, also download
[Kimodo SMPL-X](https://huggingface.co/nvidia/Kimodo-SMPLX-RP-v1) with
`python kimodo_blender/download_models.py --model smplx`, or use `--model both`
for both checkpoints. Human mesh export additionally uses the separately
authorized Blender locked-head body asset: follow [Blender setup](blender.md).
The alternative raw-NPZ exporter and upstream visualizer require
`SMPLX_NEUTRAL.npz` from your own [SMPL-X account](https://smpl-x.is.tue.mpg.de/).
For the upstream visualizer, place the removed-head-bun NPZ at
`$KIMODO_UPSTREAM/kimodo/assets/skeletons/smplx22/SMPLX_NEUTRAL.npz`, following
[upstream SMPL-X setup](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/docs/source/getting_started/installation_smpl.md).
This NPZ is not a substitute for the Blender extension's body data. Native G1
generation does not use these SMPL-X assets.

## Smoke check and register

Check imports and actual CUDA execution on the local GPU:

```bash
python - <<'PY'
import torch, kimodo, motion_correction, transformers, peft
assert torch.cuda.is_available()
x = torch.randn(128, 128, device='cuda')
assert torch.isfinite(x @ x.T).all().item()
torch.cuda.synchronize()
print(torch.__version__, torch.cuda.get_device_name(0), 'KIMODO_IMPORT_CUDA_OK')
PY
```

For native G1, run the selected-model check:

```bash
python kimodo_blender/check_runtime.py --model g1
```

It checks CUDA execution, imports and access to the G1 and Llama configuration
files. It does not load model weights or generate motion. For generated human
motion, run `python kimodo_blender/check_runtime.py --model smplx`; use
`--model both` when both checkpoints are required.

After installing the Blender executables needed by your chosen route, write a
machine-local profile. Native G1 can use the same installed Blender executable
for scene rendering and the skinning field; generated SMPL-X motion needs the
Blender 4.5 skinning executable and body extension described above:

```bash
python tools/configure_runtime.py --python "$KIMODO_ENV/bin/python" \
  --blender "$RENDER_BLENDER" --skin-blender "$SKIN_BLENDER" \
  --kimodo "$KIMODO_UPSTREAM" --checkpoint "$CHECKPOINT_DIR/Kimodo-G1-RP-v1"
```

This creates `configs/runtimes/local.json`; recipes select `"runtime": "local"`.
Optional `--threads N` and `--gpu N` set CPU threads and the GPU index (defaults:
all cores, GPU 0). Set the same `KIMODO_ENV` and source `kimodo_blender/env.sh`
in every shell. The helper validates paths, not model inference or skinning.
Kimodo's Llama 3 8B text encoder is the largest memory consumer; it was validated
on a 96 GB card and is untested on 24 GB. Follow the
[relevant scene example](../../examples/README.md) for a new output directory and
validate the full result. For generated SMPL-X human motion, five seconds at
24 fps means 120 output frames; resample rotations before skinning. Keep
source-deployment claims separate from your new machine's smoke and
full-pipeline results.
