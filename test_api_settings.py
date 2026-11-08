import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

import api_store
import workbench as w


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=w.BASE)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('STATE', self.root), ('API', {}), ('API_STORE_ERROR', ''),
                            ('SCAN', None), ('MANIFEST', None), ('PORT', None), ('PROJECT', w.PROJECT)]:
            p = patch.object(w, name, value); p.start(); self.addCleanup(p.stop)
        self.settings = {'enabled': True, 'url': 'https://example.invalid',
                         'model': 'test', 'key': 'FAKE_TEST_KEY_NOT_REAL', 'remember': True}
        # Unit tests isolate persistence from the Windows profile/sandbox.
        # The opt-in real DPAPI test below checks the actual OS implementation.
        def codec(data, decrypt=False):
            if decrypt:
                if not data.startswith(b'test:'): raise ValueError('bad ciphertext')
                return data[5:][::-1]
            return b'test:' + data[::-1]
        p = patch.object(api_store, 'crypt', side_effect=codec); p.start(); self.addCleanup(p.stop)

    def test_saved_settings_restore_on_startup(self):
        result = w.configure_api(self.settings)
        self.assertTrue(result['remembered'])
        path = self.root / 'model-settings.dpapi'
        self.assertNotIn(self.settings['key'].encode(), path.read_bytes())
        w.API.clear()
        with patch.object(w, 'scan_project', return_value={'root': 'demo'}) as scan:
            w.initialize()
        self.assertEqual(w.API['key'], self.settings['key'])
        scan.assert_called_once_with(w.BASE / 'sample_esp32')
        self.assertEqual(w.API_STORE_ERROR, '')

    def test_session_only_and_forget_remove_saved_key(self):
        w.configure_api(self.settings)
        w.configure_api(dict(self.settings, key='', remember=False))
        self.assertEqual(w.API['key'], self.settings['key'])
        self.assertFalse((self.root / 'model-settings.dpapi').exists())
        w.configure_api(self.settings)
        w.API_STORE_ERROR = 'previous failure'
        w.forget_api()
        self.assertEqual(w.API, {})
        self.assertEqual(w.API_STORE_ERROR, '')
        self.assertFalse((self.root / 'model-settings.dpapi').exists())

    def test_invalid_or_failed_save_preserves_previous_settings(self):
        w.configure_api(self.settings)
        before = (self.root / 'model-settings.dpapi').read_bytes()
        with self.assertRaises(ValueError):
            w.configure_api(dict(self.settings, url='https://other.invalid', key=''))
        with patch.object(api_store, 'crypt', side_effect=ValueError('encryption failed')):
            with self.assertRaises(ValueError): w.configure_api(dict(self.settings, key='other'))
        self.assertEqual(w.API['key'], self.settings['key'])
        self.assertEqual((self.root / 'model-settings.dpapi').read_bytes(), before)

    def test_corrupt_saved_file_does_not_block_startup(self):
        (self.root / 'model-settings.dpapi').write_bytes(b'broken')
        with patch.object(w, 'scan_project', return_value={'root': 'demo'}): w.initialize()
        self.assertFalse(w.API)
        self.assertIn('无法解密', w.API_STORE_ERROR)

    def test_http_metadata_close_and_disable(self):
        server = w.ThreadingHTTPServer(('127.0.0.1', 0), w.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(route, body=None):
            encoded = None if body is None else json.dumps(body).encode()
            with opener.open(urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/{route}',
                                                   data=encoded), timeout=3) as response:
                return response.read()
        with patch.object(w.list_ports, 'comports', return_value=[]):
            saved = request('settings', self.settings)
            metadata = request('state')
            self.assertNotIn(self.settings['key'].encode(), saved + metadata)
            self.assertTrue(json.loads(metadata)['api_remembered'])
            request('window-close', {})
            self.assertEqual(w.API['key'], self.settings['key'])
            request('settings', dict(self.settings, remember=False))
            request('window-close', {})
            self.assertEqual(w.API, {})
            request('settings', self.settings)
            request('settings', {'enabled': False})
            self.assertFalse(json.loads(request('state'))['api_remembered'])
            self.assertEqual(w.API, {})


@unittest.skipUnless(os.environ.get('WORKBENCH_TEST_REAL_DPAPI') == '1', 'requires normal Windows user context')
class RealWindowsTests(unittest.TestCase):
    def test_real_encrypted_file_roundtrip_and_tamper(self):
        with tempfile.TemporaryDirectory(dir=w.BASE) as directory:
            path = Path(directory) / 'settings.dpapi'
            fake = {'enabled': True, 'url': 'https://example.invalid', 'model': 'test',
                    'key': 'LOCAL_FAKE_TEST_KEY_NEVER_A_REAL_CREDENTIAL'}
            api_store.save(path, fake)
            self.assertNotIn(fake['key'].encode(), path.read_bytes())
            self.assertEqual(api_store.load(path), fake)
            damaged = bytearray(path.read_bytes()); damaged[-1] ^= 1; path.write_bytes(damaged)
            with self.assertRaises(ValueError): api_store.load(path)


if __name__ == '__main__': unittest.main()
