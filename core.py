"""FocusPin V2 pure-Python state, migration, recurrence, statistics, and alert audio.
No Qt dependency: this module is intentionally independently testable.
"""
from __future__ import annotations

import calendar
import copy
import csv
import io
import json
import math
import os
import shutil
import struct
import tempfile
import uuid
import wave
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

APP_NAME = "FocusPin"
DEFAULT_SETTINGS = {
    "opacity": 0.88, "idle_minutes": 30, "click_through": False,
    "show_completed": False, "mute_reminders": False, "sound_enabled": True,
    "position": None, "snooze_minutes": 10, "beep_interval": 13,
    "volume": 70, "sound_profile": "Classic", "flash_color": "Orange",
    "flash_interval_ms": 450, "focus_minutes": 25,
}
PRIORITIES = ("High", "Medium", "Low")
REPEAT_OPTIONS = ("None", "Daily", "Weekdays", "Weekly", "Monthly")


def storage_path() -> Path:
    root = os.environ.get("APPDATA")
    return (Path(root) / APP_NAME if root else Path.home() / ".focuspin") / "state.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_task(item: object) -> dict | None:
    """Keep all V1 task fields while adding sane V2 defaults."""
    if not isinstance(item, dict) or not isinstance(item.get("text"), str):
        return None
    if not item["text"].strip():
        return None
    task = dict(item)
    task["id"] = str(item.get("id") or uuid.uuid4().hex)
    task["text"] = str(item["text"])[:600]
    task["done"] = bool(item.get("done", False))
    task["created_at"] = item.get("created_at") or now_iso()
    task["completed_at"] = item.get("completed_at") if task["done"] else None
    task["priority"] = item.get("priority") if item.get("priority") in PRIORITIES else "Medium"
    task["category"] = str(item.get("category") or "General")[:60]
    task["due_at"] = item.get("due_at") if _valid_datetime(item.get("due_at")) else None
    task["repeat"] = item.get("repeat") if item.get("repeat") in REPEAT_OPTIONS else "None"
    task["notes"] = str(item.get("notes") or "")[:4000]
    parts = item.get("subtasks", [])
    task["subtasks"] = [
        {"id": str(p.get("id") or uuid.uuid4().hex), "text": str(p["text"])[:300], "done": bool(p.get("done", False))}
        for p in (parts if isinstance(parts, list) else [])
        if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip()
    ][:100]
    return task


