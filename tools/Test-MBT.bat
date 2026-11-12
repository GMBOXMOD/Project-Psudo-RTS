@echo off
setlocal
set "ENGINE_DIR=%~dp0..\.."
set "STATE_DIR=%~dp0..\..\.mygame-test"

if not exist "%ENGINE_DIR%\spring.exe" (
    echo Cannot find spring.exe. Keep MyGame.sdd inside Recoil\games.
    pause
    exit /b 1
)
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"
if not exist "%STATE_DIR%\springsettings.cfg" (
    > "%STATE_DIR%\springsettings.cfg" (
        echo Fullscreen = 0
        echo XResolutionWindowed = 1280
        echo YResolutionWindowed = 800
        echo VSync = 1
        echo Shadows = 1
    )
)

start "MyGame tank test" /D "%ENGINE_DIR%" "%ENGINE_DIR%\spring.exe" --isolation --isolation-dir "%ENGINE_DIR%" --write-dir "%STATE_DIR%" --config "%STATE_DIR%\springsettings.cfg" --window --only-local "%~dp0tools\mbt_test.txt"
endlocal
