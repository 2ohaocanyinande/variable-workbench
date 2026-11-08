"""Read-only real-model check using settings already configured in the local app.

No credentials are read by this script. Reports are written only beside the app.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parent
ROOT = Path('D:/Halpractice').resolve()
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(route, body=None, timeout=110):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request('http://127.0.0.1:8765/api/' + route, data=data,
                                     headers={'Content-Type': 'application/json'})
    try:
        with OPENER.open(request, timeout=timeout) as response: return json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(json.load(error).get('error', 'local request failed')) from None


def integrity():
    audit = json.loads((BASE / 'state/halpractice-audit-before.json').read_text(encoding='utf-8'))
    files = {}
    for project in audit:
        for relative, expected in project['hashes'].items():
            path = (Path(project['root']) / relative).resolve()
            if not path.is_relative_to(ROOT): raise ValueError('Audit path outside authorized directory')
            files[path] = expected
    changed = [str(path) for path, expected in files.items()
               if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected]
    return {'checked': len(files), 'changed': changed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('projects', nargs='*', default=['first_car_clion', 'qianrushidasaitest_1', 'qiansaitest-2'])
    parser.add_argument('--report', default='halpractice-api-results.json')
    parser.add_argument('--source', action='store_true', help='Test updated Python source in a separate local process')
    args = parser.parse_args()
    target = (BASE / 'state' / args.report).resolve()
    if target.parent != BASE / 'state': raise ValueError('Report must be in workbench/state')
    invoke = call
    if args.source:
        import workbench as workbench
        workbench.initialize()
        def invoke(route, body=None):
            if route == 'state':
                return {'api_configured': bool(workbench.API.get('enabled')),
                        'api_settings': {'model': workbench.API.get('model')}}
            if route == 'scan':
                workbench.SCAN = workbench.scan_project(Path(body['path']))
                return workbench.SCAN
            if route == 'analyze-usage': return workbench.analyze_usage(body)
            raise ValueError('Unsupported diagnostic operation')
    settings = invoke('state')
    if not settings.get('api_configured'): raise ValueError('请先在工作台启用并配置模型')
    results = {'model': settings['api_settings']['model'], 'projects': []}
    for name in args.projects:
        root = (ROOT / name).resolve()
        if not root.is_relative_to(ROOT): raise ValueError('Project outside authorized directory')
        print('START ' + name, flush=True)
        item = {'root': str(root)}; started = time.monotonic()
        try:
            scan = invoke('scan', {'path': str(root)})
            item['project_hash'] = scan['project_hash']
            if args.source:
                original_validate = workbench.validate_partial
                def capture(decoded, packet):
                    item['model_candidates'] = decoded
                    return original_validate(decoded, packet)
                workbench.validate_partial = capture
            try: item['report'] = invoke('analyze-usage', {'mode': 'devices'})
            finally:
                if args.source: workbench.validate_partial = original_validate
        except (ValueError, OSError) as error:
            item['error'] = str(error)
        item['seconds'] = round(time.monotonic() - started, 2)
        results['projects'].append(item)
        results['source_integrity'] = integrity()
        target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        report = item.get('report', {})
        print(json.dumps({'project': name, 'seconds': item['seconds'], 'error': item.get('error'),
                          'devices': [{'name': d['name'], 'kind': d['kind'], 'instance': d['instance'],
                                       'model': d.get('model')} for d in report.get('devices', [])],
                          'warnings': report.get('warnings'), 'coverage': report.get('coverage')},
                         ensure_ascii=False), flush=True)
    print(json.dumps({'integrity': results['source_integrity'], 'report': str(target)}, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
