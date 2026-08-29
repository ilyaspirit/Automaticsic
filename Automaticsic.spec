# -*- mode: python ; coding: utf-8 -*-
import hashlib
import os
import re

HERE = os.path.dirname(os.path.abspath(SPEC))

ICONS = ['icon.ico', 'icon_asic.ico']

# Версия берётся из model.py, чтобы не держать её в двух местах.
VERSION = re.search(
    r'VERSION = "([^"]+)"',
    open(os.path.join(HERE, "model.py"), encoding="utf-8").read(),
).group(1)

numbers = tuple(int(part) for part in VERSION.split("."))
numbers = (numbers + (0, 0, 0, 0))[:4]

# Свойства exe: их показывает проводник на вкладке «Подробно».
# 000004b0 — нейтральный язык плюс кодовая страница Unicode.
VERSION_FILE = os.path.join(HERE, "version_info.txt")
with open(VERSION_FILE, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('000004b0', [
        StringStruct('CompanyName', '@ilyaspirit'),
        StringStruct('FileDescription', 'Automaticsic'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', 'Automaticsic'),
        StringStruct('LegalCopyright', ''),
        StringStruct('OriginalFilename', 'Automaticsic.exe'),
        StringStruct('ProductName', 'Automaticsic'),
        StringStruct('ProductVersion', '{VERSION}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0, 1200])])
  ]
)
""")


# Повторная сборка сверяет только ПУТИ к значку и файлу версии, а не их
# содержимое. Подменил картинку под тем же именем — PyInstaller считает,
# что ничего не изменилось, пишет «Build complete» за доли секунды и
# оставляет прежний exe. Считаем отпечаток сами и, если он другой, убираем
# кэш шага EXE — тогда exe соберётся заново.
def _refresh_exe_cache():
    digest = hashlib.sha256(VERSION.encode())
    for name in ICONS + [SPEC]:
        with open(os.path.join(HERE, name), 'rb') as f:
            digest.update(f.read())
    digest = digest.hexdigest()

    stamp = os.path.join(workpath, 'assets.sha256')
    previous = ''
    if os.path.isfile(stamp):
        with open(stamp, encoding='utf-8') as f:
            previous = f.read().strip()

    if previous != digest:
        try:
            os.remove(os.path.join(workpath, 'EXE-00.toc'))
        except OSError:
            pass
        os.makedirs(workpath, exist_ok=True)
        with open(stamp, 'w', encoding='utf-8') as f:
            f.write(digest)


_refresh_exe_cache()


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # Иконка нужна и внутри exe: окно и значок в трее берут её файлом
    # через model.icon_path().
    datas=[('icon.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Automaticsic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Два значка одним списком: PyInstaller кладёт их в exe отдельными
    # группами по порядку. Нулевой — сама программа, первый — файлы .asic,
    # на него и указывает DefaultIcon в реестре. Так значок документа
    # не требует отдельного файла рядом с exe.
    icon=['icon.ico', 'icon_asic.ico'],
    version=VERSION_FILE,
    # Windows не даёт управлять окнами и процессами, запущенными с правами
    # выше своих. Сценарии почти всегда трогают что-то такое, поэтому
    # программа просит повышение сразу при запуске — иначе часть шагов
    # молча не срабатывает.
    uac_admin=True,
)
