"""Experimental generated human/object sequences, in one explicit world frame.

Scene motion is prescribed kinematics. This is not a force-controlled simulator.
"""
from copy import copy
import numpy as np
from scipy.interpolate import PchipInterpolator

KIMODO_TO_ROOM = np.array([[-1., 0, 0], [0, 0, 1.], [0, 1., 0]])
FOOT_PATCHES = ('left_heel', 'left_toe', 'right_heel', 'right_toe')


def generation_origin(root_xy, floor_height):
    """Scene origin in native axes; heights remain measured above the floor."""
    xy = np.asarray(root_xy, dtype=float)
    return np.array([-xy[0], float(floor_height), xy[1]])


def room_to_generation(points, origin):
    return np.asarray(points) @ KIMODO_TO_ROOM - np.asarray(origin)


def restore_scene_horizontal(motion, origin):
    """Restore XZ once at export; downstream skinning adds scene floor Y once.

    Native rotations, headings, velocities and contact labels are unchanged.
    """
    offset = np.asarray(origin) * [1, 0, 1]
    return {key: value + offset.astype(value.dtype)
            if key in ('root_positions', 'smooth_root_pos', 'posed_joints') else value
            for key, value in motion.items()}


def foot_contact_strength(contacts):
    """Preserve Kimodo's four independent ankle/toe support channels."""
    values = np.asarray(contacts, dtype=float)
    if values.ndim != 2 or values.shape[1] != 4 or not np.isfinite(values).all():
        raise ValueError('Expected finite [frames, 4] foot contact labels')
    if np.any((values < 0) | (values > 1)):
        raise ValueError('Foot contact labels must be in [0, 1]')
    return np.where(values > .5, values, 0.)


def split_sole_patch(rest, vertex_ids, ankle, toe):
    """Partition a sole along its own ankle-to-toe axis in the rest pose."""
    axis = np.asarray(toe)[[0, 2]] - np.asarray(ankle)[[0, 2]]
    length = np.linalg.norm(axis)
    if length < 1e-6:
        raise ValueError('Degenerate foot axis')
    projection = (rest[vertex_ids][:, [0, 2]] - np.asarray(ankle)[[0, 2]]) @ (axis / length)
    heel, forefoot = vertex_ids[projection < length / 2], vertex_ids[projection >= length / 2]
    if not len(heel) or not len(forefoot):
        raise ValueError('Sole must contain both heel and toe patches')
    return heel, forefoot


def contact_envelope(times, interval, ramp=.3, lead=0.):
    """Optional finite contact, including release before a later action."""
    t = np.asarray(times)
    if interval is None:
        return np.zeros(len(t))
    a, b = np.asarray(interval, dtype=float)
    if not np.isfinite([a, b]).all() or a < 0 or b <= a:
        raise ValueError('Contact interval must have finite increasing nonnegative times')
    return np.clip((t-a+lead)/ramp, 0, 1)*np.clip((b-t)/ramp, 0, 1)