def _valid_datetime(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def _clamp(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def read_state(path: Path) -> tuple[list[dict], dict, list[dict]]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return [], settings, []
    if not isinstance(data, dict):
        return [], settings, []
    raw_settings = data.get("settings", {})
    if isinstance(raw_settings, dict):
        settings.update({key: raw_settings[key] for key in DEFAULT_SETTINGS if key in raw_settings})
    try:
        settings["opacity"] = max(.45, min(1.0, float(settings["opacity"])))
    except (ValueError, TypeError, OverflowError):
        settings["opacity"] = .88
    for name, low, high in (("idle_minutes", 1, 240), ("snooze_minutes", 1, 120), ("beep_interval", 3, 300),
                            ("volume", 0, 100), ("flash_interval_ms", 200, 2000), ("focus_minutes", 1, 180)):
        settings[name] = _clamp(settings[name], low, high, DEFAULT_SETTINGS[name])
    for name in ("click_through", "show_completed", "mute_reminders", "sound_enabled"):
        settings[name] = bool(settings[name])
    if settings["sound_profile"] not in ("Classic", "Gentle", "Urgent"):
        settings["sound_profile"] = "Classic"
    if settings["flash_color"] not in ("Orange", "Red", "Purple"):
        settings["flash_color"] = "Orange"
    pos = settings["position"]
    settings["position"] = pos if isinstance(pos, list) and len(pos) == 2 and all(type(n) is int for n in pos) else None
    source = data.get("tasks", [])
    tasks = [x for i in (source if isinstance(source, list) else []) if (x := normalize_task(i)) is not None][:5000]
    sessions = data.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    sessions = [dict(x) for x in sessions if isinstance(x, dict) and isinstance(x.get("minutes"), (int, float)) and _valid_datetime(x.get("ended_at"))][-5000:]
    return tasks, settings, sessions


def write_state(path: Path, tasks: list[dict], settings: dict, sessions: list[dict]) -> None:
    """Atomic replacement, not append; preserves every existing task."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="focuspin-v2-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "tasks": tasks, "settings": settings, "sessions": sessions}, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def backup_v1_once(path: Path) -> Path | None:
    """Create a one-time copy of V1 data before its first V2 rewrite."""
    target = path.with_name("state.v1.backup.json")
    if target.exists() or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version", 1) < 2:
            shutil.copy2(path, target)
            return target
    except (OSError, ValueError, TypeError):
        pass
    return None


def new_task(text: str, **kwargs) -> dict:
    value = normalize_task({"id": uuid.uuid4().hex, "text": text, "done": False, "created_at": now_iso(), **kwargs})
    if value is None:
        raise ValueError("Task title cannot be empty")
    return value


def _next_month(moment: datetime, anchor_day: int | None = None) -> datetime:
    year = moment.year + (moment.month // 12)
    month = moment.month % 12 + 1
    return moment.replace(year=year, month=month, day=min(anchor_day or moment.day, calendar.monthrange(year, month)[1]))


def next_occurrence(repeat: str, previous_due: str | None, *, now: datetime | None = None, anchor_day: int | None = None) -> str | None:
    """Schedule a *single* future occurrence, keeping local wall-clock time."""
    if repeat not in REPEAT_OPTIONS or repeat == "None":
        return None
    current = now or datetime.now().astimezone()
    if previous_due and _valid_datetime(previous_due):
        scheduled = datetime.fromisoformat(previous_due)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=current.tzinfo)
        current = current.astimezone(scheduled.tzinfo)
    else:
        scheduled = current
    for _ in range(3700):
        if repeat in ("Daily", "Weekdays"):
            scheduled = scheduled + timedelta(days=1)
            if repeat == "Weekdays" and scheduled.weekday() >= 5:
                continue
        elif repeat == "Weekly":
            scheduled += timedelta(days=7)
        else:
            scheduled = _next_month(scheduled, anchor_day)
        if scheduled > current:
            return scheduled.isoformat(timespec="minutes")
    raise RuntimeError("Could not find future recurrence")


def set_completed(tasks: list[dict], task_id: str, done: bool, *, now: datetime | None = None) -> str | None:
    """Mutates tasks, adding exactly one new occurrence on first completion."""
    for item in tasks:
        if item["id"] != task_id:
            continue
        if bool(item["done"]) == done:
            return None
        item["done"] = done
        item["completed_at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds") if done else None
        if done and item.get("repeat", "None") != "None":
            nxt = copy.deepcopy(item)
            nxt["id"] = uuid.uuid4().hex
            nxt["series_id"] = item.get("series_id") or item["id"]
            nxt["created_at"] = now_iso()
            nxt["done"] = False
            nxt["completed_at"] = None
            if item["repeat"] == "Monthly":
                try:
                    original_day = datetime.fromisoformat(item["due_at"]).day if item.get("due_at") else None
                except ValueError:
                    original_day = None
                nxt["repeat_anchor_day"] = item.get("repeat_anchor_day") or original_day
            nxt["due_at"] = next_occurrence(item["repeat"], item.get("due_at"), now=now, anchor_day=nxt.get("repeat_anchor_day"))
            nxt["subtasks"] = [{**p, "id": uuid.uuid4().hex, "done": False} for p in nxt.get("subtasks", [])]
            tasks.append(nxt)
            return nxt["id"]
        return None
    return None


def is_overdue(task: dict, *, now: datetime | None = None) -> bool:
    if task.get("done") or not _valid_datetime(task.get("due_at")):
        return False
    due = datetime.fromisoformat(task["due_at"])
    reference = now or datetime.now().astimezone()
    if due.tzinfo is None:
        due = due.replace(tzinfo=reference.tzinfo)
    return due < reference.astimezone(due.tzinfo)


def overview(tasks: list[dict], sessions: list[dict], *, today: date | None = None) -> dict:
    today = today or date.today()
    starts = [today - timedelta(days=x) for x in range(6, -1, -1)]
    dates = [d.isoformat() for d in starts]
    counts = Counter()
    for task in tasks:
        completed = task.get("completed_at")
        if task.get("done") and _valid_datetime(completed):
            counts[datetime.fromisoformat(completed).astimezone().date().isoformat()] += 1
    def session_date(session):
        try:
            return datetime.fromisoformat(session["ended_at"]).astimezone().date().isoformat()
        except (ValueError, KeyError):
            return ""
    minutes = sum(float(s.get("minutes", 0)) for s in sessions if session_date(s) in dates)
    return {
        "open": sum(not t.get("done") for t in tasks),
        "done": sum(bool(t.get("done")) for t in tasks),
        "done_today": counts.get(today.isoformat(), 0),
        "overdue": sum(is_overdue(t) for t in tasks),
        "focus_minutes_week": int(round(minutes)),
        "weekly": [(d, counts.get(d, 0)) for d in dates],
    }


def export_csv(path: Path, tasks: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "text", "done", "priority", "category", "due_at", "repeat", "notes", "created_at", "completed_at", "subtasks"])
        writer.writeheader()
        for item in tasks:
            writer.writerow({key: json.dumps(item.get(key, []), ensure_ascii=False) if key == "subtasks" else item.get(key, "") for key in writer.fieldnames})


def build_alert_wav(profile: str = "Classic", volume: int = 70) -> bytes:
    """Three clear beep sounds, Windows PCM WAV, independent of network/files."""
    melodies = {"Classic": (784, 988, 784), "Gentle": (523, 659, 784), "Urgent": (880, 1109, 1318)}
    sequence = melodies.get(profile, melodies["Classic"])
    rate = 22050
    pcm = bytearray()
    gain = min(100, max(0, int(volume))) / 100
    for freq in sequence:
        length = int(.18 * rate)
        for i in range(length):
            fade = min(1, i / 220, (length - 1 - i) / 300)
            sample = int(15000 * gain * max(0.0, fade) * math.sin(2 * math.pi * freq * i / rate))
            pcm.extend(struct.pack("<h", sample))
        pcm.extend(b"\x00\x00" * int(.12 * rate))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(bytes(pcm))
    return buffer.getvalue()


def ensure_alert_file(path: Path, profile: str, volume: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_alert_wav(profile, volume))
    return path
