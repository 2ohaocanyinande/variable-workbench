"""Bounded raw serial console, independent of firmware / model protocols."""
import codecs
from collections import deque
import re
import time


class SerialConsole:
    def __init__(self):
        self.session = 0
        self.observer = None
        self.reset()

    def reset(self):
        self.session += 1
        self.events = deque()
        self.retained_bytes = 0
        self.sequence = 0
        self.rx_bytes = self.tx_bytes = 0
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def record(self, direction, data):
        self.sequence += 1
        if direction == 'RX':
            self.rx_bytes += len(data)
            text = self.decoder.decode(data)
        else:
            self.tx_bytes += len(data)
            text = data.decode('utf-8', errors='replace')
        while self.events and (len(self.events) >= 200 or self.retained_bytes + len(data) > 65536):
            self.retained_bytes -= self.events.popleft()['bytes']
        self.retained_bytes += len(data)
        self.events.append({'id': self.sequence, 'time': time.time(), 'direction': direction,
                            'bytes': len(data), 'text': text, 'hex': data.hex(' ').upper()})
        if self.observer: self.observer(self.events[-1])

    def receive(self, port):
        # Never wait for an end-of-line: a binary device may not send one.
        count = min(max(0, port.in_waiting), 16384)
        if count:
            data = port.read(count)
            if data: self.record('RX', data)

    def snapshot(self, after=0):
        events = [e for e in self.events if e['id'] > after]
        return {'session': self.session, 'events': events, 'last_id': self.sequence,
                'rx_bytes': self.rx_bytes, 'tx_bytes': self.tx_bytes,
                'history_truncated': bool(self.events and after and after < self.events[0]['id']-1)}

    def send(self, port, content, format='text', ending='none'):
        if not isinstance(content, str): raise ValueError('发送内容必须是文本')
        if format == 'hex':
            compact = re.sub(r'\s+', '', content)
            if not compact or len(compact) % 2 or re.search('[^0-9a-fA-F]', compact):
                raise ValueError('十六进制请按完整字节填写，例如 AA 55 01')
            if len(compact) > 8192: raise ValueError('单次最多发送 4096 字节')
            data = bytes.fromhex(compact)
        elif format == 'text':
            if ending not in {'none', 'lf', 'crlf'}: raise ValueError('不支持的行结束符')
            data = content.encode('utf-8') + {'none': b'', 'lf': b'\n', 'crlf': b'\r\n'}[ending]
            if not data: raise ValueError('请填写发送内容')
            if len(data) > 4096: raise ValueError('单次最多发送 4096 字节')
        else: raise ValueError('发送格式仅支持文本或十六进制')
        count = port.write(data)
        if count: self.record('TX', data[:count])
        if count != len(data): raise ValueError('数据仅部分发送，请检查串口；不要直接重复发送整条指令')
        return {'ok': True, 'sent_bytes': count, 'notice': '已写入串口，不代表设备已接受指令'}
