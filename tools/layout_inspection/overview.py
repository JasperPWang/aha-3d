"""Readable overview from existing semantic silhouettes; no new 3D rendering."""
import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def architecture(obj):
    return obj.get('semantic_class', '').startswith('structure/')


def draw_overview(background, view, objects):
    """Keep whole-object envelopes, stable ID colors and a numbered legend."""
    image = Image.open(background).convert('RGBA')
    if tuple(view.get('size', image.size)) != image.size:
        raise ValueError('Overview background and cached contours must share a raster')
    objects = sorted(objects, key=lambda obj: obj['id'])
    identities = [obj['id'] for obj in objects]
    if len(identities) != len(set(identities)) or set(identities) != set(view['objects']):
        raise ValueError('Overview must preserve the complete cached object inventory')
    font = ImageFont.load_default()
    layer = Image.new('RGBA', image.size); draw = ImageDraw.Draw(layer)
    numbers = {obj['id']: index+1 for index, obj in enumerate(objects)}
    present = [obj for obj in objects if view['objects'][obj['id']]['paths']]
    # Architectural envelopes are context, not hundreds of tile/trim boundaries.
    # Paint furniture last; preserve all objects and make every ID discoverable.
    for obj in sorted(present, key=lambda obj: not architecture(obj)):
        rgba = tuple(obj['color']) + (100 if architecture(obj) else 255,)
        for path in view['objects'][obj['id']]['paths']:
            draw.line([tuple(point) for point in path+path[:1]], fill=rgba,
                      width=1 if architecture(obj) else 2)
    occupied = []
    width, height = image.size
    for obj in sorted(present, key=lambda obj: architecture(obj)):
        paths = view['objects'][obj['id']]['paths']; path = max(paths, key=len)
        anchor = min(path, key=lambda point: point[0]+point[1])
        text = str(numbers[obj['id']]); box = draw.textbbox((0,0), text, font=font)
        tw, th = box[2]-box[0]+6, box[3]-box[1]+6
        x = min(max(0, round(anchor[0])), max(0, width-tw))
        y0 = min(max(0, round(anchor[1])), max(0, height-th))
        candidates = [y0] + list(range(2, max(3,height-th), th+2))
        y = next((y for y in candidates if not any(x < bx+bw and x+tw > bx and y < by+bh and y+th > by for bx,by,bw,bh in occupied)), y0)
        occupied.append((x,y,tw,th))
        if abs(y-y0)>th: draw.line([tuple(anchor),(x+tw/2,y+th/2)],fill=tuple(obj['color'])+(150,),width=1)
        draw.rectangle((x,y,x+tw,y+th),fill=(20,24,29,235),outline=tuple(obj['color'])+(255,))
        draw.text((x+3-box[0],y+3-box[1]),text,font=font,fill=(255,255,255,255))
    image = Image.alpha_composite(image,layer).convert('RGB')
    columns = max(1, width//230); rows = math.ceil(len(present)/columns)
    result = Image.new('RGB',(width,height+38+rows*20),(24,28,34));result.paste(image,(0,0))
    legend = ImageDraw.Draw(result)
    legend.text((8,height+5),'Model IDs: faint architecture, colored object envelopes',font=font,fill=(235,240,245))
    for index,obj in enumerate(present):
        x=8+(index%columns)*(width//columns);y=height+28+(index//columns)*20
        legend.rectangle((x,y,x+8,y+8),fill=tuple(obj['color']))
        legend.text((x+13,y-2),str(numbers[obj['id']])+' '+obj['id'],font=font,fill=(225,230,235))
    return result, [obj['id'] for obj in present]


def write_overviews(out, report, inspection):
    out, inspection = Path(out), Path(inspection)
    rows=[]
    for name,view in report['views'].items():
        for mode in ('reference','source'):
            background=inspection/f'{name}_{mode}.png'
            if not background.exists():continue
            image,present=draw_overview(background,view,report['objects'])
            path=out/f'{name}_overview_{mode}.png';image.save(path)
            rows.append(dict(view=name,background=mode,path=path.name,object_ids=present))
    manifest=dict(schema_version=1,images=rows,
                  policy='Whole-object external silhouettes from the existing exact-view packet; stable authored ID colors, numbered legend, faint architecture.',
                  limitations=['External envelopes omit internal parts and enclosed holes. Inspect openings, tile/trim details and occlusion in the detailed/clay/source views.',
                               'No automatic source identity matching. Unknown/unassigned objects remain in the inventory.',
                               'No geometry modification or new acceptance judgment.'])
    (out/'overview.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outlines',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.outlines.read_text());args.out.mkdir(parents=True,exist_ok=False)
    write_overviews(args.out,report,report['source_inspection'])
