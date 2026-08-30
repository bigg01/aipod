# PyInstaller spec: build a single-file `aipod` executable (both modes).
#
#   uv run --group build pyinstaller packaging/aipod.spec --noconfirm
#
# The Dockerfile then runs dist/aipod through staticx for a fully static binary
# that ships in a `FROM scratch` image.

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = [
    "aipod",
    "aipod.__main__",
    "aipod.governance",
    "aipod.server",
    "aipod.server.build",
    "aipod.server.contract",
    "aipod.server.data",
    "aipod.server.landing",
    "aipod.server.sampling_tools",
    "aipod.agent",
    "aipod.agent.runtime",
    "aipod.agent.card",
    "aipod.agent.http",
    "aipod.agent.config",
    "pydantic_ai.models.mcp_sampling",
]

# Skip optional CLIs / provider integrations that import extras we do not ship.
_SKIP_PREFIXES = (
    "mcp.cli",
    "pydantic_ai.models.",
    "pydantic_ai.providers.",
    "pydantic_ai._cli",
    "pydantic_ai.ext.",
)


def _keep(name: str) -> bool:
    if name.startswith(_SKIP_PREFIXES):
        return name == "pydantic_ai.models.mcp_sampling"
    return True


for pkg in (
    "mcp",
    "fastmcp",
    "pydantic_ai",
    "pydantic",
    "pydantic_core",
    "uvicorn",
    "starlette",
    "sse_starlette",
    "anyio",
    "httpx",
    "httpcore",
):
    try:
        d, b, h = collect_all(pkg, filter_submodules=_keep)
    except Exception:  # noqa: BLE001
        continue
    datas += d
    binaries += b
    hiddenimports += h

for dist in (
    "mcp",
    "fastmcp",
    "pydantic-ai-slim",
    "pydantic",
    "uvicorn",
    "starlette",
    "sse-starlette",
    "anyio",
    "httpx",
):
    try:
        datas += copy_metadata(dist, recursive=True)
    except Exception:  # noqa: BLE001
        pass


a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "pytest", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aipod",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
