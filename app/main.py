from __future__ import annotations

import json
import importlib
import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import psutil
except ImportError:
    psutil = None

try:
    import requests
except ImportError:
    requests = None

tk: Any
messagebox: Any
scrolledtext: Any
ttk: Any

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except ImportError:
    tk = None
    messagebox = None
    scrolledtext = None
    ttk = None


APP_NAME = "PC Status Reporter"
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_CLIP_SECONDS = 5
DEFAULT_CLIP_FPS = 5
MIN_INTERVAL_SECONDS = 5
MAX_INTERVAL_SECONDS = 24 * 60 * 60
MAX_CLIP_SECONDS = 30
MAX_CLIP_FPS = 15
MAX_SCREENSHOT_WIDTH = 1600
MAX_CLIP_WIDTH = 1280
JPEG_QUALITY = 75
REQUEST_TIMEOUT_SECONDS = 20
VIDEO_CRF = 30
CONFIG_FILE_NAME = "pc_status_config.json"
CAPTURE_MODES = {"screenshot", "clip", "none"}
TIME_FORMATS = {"standard", "military"}
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_TIME_FORMAT = "standard"
POPULAR_TIMEZONES: tuple[tuple[str, str], ...] = (
    ("Eastern Time", "America/New_York"),
    ("Central Time", "America/Chicago"),
    ("Mountain Time", "America/Denver"),
    ("Pacific Time", "America/Los_Angeles"),
    ("Alaska Time", "America/Anchorage"),
    ("Hawaii Time", "Pacific/Honolulu"),
    ("Atlantic Time", "America/Halifax"),
    ("Newfoundland Time", "America/St_Johns"),
    ("London", "Europe/London"),
    ("Central Europe", "Europe/Berlin"),
    ("Eastern Europe", "Europe/Athens"),
    ("Moscow", "Europe/Moscow"),
    ("Dubai", "Asia/Dubai"),
    ("India", "Asia/Kolkata"),
    ("Singapore", "Asia/Singapore"),
    ("China", "Asia/Shanghai"),
    ("Japan", "Asia/Tokyo"),
    ("Sydney", "Australia/Sydney"),
    ("Auckland", "Pacific/Auckland"),
)
FIXED_GMT_OFFSETS: tuple[tuple[str, str], ...] = tuple(
    (f"GMT{offset:+d}", f"fixed:{offset:+03d}:00") for offset in range(-12, 15)
)


@dataclass
class ReportProfile:
    webhook_url: str
    interval_seconds: int
    capture_mode: str
    include_cpu: bool
    include_ram: bool
    include_roblox: bool
    include_time: bool
    clip_length_seconds: int = DEFAULT_CLIP_SECONDS
    clip_fps: int = DEFAULT_CLIP_FPS
    timezone_name: str = DEFAULT_TIMEZONE
    time_include_year: bool = True
    time_include_month: bool = True
    time_include_day: bool = True
    time_format: str = DEFAULT_TIME_FORMAT


@dataclass
class LowRobloxAlert:
    enabled: bool
    min_roblox_instances: int
    profile: ReportProfile


@dataclass
class AppConfig:
    regular: ReportProfile
    low_roblox_alert: LowRobloxAlert
    ui_dark_mode: bool = False


def get_app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_config_path() -> Path:
    return get_app_directory() / CONFIG_FILE_NAME


def subprocess_no_window_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    startf_use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    if startupinfo_factory is not None and startf_use_show_window:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= startf_use_show_window
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _require_bool(data: dict, key: str) -> bool:
    value = data.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"`{key}` must be true or false.")


def _require_int(data: dict, key: str, minimum: int, maximum: int) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"`{key}` must be a whole number.")
    if value < minimum or value > maximum:
        raise ValueError(f"`{key}` must be between {minimum} and {maximum}.")
    return value


def _optional_bool(data: dict, key: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"`{key}` must be true or false.")


def _optional_string(data: dict, key: str, default: str) -> str:
    value = data.get(key, default)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"`{key}` must be a non-empty string.")


def parse_fixed_timezone(value: str) -> Optional[timezone]:
    if not value.startswith("fixed:"):
        return None
    offset_text = value.removeprefix("fixed:")
    sign = 1
    if offset_text.startswith("-"):
        sign = -1
        offset_text = offset_text[1:]
    elif offset_text.startswith("+"):
        offset_text = offset_text[1:]

    try:
        hour_text, minute_text = offset_text.split(":", 1)
        hours = int(hour_text)
        minutes = int(minute_text)
    except ValueError:
        return None

    if hours > 14 or minutes < 0 or minutes >= 60:
        return None
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def get_timezone(timezone_name: str):
    fixed_timezone = parse_fixed_timezone(timezone_name)
    if fixed_timezone is not None:
        return fixed_timezone
    return ZoneInfo(timezone_name)


def gmt_offset_text(timezone_name: str, when: Optional[datetime] = None) -> str:
    when = when or datetime.now(timezone.utc)
    try:
        tzinfo = get_timezone(timezone_name)
        offset = when.astimezone(tzinfo).utcoffset()
    except (ZoneInfoNotFoundError, ValueError):
        offset = None

    if offset is None:
        return "GMT+00:00"

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"GMT{sign}{hours:02d}:{minutes:02d}"


def timezone_display_name(display_name: str, timezone_name: str) -> str:
    return f"{display_name} ({gmt_offset_text(timezone_name)})"


def timezone_choices() -> tuple[str, ...]:
    popular = [timezone_display_name(display_name, zone_name) for display_name, zone_name in POPULAR_TIMEZONES]
    fixed = [timezone_display_name(display_name, zone_name) for display_name, zone_name in FIXED_GMT_OFFSETS]
    return tuple(popular + fixed)


def timezone_label_to_value(label: str) -> str:
    choices = {
        timezone_display_name(display_name, zone_name): zone_name
        for display_name, zone_name in (*POPULAR_TIMEZONES, *FIXED_GMT_OFFSETS)
    }
    return choices.get(label, label)


def timezone_value_to_label(timezone_name: str) -> str:
    for display_name, zone_name in (*POPULAR_TIMEZONES, *FIXED_GMT_OFFSETS):
        if zone_name == timezone_name:
            return timezone_display_name(display_name, zone_name)
    return timezone_name


def validate_timezone_name(timezone_name: str, label: str) -> str:
    try:
        get_timezone(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"`{label}.timezone_name` is not a valid timezone.") from exc
    return timezone_name


def format_sent_time(profile: ReportProfile) -> str:
    tzinfo = get_timezone(profile.timezone_name)
    now = datetime.now(tzinfo)
    time_format = "%I:%M:%S %p" if profile.time_format == "standard" else "%H:%M:%S"
    time_part = now.strftime(time_format)

    date_parts: list[str] = []
    if profile.time_include_month:
        date_parts.append(f"{now.month:02d}")
    if profile.time_include_day:
        date_parts.append(f"{now.day:02d}")
    if profile.time_include_year:
        date_parts.append(str(now.year))

    if date_parts:
        return f"{time_part} ({gmt_offset_text(profile.timezone_name, now)}) | {'/'.join(date_parts)}"
    return f"{time_part} ({gmt_offset_text(profile.timezone_name, now)})"


