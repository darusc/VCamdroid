# Device registration and video troubleshooting

This guide covers the failure mode where the Android camera opens and the phone
reaches the Windows client, but no device or video appears in the desktop app.

## Pairing sequence

A successful Wi-Fi pairing has four separate gates:

1. The QR code gives the Android client the Windows host and control port (`6969`).
2. Android opens the TCP control connection.
3. Android sends a `DeviceDescriptor` containing the device name, RTSP URL,
   camera resolutions, and supported filters.
4. Windows registers the device, sends the stream options, and opens the RTSP
   stream (normally on port `8554`).

A TCP connection alone is not enough. If gate 2 succeeds but gate 3 fails, the
server can log `Device connected` while the device list and video remain empty.
The QR dialog may also remain visible, so the device list, logs, and live preview
are the reliable success criteria.

## Confirmed failure mode: mismatched release artifacts

The Android and Windows clients must use the same protocol version. A package
containing a current desktop executable and an older APK can connect on port
`6969`, but the old Android client may not send the `DeviceDescriptor` expected
by Windows. Without that descriptor, Windows cannot register the device or
request the RTSP stream.

Historically, the Gradle `copyApk` task copied from `android/app/release/`, a
manually populated location, and did not depend on `assembleRelease`.
`package.bat` then reused the contents of `dist/` without building Android. This
allowed a stale APK to be distributed with a newer desktop client.

The packaging flow now prevents that combination:

- `:app:copyApk` depends on `assembleRelease`.
- It copies the exact Gradle output from
  `android/app/build/outputs/apk/release/app-release.apk`.
- `package.bat` removes the previous destination APK, invokes that task, and stops
  if the Android build does not recreate the APK.

## Diagnosis

### 1. Confirm ADB access (USB)

```cmd
adb devices -l
```

The device state must be `device`, not `unauthorized` or `offline`.

### 2. Confirm the Windows control listener

```cmd
netstat -ano | findstr :6969
```

The desktop client should have a `LISTENING` socket on port `6969`.

### 3. Check both sides of the protocol

- Windows: inspect `vcamdroid.log` beside `VCamdroid.exe`.
- Android: use the in-app log screen when available, or collect Logcat:

```cmd
adb logcat | findstr /i VCamdroid
```

If Windows logs `Device connected` but never lists the phone, reinstall an APK
built from the same source/release as the desktop client before changing network
or firewall settings.

### 4. Handle Android signature mismatch

The installer first uses `adb install -r` to preserve app data. If ADB reports:

```text
INSTALL_FAILED_UPDATE_INCOMPATIBLE
```

the installed package was signed with a different key. Back up anything needed,
then uninstall `com.darusc.vcamdroid` and install the packaged APK again. Android
removes the application's local data during uninstall.

## Build and package a matching release

From the repository root on Windows:

```cmd
android\gradlew.bat -p android clean :app:copyApk
package.bat
```

`package.bat` expects the Windows release files to already exist in `dist/`. The
resulting Android package is:

```text
VCamdroid\apk\app-release.apk
```

To verify artifact identity, compare the SHA-256 values:

```cmd
certutil -hashfile android\app\build\outputs\apk\release\app-release.apk SHA256
certutil -hashfile dist\apk\app-release.apk SHA256
certutil -hashfile VCamdroid\apk\app-release.apk SHA256
```

All three hashes must match.

## End-to-end success criteria

After installing the packaged APK and pairing again, verify all of the following:

- the phone reaches the control server on port `6969`;
- the phone appears in the Windows device list;
- Windows requests streaming after device registration;
- the RTSP stream is reachable (normally port `8554`);
- live camera video appears in the desktop preview.

Treat the test as failed if only the TCP connection or camera preview works.
