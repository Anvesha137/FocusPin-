"""FocusPin V2 · translucent always-on-top mini note + complete desktop dashboard.
Windows 10/11 • PySide6 • No cloud account.
"""
from __future__ import annotations

import copy
import ctypes
import json
import os
import shutil
import sys
import time
import uuid
from ctypes import wintypes
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QRect, QDateTime, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QBrush, QLinearGradient, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSystemTrayIcon,
    QTabWidget, QVBoxLayout, QWidget,
)

from core import (
    APP_NAME, DEFAULT_SETTINGS, PRIORITIES, REPEAT_OPTIONS, backup_v1_once,
    ensure_alert_file, export_csv, is_overdue, new_task, normalize_task,
    now_iso, overview, read_state, set_completed, storage_path, write_state,
)

STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def asset_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / name


def cursor_position() -> tuple[int, int] | None:
    if sys.platform == "win32":
        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
        p = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(p)):
            return p.x, p.y
        return None
    from PySide6.QtGui import QCursor
    p = QCursor.pos()
    return p.x(), p.y()


def desktop_is_unlocked() -> bool:
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        user32.GetUserObjectInformationW.restype = wintypes.BOOL
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        desk = user32.OpenInputDesktop(0, False, 1)
        if not desk:
            return False
        try:
            buf = ctypes.create_unicode_buffer(256)
            n = wintypes.DWORD()
            if user32.GetUserObjectInformationW(desk, 2, buf, ctypes.sizeof(buf), ctypes.byref(n)):
                return buf.value.lower() == "default"
        finally:
            user32.CloseDesktop(desk)
    except (OSError, AttributeError, ValueError):
        pass
    return True


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    executable = Path(sys.executable)
    silent = executable.with_name("pythonw.exe")
    return f'"{silent if silent.exists() else executable}" "{Path(__file__).resolve()}"'


def has_autostart() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return value == startup_command()
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        raise OSError("Auto-start is supported on Windows only.")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


BASE_STYLE = """
/* FocusPin Blossom Studio · calm editorial planner aesthetic */
QWidget { color: #4B3C42; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
QWidget#dashboard, QDialog#editor, QDialog#preferences { background: #FBF7F4; }
QLabel#brand { font-family: 'Georgia'; font-size: 20px; font-weight: 700; color: #34272D; }
QLabel#section { font-family: 'Georgia'; font-size: 18px; font-weight: 700; color: #34272D; }
QLabel#hero { font-family: 'Georgia'; font-size: 24px; font-weight: 700; color: #2F2629; }
QLabel#muted { color: #8D7D84; font-size: 12px; }
QLabel#eyebrow { color: #B07A85; font-size: 11px; font-weight: 700; text-transform: uppercase; }
QLabel#overdue { color: #B85D67; font-weight: 700; }
QLabel#noteTask { font-size: 13px; color: #47383F; }
QLabel#noteCount { color: #7E6873; font-size: 11px; font-weight: 700; }
QFrame#shell { background: #FEFCFB; border: 1px solid #EFE4E2; border-radius: 26px; }
QFrame#sidebar { background: #F8F1ED; border: 1px solid #EFE4E2; border-radius: 20px; }
QFrame#heroCard, QFrame#card, QFrame#stat, QFrame#focusCard, QFrame#rightCard, QFrame#taskRow, QFrame#softCard {
 background: #FFFCFB; border: 1px solid #EFE4E2; border-radius: 18px; }
QFrame#focusCard { background: #FEF9F7; }
QFrame#chipBar { background: transparent; border: none; }
QPushButton { background: #F7EFEC; color: #6B535E; border: 1px solid #EEDDDC; border-radius: 12px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: #F2E4E2; border-color: #E4CFCE; }
QPushButton:pressed { background: #EAD8D6; }
QPushButton:disabled { color: #B7A9AF; background: #F7F2F1; border-color: #F0E8E6; }
QPushButton#primary { background: #C98B8B; color: #FFFFFF; border: 1px solid #C98B8B; font-weight: 700; }
QPushButton#primary:hover { background: #B87B7B; border-color: #B87B7B; }
QPushButton#ghost { background: transparent; border: none; color: #7E6771; padding: 6px 8px; }
QPushButton#ghost:hover { background: #F3E9E6; border-radius: 10px; }
QPushButton#tiny { padding: 6px 10px; font-size: 12px; }
QPushButton#nav { background: transparent; border: none; text-align: left; padding: 12px 14px; color: #5F4A53; border-radius: 14px; font-weight: 600; }
QPushButton#nav:hover { background: #F5E7E3; }
QPushButton#navActive { background: #F0DAD6; border: 1px solid #E7C8C3; text-align: left; padding: 12px 14px; color: #5B434C; border-radius: 14px; font-weight: 700; }
QPushButton#pill, QPushButton#pillActive { padding: 8px 16px; border-radius: 14px; }
QPushButton#pill { background: #F6F1EF; color: #705C65; border: 1px solid #EEE4E2; }
QPushButton#pillActive { background: #D08F95; color: white; border: 1px solid #D08F95; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateTimeEdit {
 background: #FFFFFF; color: #493D46; border: 1px solid #E9DEDC; border-radius: 12px; padding: 10px 12px;
 selection-background-color: #E7C5CD; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus { border: 1px solid #C98B8B; }
QLineEdit::placeholder { color: #AF9FA5; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #DEC8C5; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTabWidget::pane { border: 0; background: transparent; }
QTabBar::tab { background: #F6F1EF; border: 1px solid #EDE4E2; color: #755E68; padding: 12px 22px; border-radius: 14px; margin-right: 10px; font-weight: 600; }
QTabBar::tab:selected { background: #F0D9D9; border-color: #E4C3C5; color: #573E48; font-weight: 700; }
QCheckBox { spacing: 8px; color: #4C3D44; }
QCheckBox::indicator { width: 18px; height: 18px; }
QProgressBar { background: #F2EAE7; color: #705C6A; border: 0; border-radius: 6px; height: 10px; text-align: center; font-size: 9px; }
QProgressBar::chunk { background: #D9A8B0; border-radius: 6px; }
QMenu { background: #FFFCFB; color: #503D4C; border: 1px solid #EADCE3; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 9px 22px; }
QMenu::item:selected { background: #F4E8EE; color: #53384B; }
QGroupBox { border: 1px solid #EEE1E7; border-radius: 14px; margin-top: 12px; padding: 14px; font-weight: 700; background: #FFFCFB; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QDialogButtonBox QPushButton { min-width: 92px; }
"""


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    return label


def button(text: str, callback, *, primary=False, tiny=False, danger=False) -> QPushButton:
    control = QPushButton(text)
    control.setObjectName("primary" if primary else "danger" if danger else "tiny" if tiny else "")
    control.clicked.connect(callback)
    return control


