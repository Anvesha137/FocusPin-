"""Executable V2 regression tests; no PySide6 or Windows required."""
import io
import json
import os
import struct
import tempfile
import unittest
import wave
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import (
    DEFAULT_SETTINGS, backup_v1_once, build_alert_wav, ensure_alert_file,
    export_csv, is_overdue, new_task, next_occurrence, normalize_task,
    overview, read_state, set_completed, write_state,
)


class StorageTests(unittest.TestCase):
    def test_v1_state_preserves_task_ids_and_completed_history(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'state.json'
            v1 = {'version': 1, 'tasks': [
                {'id':'keep1', 'text':'Finish QuickRevert 🚀', 'done':False, 'created_at':'2026-09-30T12:00:00+00:00', 'completed_at': None},
                {'id':'keep2', 'text':'Old finished', 'done':True, 'completed_at':'2026-10-01T10:00:00+00:00'}
            ], 'settings': {'opacity': 0.70, 'idle_minutes': 30, 'sound_enabled':True, 'click_through':True}}
            target.write_text(json.dumps(v1), encoding='utf8')
            self.assertIsNotNone(backup_v1_once(target))
            self.assertIsNone(backup_v1_once(target))
            tasks, settings, sessions = read_state(target)
            self.assertEqual([t['id'] for t in tasks], ['keep1','keep2'])
            self.assertFalse(tasks[0]['done']); self.assertTrue(tasks[1]['done'])
            self.assertEqual(tasks[1]['completed_at'], v1['tasks'][1]['completed_at'])
            self.assertEqual(tasks[0]['category'], 'General')
            self.assertTrue(settings['click_through'])  # UI safely resets at launch
            self.assertEqual(sessions, [])
            write_state(target,tasks,settings,sessions)
            self.assertEqual(json.loads(target.read_text(encoding='utf8'))['version'], 2)
            self.assertEqual(json.loads((Path(d)/'state.v1.backup.json').read_text())['version'],1)

    def test_roundtrip_all_v2_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'sub'/'state.json'
            task = new_task('Study agentic AI',category='Study',priority='High',repeat='Weekly',
                due_at='2026-10-12T18:30:00+05:30', notes='Relevant project',
                subtasks=[{'id':'step', 'text':'Take notes', 'done':True}])
            sessions = [{'id':'x','task_id':task['id'],'minutes':25,'ended_at':'2026-10-09T13:00:00+00:00'}]
            write_state(path, [task], dict(DEFAULT_SETTINGS), sessions)
            tasks, config, loaded = read_state(path)
            self.assertEqual(tasks, [task]); self.assertEqual(loaded,sessions)
            self.assertEqual(config, DEFAULT_SETTINGS)

    def test_corruption_safe(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'state.json'
            path.write_text('garbled{',encoding='utf8')
            tasks, cfg, history = read_state(path)
            self.assertEqual(tasks, [])
            self.assertEqual(cfg['idle_minutes'],30)
            self.assertEqual(history, [])

    def test_invalid_and_out_of_bounds_prefs(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'state.json'
            path.write_text(json.dumps({'tasks': [{'text':'Good','done':False}, {'text':12}],
                'settings': {'opacity':55, 'idle_minutes':1000,'volume':-9,'flash_color':'bad','position':['bad',1]}}))
            tasks, settings, _ = read_state(path)
            self.assertEqual(len(tasks),1)
            self.assertEqual(settings['opacity'],1)
            self.assertEqual(settings['idle_minutes'],240)
            self.assertEqual(settings['volume'],0)
            self.assertEqual(settings['flash_color'],'Orange')
            self.assertIsNone(settings['position'])

    def test_csv_export(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'export.csv'
            export_csv(path,[new_task('Local task 😊')])
            content = path.read_text(encoding='utf-8-sig')
            self.assertIn('Local task 😊',content)
            self.assertIn('priority,category,due_at',content)


class RecurrenceTests(unittest.TestCase):
    def test_weekly_creates_next_occurrence_once(self):
        now = datetime(2026,10,9,15,0,tzinfo=timezone(timedelta(hours=5,minutes=30)))
        item = new_task('Weekly call',repeat='Weekly',due_at='2026-10-09T09:00:00+05:30',
                subtasks=[{'id':'abc','text':'Prepare','done':True}])
        tasks = [item]
        new_id = set_completed(tasks,item['id'],True,now=now)
        self.assertEqual(len(tasks),2)
        self.assertIsNotNone(new_id)
        self.assertEqual(tasks[1]['due_at'],'2026-10-16T09:00+05:30')
        self.assertEqual(tasks[1]['subtasks'][0]['done'],False)
        self.assertEqual(tasks[0]['completed_at'], now.isoformat(timespec='seconds'))
        self.assertIsNone(set_completed(tasks,item['id'],True,now=now))
        self.assertEqual(len(tasks),2)
        set_completed(tasks,item['id'],False,now=now)
        self.assertFalse(tasks[0]['done'])

    def test_weekdays_skips_saturday_sunday(self):
        now = datetime.fromisoformat('2026-10-09T19:00+05:30')  # Friday
        self.assertEqual(next_occurrence('Weekdays','2026-10-09T10:00+05:30',now=now), '2026-10-12T10:00+05:30')

    def test_daily_skips_past_due_to_future(self):
        now = datetime.fromisoformat('2026-10-09T12:00+05:30')
        self.assertEqual(next_occurrence('Daily','2026-10-07T09:00+05:30',now=now), '2026-10-10T09:00+05:30')

    def test_month_end_does_not_crash(self):
        now = datetime.fromisoformat('2026-01-31T11:00+05:30')
        self.assertEqual(next_occurrence('Monthly','2026-01-31T10:00+05:30',now=now), '2026-02-28T10:00+05:30')

    def test_not_recurring_does_not_duplicate(self):
        t = new_task('One off'); tasks=[t]
        self.assertIsNone(set_completed(tasks,t['id'],True))
        self.assertEqual(len(tasks),1)


class StatisticsAndAudioTests(unittest.TestCase):
    def test_overdue(self):
        t = new_task('Late',due_at='2020-01-01T00:00:00+00:00')
        self.assertTrue(is_overdue(t))
        t['done'] = True
        self.assertFalse(is_overdue(t))

    def test_daily_stats_and_7day_chart(self):
        now = datetime.now().astimezone()
        task = new_task('Finish')
        task['done']=True
        task['completed_at']=now.isoformat()
        history = [{'minutes':25,'ended_at':now.isoformat()}]
        v=overview([task],history,today=date.today())
        self.assertEqual(v['done_today'],1)
        self.assertEqual(v['focus_minutes_week'],25)
        self.assertEqual(len(v['weekly']),7)

    def test_beep_has_three_distinct_tones_and_silence(self):
        sound = build_alert_wav('Classic', 90)
        with wave.open(io.BytesIO(sound),'rb') as audio:
            self.assertEqual(audio.getnchannels(),1)
            self.assertEqual(audio.getsampwidth(),2)
            self.assertEqual(audio.getframerate(),22050)
            data=audio.readframes(audio.getnframes())
        def amp(t):
            i=int(t*22050)*2
            return abs(struct.unpack('<h',data[i:i+2])[0])
        self.assertTrue(any(amp(t)>1000 for t in (.05,.10,.15)))
        self.assertEqual(amp(.22),0)
        self.assertEqual(amp(.52),0)
        self.assertEqual(amp(.82),0)

    def test_sound_volume_zero(self):
        wav = build_alert_wav('Urgent',0)
        with wave.open(io.BytesIO(wav),'rb') as audio:
            payload=audio.readframes(audio.getnframes())
        self.assertFalse(any(payload))

    def test_audio_file_written(self):
        with tempfile.TemporaryDirectory() as d:
            file=ensure_alert_file(Path(d)/'alert.wav', 'Gentle', 65)
            self.assertTrue(file.read_bytes().startswith(b'RIFF'))

if __name__ == '__main__':
    unittest.main()


class MonthlyAnchorRegression(unittest.TestCase):
    def test_monthly_last_day_returns_to_original_day(self):
        now = datetime.fromisoformat('2026-01-31T12:00+05:30')
        a = new_task('Month end', due_at='2026-01-31T09:00+05:30', repeat='Monthly')
        tasks = [a]
        set_completed(tasks, a['id'], True, now=now)
        self.assertEqual(tasks[-1]['due_at'], '2026-02-28T09:00+05:30')
        set_completed(tasks, tasks[-1]['id'], True, now=datetime.fromisoformat('2026-02-28T12:00+05:30'))
        self.assertEqual(tasks[-1]['due_at'], '2026-03-31T09:00+05:30')