def compile_plan(plan):
    fps = plan['fps']
    segments = plan['segments']
    if fps != 30 or not segments:
        raise ValueError('Native Kimodo 30 FPS and nonempty segments required')
    frames = [round(s['seconds'] * fps) for s in segments]
    if any(n < 2 or n > 300 for n in frames):
        raise ValueError('Each prompt must have 2 to 300 native frames')
    n = sum(frames)
    t = np.arange(n) / fps
    def curve(keys):
        a = np.array(keys, float)
        if a.ndim != 2 or not np.isfinite(a).all() or np.any(np.diff(a[:, 0]) <= 0):
            raise ValueError('Finite, increasing key times required')
        if a[0, 0] > 0 or a[-1, 0] < t[-1]:
            raise ValueError('Keys must cover complete sequence')
        return PchipInterpolator(a[:, 0], a[:, 1:], axis=0)(t)
    root = curve(plan['root_xy_keys'])
    heading = curve(plan['heading_keys'])[:, 0]
    obj = curve(plan['object_translation_keys'])
    hand_interval = plan.get('hand_contact_seconds')
    hand_on = np.zeros(n, dtype=bool)
    if hand_interval is not None:
        contact_envelope(t, hand_interval)  # validate before downstream inference
        start, end = hand_interval
        hand_on = (t >= start) & (t <= end)
        if not hand_on.any():
            raise ValueError('Hand contact interval has no samples')
        if 'hand_surface_point' not in plan:
            raise ValueError('Hand contact requires a surface point')
    elif plan.get('hand_orientation') is not None or 'hand_surface_keys' in plan:
        raise ValueError('Hand orientation/path requires an active contact interval')
    hand = (curve(plan['hand_surface_keys']) if 'hand_surface_keys' in plan
            else np.asarray(plan.get('hand_surface_point', [0, 0, 0]))) + obj
    seat = np.asarray(plan.get('seat_point', [0, 0, 0])) + obj
    if plan.get('seat_contact_seconds') is not None and 'seat_point' not in plan:
        raise ValueError('Seat contact requires a seat point')
    if plan.get('seat_contact_seconds') is not None:
        contact_envelope(t, plan['seat_contact_seconds'])
    coupling = plan.get('root_hand_coupling')
    root_binding = np.zeros(n)
    if coupling is not None:
        if hand_interval is None:
            raise ValueError('Root-hand coupling requires hand contact')
        offset = np.asarray(coupling['root_from_hand_xy'], dtype=float)
        transition = float(coupling.get('transition_seconds', .4))
        if offset.shape != (2,) or not np.isfinite(offset).all() or not np.isfinite(transition) or transition <= 0:
            raise ValueError('Finite horizontal hand-to-root offset and positive transition required')
        def smoothstep(x):
            x = np.clip(x, 0, 1)
            return x*x*x*(10+x*(-15+6*x))
        root_binding = smoothstep((t-start+transition)/transition)*smoothstep((end+transition-t)/transition)
        # One shared displacement clock: root and hand hold, pull and stop together.
        coupled = hand[:, :2] + offset
        root = root*(1-root_binding[:, None]) + coupled*root_binding[:, None]
    return dict(times=t, frames=frames, root_xy=root, heading=heading,
                object_translation=obj, hand=hand, hand_on=hand_on, seat=seat,
                root_binding=root_binding,
                root_height=curve(plan['root_height_keys'])[:,0] if 'root_height_keys' in plan else None)


class FeatureConstraint:
    """Kimodo constraint protocol with only explicitly selected feature channels.

    Indices are frame IDs or (frame, joint) pairs. Cropping preserves channels;
    hand keys therefore cannot silently acquire pelvis height or heading keys.
    """
    name = "selected-features"

    def __init__(self, channels):
        self.channels = channels

    @property
    def frame_indices(self):
        import torch
        return torch.unique(torch.cat([idx if idx.ndim == 1 else idx[:,0]
                                       for idx, _ in self.channels.values()]))

    def update_constraints(self, data_dict, index_dict):
        for name, (indices, values) in self.channels.items():
            if len(indices):
                index_dict[name].append(indices)
                data_dict[name].append(values)

    def crop_move(self, start, end):
        channels = {}
        for name, (indices, values) in self.channels.items():
            frames = indices if indices.ndim == 1 else indices[:, 0]
            mask = (frames >= start) & (frames < end)
            cropped = indices[mask].clone()
            if cropped.ndim == 1: cropped -= start
            else: cropped[:, 0] -= start
            channels[name] = (cropped, values[mask])
        return type(self)(channels)

    def to(self, device=None, dtype=None):
        self.channels = {name: (idx.to(device=device), value.to(device=device, dtype=dtype))
                         for name, (idx, value) in self.channels.items()}
        return self


def pelvis_position_constraint(frames, root_xz, heights):
    """Constrain decoded pelvis, not only the redundant smooth-root Y feature.

    Kimodo decodes root height from local_joints_positions[Hips, Y]. Its
    root_y_pos condition alone writes smooth_root_pos[Y], a separate channel.
    Use supported position conditioning with the already planned horizontal
    location, without constraining pelvis rotation or other joints.
    """
    import torch
    # Native constraints keep authored indices on CPU until their common .to().
    frames = torch.as_tensor(frames, dtype=torch.long, device='cpu')
    positions = torch.stack((root_xz[:,0], heights, root_xz[:,1]), dim=-1)
    pairs = torch.stack((frames, torch.zeros_like(frames)), dim=-1)
    return FeatureConstraint(dict(smooth_root_2d=(frames, root_xz),
        root_y_pos=(frames, heights), global_joints_positions=(pairs, positions)))


