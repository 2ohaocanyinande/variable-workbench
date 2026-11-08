"""Local directory browser. Reads names only; no upload or project mutation."""
import os
from pathlib import Path
from project_layout import identify, resolve_project_root


def browse(initial, default):
    path = Path(initial or default).expanduser()
    if not path.is_absolute(): raise ValueError('请选择完整的文件夹路径')
    path = path.resolve()
    if not path.is_dir(): raise ValueError('该文件夹不存在或无法访问')
    directories = []
    truncated = False
    try:
        for child in path.iterdir():
            if child.name.startswith(('.', '$')) or child.name == 'System Volume Information': continue
            try:
                if child.is_dir(): directories.append({'name': child.name, 'path': str(child)})
            except OSError: continue
            if len(directories) >= 1000:
                truncated = True
                break
    except OSError: raise ValueError('无法浏览此文件夹，请选择其他位置') from None
    profile = Path(os.environ.get('USERPROFILE', str(Path.home())))
    locations = [{'name': '示例工程', 'path': str(default)}]
    for name, candidate in [('桌面', profile/'Desktop'), ('文档', profile/'Documents')]:
        if candidate.is_dir(): locations.append({'name': name, 'path': str(candidate)})
    if os.name == 'nt':
        import ctypes
        bits = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if bits & (1 << index):
                drive = chr(65+index)+':\\'
                locations.append({'name': drive, 'path': drive})
    else:
        locations.append({'name': '/', 'path': '/'})
    try:
        layout = identify(resolve_project_root(path))
    except (ValueError, OSError): layout = None
    return {'path': str(path), 'parent': str(path.parent) if path.parent != path else None,
            'directories': sorted(directories, key=lambda x: x['name'].casefold()),
            'is_project': layout is not None, 'markers': layout['markers'] if layout else [],
            'platform': layout['platform'] if layout else None, 'locations': locations, 'truncated': truncated}
