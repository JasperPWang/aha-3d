// Convex support footprints are exported from verified horizontal top faces.
export function containsCircle(s,x,y,r=0){
 if(!s.footprint)return x-r>=s.min[0]&&x+r<=s.max[0]&&y-r>=s.min[1]&&y+r<=s.max[1];
 return s.footprint.every((a,i)=>{const b=s.footprint[(i+1)%s.footprint.length],dx=b[0]-a[0],dy=b[1]-a[1];return (dx*(y-a[1])-dy*(x-a[0]))/Math.hypot(dx,dy)>=r-1e-7;});
}
