# Windows standalone distribution

Run the following command on a development PC with Python and the packages in
`requirements.txt` installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Clean
```

Give users only `release\toma_shortcut_program.exe`. Python is not required on
their PC.

The temporary `.package-build` folder is removed automatically after a
successful build. Add `-KeepWorkFiles` only when investigating a build issue.

## Runtime data and paths

- The EXE's internal name is ASCII to avoid PyInstaller build-path encoding
  issues. The delivered folder can have Korean characters in its name.
- On first launch, a single `data` folder is created beside the EXE. It holds
  the databases (`hotkeys.db`, `alert_notes.db`) and every backup file
  (`auto_backup_*.json`, `backup_*.json`, `before_restore_*.json`). There is no
  separate backup folder: keeping one folder means copying or moving the program
  needs only that folder.
- Users can change the data folder from Settings. The selected path is stored in
  `%LOCALAPPDATA%\CodexShortcutLauncher\storage_paths.json` so it can be
  resolved before the database is opened.
- If the folder beside the EXE is not writable — installing under
  `C:\Program Files` is the usual cause — the launcher falls back to
  `%LOCALAPPDATA%\CodexShortcutLauncher\data`, saves that path, and tells the
  user where the data went. A damaged database is not treated this way: it still
  asks the user to pick a folder so existing data is never silently bypassed.
- Auto backups are written once a day at launch, and the seven most recent
  backup files are kept; older ones are removed automatically.
- When upgrading from a build that used a separate `backup` folder, its files are
  merged into `data` on launch. Files with the same name but different contents
  are kept as `<name>_이전1`, so nothing is overwritten.
- The packaged EXE is a one-file build. At launch, PyInstaller temporarily
  extracts its bundled Python, PyQt6, Qt plugins, SQLite, and openpyxl
  dependencies, then cleans them up when the program ends. Startup can take a
  little longer than the previous folder-based package.
- `토마2_icon.ico` is bundled for the program window, title bar, taskbar, and
  system-tray icon. Imported/exported Excel files are selected by the user and
  are not bundled.

## Icon

`토마2_icon.ico` is embedded in the EXE and is also packaged internally
for the program window and taskbar icon.

## Validation before delivery

1. Copy `토마 데스크.exe` to a Korean-named path.
2. Launch it on a PC without Python.
3. Add a shortcut, close the app, and reopen it to confirm the saved data.
4. Confirm `data\hotkeys.db` exists beside the EXE, and that the next day's
   `data\auto_backup_*.json` lands in the same folder.
5. Change the data folder in Settings, restart, and confirm the copied database
   opens.
6. Copy the EXE into a folder the account cannot write to and launch it. It must
   report the `%LOCALAPPDATA%` folder it moved to instead of failing.
