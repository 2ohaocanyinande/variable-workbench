"""Local-only UI test harness: delayed success and HTTP error; never calls cloud."""
import json
import threading
import time
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import workbench as w


class Model(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        packet = json.loads(request['messages'][1]['content'])
        if 'fail' in packet.get('question', ''):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"fixture"}')
            return
        if 'endpoints' in packet:
            time.sleep(1)
            first, second = packet['endpoints'][:2]
            sid = first['evidence_ids'][0]
            content = {'devices': [
                {'name': '模拟输出1（多行引用正确）', 'kind': 'unknown', 'instance': 'OUT_1',
                 'endpoint_ids': [first['id']], 'features': ['仅软件回归测试，不连接硬件'],
                 'reason': '自建样例的多行代码引文省略行号，应通过核验。',
                 'evidence': [{'snippet_id':sid,'quote':'case OUT_1:\n__HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, value);'}]},
                {'name': '模拟输出2（故意错误引用）', 'kind': 'unknown', 'instance': 'OUT_2',
                 'endpoint_ids': [second['id']], 'features': [], 'reason': '故意返回不存在的代码，用于验证局部失败提示。',
                 'evidence': [{'snippet_id':sid,'quote':'fabricated_call(OUT_2);'}]}]}
        else:
            time.sleep(8)
            candidate = packet['candidates'][0]
            sid = candidate['evidence_ids'][0]
            quote = packet['snippets'][sid]['code'].splitlines()[0]
            content = {'findings': [{'candidate_id': candidate['id'], 'purpose': '本地模拟用途说明',
                                'reason': '仅用于验证等待动画、结果表格和失败提示；未调用真实模型。',
                                'evidence': [{'snippet_id': sid, 'quote': quote}]}]}
        body = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    w.initialize()
    w.STATE = w.BASE/'state'/'ui-fixture-state'
    w.STATE.mkdir(exist_ok=True)
    if '--devices' in sys.argv:
        root=w.BASE/'ui-fixture-project'
        root.mkdir(exist_ok=True)
        (root/'demo.ioc').write_text('Mcu.Name=STM32F407VGTx\n')
        (root/'main.c').write_text('''// Self-made parsing fixture only; not deployable firmware.
void output(int id, uint16_t value) {
 switch (id) {
 case OUT_1:
  __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, value);
  break;
 case OUT_2:
  __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_2, value);
  break;
 }
}
''')
        w.PROJECT=root
        w.SCAN=w.scan_project(root)
        w.MANIFEST=None
    w.API = {'enabled': True, 'url': 'http://127.0.0.1:8767', 'model': 'local-ui-test', 'key': ''}
    model = ThreadingHTTPServer(('127.0.0.1', 8767), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    print('Local-only UI fixture http://127.0.0.1:8766', flush=True)
    w.ThreadingHTTPServer(('127.0.0.1', 8766), w.Handler).serve_forever()
