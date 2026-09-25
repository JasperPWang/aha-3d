"""A reversible, per-sampler-call XZ/yaw frame for both Kimodo skeletons.

The upstream multiprompt driver still owns context, blending and postprocessing.
Only the diffusion call sees this local frame; its returned features are restored
before that driver continues. Heights are never translated or prescribed here.
"""
import torch


def rotate_features(rep, features, angle):
    """Rotate raw (unnormalized) Kimodo features without decoding rotations.

    A masked-out rotation is six zeros, not a valid SO(3) matrix. Rotating its
    two columns directly avoids Gram-Schmidt NaNs and preserves model features.
    """
    out = features.clone()
    angle = torch.as_tensor(angle, device=features.device, dtype=features.dtype).reshape(-1)
    angle = angle.expand(len(features))
    c, s = angle.cos(), angle.sin()
    z, one = torch.zeros_like(c), torch.ones_like(c)
    rotation = torch.stack((c,z,s,z,one,z,-s,z,c), -1).reshape(-1,3,3)
    for name in ('smooth_root_pos', 'local_joints_positions', 'global_rot_data', 'velocities'):
        section = rep.slice_dict[name]
        vectors = features[..., section].reshape(len(features), features.shape[1], -1, 3)
        out[..., section] = torch.einsum('bij,btkj->btki', rotation, vectors).flatten(-2)
    section = rep.slice_dict['global_root_heading']
    heading = features[..., section]
    out[..., section] = torch.stack((c[:,None]*heading[...,0]-s[:,None]*heading[...,1],
                                     s[:,None]*heading[...,0]+c[:,None]*heading[...,1]), -1)
    return out


def translate_features(rep, features, offset):
    out = features.clone()
    root = out[..., rep.slice_dict['smooth_root_pos']]
    root[...,0] += offset[:,None,0]
    root[...,2] += offset[:,None,1]
    return out


def validate_mask(rep, mask):
    """A yaw mixes X/Z; reject masks whose scalar constraints cannot rotate."""
    for name in ('smooth_root_pos', 'local_joints_positions', 'global_rot_data', 'velocities'):
        vectors = mask[...,rep.slice_dict[name]].reshape(*mask.shape[:2],-1,3)
        if not torch.equal(vectors[...,0], vectors[...,2]):
            raise ValueError(f'Cannot yaw-transform unpaired X/Z mask: {name}')
    h = mask[...,rep.slice_dict['global_root_heading']]
    if not torch.equal(h[...,0], h[...,1]):
        raise ValueError('Cannot yaw-transform a partial heading mask')


def sample_in_local_frame(model, generate, texts, max_frames, *, receipt=None,
                          save_input=None, **kwargs):
    """Call an existing native sampler at zero initial XZ and heading.

    Constraints and continuation context are already encoded by upstream into
    observed_motion/motion_mask. Transform that entire observation, not just the
    root path. Return to the incoming frame before any native postprocessing.
    """
    rep = model.motion_rep
    observed = rep.unnormalize(kwargs['observed_motion'])
    mask = kwargs['motion_mask'].bool()
    validate_mask(rep, mask)
    heading = torch.as_tensor(kwargs['first_heading_angle'], device=observed.device,
                              dtype=observed.dtype).reshape(-1).expand(len(observed))
    root = observed[...,rep.slice_dict['smooth_root_pos']]
    root_mask = mask[...,rep.slice_dict['smooth_root_pos']]
    origin = torch.where(root_mask[:,0,[0,2]], root[:,0,[0,2]], 0.)
    if not torch.isfinite(heading).all() or not torch.isfinite(observed).all():
        raise ValueError('Nonfinite generation frame or observations')
    local = rotate_features(rep, translate_features(rep, observed, -origin), -heading)
    local = torch.where(mask, local, 0.)
    restored = translate_features(rep, rotate_features(rep, local, heading), origin)
    error = float(torch.where(mask, (restored-observed).abs(), 0.).max())
    if error > 2e-5:
        raise ValueError(f'Constraint frame round-trip error: {error}')
    if save_input is not None:
        save_input(local, mask)
    if receipt is not None:
        receipt.update(origin_xz=origin.detach().cpu().tolist(),
                       incoming_heading_radians=heading.detach().cpu().tolist(),
                       sampler_heading_radians=torch.zeros_like(heading).cpu().tolist(),
                       sampler_first_root_xz=local[:,0,rep.slice_dict['smooth_root_pos']][:,[0,2]].detach().cpu().tolist(),
                       masked_roundtrip_max_error=error,
                       transform='Y-up SE(2); all observations/context transformed; height unchanged')
    call = dict(kwargs, first_heading_angle=torch.zeros_like(heading),
                observed_motion=rep.normalize(local))
    generated = generate(texts, max_frames, **call)
    restored = translate_features(rep, rotate_features(rep, rep.unnormalize(generated), heading), origin)
    return rep.normalize(restored)
