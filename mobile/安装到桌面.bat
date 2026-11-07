@echo off
chcp 65001 >nul
rem 一键安装：把 ZYCSSGXX 装到本机并在桌面创建快捷方式（带小龙图标）
set "SRC=%~dp0ZYCSSGXX.exe"
if not exist "%SRC%" (
  echo [错误] 请把本脚本和 ZYCSSGXX.exe 放在同一个文件夹里再运行。
  pause
  exit /b 1
)
set "DEST=%LOCALAPPDATA%\ZYCSSGXX"
if not exist "%DEST%" mkdir "%DEST%"
copy /y "%SRC%" "%DEST%\" >nul
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$lnk = $ws.CreateShortcut((Join-Path $desktop 'ZYCSSGXX.lnk'));" ^
  "$lnk.TargetPath = Join-Path $env:LOCALAPPDATA 'ZYCSSGXX\ZYCSSGXX.exe';" ^
  "$lnk.WorkingDirectory = Join-Path $env:LOCALAPPDATA 'ZYCSSGXX';" ^
  "$lnk.IconLocation = (Join-Path $env:LOCALAPPDATA 'ZYCSSGXX\ZYCSSGXX.exe') + ',0';" ^
  "$lnk.Description = 'ZYCSSGXX 我的世界启动器';" ^
  "$lnk.Save()"
echo 安装完成！桌面已创建「ZYCSSGXX」快捷方式，双击即可启动。
pause
