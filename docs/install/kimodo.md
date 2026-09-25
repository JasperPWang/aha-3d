# Install Kimodo for approximate human motion

Kimodo is needed only for generated human motion. It generates approximate actions
and paths; it does not track the person in a reference video. Keep model files outside the source bundle.

## Shared environment and pinned code

Install [the shared core](core.md) once for Kimodo, Pi3X and SAM 3D Body. From the
checkout root:

```bash
bash tools/setup_core.sh --plan
bash tools/setup_core.sh
export KIMODO_ENV="${KIMODO_ENV:-$PWD/.venv}"
source kimodo_blender/env.sh
```

This uses Python 3.11 / Torch 2.7.1 cu128 and pins Kimodo source to
`1aece8c124d73d255ceff5086d983b844c9f4e94`. A compatible NVIDIA driver and C++ compiler
are prerequisites (on Ubuntu, `build-essential` or `gcc-12 g++-12`). The common installer
handles CMake's native executable and protects the shared Torch/Transformers versions.
Interactive Viser/SOMA extras are not required by the batch SMPL-X route. See the
[pinned upstream instructions](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/docs/source/getting_started/installation_virtual_env.md).

## Authorized weights and body assets

Obtain access with your own account to [Kimodo SMPL-X](https://huggingface.co/nvidia/Kimodo-SMPLX-RP-v1)
and [Llama 3 8B Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct).
Authenticate interactively with `hf auth login`; keep its token outside the
checkout and logs. Acquisition and use remain subject to each upstream's terms.
Then, in the environment above:

```bash
python kimodo_blender/download_models.py
test -f "$KIMODO_CHECKPOINT/config.yaml"
```

The download helper uses `KIMODO_ROOT` and `HF_HUB_CACHE` from
`kimodo_blender/env.sh`. It places the Kimodo snapshot
at `kimodo_blender/checkpoints/Kimodo-SMPLX-RP-v1` and downloads these text assets
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

The normal mesh export uses the separately authorized Blender locked-head body
asset: follow [Blender setup](blender.md). The alternative raw-NPZ exporter and
upstream visualizer require `SMPLX_NEUTRAL.npz` from your own [SMPL-X account](https://smpl-x.is.tue.mpg.de/).
For the upstream visualizer, place the removed-head-bun NPZ at
`$KIMODO_UPSTREAM/kimodo/assets/skeletons/smplx22/SMPLX_NEUTRAL.npz`, following
[upstream SMPL-X setup](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/docs/source/getting_started/installation_smpl.md).
This NPZ is not a substitute for the Blender extension's body data.

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

After installing both Blender executables, write a machine-local profile:

```bash
python tools/configure_runtime.py --python "$KIMODO_ENV/bin/python" \
  --blender "$RENDER_BLENDER" --skin-blender "$SKIN_BLENDER" \
  --kimodo "$KIMODO_UPSTREAM" --checkpoint "$KIMODO_CHECKPOINT"
python kimodo_blender/check_runtime.py
```

This creates `configs/runtimes/local.json`; recipes select `"runtime": "local"`.
Optional `--threads N` and `--gpu N` set CPU threads and the GPU index (defaults:
all cores, GPU 0). Set the same `KIMODO_ENV` and source `kimodo_blender/env.sh`
in every shell. The helper validates paths, not model inference or skinning.
Kimodo's Llama 3 8B text encoder is the largest memory consumer; it was validated
on a 96 GB card and is untested on 24 GB. Follow the
[generic scene example](../../examples/README.md) for a new output directory and
validate the full result. Five seconds at 24 fps means 120 output frames; resample
rotations before skinning. Keep source-deployment claims separate from your new
machine's smoke and full-pipeline results.
