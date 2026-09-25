"""Run in Blender: blender -b --python-exit-code 1 --python THIS_FILE."""
import pathlib
import struct
import sys
import tempfile
import zlib

import bpy

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from material_export import linked_color


def chunk(tag, data):
    return struct.pack('>I', len(data))+tag+data+struct.pack('>I', zlib.crc32(tag+data)&0xffffffff)


with tempfile.TemporaryDirectory() as folder:
    # Two different pixels establish that UV samples select source content.
    png = (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 6, 0, 0, 0))
           +chunk(b'IDAT', zlib.compress(bytes([0, 128, 64, 32, 255, 0, 255, 0, 255])))+chunk(b'IEND', b''))
    path = pathlib.Path(folder)/'sample.png'
    path.write_bytes(png)
    image = bpy.data.images.load(str(path))
    mat = bpy.data.materials.new('Linked color regression')
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    socket = nodes.get('Principled BSDF').inputs['Base Color']
    texture = nodes.new('ShaderNodeTexImage')
    texture.image = image
    links.new(texture.outputs['Color'], socket)
    assert abs(image.pixels[0]-128/255) < 1e-5
    assert abs(linked_color(socket, [(.25, .5)])[0]-.2158605) < 1e-5
    assert linked_color(socket, [(.75, .5)]) == (0., 1., 0., 1.)
    coords = nodes.new('ShaderNodeTexCoord')
    links.new(coords.outputs['Generated'], texture.inputs['Vector'])
    assert linked_color(socket, fallback=(.1, .2, .3, 1)) == (.1, .2, .3, 1)
    links.remove(texture.inputs['Vector'].links[0])
    mix = nodes.new('ShaderNodeMixRGB')
    mix.inputs[0].default_value = .25
    mix.inputs[1].default_value = (.1, .2, .3, 1)
    links.new(texture.outputs['Color'], mix.inputs[2])
    links.new(mix.outputs['Color'], socket)
    assert abs(linked_color(socket, [(.75, .5)])[1]-.4) < 1e-5
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (.1, .2, .3, 1)
    ramp.color_ramp.elements[1].color = (.3, .4, .5, 1)
    links.new(ramp.outputs['Color'], socket)
    assert abs(linked_color(socket)[0]-.2) < 1e-5
    # Unsupported scalar source preserves the previous representative midpoint.
    fresnel = nodes.new('ShaderNodeFresnel')
    links.new(fresnel.outputs[0], ramp.inputs[0])
    assert abs(linked_color(socket)[0]-.2) < 1e-5
    bpy.data.materials.remove(mat)
    bpy.data.images.remove(image)
print('Linked material color regression passed')
