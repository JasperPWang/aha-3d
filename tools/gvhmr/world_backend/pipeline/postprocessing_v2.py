"""Per-person world placement of a trusted camera-frame body.

Premise
-------
The camera-frame body is correct. GVHMR/PromptHMR estimate the person relative to
the camera well; what is uncertain is where that body belongs in the world. So the
camera-frame joints are computed once, frozen, and each person's world pose is a
*placement* of that rigid view:

    R_wc'(p,t) = R_g(p) . R_wc0(p,t)
    T_wc'(p,t) = R_g(p) . ( c_ref + s.(T_wc0(p,t) - c_ref) + dc(p,t) ) + t_g(p)
    j_world(p,t) = R_wc'(p,t) . j_cam(p,t) + T_wc'(p,t)

`j_cam` is a buffer with no path to any parameter, so no body ever deforms and no
body ever rotates relative to its own view; only where that view sits is fitted.

Orientation
-----------
`R_wc0(p,t)` is per person because, before anything is optimised, each person's
camera is re-oriented frame by frame so that the body's world orientation is the
network's global-branch prediction rather than camera rotation x in-camera
orientation (`_orientation_from_global_branch`, `postopt_orient_source`). Camera and
body turn together about the pelvis, so reprojection is untouched. Once a planted
foot pins the root, the root's path is decided by that orientation alone, and the
global branch's roughly halves its acceleration. There is no post-hoc smoothing; the
acceleration term (postopt_acc, 0.1) is the smoother.

One set of parameters per person, not shared
--------------------------------------------
    delta_v        (P, T-1, 3)  per-frame placement velocity; dc = cumsum(delta_v)
    global_r6d     (P, 6)       3-DoF rotation of that person's reconstruction
    global_transl  (P, 3)       3-DoF translation of that person's reconstruction
    log_scale      (1,)         trajectory scale, OFF unless postopt_optimize_scale

A single shared correction has three numbers per frame; two people with a planted
foot each impose six constraints, so it cannot satisfy them and splits the
difference. Per person, each body carries its own placement.

What `dc` actually is
---------------------
Note that `dc(p,t)` translates person p in the world, frame by frame. Its span is
3(T-1), plus 3 from `global_transl`, i.e. 3T -- exactly the space of
`pipeline/postprocessing.py`'s per-frame `transl`. This file is not a smaller
parameterisation than v1; it is the same translation freedom written as a velocity
so that the prior acts on smoothness rather than on absolute displacement, plus a
rotation v1 does not have, minus v1's 2D reprojection term.

Deliberately not free, each for a measured reason:

  * a per-cell ground height. A free support surface makes the contact-height term
    vacuous: every cell simply moves to wherever the foot already is. Fitted, it
    reproduced a 1.13 m "floor" in a level lounge and 26 cm of mean penetration.
    The support heights are precomputed and frozen instead.
  * the scale. Its only observer is contact velocity, which is informative only
    when the camera translates while a foot is planted. Measured across five clips
    that ratio is 0.07-0.35, and sweeping s over [0.25, 3.0] moves the contact loss
    by 0.8-17.8%; with s free the optimiser landed on 0.61 and 1.74 on the same clip
    from two different cameras. experiments/postopt_ab/scale_profile.py reports the
    ratio for a given clip.

The camera at write-back
------------------------
Each person is bound to their own camera, and that binding is never broken: the
placement moves person p's body and person p's camera together, so p's reprojection
is invariant by construction, exactly as in the shared version. What is no longer
true is that everyone shares one camera. Person p's camera lands in
`results['people'][p]['camera_world']`; the top-level `camera_world` carries the
first person's, so a consumer that reads only that field still sees a camera
consistent with at least one body.

Two cameras disagreeing is not a defect here. The object being estimated is human
motion, and for that it does not matter whether two people's recovered views of the
room coincide -- only that each body stays consistent with the view it was fitted
from. If a single consistent camera is what you need, that is the shared
formulation, and it pays for it by inflating the camera path 3-10x over the metric
estimate it was handed.

Do not "re-align to frame 0" at write-back. Such a step does not pin a gauge, it
silently cancels the global transform the optimiser just fitted, and with it the
floor alignment.
"""
import torch
import numpy as np

