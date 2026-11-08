import workbench as w
w.STATE=w.BASE/'state'/'source-display-preview';w.STATE.mkdir(exist_ok=True)
w.SCAN=w.scan_project(w.BASE/'sample_source_screen')
class Preview(w.Handler):
    def do_GET(self):
        if self.path=='/app.js':
            extra="""\nsetTimeout(async()=>{workspaceNavigated=true;showWorkspace('screen');await loadScreen(true);for(const [k,v] of Object.entries({speed:23,angle:15,page:0,key:0,kp:12}))if(ssWidgets.has(k))ssWidgets.get(k).value=v;await previewSourceScreen();},300);"""
            body=(w.BASE/'dist/app.js').read_bytes()+extra.encode();self.send_response(200);self.send_header('Content-Type','text/javascript; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        super().do_GET()
w.ThreadingHTTPServer(('127.0.0.1',8770),Preview).serve_forever()