class GlassPanel(QWidget):
    """Panel remains translucent, but the *whole note* flashes during alerts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.opacity = .88
        self.flash = False
        self.flash_color = "Orange"
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        palette = {"Orange": (245, 145, 77), "Red": (232, 90, 108), "Purple": (166, 112, 210)}
        if self.flash:
            r, g, b = palette.get(self.flash_color, palette["Orange"])
            p.setPen(QPen(QColor(r, g, b, 255), 5))
            p.setBrush(QColor(255, 232, 217, 253) if self.flash_color == "Orange" else
                       QColor(255, 215, 224, 253) if self.flash_color == "Red" else
                       QColor(239, 215, 252, 253))
        else:
            p.setPen(QPen(QColor(217, 194, 204, 155), 1.2))
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            alpha = int(255 * self.opacity)
            grad.setColorAt(0, QColor(255, 252, 251, alpha))
            grad.setColorAt(1, QColor(250, 238, 244, alpha))
            p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, 22, 22)
        p.end()


class DragArea(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.origin = e.globalPosition().toPoint() - self.window().pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self.origin is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self.origin)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.origin is not None:
            self.origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if hasattr(self.window(), "save_position"):
                self.window().save_position()


class TaskEditor(QDialog):
    """Pinteresty modal editor that mirrors the approved mockups."""
    def __init__(self, parent, task: dict | None = None):
        super().__init__(parent)
        self.original = task
        self.setObjectName("editor")
        self.setWindowTitle("Edit task · FocusPin" if task else "Add task · FocusPin")
        self.resize(640, 620)
        self.setStyleSheet(BASE_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        shell = QFrame(); shell.setObjectName("shell")
        root_shell = QVBoxLayout(shell)
        root_shell.setContentsMargins(26, 24, 26, 24)
        root_shell.setSpacing(16)
        root.addWidget(shell)

        top = QHBoxLayout()
        icon = QLabel("✿")
        icon.setStyleSheet("font-size: 26px; color: #B97883;")
        top.addWidget(icon)
        title_box = QVBoxLayout()
        title = QLabel("Add Task" if task is None else "Edit Task")
        title.setObjectName("section")
        subtitle = muted("Turn your plans into progress. ♡")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top.addLayout(title_box)
        top.addStretch()
        close_btn = button("×", self.reject, tiny=True)
        close_btn.setObjectName("ghost")
        top.addWidget(close_btn)
        root_shell.addLayout(top)

        self.title = QLineEdit(task.get("text", "") if task else "")
        self.title.setPlaceholderText("e.g. Finish marketing presentation")
        title_label = QLabel("Task title *")
        root_shell.addWidget(title_label)
        root_shell.addWidget(self.title)

        row = QHBoxLayout()
        col1 = QVBoxLayout(); col2 = QVBoxLayout()
        self.priority = QComboBox(); self.priority.addItems(PRIORITIES)
        self.priority.setCurrentText(task.get("priority", "Medium") if task else "Medium")
        col1.addWidget(QLabel("Priority"))
        col1.addWidget(self.priority)
        self.category = QComboBox(); self.category.setEditable(True)
        model = getattr(parent, "app", parent)
        names = sorted({"Work", "Study", "Personal", "Content", "General"} | {x.get("category", "General") for x in model.tasks})
        self.category.addItems(names)
        self.category.setCurrentText(task.get("category", "General") if task else "General")
        col2.addWidget(QLabel("Category"))
        col2.addWidget(self.category)
        row.addLayout(col1, 1); row.addSpacing(10); row.addLayout(col2, 1)
        root_shell.addLayout(row)

        self.details_toggle = QPushButton("More details  ⌄")
        self.details_toggle.setObjectName("ghost")
        self.details_toggle.setCheckable(True)
        root_shell.addWidget(self.details_toggle)

        self.details_panel = QFrame(); self.details_panel.setObjectName("softCard")
        details_wrap = QVBoxLayout(self.details_panel)
        details_wrap.setContentsMargins(16, 16, 16, 16)
        details_wrap.setSpacing(12)
        root_shell.addWidget(self.details_panel)

        show_details = bool(task and (task.get("due_at") or task.get("notes") or task.get("subtasks") or task.get("repeat", "None") != "None"))
        self.details_toggle.setChecked(show_details)
        self.details_panel.setVisible(show_details)
        self.details_toggle.setText("Less details  ⌃" if show_details else "More details  ⌄")
        def toggle_details(opened):
            self.details_panel.setVisible(opened)
            self.details_toggle.setText("Less details  ⌃" if opened else "More details  ⌄")
        self.details_toggle.toggled.connect(toggle_details)

        self.has_due = QCheckBox("Deadline")
        self.has_due.setChecked(bool(task and task.get("due_at")))
        details_wrap.addWidget(self.has_due)
        self.due = QDateTimeEdit(); self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("ddd, dd MMM yyyy  h:mm AP")
        if task and task.get("due_at"):
            try:
                dt = datetime.fromisoformat(task["due_at"])
                self.due.setDateTime(QDateTime(dt))
            except (ValueError, TypeError):
                self.due.setDateTime(QDateTime.currentDateTime().addDays(1))
        else:
            self.due.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.due.setEnabled(self.has_due.isChecked())
        self.has_due.toggled.connect(self.due.setEnabled)
        details_wrap.addWidget(self.due)

        self.repeat = QComboBox(); self.repeat.addItems(REPEAT_OPTIONS)
        self.repeat.setCurrentText(task.get("repeat", "None") if task else "None")
        details_wrap.addWidget(QLabel("Repeat"))
        details_wrap.addWidget(self.repeat)

        self.notes = QPlainTextEdit(task.get("notes", "") if task else "")
        self.notes.setMaximumHeight(90)
        self.notes.setPlaceholderText("Add a note")
        details_wrap.addWidget(QLabel("Notes"))
        details_wrap.addWidget(self.notes)

        details_wrap.addWidget(QLabel("Subtasks"))
        self.part_box = QWidget()
        self.part_layout = QVBoxLayout(self.part_box)
        self.part_layout.setContentsMargins(0, 0, 0, 0)
        self.part_layout.setSpacing(6)
        self.part_rows = []
        for p in (task.get("subtasks", []) if task else []):
            self.add_subtask(p)
        details_wrap.addWidget(self.part_box)
        details_wrap.addWidget(button("+ Add subtask", lambda: self.add_subtask()))

        action_row = QHBoxLayout()
        delete_btn = button("Delete", self._delete_self, danger=True)
        delete_btn.setVisible(bool(task))
        action_row.addWidget(delete_btn)
        action_row.addStretch()
        cancel = button("Cancel", self.reject)
        save = button("Save Task", self.validate, primary=True)
        action_row.addWidget(cancel)
        action_row.addWidget(save)
        root_shell.addLayout(action_row)
        self.title.setFocus()

    def _delete_self(self):
        self._delete_requested = True
        self.accept()

    def add_subtask(self, sub: dict | None = None):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        check = QCheckBox(); check.setChecked(bool(sub and sub.get("done")))
        edit = QLineEdit(sub.get("text", "") if sub else "")
        edit.setPlaceholderText("A smaller step…")
        lay.addWidget(check)
        lay.addWidget(edit, 1)
        remove = button("×", lambda: self.remove_subtask(row), tiny=True)
        remove.setObjectName("ghost")
        lay.addWidget(remove)
        self.part_rows.append((row, check, edit, sub.get("id") if sub else None))
        self.part_layout.addWidget(row)

    def remove_subtask(self, row):
        self.part_rows = [p for p in self.part_rows if p[0] is not row]
        row.setParent(None)
        row.deleteLater()

    def validate(self):
        if not self.title.text().strip():
            QMessageBox.warning(self, "Task title required", "Please write a task title.")
            self.title.setFocus(); return
        self.accept()

    def result_task(self) -> dict:
        data = copy.deepcopy(self.original) if self.original else new_task(self.title.text().strip())
        data["text"] = self.title.text().strip()[:600]
        data["priority"] = self.priority.currentText()
        data["category"] = (self.category.currentText().strip() or "General")[:60]
        due = self.due.dateTime().toPython()
        if due.tzinfo is None:
            due = due.astimezone()
        data["due_at"] = due.isoformat(timespec="minutes") if self.has_due.isChecked() else None
        data["repeat"] = self.repeat.currentText()
        data["notes"] = self.notes.toPlainText()[:4000]
        data["subtasks"] = [
            {"id": sid or uuid.uuid4().hex, "text": edit.text().strip()[:300], "done": check.isChecked()}
            for (_, check, edit, sid) in self.part_rows if edit.text().strip()
        ]
        return data


class Preferences(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.app = parent.app if hasattr(parent, "app") else parent
        cfg = self.app.settings
        self.setWindowTitle("Reminder & Focus Controls · FocusPin")
        self.setObjectName("preferences")
        self.resize(620, 760)
        self.setStyleSheet(BASE_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        shell = QFrame(); shell.setObjectName("shell")
        root.addWidget(shell)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        top = QHBoxLayout()
        dot = QLabel("◎"); dot.setStyleSheet("font-size: 24px; color: #C97F88;")
        top.addWidget(dot)
        heading_box = QVBoxLayout()
        title = QLabel("Reminder & Focus Controls")
        title.setObjectName("section")
        heading_box.addWidget(title)
        heading_box.addWidget(muted("Stay present, stay in flow. ♡"))
        top.addLayout(heading_box)
        top.addStretch()
        top.addWidget(button("×", self.reject, tiny=True))
        layout.addLayout(top)

        chips = QHBoxLayout()
        for text_chip, active in (("Focus Timer", True), ("Idle Reminders", False), ("Sounds", False), ("Blink Style", False)):
            b = QPushButton(text_chip)
            b.setObjectName("pillActive" if active else "pill")
            chips.addWidget(b)
        chips.addStretch()
        layout.addLayout(chips)

        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(14)
        layout.addLayout(grid)

        def section_card(title_text, subtitle_text=None):
            frame = QFrame(); frame.setObjectName("card")
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(16, 16, 16, 16)
            inner.setSpacing(10)
            title = QLabel(title_text); title.setObjectName("noteHeading")
            inner.addWidget(title)
            if subtitle_text:
                inner.addWidget(muted(subtitle_text))
            return frame, inner

        timer_card, timer_layout = section_card("Focus Timer Presets", "Choose a duration or set your own.")
        row = QHBoxLayout()
        self.focus_minutes = QSpinBox(); self.focus_minutes.setRange(1, 180); self.focus_minutes.setValue(cfg["focus_minutes"]); self.focus_minutes.setSuffix(" minutes")
        row.addWidget(self.focus_minutes)
        test_focus = button("Start focus", lambda: self.app.start_focus(), primary=True)
        row.addWidget(test_focus)
        timer_layout.addLayout(row)
        grid.addWidget(timer_card, 0, 0, 1, 2)

        remind_card, remind_layout = section_card("Idle Reminder", "Get a gentle reminder when you've been inactive.")
        self.idle = QSpinBox(); self.idle.setRange(1, 240); self.idle.setValue(cfg["idle_minutes"]); self.idle.setSuffix(" minutes")
        self.snooze = QSpinBox(); self.snooze.setRange(1, 120); self.snooze.setValue(cfg["snooze_minutes"]); self.snooze.setSuffix(" minutes")
        self.muted = QCheckBox("Mute all automatic reminders"); self.muted.setChecked(cfg["mute_reminders"])
        remind_layout.addWidget(QLabel("Remind me after")); remind_layout.addWidget(self.idle)
        remind_layout.addWidget(QLabel("Snooze duration")); remind_layout.addWidget(self.snooze)
        remind_layout.addWidget(self.muted)
        grid.addWidget(remind_card, 1, 0)

        sound_card, sound_layout = section_card("Audible Beep Style", "Choose a sound to play with the reminder.")
        self.sound = QCheckBox("Play beep-beep-beep with reminder"); self.sound.setChecked(cfg["sound_enabled"])
        self.profile = QComboBox(); self.profile.addItems(["Classic", "Gentle", "Urgent"]); self.profile.setCurrentText(cfg["sound_profile"])
        self.volume = QSpinBox(); self.volume.setRange(0,100); self.volume.setValue(cfg["volume"]); self.volume.setSuffix("%")
        self.interval = QSpinBox(); self.interval.setRange(3,300); self.interval.setValue(cfg["beep_interval"]); self.interval.setSuffix(" sec")
        sound_layout.addWidget(self.sound)
        sound_layout.addWidget(QLabel("Sound style")); sound_layout.addWidget(self.profile)
        sound_layout.addWidget(QLabel("Volume")); sound_layout.addWidget(self.volume)
        sound_layout.addWidget(QLabel("Repeat interval")); sound_layout.addWidget(self.interval)
        grid.addWidget(sound_card, 1, 1)

        blink_card, blink_layout = section_card("Blink Style", "Choose how the screen note blinks.")
        self.color = QComboBox(); self.color.addItems(["Orange", "Red", "Purple"]); self.color.setCurrentText(cfg["flash_color"])
        self.flash_speed = QSpinBox(); self.flash_speed.setRange(200, 2000); self.flash_speed.setValue(cfg["flash_interval_ms"]); self.flash_speed.setSuffix(" ms")
        blink_layout.addWidget(QLabel("Blink color")); blink_layout.addWidget(self.color)
        blink_layout.addWidget(QLabel("Flash speed")); blink_layout.addWidget(self.flash_speed)
        grid.addWidget(blink_card, 2, 0)

        app_card, app_layout = section_card("Appearance & System", "Launch and keyboard shortcuts.")
        self.opacity = QSpinBox(); self.opacity.setRange(45,100); self.opacity.setValue(round(cfg["opacity"] * 100)); self.opacity.setSuffix("% visible")
        self.startup = QCheckBox("Start with Windows")
        self.startup.setChecked(has_autostart() if sys.platform == 'win32' else False)
        app_layout.addWidget(QLabel("Window transparency")); app_layout.addWidget(self.opacity)
        self.click_hint = QLabel("Shortcuts: Ctrl + Alt + F → show/unlock  ·  Ctrl + Alt + T → quick add")
        self.click_hint.setWordWrap(True)
        app_layout.addWidget(self.click_hint)
        if sys.platform == 'win32':
            app_layout.addWidget(self.startup)
        grid.addWidget(app_card, 2, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(button("Test Reminder", self.test))
        bottom.addStretch()
        bottom.addWidget(button("Cancel", self.reject))
        bottom.addWidget(button("Save", self.save, primary=True))
        layout.addLayout(bottom)

    def save(self):
        cfg = self.app.settings
        cfg.update({
            "idle_minutes": self.idle.value(),
            "snooze_minutes": self.snooze.value(),
            "beep_interval": self.interval.value(),
            "volume": self.volume.value(),
            "sound_profile": self.profile.currentText(),
            "flash_color": self.color.currentText(),
            "flash_interval_ms": self.flash_speed.value(),
            "opacity": self.opacity.value() / 100,
            "sound_enabled": self.sound.isChecked(),
            "mute_reminders": self.muted.isChecked(),
            "focus_minutes": self.focus_minutes.value(),
        })
        if sys.platform == 'win32':
            try:
                set_autostart(self.startup.isChecked())
            except OSError:
                pass
        self.app.apply_preferences()
        self.accept()

    def test(self):
        self.save()
        self.app.test_alarm()


class WeeklyGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.values = []
        self.setMinimumHeight(120)

    def set_values(self, values):
        self.values = list(values)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width() / 7
        peak = max(1, *(count for _, count in self.values))
        for i, (d, count) in enumerate(self.values):
            h = 76 * count / peak
            left = i * w + w * .21
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#CEAAC2") if count else QColor("#EEE4E9"))
            p.drawRoundedRect(QRect(int(left), int(80 - h), int(w * .57), int(max(4, h))), 5, 5)
            p.setPen(QColor("#9B8D98"))
            p.drawText(QRect(int(i * w), 86, int(w), 23), Qt.AlignmentFlag.AlignCenter, d[-5:])
        p.end()


class Dashboard(QWidget):
    """Expanded aesthetic dashboard matching the approved UI direction."""
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("dashboard")
        self.setWindowTitle("FocusPin · Dashboard")
        self.setWindowIcon(app.app_icon)
        self.resize(1280, 860)
        self.setMinimumSize(980, 700)
        self.setStyleSheet(BASE_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        shell = QFrame(); shell.setObjectName("shell")
        outer_shell = QHBoxLayout(shell)
        outer_shell.setContentsMargins(18, 18, 18, 18)
        outer_shell.setSpacing(16)
        outer.addWidget(shell)

        # Sidebar
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(150)
        s = QVBoxLayout(sidebar); s.setContentsMargins(12, 14, 12, 14); s.setSpacing(10)
        brand = QLabel("FocusPin"); brand.setObjectName("brand")
        s.addWidget(brand)
        def nav_btn(text, active=False, cb=None):
            b = QPushButton(text)
            b.setObjectName("navActive" if active else "nav")
            if cb:
                b.clicked.connect(cb)
            return b
        s.addSpacing(6)
        s.addWidget(nav_btn("⌂  Home", True))
        s.addWidget(nav_btn("☑  Tasks"))
        s.addWidget(nav_btn("◔  Focus", False, self.start_focus))
        s.addWidget(nav_btn("☰  Planner"))
        s.addWidget(nav_btn("▥  Stats", False, self.open_stats))
        s.addWidget(nav_btn("⚙  Settings", False, self.open_settings))
        s.addStretch()
        mini_quote = QFrame(); mini_quote.setObjectName("card")
        mq = QVBoxLayout(mini_quote); mq.setContentsMargins(14, 14, 14, 14)
        mq.addWidget(QLabel("A calmer,\nmore focused\nyou. ♡"))
        mq.addStretch()
        s.addWidget(mini_quote)
        outer_shell.addWidget(sidebar)

        # Main center column
        center = QVBoxLayout(); center.setSpacing(14)
        outer_shell.addLayout(center, 1)

        hero = QFrame(); hero.setObjectName("heroCard")
        h = QHBoxLayout(hero); h.setContentsMargins(22, 18, 22, 18)
        left = QVBoxLayout(); left.setSpacing(4)
        eye = QLabel("☼")
        eye.setStyleSheet("font-size: 22px; color: #D88979;")
        left.addWidget(eye, 0, Qt.AlignmentFlag.AlignLeft)
        greeting = QLabel("Good morning")
        greeting.setObjectName("hero")
        left.addWidget(greeting)
        left.addWidget(muted("Small steps today, big things tomorrow. ♡"))
        h.addLayout(left)
        h.addStretch()
        date_box = QVBoxLayout()
        date_box.addWidget(QLabel(datetime.now().strftime("%a, %b %d, %Y")), 0, Qt.AlignmentFlag.AlignRight)
        quote = muted("“Focus on progress,\nnot perfection.”")
        quote.setAlignment(Qt.AlignmentFlag.AlignRight)
        date_box.addWidget(quote)
        h.addLayout(date_box)
        center.addWidget(hero)

        middle = QHBoxLayout(); middle.setSpacing(16)
        center.addLayout(middle, 1)

        # left large card with tasks
        task_card = QFrame(); task_card.setObjectName("card")
        tc = QVBoxLayout(task_card); tc.setContentsMargins(16, 16, 16, 16); tc.setSpacing(12)
        top_tabs = QHBoxLayout()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.list_views = []
        for _ in range(2):
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            container = QWidget(); lay = QVBoxLayout(container); lay.setSpacing(10); lay.setContentsMargins(2, 7, 4, 7)
            scroll.setWidget(container); self.list_views.append((scroll, container, lay))
        self.tabs.addTab(self.list_views[0][0], "To do")
        self.tabs.addTab(self.list_views[1][0], "Done")
        top_tabs.addWidget(self.tabs, 1)
        right_buttons = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search tasks..."); self.search.textChanged.connect(self.render)
        self.search.setMaximumWidth(220)
        right_buttons.addWidget(self.search)
        new_btn = button("+", self.new_task, primary=True)
        new_btn.setFixedWidth(42)
        right_buttons.addWidget(new_btn)
        top_tabs.addLayout(right_buttons)
        tc.addLayout(top_tabs)

        filter_row = QHBoxLayout(); filter_row.setSpacing(8)
        self.category = QComboBox(); self.category.currentTextChanged.connect(self.render)
        self.priority = QComboBox(); self.priority.addItems(["All priorities", *PRIORITIES]); self.priority.currentTextChanged.connect(self.render)
        filter_row.addWidget(self.category)
        filter_row.addWidget(self.priority)
        filter_row.addStretch()
        tc.addLayout(filter_row)
        tc.addWidget(self.tabs, 1)
        middle.addWidget(task_card, 3)

        # right rail
        right = QVBoxLayout(); right.setSpacing(14)
        middle.addLayout(right, 1)

        focus_frame = QFrame(); focus_frame.setObjectName("focusCard")
        f = QVBoxLayout(focus_frame); f.setContentsMargins(18, 16, 18, 16); f.setSpacing(10)
        title_row = QHBoxLayout(); title_row.addWidget(QLabel("◎  Focus Mode")); title_row.addStretch(); title_row.addWidget(button("···", self.open_settings, tiny=True))
        f.addLayout(title_row)
        mode_row = QHBoxLayout()
        for txt, active in (("Pomodoro", True), ("Deep Work", False), ("Custom", False)):
            b = QPushButton(txt); b.setObjectName("pillActive" if active else "pill"); mode_row.addWidget(b)
        f.addLayout(mode_row)
        self.focus_ring = QLabel("25:00")
        self.focus_ring.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_ring.setStyleSheet("font-family: Georgia; font-size: 36px; color: #2F2629; padding: 18px; background: #FFF8F6; border: 6px solid #D7A0A0; border-radius: 94px;")
        self.focus_ring.setFixedSize(190, 190)
        f.addWidget(self.focus_ring, 0, Qt.AlignmentFlag.AlignCenter)
        self.focus_label = muted("Focus time")
        self.focus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f.addWidget(self.focus_label)
        self.duration = QSpinBox(); self.duration.setRange(1,180); self.duration.setSuffix(" min"); self.duration.setValue(app.settings["focus_minutes"]); self.duration.valueChanged.connect(self._duration_changed)
        f.addWidget(self.duration)
        self.focus_start = button("Start Focus", self.start_focus, primary=True)
        self.focus_pause = button("Pause", app.pause_focus)
        self.focus_end = button("End Focus", app.exit_focus)
        f.addWidget(self.focus_start)
        control_row = QHBoxLayout(); control_row.addWidget(self.focus_pause); control_row.addWidget(self.focus_end)
        f.addLayout(control_row)
        right.addWidget(focus_frame)

        check_card = QFrame(); check_card.setObjectName("rightCard")
        rc = QVBoxLayout(check_card); rc.setContentsMargins(16, 16, 16, 16); rc.setSpacing(8)
        head = QHBoxLayout(); head.addWidget(QLabel("◎  Today's focus")); head.addStretch(); head.addWidget(button("···", self.open_stats, tiny=True))
        rc.addLayout(head)
        for line in ("Be present", "Do what matters most", "Take breaks", "Proud of your progress"):
            cb = QCheckBox(line)
            rc.addWidget(cb)
        right.addWidget(check_card)
        right.addStretch()

        # bottom stats cards
        stats = QHBoxLayout(); stats.setSpacing(12)
        self.stat_labels = {}
        for key, title in (("open", "Remaining"), ("done", "Completed"), ("focus_minutes_week", "Focus time")):
            frame = QFrame(); frame.setObjectName("stat")
            frame_layout = QVBoxLayout(frame); frame_layout.setContentsMargins(18, 14, 18, 14); frame_layout.setSpacing(5)
            frame_layout.addWidget(QLabel(title))
            number = QLabel("0")
            number.setStyleSheet("font-family: Georgia; font-size: 22px; color: #382B31;")
            frame_layout.addWidget(number)
            frame_layout.addWidget(muted("Keep going ♡" if key == 'open' else "Small wins matter ✨" if key == 'done' else "Deep work adds up."))
            self.stat_labels[key] = number
            stats.addWidget(frame, 1)
        center.addLayout(stats)

        foot = QHBoxLayout()
        foot.addWidget(button("↶ Undo", app.undo, tiny=True))
        foot.addWidget(button("Save backup", app.export_backup, tiny=True))
        foot.addWidget(button("Export CSV", app.export_csv, tiny=True))
        foot.addWidget(button("Import backup", app.import_backup, tiny=True))
        foot.addStretch()
        foot.addWidget(button("Mini view", self.collapse, tiny=True))
        center.addLayout(foot)

        QShortcut(QKeySequence("Ctrl+Z"), self, activated=app.undo)
        self._sync_categories()
        self.render()

    def _duration_changed(self, value):
        self.app.settings["focus_minutes"] = value
        self.app.save()

    def _sync_categories(self):
        previous = self.category.currentText()
        available = ["All categories", *sorted({t.get("category", "General") for t in self.app.tasks})]
        self.category.blockSignals(True)
        self.category.clear(); self.category.addItems(available)
        self.category.setCurrentText(previous if previous in available else "All categories")
        self.category.blockSignals(False)

    def render(self, *args):
        self._sync_categories()
        counts = overview(self.app.tasks, self.app.sessions)
        for name, widget in self.stat_labels.items():
            widget.setText(str(counts[name]))
        self.tabs.setTabText(0, f"To do  {counts['open']}")
        self.tabs.setTabText(1, f"Done  {counts['done']}")
        text = self.search.text().strip().casefold()
        category = self.category.currentText()
        priority = self.priority.currentText()
        for done, (_, container, lay) in ((False, self.list_views[0]), (True, self.list_views[1])):
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w: w.deleteLater()
            matching = [t for t in self.app.tasks if t.get("done") == done and
                (category == "All categories" or t.get("category") == category) and
                (priority == "All priorities" or t.get("priority") == priority) and
                (not text or text in (t["text"] + " " + t.get("notes", "") + " " + " ".join(x["text"] for x in t.get("subtasks", []))).casefold())]
            matching.sort(key=self.app.sort_key)
            if not matching:
                label = muted("A clean slate. Your wins will show up here ♡" if done else "All caught up. Add one little thing to keep it in sight ✿")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(label)
            for task in matching[:150]:
                lay.addWidget(self.make_card(task))
            lay.addStretch()
        self.refresh_timer_label()

    def make_card(self, task: dict) -> QFrame:
        frame = QFrame(); frame.setObjectName("taskRow")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 14, 12, 14)
        layout.setSpacing(12)
        mark = QCheckBox(); mark.setChecked(task["done"])
        mark.toggled.connect(lambda value, ident=task["id"]: self.app.complete(ident, value))
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        stack = QVBoxLayout(); stack.setSpacing(4)
        heading = QLabel(task["text"]); heading.setWordWrap(True)
        heading.setStyleSheet("font-weight: 700; font-size: 15px; color: #2F2629;" if not task["done"] else "font-weight: 700; font-size: 15px; color: #A79AA0; text-decoration: line-through;")
        stack.addWidget(heading)
        parts = task.get("subtasks", [])
        fragments = []
        pr = task.get("priority", "Medium")
        fragments.append(f"Priority: {pr}")
        fragments.append(task.get("category", "General"))
        if task.get("due_at"):
            try:
                due = datetime.fromisoformat(task["due_at"]).astimezone().strftime("%b %d")
                fragments.append(("Today" if is_overdue(task) else due))
            except ValueError:
                pass
        if task.get("repeat") != "None": fragments.append("↻ " + task["repeat"])
        meta = muted("   ·   ".join(fragments))
        if is_overdue(task): meta.setObjectName("overdue")
        stack.addWidget(meta)
        if parts:
            completed = sum(bool(x["done"]) for x in parts)
            prog = QProgressBar(); prog.setValue(int(completed / len(parts) * 100)); prog.setFormat(f"{completed}/{len(parts)} subtasks"); prog.setFixedHeight(12)
            stack.addWidget(prog)
        layout.addLayout(stack, 1)
        if not task["done"]:
            focus_button = button("Focus", lambda checked=False, ident=task["id"]: self.app.focus_on(ident), tiny=True)
            layout.addWidget(focus_button, 0, Qt.AlignmentFlag.AlignTop)
        more = QPushButton("···"); more.setObjectName("ghost"); more.setFixedWidth(36)
        def open_actions():
            menu = QMenu(more)
            menu.addAction("Edit task", lambda checked=False, ident=task["id"]: self.app.edit_task(ident))
            if task["done"]:
                menu.addAction("Move to To do", lambda checked=False, ident=task["id"]: self.app.complete(ident, False))
            menu.addSeparator()
            menu.addAction("Delete task", lambda checked=False, ident=task["id"]: self.app.delete_task(ident))
            menu.exec(more.mapToGlobal(QPoint(0, more.height())))
        more.clicked.connect(open_actions)
        layout.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        return frame

    def refresh_timer_label(self):
        app = self.app
        task = app.get_task(app.focus_target_id)
        if task:
            left = max(0, int(app.focus_remaining + .99))
            self.focus_ring.setText(f"{left//60:02d}:{left%60:02d}")
            self.focus_label.setText(task['text'][:50])
        else:
            self.focus_ring.setText(f"{self.duration.value():02d}:00")
            self.focus_label.setText("Focus time")
        self.focus_pause.setEnabled(bool(task and app.focus_running))
        self.focus_start.setEnabled(bool(task))
        self.focus_end.setEnabled(bool(task))

    def start_focus(self): self.app.start_focus()
    def new_task(self): self.app.edit_task()
    def open_settings(self): Preferences(self).exec()
    def open_stats(self):
        dialog = QDialog(self); dialog.setObjectName("preferences"); dialog.setStyleSheet(BASE_STYLE); dialog.resize(530, 300)
        lay = QVBoxLayout(dialog)
        result = overview(self.app.tasks, self.app.sessions)
        lay.addWidget(QLabel(f"{result['done_today']} tasks checked off today  ·  {result['focus_minutes_week']} min of focus this week"))
        graph = WeeklyGraph(); graph.set_values(result["weekly"])
        lay.addWidget(graph)
        lay.addWidget(muted("Bars show completed tasks. Focus time counts finished sessions only."))
        lay.addWidget(button("Close", dialog.accept))
        dialog.exec()
    def collapse(self): self.hide(); self.app.show_note()
    def closeEvent(self, event): event.ignore(); self.collapse()


class FocusPin(QWidget):
    """Always-visible miniature overlay and controller for all app state."""
    def __init__(self):
        super().__init__()
        self.state_file = storage_path()
        if self.state_file.exists():
            try:
                json.loads(self.state_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                # Retain a damaged original rather than silently destroying it on boot.
                try:
                    rescue = self.state_file.with_name("state.unreadable.backup.json")
                    if not rescue.exists():
                        shutil.copy2(self.state_file, rescue)
                except OSError:
                    pass
        backup_v1_once(self.state_file)
        self.tasks, self.settings, self.sessions = read_state(self.state_file)
        # Avoid the V1 trap: never boot straight into a non-clickable overlay.
        self.settings["click_through"] = False
        self.undo_stack: list[tuple[list[dict], list[dict]]] = []
        self.focus_target_id: str | None = None
        self.focus_remaining = float(self.settings["focus_minutes"] * 60)
        self.active_focus_duration = self.settings["focus_minutes"]
        self.focus_running = False
        self.focus_last_tick = time.monotonic()
        self._snooze_until = 0.0
        self._test_until = 0.0
        self._alerting = False
        self._flash_on = False
        self._last_mouse = cursor_position()
        self._last_move = time.monotonic()
        self._last_poll = time.monotonic()
        self._locked = False
        self._session_notifications_registered = False
        self._hotkeys: list[int] = []
        self._position_ready = False
        self._click_timeout = 0.0
        self.app_icon = QIcon(str(asset_path("focuspin.ico")))

        self.setWindowTitle("focuspin. | mini note")
        self.setWindowIcon(self.app_icon)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setFixedWidth(348)
        self.setStyleSheet(BASE_STYLE)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.surface = GlassPanel(self)
        self.surface.opacity = self.settings["opacity"]
        self.surface.flash_color = self.settings["flash_color"]
        outer.addWidget(self.surface)
        self.inner = QVBoxLayout(self.surface)
        self.inner.setContentsMargins(20, 18, 20, 17)
        self.inner.setSpacing(12)

        head = DragArea(self.surface)
        bar = QHBoxLayout(head); bar.setContentsMargins(0,0,0,0)
        title = QLabel("focuspin."); title.setObjectName("brand")
        bar.addWidget(title); bar.addStretch()
        self.open_count = QLabel("0 to do"); self.open_count.setObjectName("noteCount")
        bar.addWidget(self.open_count)
        bar.addWidget(button("↗", self.open_dashboard, tiny=True))
        bar.addWidget(button("···", self.open_menu, tiny=True))
        self.inner.addWidget(head)
        self.alert_banner = QLabel("◉  a little reminder...")
        self.alert_banner.setStyleSheet("color: #9B4056; font-weight: 800; padding: 3px 0;")
        self.alert_banner.hide()
        self.inner.addWidget(self.alert_banner)
        self.mini_status = muted("one little thing at a time ♡")
        self.inner.addWidget(self.mini_status)
        self.items = QWidget()
        self.items_layout = QVBoxLayout(self.items)
        self.items_layout.setSpacing(8)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.inner.addWidget(self.items)
        addrow = QHBoxLayout()
        self.quick = QLineEdit(); self.quick.setPlaceholderText("write something to do...")
        self.quick.returnPressed.connect(self.quick_add)
        addrow.addWidget(self.quick, 1)
        addrow.addWidget(button("+", self.quick_add, primary=True))
        self.inner.addLayout(addrow)
        foot = QHBoxLayout()
        self.footer = muted("♡  right here with you")
        foot.addWidget(self.footer)
        foot.addStretch()
        foot.addWidget(button("⌂", self.reset_corner, tiny=True))
        self.inner.addLayout(foot)
        self.dashboard: Dashboard | None = None
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip("FocusPin V2 · Ctrl+Alt+F to show/unlock")
        self.tray.activated.connect(self.tray_clicked)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.tray.setContextMenu(self.build_menu())

        self.flash_timer = QTimer(self)
        self.flash_timer.setInterval(self.settings["flash_interval_ms"])
        self.flash_timer.timeout.connect(self.flip_flash)
        self.sound_timer = QTimer(self)
        self.sound_timer.setInterval(self.settings["beep_interval"] * 1000)
        self.sound_timer.timeout.connect(self.play_beep)
        self.loop_timer = QTimer(self)
        self.loop_timer.setInterval(1000)
        self.loop_timer.timeout.connect(self.tick)
        self.loop_timer.start()
        self.render_mini()
        QTimer.singleShot(0, self.position_initially)
        QTimer.singleShot(150, self.register_windows_notifications)
        QTimer.singleShot(200, self.register_hotkeys)
        self.save()

    def save(self):
        try:
            write_state(self.state_file, self.tasks, self.settings, self.sessions)
        except OSError as ex:
            self.footer.setText("⚠ Save failed")
            self.footer.setToolTip(str(ex))

    def snapshot(self):
        self.undo_stack.append((copy.deepcopy(self.tasks), copy.deepcopy(self.sessions)))
        self.undo_stack = self.undo_stack[-30:]

    def undo(self):
        if not self.undo_stack:
            QMessageBox.information(self.dashboard or self, "Nothing to undo", "There are no recent task changes to undo.")
            return
        self.tasks, self.sessions = self.undo_stack.pop()
        self.save()
        self.refresh()

    def get_task(self, task_id):
        return next((t for t in self.tasks if t["id"] == task_id), None)

    @staticmethod
    def sort_key(task):
        priority = {"High": 0, "Medium": 1, "Low": 2}.get(task.get("priority"), 1)
        due = task.get("due_at") or "9999"
        return (task.get("done", False), priority, due, task.get("created_at", ""))

    def refresh(self):
        self.render_mini()
        if self.dashboard:
            self.dashboard.render()
        self.tray.setContextMenu(self.build_menu())
        if not any(not t["done"] for t in self.tasks) and not self._test_until:
            self.stop_alarm()

    def render_mini(self):
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        pending = sorted((t for t in self.tasks if not t["done"]), key=self.sort_key)
        target = self.get_task(self.focus_target_id)
        display = [target] if target and not target["done"] else pending[:3]
        self.open_count.setText(f"{len(pending)} to do")
        if not pending:
            self.mini_status.setText("you did it. enjoy the moment ✿")
            self.items_layout.addWidget(muted("nothing on your list yet ♡"))
        elif target and not target["done"]:
            label = f"☕  focus time  ·  {int(self.focus_remaining//60):02d}:{int(self.focus_remaining%60):02d}"
            self.mini_status.setText(label)
        else:
            self.mini_status.setText("today, at your own pace.")
        for task in display:
            line = QWidget()
            box = QHBoxLayout(line); box.setContentsMargins(0, 2, 0, 2); box.setSpacing(10)
            tick = QCheckBox(); tick.toggled.connect(lambda checked, tid=task["id"]: self.complete(tid, checked))
            box.addWidget(tick, 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel(task["text"])
            label.setObjectName("noteTask")
            label.setWordWrap(True)
            label.setToolTip("Open the dashboard to edit details")
            box.addWidget(label, 1)
            if task.get("priority") == "High":
                flag = QLabel("●"); flag.setStyleSheet("color: #BE778B; font-size: 11px;")
                box.addWidget(flag)
            if is_overdue(task):
                late = QLabel("!"); late.setToolTip("Overdue")
                late.setStyleSheet("color: #BB6874; font-weight: bold;")
                box.addWidget(late)
            self.items_layout.addWidget(line)
        if len(pending) > len(display):
            self.items_layout.addWidget(button(f"and {len(pending)-len(display)} more  ↗", self.open_dashboard, tiny=True))
        self.inner.activate()
        self.setFixedHeight(max(232, min(520, self.inner.sizeHint().height() + 12)))
        if self._position_ready:
            self.keep_on_screen()

    def quick_add(self):
        text = self.quick.text().strip()
        if not text:
            return
        self.snapshot()
        self.tasks.append(new_task(text))
        self.quick.clear()
        self.save(); self.refresh()

    def edit_task(self, task_id=None):
        original = self.get_task(task_id) if task_id else None
        dialog = TaskEditor(self.dashboard or self, original)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result_task()
            self.snapshot()
            if original:
                index = next(i for i, x in enumerate(self.tasks) if x["id"] == original["id"])
                self.tasks[index] = result
            else:
                self.tasks.append(result)
            self.save(); self.refresh()

    def complete(self, task_id: str, done: bool):
        task = self.get_task(task_id)
        if not task or task["done"] == done:
            return
        self.snapshot()
        set_completed(self.tasks, task_id, done)
        if done and task_id == self.focus_target_id:
            self.exit_focus()
        self.save(); self.refresh()

    def delete_task(self, task_id: str):
        task = self.get_task(task_id)
        if not task: return
        parent = self.dashboard or self
        if QMessageBox.question(parent, "Delete task?", f"Delete '{task['text'][:80]}'?\nYou can use Undo right after.") != QMessageBox.StandardButton.Yes:
            return
        self.snapshot()
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if task_id == self.focus_target_id:
            self.exit_focus()
        self.save(); self.refresh()

    def open_dashboard(self):
        self.unlock()
        self.stop_alarm()
        if self.dashboard is None:
            self.dashboard = Dashboard(self)
        self.dashboard.render()
        self.hide()
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    def show_note(self):
        self.unlock()
        if self.dashboard: self.dashboard.hide()
        self.show(); self.raise_(); self.activateWindow()

    def show_add(self):
        self.show_note()
        self.quick.setFocus(); self.quick.selectAll()

    def open_menu(self):
        menu = self.build_menu()
        menu.exec(self.mapToGlobal(QPoint(self.width()-250, 48)))

    def tray_clicked(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_note()

    def build_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Show and UNLOCK note   Ctrl+Alt+F", self.show_note)
        m.addAction("Quick add task   Ctrl+Alt+T", self.show_add)
        m.addAction("Open my dashboard", self.open_dashboard)
        m.addSeparator()
        m.addAction("Test flash + beep (8 seconds)", self.test_alarm)
        m.addAction("Snooze reminder", self.snooze)
        m.addAction("Stop flashing / beep", self.stop_alarm)
        m.addAction("Reminder & appearance settings", self.show_preferences)
        m.addSeparator()
        click = m.addAction("Click-through (auto-unlocks after 10 min)")
        click.setCheckable(True)
        click.setChecked(self.settings["click_through"])
        click.toggled.connect(self.set_click_through)
        m.addAction("Unlock clicks NOW", self.unlock)
        m.addAction("Move to top-right corner", self.reset_corner)
        if sys.platform == "win32":
            start = m.addAction("Start with Windows")
            start.setCheckable(True); start.setChecked(has_autostart())
            start.toggled.connect(self.toggle_startup)
        m.addSeparator()
        m.addAction("Backup all tasks (JSON)", self.export_backup)
        m.addAction("Restore backup", self.import_backup)
        m.addAction("Undo last task change", self.undo)
        m.addSeparator()
        m.addAction("Quit FocusPin completely", self.quit_app)
        return m

    def show_preferences(self):
        Preferences(self).exec()

    def apply_preferences(self):
        self.surface.opacity = self.settings["opacity"]
        self.surface.flash_color = self.settings["flash_color"]
        self.surface.update()
        self.flash_timer.setInterval(self.settings["flash_interval_ms"])
        self.sound_timer.setInterval(self.settings["beep_interval"] * 1000)
        if self.settings["mute_reminders"]:
            self.stop_alarm()
        self._last_move = time.monotonic()
        self.save(); self.refresh()

    def set_click_through(self, enabled: bool):
        if enabled and not self.tray.isVisible() and not self._hotkeys:
            QMessageBox.warning(self, "No unlock method", "Click-through requires a tray icon or registered keyboard shortcut.")
            return
        self.settings["click_through"] = bool(enabled)
        if enabled:
            self._click_timeout = time.monotonic() + 600
            self.footer.setText("◌ click-through · Ctrl+Alt+F")
            if self.tray.isVisible():
                self.tray.showMessage("FocusPin click-through", "Unlock anytime: Ctrl+Alt+F or click the FocusPin tray icon.", QSystemTrayIcon.MessageIcon.Information, 2500)
        else:
            self._click_timeout = 0.0
            self.footer.setText("♡  right here with you")
        # Qt window flag is cleaner than manually altering an HWND and works on Windows.
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        self.show()
        self.save()
        self.tray.setContextMenu(self.build_menu())

    def unlock(self):
        if self.settings["click_through"]:
            self.set_click_through(False)

    def toggle_startup(self, enabled):
        try:
            set_autostart(enabled)
        except OSError as ex:
            QMessageBox.warning(self, "Autostart unavailable", str(ex))
        self.tray.setContextMenu(self.build_menu())

    def keep_on_screen(self):
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        if not screen: return
        a = screen.availableGeometry()
        self.move(max(a.left()+4, min(self.x(), a.right()-self.width()-4)),
                  max(a.top()+4, min(self.y(), a.bottom()-self.height()-4)))

    def position_initially(self):
        self._position_ready = True
        position = self.settings.get("position")
        if position:
            self.move(position[0],position[1]); self.keep_on_screen()
        else:
            self.reset_corner()

    def save_position(self):
        if self._position_ready:
            self.settings["position"] = [self.x(), self.y()]
            self.save()

    def reset_corner(self):
        screen = QApplication.primaryScreen()
        if screen:
            a = screen.availableGeometry()
            self.move(a.right()-self.width()-16, a.top()+16)
            self.save_position()
            self.show()

    def focus_on(self, task_id: str):
        if not self.get_task(task_id): return
        self.focus_target_id = task_id
        self.focus_remaining = self.settings["focus_minutes"] * 60
        self.active_focus_duration = self.settings["focus_minutes"]
        self.focus_running = True
        self.focus_last_tick = time.monotonic()
        self.stop_alarm()
        self._last_move = time.monotonic()
        self.refresh()

    def start_focus(self):
        if not self.get_task(self.focus_target_id):
            return
        if self.focus_remaining <= 0:
            self.focus_remaining = self.settings["focus_minutes"] * 60
            self.active_focus_duration = self.settings["focus_minutes"]
        self.focus_running = True
        self.focus_last_tick = time.monotonic()
        self.stop_alarm()
        self.refresh()

    def pause_focus(self):
        self.update_focus_clock()
        self.focus_running = False
        self.refresh()

    def exit_focus(self):
        self.focus_running = False
        self.focus_target_id = None
        self.focus_remaining = self.settings["focus_minutes"] * 60
        self._last_move = time.monotonic()
        self.refresh()

    def update_focus_clock(self):
        now = time.monotonic()
        if self.focus_running:
            self.focus_remaining = max(0, self.focus_remaining - max(0, now - self.focus_last_tick))
            if self.focus_remaining <= 0:
                task_id = self.focus_target_id
                self.focus_running = False
                self.snapshot()
                self.sessions.append({"id": uuid.uuid4().hex, "task_id": task_id,
                     "minutes": self.active_focus_duration, "ended_at": now_iso()})
                self.save()
                self.refresh()
                if self.tray.isVisible():
                    self.tray.showMessage("Focus session complete 🎉", "Nice work! Your focus minutes were recorded.", QSystemTrayIcon.MessageIcon.Information, 4000)
        self.focus_last_tick = now

    def snooze(self):
        self._snooze_until = time.monotonic() + self.settings["snooze_minutes"] * 60
        self.stop_alarm()
        self.footer.setText(f"◔ Snoozed {self.settings['snooze_minutes']} min")

    def flip_flash(self):
        self._flash_on = not self._flash_on
        self.surface.flash = self._flash_on
        self.surface.update()

    def play_beep(self):
        if not self._alerting or not self.settings["sound_enabled"]:
            return
        if sys.platform == "win32":
            try:
                import winsound
                filename = ensure_alert_file(self.state_file.parent / "focuspin-v2-beep.wav", self.settings["sound_profile"], self.settings["volume"])
                winsound.PlaySound(str(filename), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except (OSError, RuntimeError) as ex:
                self.footer.setText("⚠ Beep failed: check audio")
                self.footer.setToolTip(str(ex))
        else:
            QApplication.beep()

    def start_alarm(self, *, force=False):
        if self._alerting: return
        if not force and (self.settings["mute_reminders"] or self.focus_running or not any(not t["done"] for t in self.tasks)):
            return
        self._alerting = True
        self.alert_banner.setText("◉  testing your reminder..." if force else "◉  hey, your to-dos are waiting")
        self.alert_banner.show()
        self.show(); self.raise_()
        self.surface.flash = True
        self.surface.update()
        self._flash_on = True
        self.flash_timer.start()
        self.play_beep()
        self.sound_timer.start()

    def stop_alarm(self):
        self._alerting = False
        self._test_until = 0.0
        self.flash_timer.stop()
        self.sound_timer.stop()
        self._flash_on = False
        self.surface.flash = False
        self.surface.update()
        self.alert_banner.hide()
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except (OSError, RuntimeError):
                pass

    def test_alarm(self):
        self.show_note()
        self.stop_alarm()
        self._test_until = time.monotonic() + 8
        self.start_alarm(force=True)
        # Ensure the user can hear it a second time in an 8-second test.
        QTimer.singleShot(3500, lambda: self.play_beep() if self._test_until else None)

    def tick(self):
        stamp = time.monotonic()
        gap = stamp - self._last_poll
        self._last_poll = stamp
        self.update_focus_clock()
        if self.focus_target_id:
            target = self.get_task(self.focus_target_id)
            if target is not None:
                self.mini_status.setText(f"🎯 FOCUS  {int(self.focus_remaining//60):02d}:{int(self.focus_remaining%60):02d}" + (" · PAUSED" if not self.focus_running else ""))
        if self.dashboard:
            self.dashboard.refresh_timer_label()
        if self._click_timeout and stamp > self._click_timeout:
            self.unlock()
        if gap > 15 or self._locked or not desktop_is_unlocked():
            self.stop_alarm()
            self._last_move = stamp
            self._last_mouse = cursor_position()
            return
        if self._test_until:
            if stamp >= self._test_until:
                self.stop_alarm()
                self._last_move = stamp
            return
        point = cursor_position()
        if point is not None and point != self._last_mouse:
            self._last_mouse = point
            self._last_move = stamp
            if self._alerting: self.stop_alarm()
            return
        if self.focus_running or stamp < self._snooze_until:
            return
        if stamp - self._last_move >= self.settings["idle_minutes"] * 60:
            self.start_alarm()

    def export_backup(self):
        self.save()
        name = f"FocusPin-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        path, _ = QFileDialog.getSaveFileName(self.dashboard or self, "Save task backup", str(Path.home()/"Documents"/name), "JSON files (*.json)")
        if path:
            try:
                shutil.copy2(self.state_file, path)
                QMessageBox.information(self.dashboard or self, "Backup saved", f"All tasks, settings and sessions backed up to:\n{path}")
            except OSError as ex:
                QMessageBox.warning(self.dashboard or self, "Backup failed", str(ex))

    def export_csv(self):
        name = f"FocusPin-tasks-{date.today().isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(self.dashboard or self, "Export tasks as CSV", str(Path.home()/"Documents"/name), "CSV files (*.csv)")
        if path:
            try:
                export_csv(Path(path), self.tasks)
            except OSError as ex:
                QMessageBox.warning(self.dashboard or self, "Export failed", str(ex))

    def import_backup(self):
        path, _ = QFileDialog.getOpenFileName(self.dashboard or self, "Restore task backup", str(Path.home()), "JSON files (*.json)")
        if not path: return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
                raise ValueError("Not a FocusPin backup JSON file")
            imported, settings, sessions = read_state(Path(path))
            if raw["tasks"] and not imported:
                raise ValueError("There were no valid tasks in the backup")
        except (OSError, ValueError, UnicodeError) as ex:
            QMessageBox.warning(self.dashboard or self, "Invalid backup", str(ex)); return
        if QMessageBox.question(self.dashboard or self, "Restore backup?", "Replace current tasks, settings and focus stats with the backup?\nA safety copy of your current data will be saved first.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.save()
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.state_file, self.state_file.with_name(f"before-restore-{stamp}.json"))
            self.snapshot()
            self.tasks, self.settings, self.sessions = imported, settings, sessions
            self.settings["click_through"] = False
            self.exit_focus()
            self.apply_preferences()
            self.save(); self.refresh()
        except OSError as ex:
            QMessageBox.warning(self.dashboard or self, "Restore failed", str(ex))

    def register_windows_notifications(self):
        if sys.platform != "win32" or self._session_notifications_registered:
            return
        try:
            api = ctypes.WinDLL("Wtsapi32", use_last_error=True)
            api.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
            api.WTSRegisterSessionNotification.restype = wintypes.BOOL
            self._session_notifications_registered = bool(api.WTSRegisterSessionNotification(int(self.winId()), 0))
        except (OSError, AttributeError):
            pass

    def register_hotkeys(self):
        if sys.platform != "win32": return
        try:
            api = ctypes.windll.user32
            api.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            api.RegisterHotKey.restype = wintypes.BOOL
            # MOD_CTRL 0x0002, MOD_ALT 0x0001, MOD_NOREPEAT 0x4000
            for ident, key in ((1, ord('F')), (2, ord('T'))):
                if api.RegisterHotKey(int(self.winId()), ident, 0x4003, key):
                    self._hotkeys.append(ident)
            if not self._hotkeys and self.tray.isVisible():
                self.tray.showMessage("Shortcut not available", "Use the FocusPin tray icon to unlock. Another app may own the shortcuts.", QSystemTrayIcon.MessageIcon.Warning, 4000)
        except (OSError, AttributeError):
            pass

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam == 1: self.show_note()
                    elif msg.wParam == 2: self.show_add()
                    return True, 0
                if msg.message == 0x02B1:  # WM_WTSSESSION_CHANGE
                    if msg.wParam == 7:
                        self._locked = True; self.stop_alarm()
                    elif msg.wParam == 8:
                        self._locked = False
                        self._last_move = time.monotonic()
            except (ValueError, OSError, TypeError):
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):  # noqa: N802
        event.ignore()
        self.hide()
        if self.tray.isVisible():
            self.tray.showMessage("FocusPin is still running", "Click its system tray icon to show it, or choose Quit to exit.", QSystemTrayIcon.MessageIcon.Information, 2800)

    def quit_app(self):
        self.stop_alarm()
        self.save()
        if sys.platform == "win32":
            try:
                api = ctypes.windll.user32
                for ident in self._hotkeys:
                    api.UnregisterHotKey(int(self.winId()), ident)
                if self._session_notifications_registered:
                    ctypes.WinDLL("Wtsapi32").WTSUnRegisterSessionNotification(int(self.winId()))
            except (OSError, AttributeError):
                pass
        if self.dashboard:
            self.dashboard.hide()
        self.tray.hide()
        QApplication.instance().quit()


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FocusPin.V2")
        except (OSError, AttributeError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("FocusPin")
    app.setQuitOnLastWindowClosed(False)
    instance = FocusPin()
    instance.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