from prompt_hmr.utils.rotation_conversions import (
    matrix_to_rotation_6d,
    rotation_6d_to_matrix,
    axis_angle_to_matrix,
    matrix_to_axis_angle,
)

# SMPL-X joints whose contact the static head predicts: L_Ankle, L_foot, R_Ankle, R_foot
CONTACT_JOINT_IDS = [7, 10, 8, 11]

# sigmoid(logit) gate on that head. Matches GVHMR, which thresholds it at logit > 0.
# Without a gate an uninformative logit of 0 still applies a half-weight
# zero-velocity prior on every frame.
CONTACT_CONF_THRESH = 0.5

# Target height above the support surface of the *lowest vertex* of each contact
# region. Measured on the mesh rather than on the joint, so one value is correct for
# the heel and the toe alike; a joint-space target has to differ per joint.
CONTACT_HEIGHT_TARGET = 0.02

# Below this residual the height term becomes quadratic. A pure L1 has the same
# gradient magnitude however close it is, so Adam keeps stepping ~lr across the
# target and never lands: at lr 1e-1 the foot settled anywhere in [-18, +23] cm, and
# sweeping the weight moved it around without converging, because the weight is not
# what was wrong. Quadratic near zero makes the gradient vanish as it arrives, which
# is what lets it stop. Linear further out keeps the robustness to bad contact
# labels that L1 was chosen for.
CONTACT_HEIGHT_HUBER = 0.01

# How many of the lowest vertices of each contact region are kept as candidates for
# the per-frame minimum. Only the global rotation re-orders them, and it stays small.
N_CONTACT_VERTS = 64

# Support-height map cell size, metres (postopt_ground='heightmap' only).
GROUND_CELL_M = 0.40

# SMPL-X -> OpenPose-25, then the contact joints appended
JOINT_MAPPING = np.array([55, 12, 17, 19, 21, 16, 18, 20, 0, 2, 5, 8, 1, 4, 7,
                          56, 57, 58, 59, 60, 61, 62, 63, 64, 65], dtype=np.int32)
PELVIS_IDX = 8            # OpenPose MidHip == SMPL-X pelvis == JOINT_MAPPING[8]
N_OP = len(JOINT_MAPPING)


def _gather(results, seq_len, device):
    """Per-person arrays, padded to the full clip length and masked."""
    people_ids = list(results['people'].keys())
    P = len(people_ids)
    pose = np.zeros((P, seq_len, 55 * 3))
    betas = np.zeros((P, seq_len, 10))
    transl = np.zeros((P, seq_len, 3))
    contact = np.zeros((P, seq_len, 6))
    mask = np.zeros((P, seq_len))
    for pidx, pid in enumerate(people_ids):
        v = results['people'][pid]
        f = v['frames']
        pose[pidx, f] = v['smplx_world']['pose']
        betas[pidx, f] = v['smplx_world']['shape'][:, :10]
        transl[pidx, f] = v['smplx_world']['trans']
        contact[pidx, f] = v['smplx_cam']['static_conf_logits']
        mask[pidx, f] = 1
    t = lambda x: torch.tensor(x, dtype=torch.float32, device=device)
    return people_ids, t(pose), t(betas), t(transl), t(contact), t(mask)