def profile_from_dict(data: dict, label: str) -> ReportProfile:
    webhook_url = data.get("webhook_url")
    if not isinstance(webhook_url, str) or not is_valid_webhook_url(webhook_url):
        raise ValueError(f"`{label}.webhook_url` must be a valid http or https URL.")

    capture_mode = data.get("capture_mode")
    if capture_mode not in CAPTURE_MODES:
        raise ValueError(f"`{label}.capture_mode` must be screenshot, clip, or none.")
    timezone_name = validate_timezone_name(_optional_string(data, "timezone_name", DEFAULT_TIMEZONE), label)
    time_format = _optional_string(data, "time_format", DEFAULT_TIME_FORMAT).lower()
    if time_format not in TIME_FORMATS:
        raise ValueError(f"`{label}.time_format` must be standard or military.")

    return ReportProfile(
        webhook_url=webhook_url,
        interval_seconds=_require_int(data, "interval_seconds", MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS),
        capture_mode=capture_mode,
        include_cpu=_require_bool(data, "include_cpu"),
        include_ram=_require_bool(data, "include_ram"),
        include_roblox=_require_bool(data, "include_roblox"),
        include_time=_require_bool(data, "include_time"),
        clip_length_seconds=_require_int(data, "clip_length_seconds", 1, MAX_CLIP_SECONDS),
        clip_fps=_require_int(data, "clip_fps", 1, MAX_CLIP_FPS),
        timezone_name=timezone_name,
        time_include_year=_optional_bool(data, "time_include_year", True),
        time_include_month=_optional_bool(data, "time_include_month", True),
        time_include_day=_optional_bool(data, "time_include_day", True),
        time_format=time_format,
    )


def disabled_alert_profile() -> ReportProfile:
    return ReportProfile(
        webhook_url="https://example.com/low-roblox-alert-webhook",
        interval_seconds=DEFAULT_INTERVAL_SECONDS,
        capture_mode="none",
        include_cpu=True,
        include_ram=True,
        include_roblox=True,
        include_time=True,
        clip_length_seconds=DEFAULT_CLIP_SECONDS,
        clip_fps=DEFAULT_CLIP_FPS,
    )


def config_from_dict(data: dict) -> AppConfig:
    if "regular" not in data:
        regular = profile_from_dict(data, "regular")
        alert = LowRobloxAlert(
            enabled=False,
            min_roblox_instances=1,
            profile=disabled_alert_profile(),
        )
        return AppConfig(
            regular=regular,
            low_roblox_alert=alert,
            ui_dark_mode=_optional_bool(data, "ui_dark_mode", False),
        )

    regular_data = data.get("regular")
    if not isinstance(regular_data, dict):
        raise ValueError("`regular` must be a JSON object.")

    alert_data = data.get("low_roblox_alert", {})
    if not isinstance(alert_data, dict):
        raise ValueError("`low_roblox_alert` must be a JSON object.")

    alert_enabled = alert_data.get("enabled", False)
    if not isinstance(alert_enabled, bool):
        raise ValueError("`low_roblox_alert.enabled` must be true or false.")

    alert_threshold = alert_data.get("min_roblox_instances", 1)
    if isinstance(alert_threshold, bool) or not isinstance(alert_threshold, int) or alert_threshold < 1:
        raise ValueError("`low_roblox_alert.min_roblox_instances` must be a whole number of at least 1.")

    alert_profile_data = alert_data.get("profile")
    if alert_enabled:
        if not isinstance(alert_profile_data, dict):
            raise ValueError("`low_roblox_alert.profile` must be a JSON object when alert is enabled.")
        alert_profile = profile_from_dict(alert_profile_data, "low_roblox_alert.profile")
    elif isinstance(alert_profile_data, dict):
        alert_profile = profile_from_dict(alert_profile_data, "low_roblox_alert.profile")
    else:
        alert_profile = disabled_alert_profile()

    return AppConfig(
        regular=profile_from_dict(regular_data, "regular"),
        low_roblox_alert=LowRobloxAlert(
            enabled=alert_enabled,
            min_roblox_instances=alert_threshold,
            profile=alert_profile,
        ),
        ui_dark_mode=_optional_bool(data, "ui_dark_mode", False),
    )


def load_config(config_path: Path) -> Optional[AppConfig]:
    if not config_path.exists():
        return None

    try:
        with config_path.open("r", encoding="utf-8") as file_handle:
            raw_config = json.load(file_handle)
        if not isinstance(raw_config, dict):
            raise ValueError("Config file must contain a JSON object.")
        config = config_from_dict(raw_config)
        print(f"Loaded settings from {config_path.name}.")
        return config
    except Exception as exc:
        print(f"Could not use {config_path.name}: {exc}")
        print("Setup will run again and rewrite the config file.")
        return None


def save_config(config_path: Path, config: AppConfig) -> None:
    config_data = asdict(config)
    config_path.write_text(json.dumps(config_data, indent=2) + "\n", encoding="utf-8")


def load_raw_config(config_path: Path) -> dict:
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        if isinstance(data, dict):
            return data
        raise ValueError("Config file must contain a JSON object.")

    example_path = get_app_directory() / "config.example.json"
    if example_path.exists():
        with example_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        if isinstance(data, dict):
            return data

    return asdict(
        AppConfig(
            regular=ReportProfile(
                webhook_url="https://example.com/regular-status-webhook",
                interval_seconds=DEFAULT_INTERVAL_SECONDS,
                capture_mode="screenshot",
                include_cpu=True,
                include_ram=True,
                include_roblox=True,
                include_time=True,
            ),
            low_roblox_alert=LowRobloxAlert(
                enabled=False,
                min_roblox_instances=20,
                profile=disabled_alert_profile(),
            ),
        )
    )


def save_raw_config(config_path: Path, data: dict) -> None:
    config_from_dict(data)
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def require_module(module_name: str, package_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"Missing dependency: {package_name}. Run `py -3 -m pip install -r requirements.txt` first."
        ) from exc


