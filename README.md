# PC Status Reporter

The current project files are in the `app` folder:

- `app/main.py`
- `app/requirements.txt`
- `app/README.md`
- `build_exe.bat`

## Quick start on Windows

```bat
cd app
py -3 -m pip install -r requirements.txt
py -3 main.py
```

## Build the standalone exe on Windows

```bat
build_exe.bat
```

The build script creates a fresh exe and runs a packaged self-test. Publish only if it says:

```text
The packaged self-test passed.
```

The executable will be created at:

```text
app\dist\PCMonitor.exe
```

The executable opens a basic desktop UI with two tabs:

- `Home`
- `Webhook`

On first run, the exe creates an editable config file next to itself:

```text
pc_status_config.json
```

Users can edit that file with Notepad instead of reconfiguring every run.
Deleting that file makes the app recreate default settings the next time it opens.
The config supports a regular webhook plus an optional separate low-Roblox alert webhook.

Read `app\README.md` for the full usage and safety notes.

## Build Transparency & Verification

This project is open source, and official Windows `.exe` releases are built publicly through GitHub Actions.

I do **not** manually build the release executable on my own computer and then upload it separately. Instead, the source code in this repository is used by GitHub Actions to automatically build the `.exe`. The final executable is then attached to the GitHub Release along with a SHA-256 checksum file.

This means users can verify that the downloadable `.exe` matches the file produced by the public build process.

### How to verify the release

Each official release includes:

- `View-Max.exe` — the Windows executable
- `SHA256SUMS.txt` — the SHA-256 checksum for the executable
- A public GitHub Actions build log showing how the executable was created

To verify the downloaded file on Windows, open PowerShell in the folder where the `.exe` was downloaded and run:

```powershell
Get-FileHash .\View-Max.exe -Algorithm SHA256