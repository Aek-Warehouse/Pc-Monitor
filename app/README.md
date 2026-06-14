# PC Status Reporter

A lightweight, visible desktop app that sends basic PC status updates to a webhook you provide.

## Safety and behavior

- Runs only when you start it manually.
- Does not add startup persistence.
- Opens a visible window with Start and Stop controls.
- Does not collect keystrokes, browser data, passwords, tokens, cookies, private files, or long-term recordings.
- Only captures the screen if you explicitly choose screenshot or short clip mode.
- Deletes temporary screenshots and clips after each send attempt.
- Lets you stop safely with the Stop button. The optional console fallback also supports `Ctrl+C` or typing `q`.
- Does not print your webhook URL after setup.
- Saves your settings in `pc_status_config.json` next to the app so you do not have to answer setup every time.
- Can send a separate low-Roblox alert webhook when the visible Roblox window count drops below your configured number.

## Run from Python

Open Command Prompt or PowerShell in this `app` folder, then run:

```bat
py -3 -m pip install -r requirements.txt
py -3 main.py
```

If `py -3` does not work, try:

```bat
python -m pip install -r requirements.txt
python main.py
```

## Build a standalone Windows exe

From the main project folder, build on Windows:

```bat
build_exe.bat
```

The build script creates a clean temporary Python environment, deletes the old build output, creates a fresh executable, then runs a packaged self-test. If the self-test fails, do not publish that exe.

The finished executable will be:

```text
app\dist\PCMonitor.exe
```

You can give someone that exe so they can run the program without installing Python manually.

## Publishing checklist

1. Open the main project folder on a Windows PC.
2. Double-click `build_exe.bat`.
3. Wait for `The packaged self-test passed.`
4. Upload or share only `app\dist\PCMonitor.exe`.
5. Test the uploaded exe on a normal Windows account before announcing it.

Do not share an older exe from a previous `dist` folder. Always rebuild with `build_exe.bat` after code changes.

## How to use

When the app starts, use the desktop UI to choose:

- Webhook URL
- Update interval in seconds or minutes
- Screenshot, short MP4 screen clip, or no screen capture
- Clip length and FPS if clip mode is selected
- Whether to include CPU usage
- Whether to include RAM usage
- Whether to include the number of Roblox instances running
- Whether to include the time sent
- Whether to enable the low-Roblox alert webhook
- The minimum Roblox instance count for that alert
- The alert webhook's own interval, capture mode, and include options

After setup, the app sends one update every interval. Keep the app window open while you want it running.

## Desktop UI

The app has two tabs:

- `Home`: read the basic explanation, join the Discord support/releases server, save the config, and start or stop the reporter.
- `Webhook`: edit normal webhook settings and low-Roblox alert webhook settings.

Each visible setting has a `?` button that opens a short explanation.
The tabs can be scrolled if the window is too small.
Use `Compact Mode` from the Home tab when you only want a small status window with update time plus Start, Stop, and Main Window controls.
Use `Dark mode` from the Home tab to switch between light and dark UI themes.
Discord support and release updates: `https://discord.gg/zusCzshxsD`

## Saved config

On first run, the app creates this file next to the executable:

```text
pc_status_config.json
```

You can open it with Notepad and edit the settings later. The real config file can contain your webhook URL, so do not upload or share it.
To run setup again from scratch, delete `pc_status_config.json` and reopen the app.

Example:

```json
{
  "regular": {
    "webhook_url": "https://example.com/regular-status-webhook",
    "interval_seconds": 300,
    "capture_mode": "screenshot",
    "include_cpu": true,
    "include_ram": true,
    "include_roblox": true,
    "include_time": true,
    "timezone_name": "America/New_York",
    "time_include_year": true,
    "time_include_month": true,
    "time_include_day": true,
    "time_format": "standard",
    "clip_length_seconds": 5,
    "clip_fps": 5
  },
  "low_roblox_alert": {
    "enabled": true,
    "min_roblox_instances": 20,
    "profile": {
      "webhook_url": "https://example.com/low-roblox-alert-webhook",
      "interval_seconds": 60,
      "capture_mode": "screenshot",
      "include_cpu": true,
      "include_ram": true,
      "include_roblox": true,
      "include_time": true,
      "timezone_name": "America/New_York",
      "time_include_year": true,
      "time_include_month": true,
      "time_include_day": true,
      "time_format": "standard",
      "clip_length_seconds": 5,
      "clip_fps": 5
    }
  },
  "ui_dark_mode": false
}
```

Valid `capture_mode` values:

- `screenshot`
- `clip`
- `none`

Time settings:

- `timezone_name`: use a dropdown value from the app, such as `America/New_York`, or a fixed offset like `fixed:-05:00`.
- `time_format`: use `standard` for AM/PM or `military` for 24-hour time.
- `time_include_year`, `time_include_month`, and `time_include_day`: choose which date parts appear after the time.

## Recommended low-resource settings

- Best overall choice: screenshot mode.
- If you want a screen clip, use a 5-second MP4 clip at 5 FPS.
- Use an interval of 1 to 5 minutes or longer.

## Roblox count

Roblox instances are counted by checking active process names on Windows for `RobloxPlayerBeta.exe`. If process access fails, the update says `Unknown` instead of crashing.
On Windows, the app prefers visible Roblox windows, which avoids counting a background or leftover Roblox process that does not have a visible game window.

## Notes

- The app captures only when it is time to send an update.
- Temporary screenshot and MP4 files are deleted after sending.
- Webhook or network errors are handled without crashing, then the app keeps running until you stop it.