def constraint_schedule(plan):
    """Select authored path/heading knots and isolated sitting-height targets."""
    c = compile_plan(plan); n = len(c['times']); fps = plan['fps']
    def frames(keys, stride=None):
        if stride is not None:
            if not isinstance(stride,int) or stride < 1:
                raise ValueError("Path sampling stride must be a positive integer")
            return np.unique(np.r_[np.arange(0,n,stride),n-1])
        return np.unique(np.clip(np.rint(np.asarray(keys)[:, 0]*fps).astype(int), 0, n-1))
    heights = np.asarray(plan.get('pelvis_height_targets', []), dtype=float).reshape(-1, 2)
    if len(heights):
        if not np.isfinite(heights).all() or np.any(np.diff(heights[:,0]) <= 0):
            raise ValueError('Height targets must have finite increasing times')
        if heights[0,0] < 0 or heights[-1,0] > n/fps or np.any(heights[:,1] <= 0):
            raise ValueError('Height targets must be positive and within the clip')
        height_ids = np.clip(np.rint(heights[:,0]*fps).astype(int),0,n-1)
        if len(np.unique(height_ids)) != len(height_ids):
            raise ValueError('Height target times round to duplicate frames')
    else: height_ids = np.array([],dtype=int)
    # Each call must end at a planned route key. Otherwise a ten-frame sampling
    # grid leaves nine unconstrained tail frames, then the next call projects its
    # first frame back onto the route and introduces a discontinuity.
    boundaries=np.cumsum([0]+c['frames'])
    endpoints=np.unique(np.clip(np.r_[boundaries,boundaries[1:]-1],0,n-1))
    if plan.get('generation_profile') == '1c9de0b_control' and not plan.get('segment_endpoint_keys', False):
        # Reproduce the historical sampling grid for a controlled input audit.
        # Endpoint conditioning is a separate experiment, not a hidden change.
        endpoints=np.array([],dtype=int)
    return dict(root_frames=np.union1d(frames(plan['root_xy_keys'],plan.get('root_path_sample_stride')),endpoints), heading_frames=np.union1d(frames(plan['heading_keys'],plan.get('heading_sample_stride')),endpoints),
                height_frames=height_ids, height_values=heights[:,1])


def subset_skin(skin, ids):
    """Preserve full skeleton/shape/pose corrections while skinning fewer vertices."""
    result = copy(skin)
    for name in ('v_shaped', 'posedirs', 'bind_vertices', 'lbs_indices', 'lbs_weights'):
        setattr(result, name, getattr(skin, name)[ids])
    return result


