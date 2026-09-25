"""Representative linked shader colors for the simplified browser material path.

Image colors are sampled at the material's own face UVs, never over a whole
source photograph. Spatial detail remains an approximation, not texture baking.
"""
import numpy as np


def material_uv_samples(objects):
    samples = {}
    for obj in objects:
        if obj.type != 'MESH' or not obj.data.uv_layers.active:
            continue
        uv = obj.data.uv_layers.active.data
        for face in obj.data.polygons:
            if face.material_index >= len(obj.material_slots):
                continue
            mat = obj.material_slots[face.material_index].material
            if mat:
                samples.setdefault(mat.name, []).append(np.mean([uv[i].uv[:] for i in face.loop_indices], axis=0))
    return samples


def linked_color(socket, uv_samples=(), fallback=(.5, .5, .5, 1)):
    """Evaluate common linked color graphs at face centroids; unsupported = fallback."""
    uv = np.asarray(uv_samples, dtype=float).reshape(-1, 2)
    if not len(uv):
        uv = np.array([[.5, .5]])
    # Bound evaluation costs for large repeated meshes.
    uv = uv[::max(1, len(uv)//4096)]
    count = len(uv)
    cache = {}

    def constant(value):
        a = np.asarray(value, dtype=float)
        return np.full((count, 1), float(a)) if a.ndim == 0 else np.tile(a, (count, 1))

    def evaluate(s, depth=0):
        if depth > 48:
            raise ValueError('Shader recursion limit')
        if not s.is_linked:
            return constant(s.default_value)
        output = s.links[0].from_socket
        node = output.node
        key = output.as_pointer()
        if key in cache:
            return cache[key]
        get = lambda i: evaluate(node.inputs[i], depth+1)
        if node.type == 'TEX_IMAGE' and node.image and node.image.size[0]:
            if node.inputs['Vector'].is_linked:
                link = node.inputs['Vector'].links[0]
                if not (link.from_node.type == 'TEX_COORD' and link.from_socket.name == 'UV'):
                    raise ValueError('Unsupported image coordinate transform')
            image = node.image
            w, h = image.size
            pixels = np.empty(w*h*4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            pixels = pixels.reshape(h, w, 4)
            coords = np.clip(uv, 0, 1) if node.extension == 'EXTEND' else uv % 1
            result = pixels[np.minimum((coords[:, 1]*h).astype(int), h-1), np.minimum((coords[:, 0]*w).astype(int), w-1)]
            if image.colorspace_settings.name == 'sRGB':
                result = result.copy()
                rgb = result[:, :3]
                result[:, :3] = np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
            if output.name == 'Alpha':
                result = result[:, 3:4]
        elif node.type == 'VALTORGB':
            try:
                factors = get(0)[:, 0]
            except (ValueError, KeyError, AttributeError, IndexError):
                factors = np.full(count, .5)
            result = np.array([node.color_ramp.evaluate(float(v)) for v in factors])
        elif node.type == 'MIX_RGB' and node.blend_type == 'MIX':
            f = np.clip(get(0), 0, 1)
            result = get(1)*(1-f)+get(2)*f
        elif node.type in ('SEPARATE_COLOR', 'SEPRGB'):
            index = list(node.outputs).index(output)
            result = get(0)[:, index:index+1]
        elif node.type == 'TEX_COORD' and output.name == 'UV':
            result = np.column_stack((uv, np.zeros(count)))
        elif node.type == 'SEPXYZ':
            index = list(node.outputs).index(output)
            result = get(0)[:, index:index+1]
        elif node.type == 'TEX_NOISE':
            result = constant(.5 if output.name in ('Fac', 'Factor') else (.5, .5, .5, 1))
        elif node.type == 'MATH':
            a, b = get(0), get(1)
            ops = {'MULTIPLY':lambda:a*b, 'ADD':lambda:a+b, 'SUBTRACT':lambda:a-b,
                   'ABSOLUTE':lambda:abs(a), 'FRACT':lambda:a-np.floor(a),
                   'LESS_THAN':lambda:(a<b).astype(float), 'GREATER_THAN':lambda:(a>b).astype(float),
                   'MINIMUM':lambda:np.minimum(a,b), 'MAXIMUM':lambda:np.maximum(a,b)}
            result = ops[node.operation]()
            if node.use_clamp:
                result = np.clip(result, 0, 1)
        elif node.type == 'RGB':
            result = constant(output.default_value)
        else:
            raise ValueError('Unsupported shader node '+node.type)
        cache[key] = result
        return result

    try:
        value = evaluate(socket).mean(axis=0)
        return tuple(float(v) for v in value[:3])+(1.,) if len(value) >= 3 else tuple([float(value[0])]*3)+(1.,)
    except (ValueError, KeyError, AttributeError, IndexError):
        return tuple(fallback)