def _camera_space_body(smplx, pose, betas, transl, Rcw0, Tcw0, device):
    """Run SMPL-X once, then move everything into the camera frame and keep only that.

    Returns joints, contact-region candidate vertices and the body's global
    orientation, all expressed relative to the camera on their own frame. These are
    the quantities the premise says are correct, and nothing downstream may change
    them -- they are returned detached.
    """
    P, T = pose.shape[:2]
    B = P * T
    z = lambda k: torch.zeros(B, k, device=device)
    with torch.no_grad():
        out = smplx(
            global_orient=pose[:, :, :3].reshape(-1, 3),
            body_pose=pose[:, :, 3:66].reshape(-1, 21 * 3),
            betas=betas.reshape(-1, 10),
            transl=transl.reshape(-1, 3),
            left_hand_pose=pose[:, :, 75:120].reshape(-1, 15 * 3),
            right_hand_pose=pose[:, :, 120:165].reshape(-1, 15 * 3),
            jaw_pose=z(3), leye_pose=z(3), reye_pose=z(3), expression=z(10),
            pose2rot=True,
        )
        j_w = torch.cat([out.joints[:, JOINT_MAPPING],
                         out.joints[:, CONTACT_JOINT_IDS]], dim=1)
        j_w = j_w.reshape(P, T, -1, 3)

        # lowest vertices of each contact region, by dominant LBS weight
        part = smplx.lbs_weights.argmax(dim=1)
        vert_ids = [torch.nonzero(part == c, as_tuple=False).squeeze(-1)
                    for c in CONTACT_JOINT_IDS]
        for c, vid in zip(CONTACT_JOINT_IDS, vert_ids):
            if vid.numel() == 0:
                raise ValueError(f'no SMPL-X vertex is skinned to joint {c}')
        k = min([N_CONTACT_VERTS] + [int(v.numel()) for v in vert_ids])
        cvs = []
        for vid in vert_ids:
            v_c = out.vertices[:, vid]
            low = torch.topk(-v_c[..., 1], k, dim=1).indices
            cvs.append(torch.gather(v_c, 1, low[..., None].expand(-1, -1, 3)))
        cv_w = torch.stack(cvs, dim=1).reshape(P, T, len(CONTACT_JOINT_IDS), k, 3)

        # world -> camera, with the camera the estimator actually produced.
        # Rcw0 is (T,3,3) and broadcasts over the person and joint axes.
        j_cam = j_w @ Rcw0.mT + Tcw0[None, :, None, :]
        cv_cam = cv_w @ Rcw0[:, None].mT + Tcw0[None, :, None, None, :]
        Rco = Rcw0 @ axis_angle_to_matrix(pose[:, :, :3])
    return j_cam.detach(), cv_cam.detach(), Rco.detach(), j_w.detach()


def _support_heights(j_world_init, cv_world_y, contacts_conf, mask, mode, device):
    """Fixed support height under each contact sample. Never optimised.

    'flat'      the single plane at y=0, which is where the floor fit already put it.
    'heightmap' a per-cell robust height over the cells the feet actually touch, for
                stairs, slopes and split levels. Precomputed from the initial
                estimate and frozen: left free it would absorb the error it is meant
                to expose.
    """
    if mode == 'flat':
        return torch.zeros((), device=device), None

    touch = (contacts_conf > 0) & (mask[:, :, None] > 0)
    if int(touch.sum()) == 0:
        print("  ground: no contact samples, using a flat floor")
        return torch.zeros((), device=device), None
    xz = j_world_init[:, :, N_OP:][..., [0, 2]]
    cell = torch.floor(xz / GROUND_CELL_M).long()
    key = cell[..., 0] * 100003 + cell[..., 1]
    keys, inverse = torch.unique(key[touch], return_inverse=True)
    ys = cv_world_y[touch]
    h = torch.stack([ys[inverse == c].median() for c in range(int(keys.numel()))])
    support = torch.zeros_like(key, dtype=torch.float32)
    support[touch] = h[inverse]
    print(f"  ground: {int(keys.numel())} support cells of {GROUND_CELL_M} m over "
          f"{int(touch.sum())} contact samples, spread {float(h.max() - h.min()):.3f} m")
    return support, h


