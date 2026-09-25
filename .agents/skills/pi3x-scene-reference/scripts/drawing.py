"""Plain equal-axis-scale drawing for measurement evidence."""
import math
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def font(size):
    candidates=[os.environ.get('PI3X_REFERENCE_FONT',''),
                '/usr/share/fonts/dejavu/DejaVuSansMono.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']
    for path in candidates:
        if path and Path(path).is_file():return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)

class Sheet:
    def __init__(self,title,axes,bounds,cloud,scale,grid=0.5,ppm=None,status=None,floor_label='Z=0 is a reference plane; verify its meaning',colors=None):
        self.im=Image.new('RGB',(1760,1350),'white');self.d=ImageDraw.Draw(self.im)
        self.axes=axes;self.bounds=np.array(bounds)*scale
        self.area=(120,190,1200,1220)
        x0,y0,x1,y1=self.area
        span=self.bounds[:,1]-self.bounds[:,0]
        self.ppm=min(240/scale,(x1-x0)/span[0],(y1-y0)/span[1])
        if ppm is not None:self.ppm=ppm
        self.center=np.mean(self.bounds,axis=1);self.origin=np.array([(x0+x1)/2,(y0+y1)/2])
        self.d.text((45,25),title,fill='black',font=font(37))
        self.d.text((45,82),f'METRES | {grid:g} m grid | Equal scale on both axes',fill='black',font=font(25))
        status=status or 'Pi3X predicted scale, not physically calibrated'
        self.d.text((45,122),status,fill='black',font=font(24))
        pixels=np.rint(self.map(cloud)).astype(int)
        inside=(pixels[:,0]>x0)&(pixels[:,0]<x1)&(pixels[:,1]>y0)&(pixels[:,1]<y1)
        raster=np.asarray(self.im).copy()
        selected=np.flatnonzero(inside)
        # Keep the nearest observed point at each projected pixel, not the last arbitrary sample.
        depth_axis=next(i for i in range(3) if i not in axes)
        sign=-1 if depth_axis==2 else 1
        selected=selected[np.argsort(sign*np.asarray(cloud)[selected,depth_axis],kind='stable')]
        flat=pixels[selected,1]*self.im.width+pixels[selected,0]
        _,first=np.unique(flat,return_index=True);selected=selected[first]
        raster[pixels[selected,1],pixels[selected,0]]=(200,200,200) if colors is None else np.asarray(colors,dtype=np.uint8)[selected]
        self.im=Image.fromarray(raster);self.d=ImageDraw.Draw(self.im)
        for axis in range(2):
            ticks=np.arange(math.ceil(self.bounds[axis,0]/grid),math.floor(self.bounds[axis,1]/grid)+1)*grid
            for value in ticks:
                a=self.center.copy();b=self.center.copy();a[axis]=b[axis]=value
                a[1-axis]=self.bounds[1-axis,0];b[1-axis]=self.bounds[1-axis,1]
                ap=self.map2(a);bp=self.map2(b)
                self.d.line((*ap,*bp),fill=(215,215,215) if value else (110,110,110),width=1 if value else 2)
                if axis==0:self.label((ap[0],y1+25),f'{value:g}',size=21)
                else:self.label((x0-50,ap[1]),f'{value:g}',size=21)
        self.d.rectangle(self.area,outline='black',width=2)
        self.label(((x0+x1)/2,y1+66),f'{"XYZ"[axes[0]]} (m)',size=27)
        self.d.text((42,155),f'{"XYZ"[axes[1]]} (m)',fill='black',font=font(27))
        self.d.text((1260,1170),'RGB: observed source colors' if colors is not None else 'Grey: observed points',fill='black',font=font(21))
        self.d.text((1260,1200),'Blank: unobserved/filtered',fill='black',font=font(21))
        self.d.text((45,1310),floor_label[:125],fill='black',font=font(20))

    def map2(self,xy):
        q=(np.asarray(xy)-self.center)*self.ppm*np.array([1,-1])+self.origin
        return tuple(q.tolist())
    def map(self,xyz):return (np.asarray(xyz)[...,self.axes]-self.center)*self.ppm*np.array([1,-1])+self.origin
    def label(self,xy,text,size=23):
        f=font(size);box=self.d.textbbox((0,0),text,font=f);w,h=box[2]-box[0],box[3]-box[1]
        x,y=xy;self.d.rectangle((x-w/2-5,y-h/2-6,x+w/2+5,y+h/2+6),fill='white')
        self.d.text((x-w/2,y-h/2-box[1]),text,fill='black',font=f)
    def line(self,points,color='black',width=3):
        self.d.line([tuple(p) for p in self.map(np.asarray(points))],fill=color,width=width)
    def point(self,p,label=None,offset=(15,-18)):
        x,y=self.map(p);self.d.ellipse((x-5,y-5,x+5,y+5),fill='black')
        if label:self.label((x+offset[0],y+offset[1]),label,size=21)
    def dimension(self,a,b,text,offset):
        ap,bp=self.map(a),self.map(b);delta=bp-ap;length=np.linalg.norm(delta)
        if length<1:return
        unit=delta/length;normal=np.array([-unit[1],unit[0]])
        aa=ap+normal*offset;bb=bp+normal*offset
        self.d.line([tuple(ap),tuple(aa+normal*8)],fill='black',width=1)
        self.d.line([tuple(bp),tuple(bb+normal*8)],fill='black',width=1)
        self.d.line([tuple(aa),tuple(bb)],fill='black',width=2)
        for end,direction in [(aa,unit),(bb,-unit)]:
            self.d.polygon([tuple(end),tuple(end+direction*12+normal*5),tuple(end+direction*12-normal*5)],fill='black')
        self.label((aa+bb)/2,text,size=25)
    def legend(self,measurements):
        import textwrap
        y=210
        for m in measurements:
            self.d.text((1260,y),m['id'],fill='black',font=font(25))
            self.d.text((1260,y+32),f"~{m['value_m']:.2f} m",fill='black',font=font(25))
            for j,line in enumerate(textwrap.wrap(m['label'],width=34)[:2]):self.d.text((1260,y+66+j*24),line,fill='black',font=font(21))
            y+=min(135,690//max(1,len(measurements)))
        for text in ['Endpoints: source_*.png','Numbers/data: measurements.json','Values rounded to 0.01 m;', 'this is not an accuracy claim.']:
            self.d.text((1260,y+35),text,fill='black',font=font(20));y+=32
