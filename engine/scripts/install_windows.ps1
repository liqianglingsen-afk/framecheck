$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment..."
python -m venv .venv

Write-Host "Installing Python dependencies..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host ""
  Write-Host "FFmpeg was not found in PATH."
  Write-Host "Install options:"
  Write-Host "  winget install Gyan.FFmpeg"
  Write-Host "  choco install ffmpeg"
  Write-Host "  scoop install ffmpeg"
  Write-Host "Then restart PowerShell and rerun scripts/check_environment.py."
}

Write-Host "Running environment check..."
.\.venv\Scripts\python.exe scripts\check_environment.py