def _orientation_from_global_branch(cfg, results, people_ids, mask, Rwc0, Twc0, Rco,
                                    j_cam, j_world_init, device):
    """Give each person a camera whose orientation follows the network's own
    world-frame prediction, so the body's world orientation is the global branch's.

    Why. After the contact term has done its job the root can no longer move
    freely: a planted foot fixes it at foot - R(t) * (root->foot in body coords).
    The pose is shared by every variant, so the smoothness of the corrected root is
    decided by the world orientation R(t) alone, and v2's R(t) was the estimated
    camera rotation times the in-camera orientation. Measured on the five clips,
    swapping in the global branch's R(t) (same pose, same contacts, same camera
    position) reproduces GVHMR's own post-processed trajectory to the last digit,
    and roughly halves the root acceleration at equal or lower foot sliding.

    How. The two orientations live in different worlds, so one constant rotation G
    per person is fitted first (Kabsch over that person's frames): the residual
    G R_g(t) R_m(t)^T is 2-3 deg rms on these clips. That residual is applied to the
    camera AND the body together, about the pelvis, so the body in the camera frame
    -- and therefore its reprojection -- is untouched, and the pelvis does not move.
    The camera then differs from the estimated one by the residual, per person.

    `postopt_orient_source`: 'global' (default) or 'camera' (the previous behaviour).
    People without a stored `global_orient_world` keep the camera's orientation.

    Returns per-person Rwc (P,T,3,3), Twc (P,T,3) and j_world_init rebuilt from them.
    """
    P, T = mask.shape
    Rwc = Rwc0[None].expand(P, -1, -1, -1).clone()
    Twc = Twc0[None].expand(P, -1, -1).clone()
    source = str(cfg.get('postopt_orient_source', 'global'))
    if source not in ('global', 'camera'):
        raise ValueError(f"postopt_orient_source must be global or camera, got {source!r}")
    if source == 'camera':
        return Rwc, Twc, j_world_init
    for pidx, pid in enumerate(people_ids):
        aa = results['people'][pid]['smplx_cam'].get('global_orient_world')
        f = torch.nonzero(mask[pidx] > 0, as_tuple=False).squeeze(-1)
        if aa is None:
            print(f"  person {pid}: no global-branch orientation stored, keeping the camera's")
            continue
        R_g = axis_angle_to_matrix(torch.tensor(np.asarray(aa), dtype=torch.float32,
                                                device=device))              # (n,3,3)
        if R_g.shape[0] != f.numel():
            raise ValueError(f"person {pid}: global_orient_world has {R_g.shape[0]} "
                             f"frames, the track has {f.numel()}")
        R_m = Rwc0[f] @ Rco[pidx, f]                     # world orientation as lifted
        # one constant rotation between the two worlds: G R_g ~ R_m
        U, _, Vh = torch.linalg.svd((R_m @ R_g.mT).sum(0))
        d = torch.sign(torch.det(U @ Vh))
        G = U @ torch.diag(torch.tensor([1.0, 1.0, float(d)], device=device)) @ Vh
        R_fix = G @ R_g @ R_m.mT                          # (n,3,3), world frame
        pel = j_world_init[pidx, f, PELVIS_IDX]           # (n,3)
        Rwc[pidx, f] = R_fix @ Rwc0[f]
        Twc[pidx, f] = torch.einsum('tij,tj->ti', R_fix, Twc0[f] - pel) + pel
        ang = torch.rad2deg(matrix_to_axis_angle(R_fix).norm(dim=-1))
        print(f"  person {pid}: orientation from the global branch; camera re-oriented "
              f"by {float(ang.mean()):.2f} deg mean / {float(ang.max()):.2f} deg max")
    j_world_init = torch.einsum('ptij,ptkj->ptki', Rwc, j_cam) + Twc[:, :, None]
    return Rwc, Twc, j_world_init


