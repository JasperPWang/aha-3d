"""Import RoomKit generated PBR tiles and apply them to a distinct scene copy.

Run with Blender --background --python-exit-code 1 --python THIS_FILE -- ...
The Node generator owns the pattern math; Blender and the browser share its recipe.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

UV_NAME = "RoomKitMaterial"
RECIPE_KEY = "roomkit_procedural_material"


def load_material(bundle):
    import bpy

    bundle = Path(bundle).resolve()
    manifest = json.loads(bundle.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("generator") not in ("roomkit-pbr-v1", "roomkit-pbr-v2", "roomkit-pbr-v3"):
        raise ValueError("Unsupported material bundle")
    recipe = manifest["recipe"]
    if recipe.get("version") not in (1, 2, 3) or manifest["generator"] != f'roomkit-pbr-v{recipe["version"]}':
        raise ValueError("Unsupported material recipe")
    size, rotation = recipe["tileSize"], recipe["rotation"]
    if not .05 <= size <= 10 or not -180 <= rotation <= 180:
        raise ValueError("Invalid material mapping")
    images = {}
    for key in ("baseColor", "orm", "normal"):
        path = (bundle.parent / manifest["maps"][key]).resolve()
        if not path.is_relative_to(bundle.parent) or not path.is_file():
            raise ValueError("Material map must exist inside its bundle: " + key)
        image = bpy.data.images.load(str(path), check_existing=False)
        image.colorspace_settings.name = "sRGB" if key == "baseColor" else "Non-Color"
        image.pack()
        images[key] = image
    material = bpy.data.materials.new("Procedural | " + recipe["preset"])
    material.use_nodes = True
    material[RECIPE_KEY] = json.dumps(recipe, sort_keys=True)
    tree = material.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    if recipe['version'] >= 3:
        ranges = {'transmission': (0, 1), 'ior': (1, 2.333), 'thickness': (0, 1),
                  'clearcoat': (0, 1), 'clearcoatRoughness': (0, 1)}
        for key, (lo, hi) in ranges.items():
            value = recipe.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not lo <= value <= hi:
                raise ValueError('Invalid physical material parameter: ' + key)
        for key, socket in [('transmission', 'Transmission Weight'), ('ior', 'IOR'),
                            ('clearcoat', 'Coat Weight'), ('clearcoatRoughness', 'Coat Roughness')]:
            bsdf.inputs[socket].default_value = recipe[key]
        # Blender traces the actual mesh volume. Preserve the browser's optical
        # thickness approximation separately so the exported recipe is unchanged.
        material['roomkit_transmission_thickness'] = recipe['thickness']
        if hasattr(material, 'use_raytrace_refraction'):
            material.use_raytrace_refraction = recipe['transmission'] > 0
    uv = tree.nodes.new("ShaderNodeUVMap")
    uv.uv_map = UV_NAME
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    mapping.inputs["Scale"].default_value = (1 / size, 1 / size, 1)
    # Three Texture.rotation rotates UV coordinates clockwise around the origin.
    mapping.inputs["Rotation"].default_value[2] = -math.radians(rotation)
    tree.links.new(uv.outputs["UV"], mapping.inputs["Vector"])
    textures = {}
    for key, image in images.items():
        node = tree.nodes.new("ShaderNodeTexImage")
        node.name = "RoomKit " + key
        node.image = image
        node.extension = "REPEAT"
        tree.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        textures[key] = node
    tree.links.new(textures["baseColor"].outputs["Color"], bsdf.inputs["Base Color"])
    split = tree.nodes.new("ShaderNodeSeparateColor")
    tree.links.new(textures["orm"].outputs["Color"], split.inputs["Color"])
    tree.links.new(split.outputs["Green"], bsdf.inputs["Roughness"])
    tree.links.new(split.outputs["Blue"], bsdf.inputs["Metallic"])
    normal = tree.nodes.new("ShaderNodeNormalMap")
    normal.uv_map = UV_NAME
    tree.links.new(textures["normal"].outputs["Color"], normal.inputs["Color"])
    tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
    material.diffuse_color = tuple(int(recipe["color"][i:i + 2], 16) / 255 for i in (1, 3, 5)) + (1,)
    return material


def project_uv(obj):
    """Per-face planar projection in object axes, measured in world metres."""
    uv = obj.data.uv_layers.get(UV_NAME) or obj.data.uv_layers.new(name=UV_NAME)
    scale = obj.matrix_world.to_scale()
    for face in obj.data.polygons:
        normal = [abs(v) for v in face.normal]
        axis = max(range(3), key=normal.__getitem__)
        axes = ((1, 2), (0, 2), (0, 1))[axis]
        for loop_index in face.loop_indices:
            point = obj.data.vertices[obj.data.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = [point[k] * scale[k] for k in axes]
    return uv


def apply_material(objects, material, source_material=None):
    """Apply to explicit meshes; optionally filter by existing material name.

    Copy mesh data before assigning so linked duplicates outside the selection
    keep both their materials and UVs. Preserve the other UV layers and slots.
    """
    changed = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        indices = [i for i, slot in enumerate(obj.material_slots)
                   if source_material is None or (slot.material and slot.material.name == source_material)]
        if source_material is not None and not indices:
            continue
        obj.data = obj.data.copy()
        project_uv(obj)
        if not obj.material_slots:
            obj.data.materials.append(material)
        else:
            for index in indices:
                obj.material_slots[index].material = material
        changed.append(obj.name)
    if not changed:
        raise ValueError("No mesh material slots matched; source is unchanged")
    return changed


def main():
    import bpy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path, help="Generated material.json")
    parser.add_argument("--object", action="append", required=True, help="Exact object or root name; includes its mesh descendants")
    parser.add_argument("--material", help="Only replace slots with this original material name")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    source, output = args.source.resolve(), args.out.resolve()
    if output == source or output.exists():
        raise ValueError("Use a new output .blend; never overwrite a source")
    if output.suffix != ".blend":
        raise ValueError("Output must be a .blend file")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    objects = {}
    for name in args.object:
        root = bpy.data.objects.get(name)
        if root is None:
            raise ValueError("Object not found: " + name)
        for obj in (root, *root.children_recursive):
            objects[obj.name] = obj
    material = load_material(args.bundle)
    changed = apply_material(objects.values(), material, args.material)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError("Source changed during material import")
    report = {"source": str(source), "source_sha256": digest, "output": str(output),
              "bundle": str(args.bundle.resolve()), "recipe": json.loads(material[RECIPE_KEY]),
              "objects": changed, "source_unchanged": True, "images_packed": True}
    output.with_suffix(".materials.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
