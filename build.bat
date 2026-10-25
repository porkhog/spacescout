@echo off
REM Build dist\SpaceScout.exe on your own Windows PC.
REM Needs Python 3.10+ from python.org (tick "Add Python to PATH" when installing).

python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m PyInstaller SpaceScout.spec --noconfirm --clean || goto :error

echo.
echo Done! Your app is at dist\SpaceScout.exe
pause
exit /b 0

:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
