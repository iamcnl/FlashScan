a = Analysis(
    ["main.py"],
    datas=[("ui", "ui"), ("export_templates", "export_templates"), ("assets", "assets")],
    excludes=["pytest", "tkinter"],
)
a.datas = [d for d in a.datas if "__pycache__" not in d[0]]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FlashScan",
    icon="assets/FlashScan.ico",
    console=False,
    upx=False,
)
