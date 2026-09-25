# PyInstaller: gera dist\Tabimoney.exe, um arquivo só, com Python e dependências dentro.
# Rode pelo build.bat na raiz do projeto.
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)
numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)

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
# o keyring acha o backend do Windows (Credential Manager) por entry points
datas += copy_metadata("keyring")

hiddenimports = (
    collect_submodules("uvicorn") + collect_submodules("keyring.backends") + collect_submodules("app")
    + ["win32ctypes.core", "multipart"]
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

a = Analysis(
    [str(ROOT / "packaging" / "entrada.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Tabimoney",
    icon=str(ROOT / "app" / "static" / "brand" / "favicon.ico"),
    version=version_info,
    console=True,   # a janela mostra o progresso ao abrir e a saída da CLI; o servidor roda sem janela
    upx=False,      # UPX aumenta alarmes falsos de antivírus
    runtime_tmpdir=None,
)
