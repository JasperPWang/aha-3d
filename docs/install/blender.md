# Install Blender and the SMPL-X skinning extension

Room assembly/rendering and body skinning use separate executables in the recorded
deployment. Baked final room animations play without Kimodo or a body add-on.

| Role | Recorded compatibility target |
| --- | --- |
| Reusable asset libraries and final assembly | Blender 5.2.1, the version that saved the supplied libraries |
| SMPL-X mesh skinning | Blender 4.5.0 with `smplx_blender_addon` extension 1.0.3 |

## Executables

Acquire official binaries for your OS/architecture from [Blender downloads](https://www.blender.org/download/)
or the [release archive](https://download.blender.org/release/). Extract them into
separate user-owned directories, preserving each version's bundled Python. The 5.2.1 designation is
source-deployment provenance, not a claim that every mirror currently provides
that release. If it is unavailable, obtain a compatible approved build and verify
that it can open the libraries before continuing; do not silently select an older
major version.

```bash
export RENDER_BLENDER=/path/to/blender-render/blender
export SKIN_BLENDER=/path/to/blender-4.5/blender
"$RENDER_BLENDER" --version
"$SKIN_BLENDER" --version
```

Linux binaries also need the distribution's X11/OpenGL shared libraries; on a
minimal Ubuntu or WSL2 install add them with the system package manager (for
example `libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libgl1`)
rather than altering the ML environment. Cycles uses the GPU through CUDA/OptiX,
which works under WSL2 with the Windows NVIDIA driver.

## Authorized extension and body data

Use the original [SMPL-X for Blender project](https://gitlab.tuebingen.mpg.de/jtesch/smplx_blender_addon)
and the download area of your own [SMPL-X account](https://smpl-x.is.tue.mpg.de/). Obtain the Blender 4.5 extension and its authorized body data. In Blender 4.5,
install the extension ZIP through Preferences, using the `user_default` extension
repository, and enable it. Follow its distribution's data installation directions. The recorded extension manifest identifies version `1.0.3`, minimum Blender
`4.5.0`, and extension ID `smplx_blender_addon`; its body data contains
`data/smplx_model_lh_20230302.blend`. Neither the ZIP nor that licensed file is in
this bundle.

The adapter in `kimodo_blender/export_body_addon.py` requires:

- Module `bl_ext.user_default.smplx_blender_addon`.
- `bpy.context.window_manager.smplx_tool` and `bpy.ops.object.smplx_add_animation`.
- The `locked_head` model, `UV_2023` layout and AMASS animation import with pose
  correctives.

The [Meshcapade add-on](https://github.com/Meshcapade/SMPL_blender_addon) is related
upstream software with separate data acquisition instructions; its current
`meshcapade_addon` API is not established as a drop-in replacement for this adapter.
Installing a raw `SMPLX_NEUTRAL.npz` alone also does not satisfy these requirements.

## Verify and register

Run the extension smoke check with the same user configuration that future
runs will use (do not use factory startup for this check):

```bash
"$SKIN_BLENDER" --background --python-exit-code 1 --python-expr \
  "import bpy, addon_utils; addon_utils.enable('bl_ext.user_default.smplx_blender_addon', default_set=False); assert hasattr(bpy.context.window_manager, 'smplx_tool'); assert hasattr(bpy.ops.object, 'smplx_add_animation'); print('SMPLX_EXTENSION_API_OK')"
"$RENDER_BLENDER" --background --factory-startup --python-exit-code 1 --python-expr \
  "import bpy; print(bpy.app.version_string); assert hasattr(bpy.types, 'ShaderNodeBsdfPrincipled'); print('BLENDER_API_OK')"
```

These checks do not load the licensed body or validate skinning. After producing
a valid resampled AMASS motion, the real adapter invocation is:

```bash
"$SKIN_BLENDER" --background --python-exit-code 1 \
  --python kimodo_blender/export_body_addon.py -- \
  --motion /path/to/prepared_motion.npz --out /path/to/new_body_output.npz
```

Use the registration command in [Kimodo setup](kimodo.md#smoke-check-and-register)
to save both executable paths. Then run a generic scene example, reopen its saved
blend, inspect representative rendered frames, and verify timing/full video decode.
Asset-file compatibility, import checks, body deformation and final rendering are
separate checks.
