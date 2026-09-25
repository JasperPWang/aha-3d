#!/usr/bin/env python3
"""Loopback-only review server with an explicit artifact allowlist and byte ranges."""
import argparse,json,re,os
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import unquote,urlsplit
if __package__:
    from .inspection_bundle import bundle_artifacts
else:
    from inspection_bundle import bundle_artifacts
ROOT=Path(__file__).resolve().parents[2]

def artifact_allowlist(entry):
    content=entry.read_text();match=re.search(r'<script id="caseData" type="application/json">(.*?)</script>',content,re.S)
    if not match:raise ValueError('Not a built experiment portal')
    paths={entry.resolve()}
    def walk(obj):
        if isinstance(obj,dict):
            if obj.get('bundle'):
                if not obj.get('report'):
                    raise ValueError('Inspection bundle requires its linked report')
                paths.update(bundle_artifacts(entry.parent / obj['bundle'], root=ROOT,
                                               entry=entry.parent / obj['report']))
            for key,value in obj.items():
                if key in ('source_video','source_original','room_blend','report','video','blend','motion','figure','attribution') and value:
                    path=(entry.parent/value).resolve()
                    if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError(f'Invalid review artifact {value}')
                    paths.add(path)
                else:walk(value)
        elif isinstance(obj,list):
            for value in obj:walk(value)
    walk(json.loads(match.group(1)))
    return paths

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--entry',type=Path,required=True);p.add_argument('--port',type=int,default=8080);a=p.parse_args();entry=a.entry.resolve();allowed=artifact_allowlist(entry);entry_url='/'+entry.relative_to(ROOT).as_posix()
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
        def send_head(self):
            self._remaining=None
            url=unquote(urlsplit(self.path).path)
            if url=='/':self.send_response(302);self.send_header('Location',entry_url);self.send_header('Content-Length','0');self.end_headers();return None
            path=(ROOT/url.lstrip('/')).resolve()
            if path not in allowed:self.send_error(404,'Not a review artifact');return None
            try:f=path.open('rb')
            except OSError:self.send_error(404);return None
            size=os.fstat(f.fileno()).st_size;start=0;end=size-1;status=200
            value=self.headers.get('Range')
            if value:
                m=re.fullmatch(r'bytes=(\d*)-(\d*)',value.strip())
                try:
                    if not m or not any(m.groups()):raise ValueError()
                    if m[1]:start=int(m[1]);end=min(int(m[2]),size-1) if m[2] else size-1
                    else:start=max(0,size-int(m[2]));end=size-1
                    if start<0 or start>=size or end<start:raise ValueError()
                except ValueError:
                    f.close();self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
                status=206
            self.send_response(status);self.send_header('Content-Type',self.guess_type(str(path)));self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-cache')
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers();f.seek(start);self._remaining=end-start+1;return f
        def copyfile(self,source,outputfile):
            left=self._remaining
            try:
                while left:
                    data=source.read(min(left,1024*1024))
                    if not data:break
                    outputfile.write(data);left-=len(data)
            except (BrokenPipeError,ConnectionResetError):pass
    print(json.dumps({'listen':f'http://127.0.0.1:{a.port}/','entry':entry_url,'allowed_artifacts':len(allowed)}),flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
