"""The translation's workers: how many the device's free memory affords, and the low-memory mode's cap.
The shader translation starts one process per batch, and each of them holds the .NET runtime and its own batch:
a phone with little memory free runs out of it and the system kills the build. The number of processes therefore
follows the free memory (plenty of it -> one per core, as before; little of it -> fewer, so the build finishes)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from porter import memory
from porter import phone_cli
from porter import phone_port


class MemoryJobsTest(unittest.TestCase):

    def test_plenty_of_memory_runs_one_worker_per_core(self):
        self.assertEqual(8, memory.jobs(8192, 8))
        self.assertEqual(8, memory.jobs(6144, 8))

    def test_the_free_memory_caps_the_workers(self):
        self.assertEqual(5, memory.jobs(4096, 8))
        self.assertEqual(2, memory.jobs(2048, 8))

    def test_a_little_memory_runs_one_worker(self):
        self.assertEqual(1, memory.jobs(1200, 8))

    def test_no_room_at_all_is_zero(self):
        self.assertEqual(0, memory.jobs(900, 8))

    def test_a_desktop_machine_keeps_one_worker_per_core(self):
        """No /proc (a Mac, a Windows): the memory is unknown, so the workers stay as they were"""
        self.assertEqual(8, memory.jobs(None, 8))
        self.assertEqual(4, memory.jobs(None, 4))

    def test_the_low_memory_mode_caps_the_workers(self):
        self.assertEqual(2, memory.jobs(2048, 8, forced=True))
        self.assertEqual(2, memory.jobs(8192, 8, forced=True))

    def test_the_low_memory_mode_makes_no_room(self):
        """It caps the workers, it does not create memory: below the floor the stage still has no room"""
        self.assertEqual(0, memory.jobs(900, 8, forced=True))

    def test_the_workers_never_exceed_the_cores(self):
        self.assertEqual(4, memory.jobs(65536, 4))
        self.assertEqual(2, memory.jobs(65536, 2, forced=True))

    def test_the_budgets_can_be_overridden(self):
        """The budgets are the environment's business: a device that needs other numbers gets them"""
        old = {k: os.environ.get(k) for k in ('NX2A_MEM_WORKER_MB', 'NX2A_MEM_RESERVE_MB', 'NX2A_MEM_FLOOR_MB')}
        try:
            os.environ['NX2A_MEM_WORKER_MB'] = '1000'
            os.environ['NX2A_MEM_RESERVE_MB'] = '2000'
            os.environ['NX2A_MEM_FLOOR_MB'] = '3000'
            import importlib
            m = importlib.reload(memory)
            self.assertEqual(1000, m.WORKER_MB)
            self.assertEqual(2000, m.RESERVE_MB)
            self.assertEqual(3000, m.FLOOR_MB)
            self.assertEqual(0, m.jobs(2500, 8))          # below the floor: no room
            self.assertEqual(2, m.jobs(4000, 8))          # (4000 - 2000) // 1000
        finally:
            for k, v in old.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
            import importlib
            importlib.reload(memory)

    def test_the_basis_says_why(self):
        self.assertIn('forced', memory.basis(2048, True))
        self.assertIn('free memory', memory.basis(2048, False))
        self.assertIn('no memory', memory.basis(None, False))


class AvailableMemoryTest(unittest.TestCase):

    def test_the_free_memory_is_read_from_the_meminfo(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'meminfo'
            path.write_text('MemTotal:       8000000 kB\nMemAvailable:   2097152 kB\nMemFree:        100 kB\n')
            self.assertEqual(2048.0, memory.available_mb(path))

    def test_no_meminfo_is_no_answer(self):
        self.assertIsNone(memory.available_mb('/nonexistent/meminfo'))


class CommandLineTest(unittest.TestCase):

    def test_the_low_memory_mode_is_an_option_of_the_port(self):
        """The flag reaches the build options: the port takes it as one of its own"""
        args = phone_cli._parser().parse_args(['port', '/sdcard/game.nsp', '--low-mem'])
        self.assertTrue(args.low_mem)

    def test_without_the_flag_it_is_off(self):
        args = phone_cli._parser().parse_args(['port', '/sdcard/game.nsp'])
        self.assertFalse(args.low_mem)


class TranslationWorkersTest(unittest.TestCase):
    """The pipeline's own count: what it hands to the translation, and what it says when there is no room"""

    def port(self, low_mem=False, jobs=8):
        p = phone_port.PhonePort.__new__(phone_port.PhonePort)
        p.o = phone_port.Options(folder=Path('/tmp'), jobs=jobs, low_mem=low_mem)
        return p

    def workers(self, avail=None, **kw):
        """the pipeline's count on a machine with 8 cores: the count follows the cores (one worker per core), so a
        runner with fewer of them would answer with its own number and the test would not say what it means"""
        with mock.patch.object(memory, 'available_mb', return_value=avail), \
                mock.patch.object(phone_port.os, 'cpu_count', return_value=8):
            return self.port(**kw).translation_workers()

    def test_the_workers_follow_the_free_memory(self):
        self.assertEqual((2, 2048), self.workers(2048))

    def test_a_phone_with_room_keeps_one_worker_per_core(self):
        self.assertEqual((8, 8192), self.workers(8192))

    def test_the_low_memory_mode_caps_them(self):
        self.assertEqual((2, 8192), self.workers(8192, low_mem=True))

    def test_jobs_still_caps_them(self):
        """The maintenance knob keeps its meaning: --jobs 2 is two workers, memory or not"""
        self.assertEqual((2, 8192), self.workers(8192, jobs=2))

    def test_no_room_stops_the_stage_with_a_clear_error(self):
        with self.assertRaises(phone_port.BuildError) as cm:
            self.workers(900)
        self.assertIn('memory', str(cm.exception))

    def test_a_desktop_machine_keeps_one_worker_per_core(self):
        self.assertEqual((8, None), self.workers(None))


if __name__ == '__main__':
    unittest.main()