def optimize_motion(skeleton, local, root, *, joint_targets=None, iterations=180,
                    contact_skin=None, patch_layout=None, contact_data=None,
                    fixed_joints=(12, 15), orientation_targets=None, root_trajectory=None,
                    root_path_prior=None):
    """Jointly refine rotations/root with pose priors, contact and temporal losses.

    Supports FK targets for native condition authoring; final refinement uses actual
    skinned palm/sole/seat patches. Never scales body dimensions or changes timing.
    """
    if iterations < 1:
        raise ValueError('Positive optimization iterations required')
    import torch
    device = skeleton.neutral_joints.device
    tensor = lambda a: torch.as_tensor(a, dtype=torch.float32, device=device)
    base = tensor(local).detach(); original_root = tensor(root).detach()
    six = torch.nn.Parameter(base[..., :2].transpose(-1, -2).reshape(*base.shape[:2], 6).clone())
    fixed = torch.zeros(base.shape[1], dtype=torch.bool, device=device)
    for joint in fixed_joints:
        if joint < len(fixed): fixed[joint] = True
    def current_rotations():
        return torch.where(fixed[None, :, None, None], base, rotation_6d_to_matrix(six))
    translation = torch.nn.Parameter(torch.zeros_like(original_root))
    def current_roots():
        free = original_root + translation
        if root_trajectory is None:return free
        # Native Y is height. Keep it free, while fixing horizontal root motion
        # during grasp and blending back to free motion outside the interval.
        on = tensor(root_trajectory['binding'])[:, None]
        xy = tensor(root_trajectory['positions'])
        horizontal = free[:, [0, 2]]*(1-on) + xy*on
        return torch.stack((horizontal[:,0],free[:,1],horizontal[:,1]),dim=-1)
    opt = torch.optim.Adam([six, translation], lr=.015)
    target = None if joint_targets is None else (tensor(joint_targets[0]), tensor(joint_targets[1]))
    logs=[]
    for step in range(iterations):
        opt.zero_grad()
        for group in opt.param_groups:
            group['lr']=.012*(.1+.9*(1-step/max(1,iterations-1))**2)
        rotations = current_rotations()
        roots = current_roots()
        global_rotations, joints, _ = skeleton.fk(rotations, roots)
        correction = rotations @ base.transpose(-1, -2)
        loss = .6 * (rotations-base).square().mean() + 2 * translation.square().mean()
        if len(root) > 2:
            loss = loss + 15 * torch.diff(translation, n=2, dim=0).square().mean()
            loss = loss + 6 * torch.diff(correction, dim=0).square().mean()
            # SO(3) relative matrices avoid coordinate branch cuts, including at pi.
            velocity = rotations[1:] @ rotations[:-1].transpose(-1, -2)
            loss = loss + 20 * torch.diff(velocity, dim=0).square().mean()
            loss = loss + 3000 * torch.diff(joints, n=2, dim=0).square().mean()
        if root_path_prior is not None:
            prior = root_path_prior
            strength = tensor(prior["strength"])
            error = (roots[:, [0, 2]] - tensor(prior["positions"])).square().sum(-1)
            loss = loss + prior.get("weight", 100.) * (error * strength).sum() / strength.sum().clamp_min(1)
        if orientation_targets is not None:
            goal=orientation_targets
            on=tensor(goal['strength'])
            error=(global_rotations[:,goal['joint']]-tensor(goal['rotations'])).square().sum((-1,-2))
            loss=loss+goal.get('weight',40.)*(error*on).sum()/on.sum().clamp_min(1)
        if target is not None:
            positions, weights = target
            loss = loss + 200 * ((joints-positions).square().sum(-1)*weights).sum()/weights.sum().clamp_min(1)
        if contact_skin is not None:
            vertices = contact_skin.skin(rotations, joints)
            cd = contact_data
            palm = vertices[:, patch_layout['palm']].mean(1)
            hand_on = tensor(cd['hand_strength'])
            hand_loss = ((palm-tensor(cd['hand_target'])).square().sum(-1)*hand_on).sum()/hand_on.sum().clamp_min(1)
            loss = loss + 500 * hand_loss
            if 'palm_triangles' in cd:
                faces=torch.as_tensor(cd['palm_triangles'],device=device,dtype=torch.long)
                triangles=vertices[:,faces]
                normal=torch.cross(triangles[:,:,1]-triangles[:,:,0],triangles[:,:,2]-triangles[:,:,0],dim=-1).sum(1)
                normal=normal/normal.norm(dim=-1,keepdim=True).clamp_min(1e-10)
                error=(normal-tensor(cd['palm_normal_target'])).square().sum(-1)
                loss=loss+80*(error*hand_on).sum()/hand_on.sum().clamp_min(1)
            foot_scale = cd.get('foot_loss_scale', 1.)
            for i, part in enumerate(cd.get('foot_parts', FOOT_PATCHES)):
                foot = vertices[:, patch_layout[part]]
                strength = tensor(cd['foot_strength'][:, i])
                # Penalize below-floor patch points and motion of corresponding
                # vertices across adjacent predicted contact frames.
                low = foot[:, :, 1].amin(1)
                height = ((low-cd['floor_y']).square()*strength).sum()/strength.sum().clamp_min(1)
                loss = loss + foot_scale * 250 * height
                if not cd.get('floor_parts'):
                    loss = loss + foot_scale * 600 * torch.relu(cd['floor_y']-low).square().mean()
                pairs = torch.minimum(strength[1:],strength[:-1])
                slip = torch.diff(foot,dim=0).square().sum(-1).mean(1)*cd['fps']**2
                loss = loss + foot_scale * 80 * (slip*pairs).sum()/pairs.sum().clamp_min(1)
                anchors=tensor(cd['foot_anchors'][part])
                loss = loss + foot_scale * 400*((foot-anchors).square().sum(-1).mean(1)*strength).sum()/strength.sum().clamp_min(1)
            # Floor exclusion is per whole sole, independent of support labels.
            # Splitting support into heel/toe must not halve the cost of the
            # deepest penetrating point when only one patch goes below ground.
            for part in cd.get('floor_parts', ()):
                low = vertices[:, patch_layout[part], 1].amin(1)
                loss = loss + 600 * torch.relu(cd['floor_y']-low).square().mean()
            if 'seat' in patch_layout:
                patch = vertices[:, patch_layout['seat']]
                on = tensor(cd['seat_strength'])
                target_seat = tensor(cd['seat_target'])
                low = patch[:,:,1].amin(1)
                loss = loss + 350*((low-target_seat[:,1]).square()*on).sum()/on.sum().clamp_min(1)
                center = patch.mean(1)
                loss = loss + 80*((center[:,[0,2]]-target_seat[:,[0,2]]).square().sum(-1)*on).sum()/on.sum().clamp_min(1)
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite interaction objective')
        loss.backward(); torch.nn.utils.clip_grad_norm_([six,translation],10); opt.step()
        if step % 40 == 0 or step == iterations-1:
            logs.append(dict(step=step,loss=float(loss.detach())))
            print('Optimize',logs[-1],flush=True)
    with torch.no_grad():
        final = current_rotations()
    return final.detach().cpu().numpy(), current_roots().detach().cpu().numpy(), logs


