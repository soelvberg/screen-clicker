$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3.13 -m venv .venv
    & $python -m pip install --upgrade pip
}
& $python -m pip install -r requirements.txt

New-Item -ItemType Directory -Force build | Out-Null
& $python -c "from screen_clicker.tray import make_icon; make_icon('#00f5d4', 256).save('build/icon.ico', sizes=[(16,16),(32,32),(48,48),(256,256)])"

& $python -m PyInstaller `
    --noconfirm --clean --onefile --console `
    --name screen-clicker `
    --icon build/icon.ico `
    --paths src `
    --collect-submodules winrt `
    --collect-submodules textual `
    --collect-submodules rich `
    --collect-data textual `
    --add-data "src/screen_clicker/tui/theme.tcss;screen_clicker/tui" `
    --hidden-import pynput.keyboard._win32 `
    --hidden-import pynput.mouse._win32 `
    --hidden-import pystray._win32 `
    src/screen_clicker/__main__.py

Write-Host "`nBuilt dist\screen-clicker.exe" -ForegroundColor Cyan
Write-Host "Run 'screen-clicker.exe' for the TUI, or 'screen-clicker.exe --headless' for tray-only mode."
