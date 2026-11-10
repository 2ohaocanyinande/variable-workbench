import csv
import json
from pathlib import Path
import tempfile
import unittest
import threading
import urllib.request
from unittest.mock import patch
import telemetry as t
import workbench as w


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=w.BASE);self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/'records'

    def test_demo_wrap_gap_spikes_and_reload(self):
        meta=t.demo(self.base)
        self.assertEqual(meta['source'],'simulation');self.assertEqual(meta['samples'],400)
        report=t.analyze(self.base,meta['id'],'encoder_count','encoder',4096,1024)
        self.assertEqual(report['wrap_count'],2);self.assertEqual(report['net_change'],4788)
        self.assertEqual(report['gap_count'],1);self.assertEqual(report['spike_count'],2)
        self.assertEqual(report['rotation_degrees'],4788*360/1024)
        self.assertEqual(t.listing(self.base)[0]['id'],meta['id'])
        angle=t.analyze(self.base,meta['id'],'angle_deg','angle',360,0,'target_deg',10)
        self.assertEqual(angle['spike_count'],2);self.assertIsNotNone(angle['mae'])

    def test_serial_chunk_framing_and_raw_bytes_persist(self):
        r=t.Recorder(self.base);meta=r.start()
        r.event({'direction':'RX','text':'{"t":0,"angle":1','hex':'AA'})
        r.event({'direction':'TX','text':'command','hex':'AB'})
        r.event({'direction':'RX','text':'}\n{"t":0.1,"angle":2}\n','hex':'BB'})
        r.event({'direction':'RX','text':'{"t":0.2,"angle":3}\n','hex':'CC'})
        r.stop();saved,rows=t.load(self.base,meta['id'])
        self.assertEqual(saved['samples'],3);self.assertEqual(rows[0]['values']['angle'],1)
        raw=(self.base/meta['id']/'raw.jsonl').read_text(encoding='utf-8')
        self.assertIn('command',raw);self.assertIn('AA',raw)

    def test_key_values_csv_and_invalid_lines(self):
        r=t.Recorder(self.base);meta=r.start()
        for line in ['ordinary log','t,angle,encoder','0,10,20','0.1,11,21','t=0.2,angle=12,encoder=22','{"t":0.3,"angle":NaN}']:
            r.line(line)
        r.stop();saved,rows=t.load(self.base,meta['id'])
        self.assertEqual(len(rows),3);self.assertEqual(saved['invalid_lines'],2)

    def test_circular_error_and_invalid_timestamps(self):
        r=t.Recorder(self.base);meta=r.start()
        for ts,a in [(0,359),(0,1),(.1,2)]:r.sample(ts,{'angle':a,'target':0})
        r.stop();report=t.analyze(self.base,meta['id'],'angle','angle',360,0,'target')
        self.assertEqual(report['invalid_time_count'],1)
        self.assertAlmostEqual(report['mae'],4/3)
        self.assertEqual(report['net_change'],3)

    def test_source_label_in_csv_and_path_rejection(self):
        meta=t.demo(self.base);path=t.export_csv(self.base,meta['id'])
        with open(path,encoding='utf-8-sig',newline='') as file:rows=list(csv.reader(file))
        self.assertEqual(rows[0][:2],['source','t_seconds']);self.assertEqual(rows[1][0],'simulation')
        self.assertEqual(len(rows),401)
        with self.assertRaises(ValueError):t.load(self.base,'../other')
        with self.assertRaises(ValueError):t.analyze(self.base,meta['id'],'not present')
        with self.assertRaises(ValueError):t.analyze(self.base,meta['id'],'angle_deg',period=float('nan'))

    def test_unknown_unit_is_not_guessed_and_trailing_frame_not_fabricated(self):
        r=t.Recorder(self.base);meta=r.start()
        r.event({'direction':'RX','text':'{"angle":','hex':'00'})
        r.stop();saved,rows=t.load(self.base,meta['id'])
        self.assertFalse(rows);self.assertEqual(saved['invalid_lines'],1)

    def test_http_saved_record_analysis_report_and_csv_download(self):
        with patch.object(w,'STATE',Path(self.tmp.name)),patch.object(w,'RECORDER',None):
            server=w.ThreadingHTTPServer(('127.0.0.1',0),w.Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(route,body=None):
                encoded=None if body is None else json.dumps(body).encode()
                return opener.open(urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/{route}',data=encoded),timeout=3)
            try:
                meta=t.demo(w.STATE/'records')
                with request('record-analyze',{'id':meta['id'],'channel':'encoder_count','kind':'encoder','period':4096,'cpr':1024}) as r:report=json.load(r)
                self.assertTrue(Path(report['report_path']).is_file())
                with request('record-download?id='+meta['id']) as r:
                    self.assertIn('simulation_samples.csv',r.headers['Content-Disposition'])
                    self.assertIn('simulation',r.read().decode('utf-8-sig'))
                with request('records') as r:self.assertEqual(json.load(r)['records'][0]['samples'],400)
            finally:server.shutdown();server.server_close()

    def test_loopback_samples_are_persisted_via_console_observer(self):
        import serial
        from serial_console import SerialConsole
        port=serial.serial_for_url('loop://',timeout=.05)
        try:
            with patch.object(w,'STATE',Path(self.tmp.name)),patch.object(w,'RECORDER',None),\
                 patch.object(w,'PORT',port),patch.object(w,'PORT_MODE','raw'),\
                 patch.object(w,'CONSOLE',SerialConsole()),patch.object(w,'RECORD_THREAD_STARTED',True):
                meta=w.start_record()
                with w.LOCK:
                    w.serial_send({'content':'{"t":0,"angle":1}\n{"t":0.1,"angle":2}\n{"t":0.2,"angle":3}\n'})
                    w.serial_data()
                    w.record_store().stop()
                saved,rows=t.load(Path(self.tmp.name)/'records',meta['id'])
                self.assertEqual(saved['source'],'serial');self.assertEqual(len(rows),3)
                self.assertTrue((Path(self.tmp.name)/'records'/meta['id']/'raw.jsonl').is_file())
        finally:port.close()


if __name__=='__main__':unittest.main()
