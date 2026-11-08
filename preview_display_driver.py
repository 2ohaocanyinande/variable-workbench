"""Isolated local visual check. Does not load API settings or change app state."""
import argparse
import json
from pathlib import Path
import workbench as w

p=argparse.ArgumentParser()
p.add_argument('--root',required=True)
p.add_argument('--port',type=int,default=8771)
p.add_argument('--values',default='{}')
p.add_argument('--values-file')
a=p.parse_args()
values=json.loads(Path(a.values_file).read_text(encoding='utf-8')) if a.values_file else json.loads(a.values)
w.STATE=w.BASE/'state'/'display-driver-preview';w.STATE.mkdir(exist_ok=True)
w.SCAN=w.scan_project(Path(a.root))

class Preview(w.Handler):
    def do_GET(self):
        if self.path=='/app.js':
            extra='\nsetTimeout(async()=>{workspaceNavigated=true;showWorkspace("screen");await loadScreen(true);for(const [k,v] of Object.entries('+json.dumps(values)+'))if(ssWidgets.has(k))ssWidgets.get(k).value=v;await previewSourceScreen();},400);'
            body=(w.BASE/'dist/app.js').read_bytes()+extra.encode()
            self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        super().do_GET()

w.ThreadingHTTPServer(('127.0.0.1',a.port),Preview).serve_forever()
