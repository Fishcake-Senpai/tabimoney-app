# PyInstaller: gera o Tabimoney com Python e dependências dentro.
#   Windows: dist\Tabimoney.exe, um arquivo só (build.bat).
#   macOS:   dist/Tabimoney.app (GitHub Actions; o PyInstaller só gera o app de Mac rodando num Mac).
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)
numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)
MAC = sys.platform == "darwin"
BRAND = ROOT / "app" / "static" / "brand"

datas = [
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "migrations"), "migrations"),
    # pasta da IA (ver app/agent_workspace.py)
    (str(ROOT / ".claude" / "skills"), ".claude/skills"),
    (str(ROOT / "docs" / "agente-financeiro.md"), "docs"),
    (str(ROOT / "docs" / "agentes"), "docs/agentes"),
]
datas += collect_data_files("tzdata") + collect_data_files("certifi")
# o keyring acha o cofre do sistema (Credential Manager, Porta-chaves) por entry points
datas += copy_metadata("keyring")

hiddenimports = collect_submodules("uvicorn") + collect_submodules("keyring.backends") + collect_submodules("app")
hiddenimports += ["multipart"] + ([] if MAC else ["win32ctypes.core"])

a = Analysis(
    [str(ROOT / "packaging" / "entrada.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "PIL"],  # PIL: só o gerador do manual usa
    noarchive=False,
)
pyz = PYZ(a.pure)

if MAC:
    # Mac: app em pasta (o formato que o macOS espera); sem janela de terminal ao abrir pelo Finder.
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True, name="Tabimoney",
        console=False, argv_emulation=False, upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Tabimoney", upx=False)
    app = BUNDLE(
        coll,
        name="Tabimoney.app",
        icon=str(BRAND / "icon-512.png"),  # o PyInstaller converte para .icns (precisa do Pillow no build)
        bundle_identifier="io.github.fishcake-senpai.tabimoney",
        version=VERSION,
        info_plist={
            "CFBundleName": "Tabimoney",
            "CFBundleDisplayName": "Tabimoney",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "Tabimoney — finanças sérias (mais ou menos)",
        },
    )
else:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("041604B0", [
                StringStruct("CompanyName", "Tabimoney"),
                StringStruct("FileDescription", "Tabimoney — finanças pessoais locais"),
                StringStruct("FileVersion", VERSION),
                StringStruct("ProductName", "Tabimoney"),
                StringStruct("ProductVersion", VERSION),
                StringStruct("OriginalFilename", "Tabimoney.exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="Tabimoney",
        icon=str(BRAND / "favicon.ico"),
        version=version_info,
        console=True,   # a janela mostra o progresso ao abrir e a saída da CLI; o servidor roda sem janela
        upx=False,      # UPX aumenta alarmes falsos de antivírus
        runtime_tmpdir=None,
    )
