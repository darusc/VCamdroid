@echo off
setlocal
pushd "%~dp0"

:: --- Configuration ---
set "SOURCE_DIST=dist"
set "SOURCE_ADB=windows\adb"
set "OUTPUT_DIR=VCamdroid"
set "GRADLE_WRAPPER=android\gradlew.bat"
set "ANDROID_APK=%SOURCE_DIST%\apk\app-release.apk"
set "WINDOWS_APP=%SOURCE_DIST%\VCamdroid.exe"

:: List of scripts to copy (located in the current root dir)
set "SCRIPTS_TO_COPY=install.bat install_apk.bat uninstall.bat"

echo [INFO] Starting Package Build...

:: 1. Verify the Windows release exists before Android creates dist/apk
if not exist "%WINDOWS_APP%" (
    echo [ERROR] Windows release not found at: %WINDOWS_APP%
    goto :Error
)

:: 2. Build and copy the Android client from the current source tree
if not exist "%GRADLE_WRAPPER%" (
    echo [ERROR] Gradle wrapper not found at: %GRADLE_WRAPPER%
    goto :Error
)

if not exist "%SOURCE_ADB%\adb.exe" (
    echo [ERROR] ADB executable not found at: %SOURCE_ADB%\adb.exe
    goto :Error
)

for %%f in (%SCRIPTS_TO_COPY%) do (
    if not exist "%%f" (
        echo [ERROR] Required script not found: %%f
        goto :Error
    )
)

if exist "%ANDROID_APK%" (
    echo [INFO] Removing previous Android APK...
    del /f /q "%ANDROID_APK%"
    if exist "%ANDROID_APK%" (
        echo [ERROR] Could not remove the previous APK at: %ANDROID_APK%
        goto :Error
    )
)

echo [INFO] Building current Android release...
call "%GRADLE_WRAPPER%" -p android :app:copyApk --console=plain
if errorlevel 1 (
    echo [ERROR] Android release build failed.
    goto :Error
)

if not exist "%ANDROID_APK%" (
    echo [ERROR] Android APK was not created at: %ANDROID_APK%
    goto :Error
)

:: 3. Clean previous build
if exist "%OUTPUT_DIR%" (
    echo [INFO] Cleaning old output directory...
    rmdir /s /q "%OUTPUT_DIR%"
    if exist "%OUTPUT_DIR%" (
        echo [ERROR] Could not clean output directory: %OUTPUT_DIR%
        goto :Error
    )
)

:: 4. Create new directory structure
echo [INFO] Creating directory structure...
mkdir "%OUTPUT_DIR%"
mkdir "%OUTPUT_DIR%\scripts"
mkdir "%OUTPUT_DIR%\adb"
if not exist "%OUTPUT_DIR%\scripts" (
    echo [ERROR] Could not create scripts directory.
    goto :Error
)
if not exist "%OUTPUT_DIR%\adb" (
    echo [ERROR] Could not create ADB directory.
    goto :Error
)

:: 5. Copy App Executables (contents of /dist -> /vcamdroid)
if exist "%SOURCE_DIST%" (
    echo [INFO] Copying application executables...
    xcopy /s /e /y /q "%SOURCE_DIST%\*" "%OUTPUT_DIR%\"
    if errorlevel 1 goto :Error
) else (
    echo [ERROR] Dist folder not found at: %SOURCE_DIST%
    goto :Error
)

:: 6. Copy ADB folder (/windows/adb -> /vcamdroid/adb)
if exist "%SOURCE_ADB%" (
    echo [INFO] Copying ADB binaries...
    xcopy /s /e /y /q "%SOURCE_ADB%\*" "%OUTPUT_DIR%\adb\"
    if errorlevel 1 goto :Error
) else (
    echo [ERROR] ADB folder not found at: %SOURCE_ADB%
    goto :Error
)

:: 7. Copy Batch Scripts (root -> /vcamdroid/scripts/)
echo [INFO] Copying batch scripts...
for %%f in (%SCRIPTS_TO_COPY%) do (
    copy /y "%%f" "%OUTPUT_DIR%\scripts\%%f" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to copy script: %%f
        goto :Error
    )
    echo    - Copied %%f
)

if not exist "%OUTPUT_DIR%\VCamdroid.exe" (
    echo [ERROR] Packaged Windows executable is missing.
    goto :Error
)
if not exist "%OUTPUT_DIR%\apk\app-release.apk" (
    echo [ERROR] Packaged Android APK is missing.
    goto :Error
)
if not exist "%OUTPUT_DIR%\adb\adb.exe" (
    echo [ERROR] Packaged ADB executable is missing.
    goto :Error
)

echo.
echo ===================================================
echo [SUCCESS] Package created successfully in: %OUTPUT_DIR%
echo ===================================================
popd
pause
exit /b 0

:Error
echo.
echo [FAIL] An error occurred during packaging.
popd
pause
exit /b 1