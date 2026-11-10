"""Small, source-verified display contracts; no firmware or driver code is run."""
import re
from usage_analysis import masked, balanced


def functions(sources):
    result = {}
    for path, raw in sources.items():
        if not path.endswith(('.c', '.cpp')):
            continue
        code = masked(raw)
        for m in re.finditer(r'(?m)^[ \t]*(?:[A-Za-z_]\w*[ \t*]+)+([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{', code):
            if m[1] in {'if','for','while','switch'}:
                continue
            end = balanced(code, m.end()-1, '{', '}')
            if end is None:
                continue
            result.setdefault(m[1], []).append(dict(path=path, name=m[1], start=m.start(), opening=m.end()-1,
                end=end, body=code[m.end():end], params=m[2], line=raw.count('\n', 0, m.start(1))+1))
    return result


def one(defs, name):
    matches = defs.get(name, [])
    return matches[0] if len(matches) == 1 else None


def transport(defs, entry):
    pending = [entry]; seen = set(); spi = False; gpio = False
    while pending and len(seen) < 120:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for fn in defs.get(name, []):
            spi |= bool(re.search(r'\b(?:HAL_SPI_Transmit(?:_DMA|_IT)?|SPI_I2S_SendData|LL_SPI_TransmitData8|spi_device_(?:polling_)?transmit)\s*\(', fn['body']))
            gpio |= bool(re.search(r'\bGPIO\w*\s*->\s*(?:ODR|BSRR|BRR)\b', fn['body']))
            pending.extend(n for n in re.findall(r'\b(\w+)\s*\(', fn['body']) if n in defs)
    return 'SPI' if spi and not gpio else 'SPI / GPIO 控制' if spi else 'GPIO 总线' if gpio else '传输接口未确认'


def detect(sources, constants):
    defs = functions(sources); profiles = {}
    oled = defs.get('OLED_ShowChar', [])
    cursor = r'OLED_SetCursor\s*\(\s*\(\s*Line\s*-\s*1\s*\)\s*\*\s*2\s*,\s*\(\s*Column\s*-\s*1\s*\)\s*\*\s*8\s*\)'
    if oled and all(re.search(cursor, f['body']) for f in oled):
        profiles['oled'] = dict(id='oled', width=128, height=64, rows=4, columns=16, font_width=8, font_height=16,
            title='行列式 OLED · 128×64 字符近似预览', transport=transport(defs, 'OLED_ShowChar'),
            evidence=[dict(path=f['path'], line=f['line']) for f in oled])
    string, char, draw, clear = (one(defs, n) for n in ('LCD_DisplayStringLine', 'LCD_DisplayChar', 'LCD_DrawChar', 'LCD_Clear'))
    if all((string, char, draw, clear)):
        body = string['body']
        valid = (re.search(r'\brefcolumn\s*=\s*319\b', body) and re.search(r'\brefcolumn\s*-=\s*16\b', body)
            and re.search(r'\bi\s*<\s*20\b', body) and re.search(r'LCD_DisplayChar\s*\(\s*Line\s*,\s*refcolumn\s*,\s*\*ptr\s*\)', body)
            and re.search(r'\bindex\s*<\s*24\b', draw['body']) and re.search(r'\bi\s*<\s*16\b', draw['body'])
            and 'LCD_DrawChar' in char['body'] and re.search(r'\bindex\s*<\s*76800\b', clear['body'])
            and all(constants.get('Line'+str(i)) == i*24 for i in range(10)))
        if valid:
            profiles['lcd_line'] = dict(id='lcd_line', width=320, height=240, rows=10, columns=20, font_width=16, font_height=24,
                title='LCD · 320×240 · 16×24 字符近似预览', transport=transport(defs, 'LCD_DisplayStringLine'),
                evidence=[dict(path=f['path'], line=f['line']) for f in (string, draw, clear)])
    # A second, deliberately narrow contract for common x/y RGB565 SPI drivers.
    # Verify argument flow, character advance and the glyph loop in local code.
    string, char = one(defs, 'LCD_ShowString'), one(defs, 'LCD_ShowChar')
    if string and char:
        param = lambda f: [re.findall(r'\b\w+\b', p)[-1] for p in f['params'].split(',') if re.findall(r'\b\w+\b', p)]
        sp, cp = param(string), param(char)
        if len(sp) in (6, 7) and len(cp) == len(sp):
            x,y,p,fc,bc,size = sp[:6]; cs = re.escape(cp[5]); body = string['body']
            flow = r'LCD_ShowChar\s*\(\s*'+r'\s*,\s*'.join(map(re.escape, [x,y,'*'+p,fc,bc,size]))+(r'\s*,\s*'+re.escape(sp[6]) if len(sp)==7 else '')+r'\s*\)'
            valid = (re.search(flow, body) and re.search(r'\b'+re.escape(x)+r'\s*\+=\s*'+re.escape(size)+r'\s*/\s*2\b', body)
                and re.search(r'<\s*'+cs+r'\s*/\s*2\b', char['body']) and re.search(r'<\s*'+cs+r'\s*;', char['body'])
                and re.search(r'\bLCD_DrawPoint\s*\(', char['body']) and 16 <= constants.get('LCD_W',0) <= 1024 and 16 <= constants.get('LCD_H',0) <= 1024)
            if valid:
                profiles['lcd_xy'] = dict(id='lcd_xy', width=int(constants['LCD_W']), height=int(constants['LCD_H']), rows=0, columns=0,
                    title='LCD 像素坐标文字 · 本地驱动已核对', transport=transport(defs, 'LCD_ShowString'),
                    evidence=[dict(path=f['path'], line=f['line']) for f in (string,char)])
    return profiles, defs
