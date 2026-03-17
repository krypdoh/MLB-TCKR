@echo off
REM Build script for MLB ticker Cython optimizations
REM Run this to compile the performance-critical code

set PYTHON_EXE=C:\Users\pchar\AppData\Local\Programs\Python\Python313\python.exe
set PIP_EXE=C:\Users\pchar\AppData\Local\Programs\Python\Python313\pip.exe

echo ========================================
echo MLB-TCKR Performance Build Script
echo ========================================
echo.

REM Check if Python is available
"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found at %PYTHON_EXE%
    echo Please verify Python 3.13 installation path
    pause
    exit /b 1
)

echo [1/4] Checking Cython installation...
"%PYTHON_EXE%" -c "import Cython" >nul 2>&1
if errorlevel 1 (
    echo Cython not found. Installing...
    "%PIP_EXE%" install cython numpy
) else (
    echo Cython is already installed
)

echo.
echo [2/4] Checking NumPy installation...
"%PYTHON_EXE%" -c "import numpy" >nul 2>&1
if errorlevel 1 (
    echo NumPy not found. Installing...
    "%PIP_EXE%" install numpy
) else (
    echo NumPy is already installed
)

echo.
echo [3/4] Building MLB ticker Cython module...
"%PYTHON_EXE%" setup_mlb_cython.py build_ext --inplace

if errorlevel 1 (
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo ========================================
    echo.
    echo This could be because:
    echo   1. Visual C++ Build Tools are not installed
    echo   2. Missing dependencies
    echo.
    echo SOLUTION: Install Visual C++ Build Tools 2022
    echo   Download from: https://visualstudio.microsoft.com/downloads/
    echo   Select "Desktop development with C++"
    echo.
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up build artifacts...
if exist mlb_ticker_utils_cython.c del mlb_ticker_utils_cython.c

echo.
echo [5/5] Rebuilding PyInstaller EXE with Cython bundled...

REM Confirm PyInstaller is available
"%PYTHON_EXE%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo WARNING: PyInstaller not found. EXE not rebuilt.
    echo Run: pip install pyinstaller
    echo Then rebuild manually: pyinstaller MLB-TCKR-console.spec
    goto :done
)

"%PYTHON_EXE%" -m PyInstaller MLB-TCKR-console.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ========================================
    echo PYINSTALLER BUILD FAILED!
    echo ========================================
    pause
    exit /b 1
)

:done
echo.
echo ========================================
echo BUILD SUCCESSFUL!
echo ========================================
echo.
echo The MLB ticker will now run with Cython optimizations
echo for ultra-smooth 60 FPS scrolling.
echo.
echo EXE location: dist\MLB-TCKR-console.exe
echo.
pause
