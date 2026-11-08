import json
import threading
import unittest
import urllib.request
from unittest.mock import patch, PropertyMock

import serial
import workbench as w
from serial_console import SerialConsole


class SerialTests(unittest.TestCase):
    def setUp(self):
        for name, value in [('PORT',None),('PORT_MODE',None),('CONSOLE',SerialConsole()),
                            ('SCAN',{'platform':'stm32'}),('MANIFEST',None),('REQUEST_ID',0)]:
            p=patch.object(w,name,value);p.start();self.addCleanup(p.stop)
        self.addCleanup(w.close_port)
        def factory(**kwargs):
            kwargs.pop('port',None)
            return serial.serial_for_url('loop://',do_not_open=True,**kwargs)
        p=patch.object(w.serial,'Serial',side_effect=factory);p.start();self.addCleanup(p.stop)

    def connect(self): return w.connect_port({'mode':'raw','port':'loop://','baudrate':115200})

    def test_stm32_opens_without_manifest_or_handshake(self):
        result=self.connect()
        self.assertFalse(result['protocol_ready'])
        self.assertEqual(w.PORT.in_waiting,0)
        self.assertEqual(w.CONSOLE.tx_bytes,0)
        with self.assertRaises(ValueError): w.exchange('hello')
        self.assertEqual(w.CONSOLE.tx_bytes,0)

    def test_text_and_binary_loopback_cursor(self):
        self.connect()
        text='你好 STM32'
        sent=w.serial_send({'content':text,'ending':'crlf'})
        self.assertEqual(sent['sent_bytes'],len(text.encode())+2)
        snapshot=w.serial_data()
        rx=[e for e in snapshot['events'] if e['direction']=='RX']
        self.assertEqual(rx[0]['text'],text+'\r\n')
        after=snapshot['last_id']
        self.assertEqual(w.serial_data(after)['events'],[])
        w.serial_send({'content':'00 AA ff 55','format':'hex'})
        snapshot=w.serial_data(after)
        self.assertEqual(snapshot['events'][-1]['hex'],'00 AA FF 55')
        self.assertEqual(snapshot['rx_bytes'],len(text.encode())+6)

    def test_invalid_send_is_rejected_before_write(self):
        self.connect()
        for data in [{'content':'GG','format':'hex'}, {'content':'ABC','format':'hex'},
                     {'content':'AA'*4097,'format':'hex'}, {'content':'x'*4097},
                     {'content':None}, {'content':'x','ending':'bad'}]:
            with self.assertRaises(ValueError): w.serial_send(data)
        self.assertEqual(w.PORT.in_waiting,0)

    def test_close_and_validation(self):
        for data in [{'mode':'raw','port':''},{'mode':'raw','port':'loop://','baudrate':True},
                     {'mode':'raw','port':'loop://','baudrate':0},{'mode':'other','port':'loop://'},
                     {'mode':'bridge','port':'loop://'}]:
            with self.assertRaises(ValueError): w.connect_port(data)
        self.connect();port=w.PORT;w.close_port()
        self.assertFalse(port.is_open)
        with self.assertRaises(ValueError): w.serial_send({'content':'hello'})

    def test_stream_decoder_and_bounded_history(self):
        console=SerialConsole();data='中'.encode()
        console.record('RX',data[:1]);console.record('RX',data[1:])
        self.assertEqual(''.join(e['text'] for e in console.events),'中')
        for _ in range(40): console.record('RX',b'x'*4096)
        self.assertLessEqual(console.retained_bytes,65536)
        self.assertGreater(console.rx_bytes,65536)
        self.assertTrue(console.snapshot(1)['history_truncated'])

    def test_unplug_error_clears_connection(self):
        self.connect()
        with patch.object(type(w.PORT),'in_waiting',new_callable=PropertyMock,side_effect=serial.SerialException('removed')):
            with self.assertRaisesRegex(ValueError,'串口已断开'): w.serial_data()
        self.assertIsNone(w.PORT)
        self.assertIsNone(w.PORT_MODE)

    def test_partial_write_records_only_written_bytes(self):
        self.connect()
        with patch.object(w.PORT,'write',return_value=2):
            with self.assertRaisesRegex(ValueError,'部分发送'): w.serial_send({'content':'ABCD'})
        self.assertEqual(w.CONSOLE.tx_bytes,2)
        self.assertEqual(w.CONSOLE.events[-1]['text'],'AB')

    def test_http_connect_receive_disconnect(self):
        server=w.ThreadingHTTPServer(('127.0.0.1',0),w.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(route,body=None):
            data=None if body is None else json.dumps(body).encode()
            with opener.open(urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/{route}',data=data),timeout=3) as r:
                return json.load(r)
        request('connect',{'mode':'raw','port':'loop://','baudrate':9600})
        with patch.object(w.list_ports,'comports',return_value=[]):
            state=request('state')
        self.assertTrue(state['connected']);self.assertFalse(state['bridge_connected'])
        self.assertEqual(state['serial_baudrate'],9600)
        request('serial-send',{'content':'PING','ending':'lf'})
        data=request('serial-data?after=0')
        self.assertEqual(data['rx_bytes'],5)
        request('serial-clear',{})
        self.assertEqual(request('serial-data?after=0')['rx_bytes'],0)
        request('disconnect',{})
        self.assertIsNone(w.PORT)

    def test_existing_bridge_handshake_and_schema_rejection(self):
        class Bridge:
            def __init__(self,**kwargs):
                self.baudrate=kwargs['baudrate'];self.is_open=False;self.writes=[]
            def open(self): self.is_open=True
            def close(self): self.is_open=False
            def reset_input_buffer(self): pass
            def write(self,data): self.writes.append(json.loads(data));return len(data)
            def readline(self): return json.dumps({'id':self.writes[-1]['id'],'ok':True,'schema_id':'test'}).encode()+b'\n'
        port=Bridge(baudrate=115200)
        with patch.object(w,'SCAN',{'platform':'esp32'}),patch.object(w,'MANIFEST',{'schema_id':'test'}),\
             patch.object(w,'ensure_current'),patch.object(w.serial,'Serial',return_value=port):
            self.assertTrue(w.connect_port({'port':'COM_TEST'})['protocol_ready'])
            self.assertEqual(port.writes[0]['op'],'hello')
            with self.assertRaises(ValueError): w.serial_send({'content':'arbitrary'})
            w.MANIFEST={'schema_id':'wrong'}
            with self.assertRaises(ValueError): w.connect_port({'port':'COM_TEST'})
            self.assertFalse(port.is_open)


if __name__=='__main__': unittest.main()