def post_optimization_v2(cfg, results, images, smplx, flat_ground=True):
    device = 'cuda'
    smplx = smplx.to(device)
    seq_len = len(images)
    cam = results['camera_world']

    Rwc0 = torch.tensor(np.asarray(cam['Rwc']), dtype=torch.float32, device=device)
    Twc0 = torch.tensor(np.asarray(cam['Twc']), dtype=torch.float32, device=device)
    Rcw0 = Rwc0.mT
    Tcw0 = -(Rcw0 @ Twc0[..., None])[..., 0]

    people_ids, pose, betas, transl_init, contact_logits, mask = _gather(
        results, seq_len, device)
    num_people = len(people_ids)
    print("Postprocessing the results")

    j_cam, cv_cam, Rco, j_world_init = _camera_space_body(
        smplx, pose, betas, transl_init, Rcw0, Tcw0, device)
    assert not j_cam.requires_grad, 'camera-frame body must stay a constant'

    # From here on the camera is per person: (P,T,3,3) and (P,T,3).
    Rwc0, Twc0, j_world_init = _orientation_from_global_branch(
        cfg, results, people_ids, mask, Rwc0, Twc0, Rco, j_cam, j_world_init, device)

    # the contact head is a hard gate, not a soft weight
    contacts_conf = torch.sigmoid(contact_logits)[..., :len(CONTACT_JOINT_IDS)]
    contacts_conf = contacts_conf * (contacts_conf > CONTACT_CONF_THRESH)
    contacts_pair = torch.minimum(contacts_conf[:, 1:], contacts_conf[:, :-1])

    #   'flat'      one horizontal floor at y=0
    #   'heightmap' a precomputed per-cell support height, for uneven ground
    #   'none'      no height term at all; contact then only says the foot must not
    #               move, and nothing fixes how high off the ground it is
    ground_mode = str(cfg.get('postopt_ground', 'flat' if flat_ground else 'heightmap'))
    if ground_mode not in ('flat', 'heightmap', 'none'):
        raise ValueError(
            f"postopt_ground must be flat, heightmap or none, got {ground_mode!r}")
    support = None
    if ground_mode != 'none':
        cv_world_y0 = (torch.einsum('ptij,ptckj->ptcki', Rwc0, cv_cam)
                       + Twc0[:, :, None, None])[..., 1].min(dim=-1).values
        support, _ = _support_heights(j_world_init, cv_world_y0, contacts_conf,
                                      mask, ground_mode, device)

    # ---- free parameters ---------------------------------------------------
    eye3 = torch.eye(3, device=device)
    # One set per person. A single shared correction cannot satisfy two people whose
    # feet are planted at once: it has three numbers per frame and they have six
    # constraints. Per person, each body carries its own placement.
    delta_v = torch.zeros(num_people, max(seq_len - 1, 0), 3,
                          device=device, requires_grad=True)
    global_r6d = matrix_to_rotation_6d(eye3).clone().repeat(
        num_people, 1).requires_grad_(True)
    global_transl = torch.zeros(num_people, 3, device=device, requires_grad=True)
    log_scale = torch.zeros(1, device=device)
    opt_scale = bool(cfg.get('postopt_optimize_scale', False))
    log_scale.requires_grad = opt_scale

    # Scale about a fixed reference rather than the world origin, so that changing s
    # does not also induce a global translation for `global_transl` to undo.
    c_ref = Twc0.mean((0, 1))

    # One rate for every parameter. Adam already normalises per parameter -- its step
    # is ~lr whatever the gradient magnitude or the units -- so scaling a group down
    # only makes it learn that many times slower, for nothing. `delta_v` used to be
    # scaled by 0.1 and that alone was the long-standing "v2 cannot reach GVHMR"
    # result: at an effective 1e-3, 1000 Adam steps stall at 0.071 m/s foot slip on
    # clip32, where the closed-form optimum of this very loss is 0.032. At 1e-2 it
    # converges to 0.040, i.e. GVHMR's own 0.039.
    #
    # v2 keeps its own key rather than reading `postopt_lr`, so the A/B stays honest
    # when one of the two is retuned.
    lr = float(cfg.get('postopt_lr_v2', 1e-2))
    params = [global_r6d, global_transl]
    if delta_v.numel() > 0:
        params.append(delta_v)
    if opt_scale:
        params.append(log_scale)
    optim = torch.optim.Adam([{'params': params, 'lr': lr}])
    # Adam's step stays ~lr forever, so without decay the last iterate is wherever
    # the hunt happened to be, not the minimum. Cosine to zero makes the final
    # iterate the answer.
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        optim, T_max=max(int(cfg.get('postopt_iters', 1000)), 1), eta_min=0.0)

    # ---- masks -------------------------------------------------------------
    mask2 = mask[:, 1:] * mask[:, :-1]
    mask3 = mask[:, 2:] * mask[:, 1:-1] * mask[:, :-2]
    n1, n2, n3 = (m.sum().clamp(min=1.0) for m in (mask, mask2, mask3))
    # each person's correction is constrained only on that person's own frames
    cam_mask2 = mask2
    n_cam2 = cam_mask2.sum().clamp(min=1.0)

    # ---- weights, in the units of what each term penalises -----------------
    w_cont_vel = float(cfg.get('postopt_cont_vel', 1000.0)) # (m/s)^2
    w_cont_height = float(cfg.get('postopt_cont_height', 10.0))  # m
    # 1e-1, not 1e-3: at 1e-3 against a contact weight of 1000 the term is absent
    # and the root lands on the zero-slip closed form. At 1e-1 it does what GVHMR's
    # gaussian smoother does, inside the objective: root accel 3.2 -> 2.4 (clip32),
    # 8.1 -> 1.9 (clip42) for +0.003 m/s slip, still below GVHMR's on every clip.
    w_acc = float(cfg.get('postopt_acc', 1e-1))             # (m/s^2)^2
    w_vreg = float(cfg.get('postopt_vreg', 0.25))           # (m/s)^2
    w_rot = float(cfg.get('postopt_rot_reg', 1.0))          # ||R_g - I||_F^2
    w_transl = float(cfg.get('postopt_transl_reg', 0.5))    # ||t_g||^2, m^2

    zero1 = torch.zeros(1, 1, 3, device=device)
    fps = cfg.fps
    n_iter = int(cfg.get('postopt_iters', 1000))
    history = {}

    def forward():
        """Each person gets their own placement of the camera-frame body.

        `j_cam` is still frozen, so person p's body never deforms and never rotates
        relative to their own view; what is fitted is where that rigid view sits in
        the world. With one person this is exactly the old shared formulation. With
        several it is P independent placements, which is the point.
        """
        R_g = rotation_6d_to_matrix(global_r6d)                      # (P,3,3)
        dc = torch.cat([zero1.expand(num_people, -1, -1),
                        delta_v.cumsum(dim=1)], dim=1)               # (P,T,3)

        centre = c_ref + log_scale.exp() * (Twc0 - c_ref) + dc      # (P,T,3)
        Twc = torch.einsum('pij,ptj->pti', R_g, centre) + global_transl[:, None]
        Rwc = R_g[:, None] @ Rwc0                                    # (P,T,3,3)

        j_world = torch.einsum('ptij,ptkj->ptki', Rwc, j_cam) + Twc[:, :, None]
        return R_g, Rwc, Twc, dc, j_world

    for i in range(n_iter):
        optim.zero_grad()
        R_g, Rwc, Twc, dc, j_world = forward()

        # a planted foot does not move; gated at both ends of the interval so a
        # step that only touches down at t+1 is not counted
        cvel = (j_world[:, 1:, N_OP:] - j_world[:, :-1, N_OP:]) * fps
        loss_cvel = (cvel.pow(2).sum(-1) * contacts_pair)
        loss_cvel = w_cont_vel * (loss_cvel * mask2[..., None]).mean(-1).sum() / n2

        # a planted foot rests on the support surface, measured on the sole
        if support is None:
            loss_cheight = torch.zeros((), device=device)
        else:
            cv_world = (torch.einsum('ptij,ptckj->ptcki', Rwc, cv_cam)
                        + Twc[:, :, None, None])
            foot_y = cv_world[..., 1].min(dim=-1).values                # (P,T,C)
            resid = foot_y - support - CONTACT_HEIGHT_TARGET
            d = CONTACT_HEIGHT_HUBER
            loss_cheight = torch.where(resid.abs() < d,
                                       resid.pow(2) / (2 * d),
                                       resid.abs() - d / 2) * contacts_conf
            loss_cheight = w_cont_height * (loss_cheight * mask[..., None]).mean(-1).sum() / n1

        acc = (j_world[:, 2:, :N_OP] + j_world[:, :-2, :N_OP] - 2 * j_world[:, 1:-1, :N_OP]) * fps ** 2
        loss_acc = w_acc * (acc.pow(2).sum(-1).mean(-1) * mask3).sum() / n3

        # the only thing holding the fitted camera near the estimated one
        loss_vreg = (delta_v * fps).pow(2).mean(-1)
        loss_vreg = w_vreg * (loss_vreg * cam_mask2).sum() / n_cam2

        loss_greg = (w_rot * (R_g - eye3).pow(2).sum()
                     + w_transl * global_transl.pow(2).sum()) / num_people

        loss = loss_cvel + loss_cheight + loss_acc + loss_vreg + loss_greg
        logs = {'contact_vel': loss_cvel, 'contact_height': loss_cheight,
                'acc': loss_acc, 'vreg': loss_vreg, 'greg': loss_greg, 'total': loss}
        for k, v in logs.items():
            history.setdefault(k, []).append(v.item())
        loss.backward()
        optim.step()
        sched.step()

    if n_iter:
        fmt = lambda i: ', '.join(f'{k}={v[i]:.4f}' for k, v in history.items())
        print(f"  start: {fmt(0)}")
        print(f"  end:   {fmt(-1)}")

    # ---- write back --------------------------------------------------------
    with torch.no_grad():
        # the optimised result, in world coordinates
        R_g, Rwc, Twc, dc, j_world = forward()

        R_world = Rwc @ Rco                           # body orientation in world

        # `trans` offsets the posed body, whose pelvis sits at pelvis0 + trans, so the
        # pelvis displacement *is* the translation delta -- pelvis0 never has to be
        # recovered.
        transl_final = transl_init + (j_world[:, :, PELVIS_IDX]
                                      - j_world_init[:, :, PELVIS_IDX])
        orient_final = matrix_to_axis_angle(R_world.reshape(-1, 3, 3)).reshape(
            num_people, seq_len, 3)

    # the norm of an axis-angle vector is the rotation angle
    rot_g = torch.rad2deg(matrix_to_axis_angle(R_g).norm(dim=-1))
    shift = torch.linalg.norm(dc, dim=-1)
    for pidx, pid in enumerate(people_ids):
        print(f"  person {pid}: rotation {float(rot_g[pidx]):.2f} deg, translation "
              f"{np.round(global_transl[pidx].detach().cpu().numpy(), 4).tolist()}, "
              f"shift {float(shift[pidx].mean()):.3f} m mean / "
              f"{float(shift[pidx].max()):.3f} m max")
    print(f"  scale {float(log_scale.exp()):.4f}")

    for pidx, pid in enumerate(people_ids):
        m = mask[pidx].bool()
        sw = results['people'][pid]['smplx_world']
        sw['trans'] = transl_final[pidx][m].cpu().numpy()
        sw['pose'][:, :3] = orient_final[pidx][m].cpu().numpy().astype(sw['pose'].dtype)

    # Each person is bound to THEIR OWN camera. The placement moves the body and its
    # camera together, exactly as the shared version did, so that person's
    # reprojection is still invariant -- it is only invariant against their own
    # camera, not against a single shared one. Whether two people's cameras agree
    # does not matter for getting good motion, so each is stored on the person.
    Rwc_np = Rwc.cpu().numpy().astype(np.float64)
    Twc_np = Twc.cpu().numpy().astype(np.float64)
    for pidx, pid in enumerate(people_ids):
        m = mask[pidx].bool().cpu().numpy()
        R_p, T_p = Rwc_np[pidx], Twc_np[pidx]
        Rcw_p = R_p.transpose(0, 2, 1)
        results['people'][pid]['camera_world'] = {
            'Rwc': R_p, 'Twc': T_p, 'Rcw': Rcw_p,
            'Tcw': -(Rcw_p @ T_p[..., None])[..., 0],
            'frames_mask': m,
        }

    # The top-level camera is the first person's, so anything that reads only the
    # shared field still sees a camera consistent with at least one body. Consumers
    # that care read `results['people'][pid]['camera_world']`.
    R0, T0 = Rwc_np[0], Twc_np[0]
    Rcw0_np = R0.transpose(0, 2, 1)
    cam['Rwc'], cam['Twc'] = R0, T0
    cam['Rcw'] = Rcw0_np
    cam['Tcw'] = -(Rcw0_np @ T0[..., None])[..., 0]
    cam['pred_cam_R'], cam['pred_cam_T'] = R0, T0
    return results