def run_self_test() -> int:
    print(f"{APP_NAME} self-test")

    checks = [
        ("requests", "requests"),
        ("psutil", "psutil"),
        ("mss", "mss"),
        ("PIL.Image", "Pillow"),
        ("imageio_ffmpeg", "imageio-ffmpeg"),
        ("tzdata", "tzdata"),
        ("tkinter", "tkinter"),
    ]

    failed = False
    for module_name, package_name in checks:
        try:
            require_module(module_name, package_name)
            print(f"OK: {package_name}")
        except RuntimeError as exc:
            failed = True
            print(f"FAIL: {exc}")

    if not failed:
        try:
            imageio_ffmpeg = require_module("imageio_ffmpeg", "imageio-ffmpeg")
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            if Path(ffmpeg_path).exists():
                print("OK: bundled ffmpeg")
            else:
                failed = True
                print(f"FAIL: bundled ffmpeg was not found at {ffmpeg_path}")
        except Exception as exc:
            failed = True
            print(f"FAIL: bundled ffmpeg unavailable: {exc}")

    if failed:
        print("Self-test failed.")
        return 1

    print("Self-test passed.")
    return 0


def ask_nonempty_string(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def is_valid_webhook_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def ask_webhook_url() -> str:
    while True:
        webhook_url = ask_nonempty_string("Webhook URL: ")
        if is_valid_webhook_url(webhook_url):
            return webhook_url
        print("Please enter a valid http or https webhook URL.")


def ask_positive_int(
    prompt: str,
    minimum: int = 1,
    maximum: Optional[int] = None,
    default: Optional[int] = None,
) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default

        try:
            value = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue

        if value < minimum:
            print(f"Please enter a number of at least {minimum}.")
            continue
        if maximum is not None and value > maximum:
            print(f"Please enter a number of at most {maximum}.")
            continue
        return value


def ask_yes_no(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} [y/n]: ").strip().lower()
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer with y or n.")


def ask_interval_seconds() -> int:
    print("\nHow often should updates be sent?")
    amount = ask_positive_int("Enter the number: ", minimum=1)

    while True:
        unit = input("Seconds or minutes? [s/m]: ").strip().lower()
        if unit in {"s", "sec", "secs", "second", "seconds"}:
            interval_seconds = amount
            break
        if unit in {"m", "min", "mins", "minute", "minutes"}:
            interval_seconds = amount * 60
            break
        print("Please choose seconds or minutes.")

    if interval_seconds < MIN_INTERVAL_SECONDS:
        print(f"Using a minimum interval of {MIN_INTERVAL_SECONDS} seconds to keep resource usage low.")
        interval_seconds = MIN_INTERVAL_SECONDS
    if interval_seconds > MAX_INTERVAL_SECONDS:
        print("Using a maximum interval of 24 hours.")
        interval_seconds = MAX_INTERVAL_SECONDS

    return interval_seconds


def ask_capture_mode() -> tuple[str, int, int]:
    print("\nScreen capture mode:")
    print("  1) Screenshot")
    print("  2) Short screen clip")
    print("  3) No screen capture")

    while True:
        choice = input("Choose 1, 2, or 3: ").strip()
        if choice == "1":
            return "screenshot", DEFAULT_CLIP_SECONDS, DEFAULT_CLIP_FPS
        if choice == "2":
            print("Recommended low-resource settings: 5 seconds at 5 FPS.")
            clip_length = ask_positive_int(
                f"Clip length in seconds [{DEFAULT_CLIP_SECONDS} recommended]: ",
                minimum=1,
                maximum=MAX_CLIP_SECONDS,
                default=DEFAULT_CLIP_SECONDS,
            )
            clip_fps = ask_positive_int(
                f"FPS [{DEFAULT_CLIP_FPS} recommended]: ",
                minimum=1,
                maximum=MAX_CLIP_FPS,
                default=DEFAULT_CLIP_FPS,
            )
            return "clip", clip_length, clip_fps
        if choice == "3":
            return "none", DEFAULT_CLIP_SECONDS, DEFAULT_CLIP_FPS
        print("Please choose 1, 2, or 3.")


def ask_report_profile(profile_name: str) -> ReportProfile:
    print(f"\n{profile_name}")
    webhook_url = ask_webhook_url()
    interval_seconds = ask_interval_seconds()
    capture_mode, clip_length_seconds, clip_fps = ask_capture_mode()

    print("\nChoose what to include:")
    include_cpu = ask_yes_no("Include CPU usage?")
    include_ram = ask_yes_no("Include RAM usage?")
    include_roblox = ask_yes_no("Include number of Roblox instances running?")
    include_time = ask_yes_no("Include time sent?")

    return ReportProfile(
        webhook_url=webhook_url,
        interval_seconds=interval_seconds,
        capture_mode=capture_mode,
        include_cpu=include_cpu,
        include_ram=include_ram,
        include_roblox=include_roblox,
        include_time=include_time,
        clip_length_seconds=clip_length_seconds,
        clip_fps=clip_fps,
    )


def ask_setup_questions() -> AppConfig:
    print(f"{APP_NAME} setup")
    print("This app is visible, non-stealthy, and only runs when you start it.")
    print("It does not collect keystrokes, browser data, passwords, tokens, cookies, or files.")
    print("You can quit safely with Ctrl+C or by typing q and pressing Enter while it is running.\n")
    print(f"These answers will be saved to {CONFIG_FILE_NAME}.")
    print("You can edit that file later with Notepad.\n")

    regular = ask_report_profile("Regular status webhook")

    alert_enabled = ask_yes_no("\nEnable a separate webhook when Roblox instances are below a number?")
    if alert_enabled:
        min_roblox_instances = ask_positive_int(
            "Send alert when Roblox instances are less than this number: ",
            minimum=1,
            maximum=500,
        )
        alert_profile = ask_report_profile("Low Roblox alert webhook")
    else:
        min_roblox_instances = 1
        alert_profile = disabled_alert_profile()

    return AppConfig(
        regular=regular,
        low_roblox_alert=LowRobloxAlert(
            enabled=alert_enabled,
            min_roblox_instances=min_roblox_instances,
            profile=alert_profile,
        ),
    )


def get_cpu_ram_stats() -> Optional[dict[str, float]]:
    if psutil is None:
        print("CPU/RAM unavailable: psutil is not installed.")
        return None

    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
    except Exception as exc:
        print(f"CPU/RAM unavailable: {exc}")
        return None

    return {
        "cpu_percent": cpu_percent,
        "ram_percent": memory.percent,
        "ram_used_gb": memory.used / (1024**3),
        "ram_total_gb": memory.total / (1024**3),
    }


def count_roblox_instances() -> Optional[int]:
    roblox_pids = find_matching_process_pids(["RobloxPlayerBeta.exe", "RobloxPlayerBeta"])
    if roblox_pids is None:
        return None

    if os.name == "nt" and roblox_pids:
        visible_window_count = count_visible_windows_for_pids(roblox_pids)
        if visible_window_count is not None and visible_window_count > 0:
            return visible_window_count

    return len(roblox_pids)


def collect_process_snapshot() -> Optional[list[tuple[str, int]]]:
    if psutil is None:
        print("Process count unavailable: psutil is not installed.")
        return None

    snapshot: list[tuple[str, int]] = []

    try:
        for process in psutil.process_iter(["name"]):
            try:
                name = (process.info.get("name") or "").lower()
                if name:
                    snapshot.append((name, process.pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception:
        return None

    return snapshot


def find_matching_process_pids(
    process_names: list[str],
    process_snapshot: Optional[list[tuple[str, int]]] = None,
) -> Optional[set[int]]:
    if process_snapshot is None:
        process_snapshot = collect_process_snapshot()
    if process_snapshot is None:
        return None

    normalized_names = {name.lower() for name in process_names}
    matching_pids = {pid for name, pid in process_snapshot if name in normalized_names}
    return matching_pids


def count_visible_windows_for_pids(target_pids: set[int]) -> Optional[int]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    visible_pids = set()
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None

    user32 = windll.user32

    try:
        dwmapi = windll.dwmapi
    except Exception:
        dwmapi = None

    def is_cloaked(hwnd) -> bool:
        if dwmapi is None:
            return False
        cloaked = ctypes.c_int(0)
        result = dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return result == 0 and cloaked.value != 0

    winfunctype = getattr(ctypes, "WINFUNCTYPE", None)
    if winfunctype is None:
        return None
    enum_windows_proc = winfunctype(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or is_cloaked(hwnd):
            return True

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in target_pids:
            visible_pids.add(pid.value)
        return True

    try:
        user32.EnumWindows(enum_windows_proc(callback), 0)
    except Exception:
        return None

    return len(visible_pids)


def _resize_for_low_resource(image, max_width: int):
    if image.width <= max_width:
        return image
    new_height = max(1, round(image.height * (max_width / image.width)))
    pil_image = require_module("PIL.Image", "Pillow")
    resample_filter = getattr(getattr(pil_image, "Resampling", pil_image), "LANCZOS")
    return image.resize((max_width, new_height), resample_filter)


def _make_even_size(image):
    width = image.width - (image.width % 2)
    height = image.height - (image.height % 2)
    if width == image.width and height == image.height:
        return image
    return image.crop((0, 0, max(2, width), max(2, height)))


def take_screenshot() -> str:
    mss = require_module("mss", "mss")
    pil_image = require_module("PIL.Image", "Pillow")

    temp_file = tempfile.NamedTemporaryFile(prefix="pc_status_screenshot_", suffix=".jpg", delete=False)
    temp_file.close()
    screenshot_path = Path(temp_file.name)

    with mss.mss() as screen:
        if len(screen.monitors) < 2:
            raise RuntimeError("No monitor was found for screenshot capture.")

        monitor = screen.monitors[1]
        shot = screen.grab(monitor)
        image = pil_image.frombytes("RGB", shot.size, shot.rgb)
        image = _resize_for_low_resource(image, MAX_SCREENSHOT_WIDTH)
        image.save(
            str(screenshot_path),
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )

    return str(screenshot_path)


def record_screen_clip(clip_length_seconds: int, clip_fps: int) -> str:
    mss = require_module("mss", "mss")
    pil_image = require_module("PIL.Image", "Pillow")
    imageio_ffmpeg = require_module("imageio_ffmpeg", "imageio-ffmpeg")

    temp_file = tempfile.NamedTemporaryFile(prefix="pc_status_clip_", suffix=".mp4", delete=False)
    temp_file.close()
    clip_path = Path(temp_file.name)

    frame_interval = 1.0 / clip_fps
    total_frames = max(1, int(round(clip_length_seconds * clip_fps)))
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    process: Optional[subprocess.Popen] = None
    stderr_text = ""

    try:
        with mss.mss() as screen:
            if len(screen.monitors) < 2:
                raise RuntimeError("No monitor was found for screen clip capture.")

            monitor = screen.monitors[1]
            first_shot = screen.grab(monitor)
            first_frame = pil_image.frombytes("RGB", first_shot.size, first_shot.rgb)
            first_frame = _make_even_size(_resize_for_low_resource(first_frame, MAX_CLIP_WIDTH))

            command = [
                ffmpeg_path,
                "-y",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{first_frame.width}x{first_frame.height}",
                "-r",
                str(clip_fps),
                "-i",
                "-",
                "-an",
                "-vcodec",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(VIDEO_CRF),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(clip_path),
            ]

            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **subprocess_no_window_kwargs(),
            )

            if process.stdin is None:
                raise RuntimeError("Could not open ffmpeg input pipe.")

            next_frame_time = time.perf_counter()
            for frame_number in range(total_frames):
                if frame_number == 0:
                    frame = first_frame
                else:
                    shot = screen.grab(monitor)
                    frame = pil_image.frombytes("RGB", shot.size, shot.rgb)
                    frame = _make_even_size(_resize_for_low_resource(frame, MAX_CLIP_WIDTH))

                process.stdin.write(frame.tobytes())

                next_frame_time += frame_interval
                sleep_for = next_frame_time - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)

            process.stdin.close()
            stderr_bytes = process.stderr.read() if process.stderr else b""
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(f"ffmpeg failed with code {return_code}: {stderr_text[-500:]}")
        if not clip_path.exists() or clip_path.stat().st_size == 0:
            raise RuntimeError("ffmpeg did not create a video file.")
    finally:
        if process is not None and process.poll() is None:
            process.kill()

    return str(clip_path)


def build_message(
    profile: ReportProfile,
    stats: Optional[dict[str, float]],
    roblox_count: Optional[int],
    attachment_error: Optional[str] = None,
    title: str = "PC Status Update",
    detail_lines: Optional[list[str]] = None,
) -> str:
    lines: list[str] = [f"**{title}**"]
    if detail_lines:
        lines.extend(detail_lines)

    if profile.include_time:
        lines.append(f"Time sent: `{format_sent_time(profile)}`")
    if profile.include_cpu:
        if stats is None:
            lines.append("CPU usage: `Unknown`")
        else:
            lines.append(f"CPU usage: `{stats['cpu_percent']:.1f}%`")
    if profile.include_ram:
        if stats is None:
            lines.append("RAM usage: `Unknown`")
        else:
            lines.append(
                f"RAM usage: `{stats['ram_used_gb']:.1f}/{stats['ram_total_gb']:.1f} GB "
                f"({stats['ram_percent']:.1f}%)`"
            )
    if profile.include_roblox:
        roblox_display = "Unknown" if roblox_count is None else str(roblox_count)
        lines.append(f"Roblox instances: `{roblox_display}`")

    lines.append(f"Capture mode: `{profile.capture_mode}`")
    if attachment_error:
        lines.append(f"Attachment: `Failed - {attachment_error}`")

    return "\n".join(lines)


def send_report(
    profile: ReportProfile,
    title: str,
    roblox_count: Optional[int],
    detail_lines: Optional[list[str]] = None,
    error_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    temp_files: list[str] = []
    attachment_path: Optional[str] = None
    attachment_error: Optional[str] = None

    try:
        stats = get_cpu_ram_stats() if (profile.include_cpu or profile.include_ram) else None

        try:
            if profile.capture_mode == "screenshot":
                attachment_path = take_screenshot()
                temp_files.append(attachment_path)
            elif profile.capture_mode == "clip":
                attachment_path = record_screen_clip(profile.clip_length_seconds, profile.clip_fps)
                temp_files.append(attachment_path)
        except Exception as exc:
            attachment_error = str(exc)
            if error_callback is not None:
                error_callback(f"Screen capture error: {attachment_error}")
            else:
                print(f"Screen capture error: {attachment_error}")

        message = build_message(profile, stats, roblox_count, attachment_error, title, detail_lines)
        return send_webhook(profile.webhook_url, message, attachment_path, error_callback)
    finally:
        clean_temp_files(*temp_files)


def send_webhook(
    webhook_url: str,
    message: str,
    attachment_path: Optional[str] = None,
    error_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    def report_error(error_message: str) -> None:
        if error_callback is not None:
            error_callback(error_message)
        else:
            print(error_message)

    if requests is None:
        report_error("Webhook unavailable: requests is not installed.")
        return False

    try:
        if attachment_path:
            file_name = Path(attachment_path).name
            mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            with open(attachment_path, "rb") as file_handle:
                response = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps({"content": message})},
                    files={"file": (file_name, file_handle, mime_type)},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
        else:
            response = requests.post(
                webhook_url,
                json={"content": message},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        if 200 <= response.status_code < 300:
            return True

        report_error(f"Webhook error: HTTP {response.status_code}")
        if response.text:
            report_error(response.text[:500])
        return False
    except Exception as exc:
        report_error(f"Webhook error: {exc}")
        return False


def clean_temp_files(*file_paths: Optional[str]) -> None:
    for file_path in file_paths:
        if not file_path:
            continue
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            pass


def quit_listener(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            command = input().strip().lower()
        except EOFError:
            return
        except KeyboardInterrupt:
            stop_event.set()
            return

        if command in {"q", "quit", "exit"}:
            stop_event.set()
            return


def run_reporter(
    config: AppConfig,
    stop_event: Optional[threading.Event] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    listen_for_console_quit: bool = True,
) -> None:
    if stop_event is None:
        stop_event = threading.Event()
    if listen_for_console_quit:
        threading.Thread(target=quit_listener, args=(stop_event,), daemon=True).start()

    def log(message: str) -> None:
        if log_callback is not None:
            log_callback(message)
        else:
            print(message)

    log("Running.")
    if listen_for_console_quit:
        log("Press Ctrl+C or type q then Enter to quit.")

    regular = config.regular
    alert = config.low_roblox_alert
    next_regular_send = 0.0
    next_alert_send = 0.0

    try:
        while not stop_event.is_set():
            now = time.monotonic()

            try:
                should_send_regular = now >= next_regular_send
                should_check_alert = alert.enabled and now >= next_alert_send

                if should_send_regular or should_check_alert:
                    roblox_count = count_roblox_instances()
                else:
                    roblox_count = None

                if should_send_regular:
                    success = send_report(regular, "PC Status Update", roblox_count, error_callback=log)
                    next_regular_send = time.monotonic() + regular.interval_seconds
                    if success:
                        log(f"Sent regular update at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    else:
                        log("Regular update was not sent. Check the webhook URL and network connection.")

                if should_check_alert:
                    if roblox_count is None:
                        log("Low Roblox alert skipped because Roblox count is Unknown.")
                    elif roblox_count < alert.min_roblox_instances:
                        detail_lines = [
                            f"Alert: Roblox instances below `{alert.min_roblox_instances}`",
                            f"Current Roblox instances: `{roblox_count}`",
                        ]
                        success = send_report(
                            alert.profile,
                            "Low Roblox Instance Alert",
                            roblox_count,
                            detail_lines,
                            log,
                        )
                        if success:
                            log(f"Sent low Roblox alert at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        else:
                            log("Low Roblox alert was not sent. Check the alert webhook URL and network connection.")
                    next_alert_send = time.monotonic() + alert.profile.interval_seconds
            except Exception as exc:
                log(f"Unexpected error: {exc}")
                next_regular_send = time.monotonic() + regular.interval_seconds
                if alert.enabled:
                    next_alert_send = time.monotonic() + alert.profile.interval_seconds

            next_due = next_regular_send
            if alert.enabled:
                next_due = min(next_due, next_alert_send)
            sleep_for = max(0.1, min(1.0, next_due - time.monotonic()))
            stop_event.wait(sleep_for)
    except KeyboardInterrupt:
        log("Stopping.")
        stop_event.set()

    log("Exited cleanly.")


HELP_TEXT = {
    "regular.webhook_url": "The Discord webhook URL used for normal status updates.",
    "interval_seconds": "How often this webhook sends. Use at least 60 seconds for low resource usage.",
    "capture_mode": "screenshot sends a compressed image, clip sends a short MP4, none sends text only.",
    "include_cpu": "Adds current CPU usage to the Discord message.",
    "include_ram": "Adds current RAM usage to the Discord message.",
    "include_roblox": "Adds the visible Roblox instance count to the Discord message.",
    "include_time": "Adds the time the report was sent.",
    "timezone_name": "Timezone used for the sent time. The dropdown shows the current GMT offset in parentheses.",
    "time_include_year": "Adds the year to the date after the time.",
    "time_include_month": "Adds the month to the date after the time.",
    "time_include_day": "Adds the day to the date after the time.",
    "time_format": "Standard uses AM/PM. Military uses 24-hour time.",
    "clip_length_seconds": "Length of MP4 screen clips. Five seconds is recommended.",
    "clip_fps": "Frames per second for MP4 clips. Five FPS is recommended for low resource usage.",
    "low_enabled": "Turns on a separate webhook that only sends when Roblox count is below your threshold.",
    "min_roblox_instances": "The alert sends when visible Roblox instances are less than this number.",
}

def show_help(title: str, key: str) -> None:
    if messagebox is not None:
        messagebox.showinfo(title, HELP_TEXT.get(key, "No help text is available for this setting."))


class ConfigApp:
    def __init__(self, root: Any):
        self.root = root
        self.config_path = get_config_path()
        self.stop_event: Optional[threading.Event] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.vars: dict[str, Any] = {}
        self.raw_config: dict[str, Any] = {}
        self.style: Any = ttk.Style(self.root)
        self.dark_mode_var: Any = None
        self.notebook: Any = None
        self.home_tab: Any = None
        self.webhook_tab: Any = None
        self.status_var: Any = None
        self.log_box: Any = None
        self.compact_window: Any = None
        self.last_update_var: Any = None
        self.scroll_canvases: list[Any] = []
        self.text_widgets: list[Any] = []
        self.title_label: Any = None
        self.compact_title_label: Any = None

        self.root.title(APP_NAME)
        self.root.geometry("900x680")
        self.root.minsize(780, 560)

        self.raw_config = self.load_initial_config()
        self.dark_mode_var = tk.BooleanVar(value=bool(self.raw_config.get("ui_dark_mode", False)))
        self.apply_theme()
        self.create_widgets()
        self.populate_from_config(self.raw_config)
        self.apply_theme()

    def load_initial_config(self) -> dict[str, Any]:
        try:
            raw_config = load_raw_config(self.config_path)
            return asdict(config_from_dict(raw_config))
        except Exception as exc:
            if messagebox is not None:
                messagebox.showwarning(
                    "Config problem",
                    f"Could not use {CONFIG_FILE_NAME}:\n\n{exc}\n\nLoading the example config instead.",
                )
            example_path = get_app_directory() / "config.example.json"
            if example_path.exists():
                with example_path.open("r", encoding="utf-8") as file_handle:
                    data = json.load(file_handle)
                return asdict(config_from_dict(data))
            return asdict(
                AppConfig(
                    regular=ReportProfile(
                        webhook_url="https://example.com/regular-status-webhook",
                        interval_seconds=DEFAULT_INTERVAL_SECONDS,
                        capture_mode="screenshot",
                        include_cpu=True,
                        include_ram=True,
                        include_roblox=True,
                        include_time=True,
                    ),
                    low_roblox_alert=LowRobloxAlert(False, 20, disabled_alert_profile()),
                )
            )

    def theme_colors(self) -> dict[str, str]:
        if self.dark_mode_var is not None and self.dark_mode_var.get():
            return {
                "bg": "#111318",
                "panel": "#1B1F27",
                "field": "#242A35",
                "text": "#F4F6FA",
                "muted": "#B8C0CC",
                "accent": "#8EA2FF",
                "border": "#303746",
                "select": "#2F3A56",
            }
        return {
            "bg": "#F4F6FA",
            "panel": "#FFFFFF",
            "field": "#FFFFFF",
            "text": "#1F2328",
            "muted": "#4E5969",
            "accent": "#5865F2",
            "border": "#D8DEE9",
            "select": "#DDE4FF",
        }

    def apply_theme(self) -> None:
        colors = self.theme_colors()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.root.configure(bg=colors["bg"])
        self.style.configure(".", background=colors["bg"], foreground=colors["text"], fieldbackground=colors["field"])
        self.style.configure("TFrame", background=colors["bg"])
        self.style.configure("TLabelframe", background=colors["bg"], foreground=colors["text"], bordercolor=colors["border"])
        self.style.configure("TLabelframe.Label", background=colors["bg"], foreground=colors["text"])
        self.style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
        self.style.configure("TButton", background=colors["panel"], foreground=colors["text"], bordercolor=colors["border"])
        self.style.map("TButton", background=[("active", colors["select"])], foreground=[("active", colors["text"])])
        self.style.configure("TCheckbutton", background=colors["bg"], foreground=colors["text"])
        self.style.map("TCheckbutton", background=[("active", colors["bg"])], foreground=[("active", colors["text"])])
        self.style.configure("TEntry", fieldbackground=colors["field"], foreground=colors["text"], bordercolor=colors["border"])
        self.style.configure("TCombobox", fieldbackground=colors["field"], foreground=colors["text"], bordercolor=colors["border"])
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", colors["field"])],
            foreground=[("readonly", colors["text"])],
            selectbackground=[("readonly", colors["select"])],
            selectforeground=[("readonly", colors["text"])],
        )
        self.style.configure("TNotebook", background=colors["bg"], bordercolor=colors["border"])
        self.style.configure("TNotebook.Tab", background=colors["panel"], foreground=colors["text"])
        self.style.map("TNotebook.Tab", background=[("selected", colors["select"])])

        for canvas in self.scroll_canvases:
            canvas.configure(bg=colors["bg"])
        for text_widget in self.text_widgets:
            text_widget.configure(
                bg=colors["field"],
                fg=colors["text"],
                insertbackground=colors["text"],
                selectbackground=colors["select"],
                selectforeground=colors["text"],
            )
        if self.title_label is not None:
            self.title_label.configure(bg=colors["bg"], fg=colors["accent"])
        if self.compact_title_label is not None and self.compact_title_label.winfo_exists():
            self.compact_title_label.configure(bg=colors["bg"], fg=colors["accent"])
        if self.compact_window is not None and self.compact_window.winfo_exists():
            self.compact_window.configure(bg=colors["bg"])

    def toggle_dark_mode(self) -> None:
        self.apply_theme()
        self.log("Dark mode enabled." if self.dark_mode_var.get() else "Dark mode disabled.")

    def create_widgets(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        home_page, self.home_tab = self.create_scrollable_tab()
        webhook_page, self.webhook_tab = self.create_scrollable_tab()

        self.notebook.add(home_page, text="Home")
        self.notebook.add(webhook_page, text="Webhook")

        self.create_home_tab()
        self.create_webhook_tab()

    def create_scrollable_tab(self) -> tuple[Any, Any]:
        container = ttk.Frame(self.notebook)
        canvas = tk.Canvas(container, highlightthickness=0)
        self.scroll_canvases.append(canvas)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_content_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def on_mousewheel(event) -> None:
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
            else:
                delta = getattr(event, "delta", 0)
                if abs(delta) >= 120:
                    scroll_units = int(-1 * (delta / 120))
                else:
                    scroll_units = -1 if delta > 0 else 1
                canvas.yview_scroll(scroll_units, "units")

        def bind_mousewheel(_event=None) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)
            canvas.bind_all("<Button-4>", on_mousewheel)
            canvas.bind_all("<Button-5>", on_mousewheel)

        def unbind_mousewheel(_event=None) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_content_width)
        container.bind("<Enter>", bind_mousewheel)
        container.bind("<Leave>", unbind_mousewheel)

        return container, content

    def add_help_button(self, parent: Any, title: str, key: str, row: int, column: int) -> None:
        button = ttk.Button(parent, text="?", width=3, command=lambda: show_help(title, key))
        button.grid(row=row, column=column, padx=(6, 0), pady=4, sticky="w")

    def add_entry_row(self, parent: Any, row: int, label: str, key: str, help_key: str, width: int = 42) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        variable = self.vars.get(key)
        if variable is None:
            variable = tk.StringVar()
            self.vars[key] = variable
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky="ew", pady=4)
        self.add_help_button(parent, label, help_key, row, 2)

    def add_bool_row(self, parent: Any, row: int, label: str, key: str, help_key: str) -> None:
        variable = self.vars.get(key)
        if variable is None:
            variable = tk.BooleanVar()
            self.vars[key] = variable
        ttk.Checkbutton(parent, text=label, variable=variable).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        self.add_help_button(parent, label, help_key, row, 2)

    def add_capture_row(self, parent: Any, row: int, label: str, key: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        variable = self.vars.get(key)
        if variable is None:
            variable = tk.StringVar()
            self.vars[key] = variable
        ttk.Combobox(
            parent,
            textvariable=variable,
            values=("screenshot", "clip", "none"),
            state="readonly",
            width=20,
        ).grid(row=row, column=1, sticky="w", pady=4)
        self.add_help_button(parent, label, "capture_mode", row, 2)

    def add_choice_row(
        self,
        parent: Any,
        row: int,
        label: str,
        key: str,
        help_key: str,
        choices: tuple[str, ...],
        width: int = 32,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        variable = self.vars.get(key)
        if variable is None:
            variable = tk.StringVar()
            self.vars[key] = variable
        ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly", width=width).grid(
            row=row,
            column=1,
            sticky="w",
            pady=4,
        )
        self.add_help_button(parent, label, help_key, row, 2)

    def create_home_tab(self) -> None:
        self.home_tab.columnconfigure(1, weight=1)

        self.title_label = tk.Label(
            self.home_tab,
            text=APP_NAME,
            font=("Bahnschrift SemiBold", 24),
            fg="#5865F2",
            bg=self.root.cget("bg"),
        )
        self.title_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        description = (
            "This window configures and runs the PC status reporter. It sends the selected stats "
            "and optional screen capture to your Discord webhook on the schedule you choose. "
            "The app stays visible and can be stopped here at any time."
        )
        ttk.Label(self.home_tab, text=description, wraplength=760).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(0, 12),
        )

        support_frame = ttk.LabelFrame(self.home_tab, text="Support and Updates", padding=10)
        support_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        support_frame.columnconfigure(0, weight=1)
        ttk.Label(
            support_frame,
            text=(
                "Join the Discord server for support, release updates, setup help, and notices "
                "when a new version is available."
            ),
            wraplength=740,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        discord_link = ttk.Entry(support_frame, width=40)
        discord_link.insert(0, "https://discord.gg/zusCzshxsD")
        discord_link.configure(state="readonly")
        discord_link.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(self.home_tab, text=f"Config file: {self.config_path}").grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 4),
        )
        ttk.Checkbutton(
            self.home_tab,
            text="Dark mode",
            variable=self.dark_mode_var,
            command=self.toggle_dark_mode,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 8))

        self.status_var = tk.StringVar(value="Stopped")
        self.last_update_var = tk.StringVar(value="Last update: not sent yet")
        ttk.Label(self.home_tab, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=5,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(4, 8),
        )
        ttk.Label(self.home_tab, textvariable=self.last_update_var).grid(
            row=6,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(0, 8),
        )

        buttons = ttk.Frame(self.home_tab)
        buttons.grid(row=7, column=0, columnspan=3, sticky="w", pady=8)
        ttk.Button(buttons, text="Save Config", command=self.save_config).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Start", command=self.start_reporter).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Stop", command=self.stop_reporter).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Compact Mode", command=self.open_compact_mode).pack(side="left")

        ttk.Label(self.home_tab, text="Activity").grid(row=8, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.log_box = scrolledtext.ScrolledText(self.home_tab, height=14, state="disabled", wrap="word")
        self.text_widgets.append(self.log_box)
        self.log_box.grid(row=9, column=0, columnspan=3, sticky="nsew")
        self.home_tab.rowconfigure(9, weight=1)

    def create_profile_section(self, parent: Any, title: str, prefix: str, start_row: int) -> int:
        section = ttk.LabelFrame(parent, text=title, padding=10)
        section.grid(row=start_row, column=0, sticky="nsew", pady=(0, 12))
        section.columnconfigure(1, weight=1)

        row = 0
        self.add_entry_row(section, row, "Webhook URL", f"{prefix}.webhook_url", "regular.webhook_url", 60)
        row += 1
        self.add_entry_row(section, row, "Send interval seconds", f"{prefix}.interval_seconds", "interval_seconds", 16)
        row += 1
        self.add_capture_row(section, row, "Capture mode", f"{prefix}.capture_mode")
        row += 1
        self.add_bool_row(section, row, "Include CPU usage", f"{prefix}.include_cpu", "include_cpu")
        row += 1
        self.add_bool_row(section, row, "Include RAM usage", f"{prefix}.include_ram", "include_ram")
        row += 1
        self.add_bool_row(section, row, "Include Roblox instances", f"{prefix}.include_roblox", "include_roblox")
        row += 1
        self.add_bool_row(section, row, "Include time sent", f"{prefix}.include_time", "include_time")
        row += 1
        self.add_choice_row(
            section,
            row,
            "Timezone",
            f"{prefix}.timezone_name",
            "timezone_name",
            timezone_choices(),
            42,
        )
        row += 1
        self.add_choice_row(
            section,
            row,
            "Time format",
            f"{prefix}.time_format",
            "time_format",
            ("standard", "military"),
            16,
        )
        row += 1
        self.add_bool_row(section, row, "Include year in date", f"{prefix}.time_include_year", "time_include_year")
        row += 1
        self.add_bool_row(section, row, "Include month in date", f"{prefix}.time_include_month", "time_include_month")
        row += 1
        self.add_bool_row(section, row, "Include day in date", f"{prefix}.time_include_day", "time_include_day")
        row += 1
        self.add_entry_row(section, row, "Clip length seconds", f"{prefix}.clip_length_seconds", "clip_length_seconds", 16)
        row += 1
        self.add_entry_row(section, row, "Clip FPS", f"{prefix}.clip_fps", "clip_fps", 16)
        return start_row + 1

    def create_webhook_tab(self) -> None:
        self.webhook_tab.columnconfigure(0, weight=1)

        row = self.create_profile_section(self.webhook_tab, "Regular Webhook", "regular", 0)

        alert_frame = ttk.LabelFrame(self.webhook_tab, text="Low Roblox Alert", padding=10)
        alert_frame.grid(row=row, column=0, sticky="nsew")
        alert_frame.columnconfigure(1, weight=1)

        self.add_bool_row(alert_frame, 0, "Enable low Roblox alert webhook", "low_roblox_alert.enabled", "low_enabled")
        self.add_entry_row(
            alert_frame,
            1,
            "Alert when Roblox count is less than",
            "low_roblox_alert.min_roblox_instances",
            "min_roblox_instances",
            16,
        )

        profile_frame = ttk.Frame(alert_frame)
        profile_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        profile_frame.columnconfigure(0, weight=1)
        self.create_profile_section(profile_frame, "Alert Webhook Options", "low_roblox_alert.profile", 0)

    def populate_profile(self, prefix: str, profile: dict[str, Any]) -> None:
        for key in (
            "webhook_url",
            "interval_seconds",
            "capture_mode",
            "include_cpu",
            "include_ram",
            "include_roblox",
            "include_time",
            "timezone_name",
            "time_include_year",
            "time_include_month",
            "time_include_day",
            "time_format",
            "clip_length_seconds",
            "clip_fps",
        ):
            variable = self.vars.get(f"{prefix}.{key}")
            if variable is not None:
                value = profile.get(key)
                if key == "timezone_name":
                    value = timezone_value_to_label(value or DEFAULT_TIMEZONE)
                variable.set(value)

    def populate_from_config(self, config: dict[str, Any]) -> None:
        self.populate_profile("regular", config.get("regular", {}))
        alert = config.get("low_roblox_alert", {})
        self.vars["low_roblox_alert.enabled"].set(alert.get("enabled", False))
        self.vars["low_roblox_alert.min_roblox_instances"].set(alert.get("min_roblox_instances", 20))
        self.populate_profile("low_roblox_alert.profile", alert.get("profile", {}))

    def read_profile(self, prefix: str) -> dict[str, Any]:
        return {
            "webhook_url": self.vars[f"{prefix}.webhook_url"].get().strip(),
            "interval_seconds": int(self.vars[f"{prefix}.interval_seconds"].get()),
            "capture_mode": self.vars[f"{prefix}.capture_mode"].get(),
            "include_cpu": bool(self.vars[f"{prefix}.include_cpu"].get()),
            "include_ram": bool(self.vars[f"{prefix}.include_ram"].get()),
            "include_roblox": bool(self.vars[f"{prefix}.include_roblox"].get()),
            "include_time": bool(self.vars[f"{prefix}.include_time"].get()),
            "timezone_name": timezone_label_to_value(self.vars[f"{prefix}.timezone_name"].get()),
            "time_include_year": bool(self.vars[f"{prefix}.time_include_year"].get()),
            "time_include_month": bool(self.vars[f"{prefix}.time_include_month"].get()),
            "time_include_day": bool(self.vars[f"{prefix}.time_include_day"].get()),
            "time_format": self.vars[f"{prefix}.time_format"].get(),
            "clip_length_seconds": int(self.vars[f"{prefix}.clip_length_seconds"].get()),
            "clip_fps": int(self.vars[f"{prefix}.clip_fps"].get()),
        }

    def read_ui_config(self) -> dict[str, Any]:
        return {
            "regular": self.read_profile("regular"),
            "low_roblox_alert": {
                "enabled": bool(self.vars["low_roblox_alert.enabled"].get()),
                "min_roblox_instances": int(self.vars["low_roblox_alert.min_roblox_instances"].get()),
                "profile": self.read_profile("low_roblox_alert.profile"),
            },
            "ui_dark_mode": bool(self.dark_mode_var.get()),
        }

    def save_config(self) -> Optional[AppConfig]:
        try:
            data = self.read_ui_config()
            config = config_from_dict(data)
            save_raw_config(self.config_path, data)
            self.log(f"Saved config to {self.config_path.name}.")
            return config
        except Exception as exc:
            if messagebox is not None:
                messagebox.showerror("Config problem", str(exc))
            return None

    def start_reporter(self) -> None:
        if self.worker_thread is not None and self.worker_thread.is_alive():
            self.log("Reporter is already running.")
            return

        config = self.save_config()
        if config is None:
            return

        self.stop_event = threading.Event()
        self.worker_thread = threading.Thread(
            target=run_reporter,
            args=(config, self.stop_event, self.thread_log, False),
            daemon=True,
        )
        self.worker_thread.start()
        self.status_var.set("Running")
        self.log("Started reporter.")

    def stop_reporter(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
            self.status_var.set("Stopping...")
            self.log("Stopping reporter...")
        else:
            self.log("Reporter is not running.")

    def open_compact_mode(self) -> None:
        if self.compact_window is not None and self.compact_window.winfo_exists():
            self.compact_window.lift()
            return

        self.compact_window = tk.Toplevel(self.root)
        self.compact_window.title(f"{APP_NAME} Compact")
        self.compact_window.geometry("320x170")
        self.compact_window.minsize(240, 120)
        self.compact_window.columnconfigure(0, weight=1)

        self.compact_title_label = tk.Label(
            self.compact_window,
            text="PC Status",
            font=("Bahnschrift SemiBold", 16),
            fg="#5865F2",
        )
        self.compact_title_label.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        ttk.Label(self.compact_window, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=1,
            column=0,
            sticky="w",
            padx=12,
            pady=(0, 4),
        )
        ttk.Label(self.compact_window, textvariable=self.last_update_var, wraplength=280).grid(
            row=2,
            column=0,
            sticky="w",
            padx=12,
            pady=(0, 10),
        )

        buttons = ttk.Frame(self.compact_window)
        buttons.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="Start", command=self.start_reporter).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Stop", command=self.stop_reporter).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Main Window", command=self.return_to_main_window).pack(side="left")

        self.compact_window.protocol("WM_DELETE_WINDOW", self.return_to_main_window)
        self.apply_theme()
        self.root.withdraw()

    def return_to_main_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        if self.compact_window is not None and self.compact_window.winfo_exists():
            self.compact_window.destroy()
        self.compact_window = None

    def close_app(self) -> None:
        self.stop_reporter()
        if self.compact_window is not None and self.compact_window.winfo_exists():
            self.compact_window.destroy()
        self.root.after(200, self.root.destroy)

    def thread_log(self, message: str) -> None:
        self.root.after(0, lambda: self.log(message))

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        if message.startswith("Sent regular update") or message.startswith("Sent low Roblox alert"):
            self.last_update_var.set(f"Last update: {timestamp}")
        if message == "Exited cleanly.":
            self.status_var.set("Stopped")


def launch_gui() -> int:
    if tk is None or ttk is None or scrolledtext is None or messagebox is None:
        print("Tkinter is not available. Cannot start the GUI.")
        return 1

    root = tk.Tk()
    app = ConfigApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close_app)
    root.mainloop()
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return run_self_test()
    if "--console" not in sys.argv:
        return launch_gui()

    config_path = get_config_path()
    config = load_config(config_path)

    if config is None:
        try:
            config = ask_setup_questions()
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            return 130

        try:
            save_config(config_path, config)
            print(f"\nSaved settings to {config_path.name}.")
        except OSError as exc:
            print(f"\nCould not save {config_path.name}: {exc}")
            print("The app will still run, but setup will be needed next time.")

    print("\nSetup complete.")
    print(f"Config file: {config_path}")
    print("Webhook URL will not be printed.")
    print(f"Regular interval: {config.regular.interval_seconds} seconds")
    print(f"Regular capture mode: {config.regular.capture_mode}")
    if config.low_roblox_alert.enabled:
        print(
            "Low Roblox alert: enabled "
            f"(less than {config.low_roblox_alert.min_roblox_instances}, "
            f"every {config.low_roblox_alert.profile.interval_seconds} seconds)"
        )
    else:
        print("Low Roblox alert: disabled")

    run_reporter(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
