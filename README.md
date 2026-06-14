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

PC Monitor is open source, and official Windows releases are built publicly through GitHub Actions.

The release executable is not manually built on a private computer and uploaded separately. Instead, GitHub Actions checks out the source code from this repository, installs the required Python dependencies, runs the build script, packages the executable, and uploads the final release file to GitHub Releases.

Each official release includes:

- `PCMonitor-windows.zip` — the packaged Windows release
- `SHA256SUMS.txt` — SHA-256 hashes for the release zip and executable
- A public GitHub Actions workflow run showing the build process

This allows users to verify that the downloaded release matches the file produced by the public GitHub Actions build.

### How to verify the download

After downloading `PCMonitor-windows.zip`, open PowerShell in the folder where the file was downloaded and run:

```powershell
Get-FileHash .\PCMonitor-windows.zip -Algorithm SHA256