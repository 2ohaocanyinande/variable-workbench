"""Project markers and source manifests; never executes build scripts."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def identify(root):
    root = Path(root).resolve()
    markers = list(root.glob('*.ioc')) + list(root.glob('*.uvprojx')) + list(root.glob('*.uvproj'))
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir() and folder.name.casefold() in {'mdk-arm','user','keil'}:
                markers += list(folder.glob('*.uvprojx'))+list(folder.glob('*.uvproj'))
    markers += [root/name for name in ('CMakeLists.txt', '.project', '.cproject') if (root/name).is_file()]
    devices, sources, targets = [], set(), []
    formats = set()
    stm32 = False
    for marker in markers:
        text = marker.read_text(encoding='utf-8-sig', errors='replace')
        if marker.suffix == '.ioc':
            found = re.findall(r'^Mcu\.(?:Name|CPN|Family)=(STM32[^\r\n]+)', text, re.M)
            if found: stm32 = True; devices.extend(found); formats.add('CubeMX')
        elif marker.suffix in {'.uvprojx','.uvproj'}:
            try: tree = ET.fromstring(text)
            except ET.ParseError: continue
            found = [e.text for e in tree.iter('Device') if e.text and e.text.upper().startswith('STM32')]
            if not found: continue
            stm32 = True; devices.extend(found); formats.add('Keil')
            for target in tree.iter('Target'):
                targets.append(target.findtext('TargetName', '未命名 Target'))
                for item in target.iter('File'):
                    if item.findtext('.//IncludeInBuild') == '0': continue
                    name = item.findtext('FilePath')
                    if name: sources.add((marker.parent / name.replace('\\', '/')).resolve())
        elif marker.name in {'.project', '.cproject'}:
            if 'com.st.stm32cube' in text or 'STM32CubeIDE' in text:
                stm32 = True; formats.add('CubeIDE')
        elif marker.name == 'CMakeLists.txt':
            formats.add('CMake')
            if re.search(r'\bstm32\w*', text, re.I): stm32 = True
    if not markers or not (stm32 or 'CMake' in formats):
        raise ValueError('请选择工程根文件夹：支持 ESP-IDF/CMake、STM32 .ioc、Keil .uvprojx 或 CubeIDE 工程。')
    if stm32:
        platform = 'stm32'
    elif any((root/name).is_file() for name in ('sdkconfig', 'sdkconfig.defaults')) or any(
            'idf_' in m.read_text(encoding='utf-8-sig', errors='replace') for m in markers if m.name == 'CMakeLists.txt'):
        platform = 'esp32'
    else:
        platform = 'cmake'
    return {'platform': platform, 'formats': sorted(formats), 'devices': sorted(set(devices)),
            'markers': [m.relative_to(root).as_posix() for m in markers],
            'listed_sources': sources, 'targets': targets}


def resolve_project_root(root):
    """Accept a single packaging folder, never scan parents or choose among projects."""
    root=Path(root).resolve()
    try:identify(root);return root
    except ValueError as original:
        choices=[]
        if root.is_dir():
            children=list(root.iterdir())
            if len(children)>200:raise ValueError('目录过大，请选择实际工程文件夹')
            for child in children:
                if not child.is_dir() or child.name.casefold() in {'build','node_modules','.git','objects','listings'}:continue
                try:identify(child);choices.append(child)
                except (ValueError,OSError):pass
        if len(choices)==1:return choices[0]
        if len(choices)>1:raise ValueError('该目录包含多个工程，请选择具体工程文件夹')
        raise original


def is_vendor_source(relative):
    path = Path(relative)
    if re.fullmatch(r'core_cm(?:\d+\w*|Instr|Func)\.[ch]',path.name,re.I):return True
    if re.fullmatch(r'stm32[a-z]\d+xx\.h',path.name,re.I):return True
    if path.parent.name.casefold() == 'core' and re.match(r'vl53l[01]\w*\.[ch]$',path.name,re.I): return True
    # Keep vendor files in hash coverage; omit their implementation from AI indexing.
    return any(p.casefold() in {'cmsis', 'freertos', 'lwip', 'mbedtls', 'usb_device_library'} or
               re.fullmatch(r'stm32\w+_(?:hal|ll)_driver', p, re.I) for p in path.parts) or bool(
        re.match(r'stm32\w*_(?:hal|ll|gpio|tim|adc|usart|i2c|spi|rcc|dma|exti|flash|pwr|rtc|wwdg|iwdg|crc|can|dac|sdio|fsmc|dbg)\w*\.[ch]$', path.name, re.I))
