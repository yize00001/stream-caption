import queue
import threading
import unittest

import numpy as np

from stream_caption.audio import PauseState, SAMPLE_RATE, recording


class AudioTests(unittest.TestCase):
    def test_capture_uses_configured_duration_and_mixes_channels(self):
        for step in (1, 2):
            with self.subTest(step=step):
                requested = []
                delivered = threading.Event()

                class Mic:
                    def record(self, numframes):
                        requested.append(numframes)
                        if len(requested) > 1:
                            delivered.wait(2)
                        return np.tile([0.25, 0.75], (numframes, 1))

                audio_q = queue.Queue(maxsize=4)
                with recording(Mic(), audio_q, PauseState(), step) as thread:
                    try:
                        item = audio_q.get(timeout=2)
                        mono = item.audio
                        self.assertEqual(item.generation, 0)
                        self.assertEqual(item.start_sample, 0)
                        self.assertEqual(item.end_sample, SAMPLE_RATE * step)
                        self.assertEqual(len(mono), SAMPLE_RATE * step)
                        np.testing.assert_allclose(mono, 0.5)
                        self.assertEqual(mono.dtype, np.float32)
                    finally:
                        delivered.set()
                self.assertFalse(thread.is_alive())
                self.assertTrue(all(n == SAMPLE_RATE * step for n in requested))

    def test_audio_spanning_pause_resume_is_discarded(self):
        pause = PauseState()
        entered = threading.Event()
        release = threading.Event()
        second_entered = threading.Event()
        finish = threading.Event()

        class Mic:
            calls = 0

            def record(self, numframes):
                self.calls += 1
                if self.calls == 1:
                    entered.set()
                    release.wait(2)
                else:
                    second_entered.set()
                    finish.wait(2)
                return np.ones((numframes, 1))

        audio_q = queue.Queue()
        with recording(Mic(), audio_q, pause, 1) as thread:
            try:
                self.assertTrue(entered.wait(2))
                pause.set()
                pause.clear()
                release.set()
                self.assertTrue(second_entered.wait(2))
                self.assertTrue(audio_q.empty())
                self.assertFalse(pause.accepts(0))
            finally:
                release.set()
                finish.set()
        self.assertFalse(thread.is_alive())

    def test_cleanup_joins_before_exception_leaves_context(self):
        class Mic:
            def record(self, numframes):
                return np.zeros((numframes, 1))

        with self.assertRaisesRegex(RuntimeError, 'pipeline crashed'):
            with recording(Mic(), queue.Queue(maxsize=1), PauseState(), 1) as thread:
                raise RuntimeError('pipeline crashed')
        self.assertFalse(thread.is_alive())

    def test_full_queue_keeps_latest_chunk(self):
        third_entered = threading.Event()
        finish = threading.Event()

        class Mic:
            calls = 0

            def record(self, numframes):
                self.calls += 1
                if self.calls == 3:
                    third_entered.set()
                    finish.wait(2)
                return np.full((numframes, 1), self.calls, dtype=np.float32)

        audio_q = queue.Queue(maxsize=1)
        with recording(Mic(), audio_q, PauseState(), 1):
            try:
                self.assertTrue(third_entered.wait(2))
                item = audio_q.get_nowait()
                np.testing.assert_allclose(item.audio, 2)
                self.assertEqual(item.start_sample, SAMPLE_RATE)
            finally:
                finish.set()


if __name__ == "__main__":
    unittest.main()