def rotation_6d_to_matrix(six):
    """Continuous two-column representation; no axis-angle conversion anywhere.

    Temporal objectives operate on matrices on SO(3), not raw six-vector distance.
    """
    import torch
    from torch.nn.functional import normalize
    a, b = six[..., :3], six[..., 3:]
    x = normalize(a, dim=-1, eps=1e-8)
    y = normalize(b - (x*b).sum(-1, keepdim=True)*x, dim=-1, eps=1e-8)
    return torch.stack((x, y, torch.cross(x, y, dim=-1)), dim=-1)


def right_palm_frame(wrist, index_base, middle_base, pinky_base):
    """Right-hand anatomical frame: distal, transverse, outward palmar normal.

    For the right hand, radial (pinky-to-index) cross distal points out of the
    palm. All inputs must be expressed in the same wrist-local/rest coordinates.
    """
    def unit(a):
        a=np.asarray(a,dtype=float)
        if not np.isfinite(a).all() or np.linalg.norm(a)<1e-8:raise ValueError('Degenerate hand frame')
        return a/np.linalg.norm(a)
    distal=unit(np.asarray(middle_base)-wrist)
    normal=unit(np.cross(np.asarray(index_base)-pinky_base,distal))
    return np.column_stack([distal,np.cross(normal,distal),normal])


def hand_orientation_target(local_frame, palm_normal_room, fingers_room):
    """Return a proper native global wrist rotation, without angular coordinates."""
    normal=np.asarray(palm_normal_room,dtype=float);normal/=np.linalg.norm(normal)
    distal=np.asarray(fingers_room,dtype=float)
    distal=distal-normal*np.dot(normal,distal)
    if not np.isfinite(normal).all() or np.linalg.norm(distal)<1e-8:raise ValueError('Invalid hand directions')
    distal/=np.linalg.norm(distal)
    target_room=np.column_stack([distal,np.cross(normal,distal),normal])
    return KIMODO_TO_ROOM.T@target_room@np.asarray(local_frame).T
