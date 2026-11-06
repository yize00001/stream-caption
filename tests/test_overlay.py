import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from stream_caption.overlay import SubtitleOverlay
from stream_caption.settings import OverlaySettings


class OverlayTests(unittest.TestCase):
    """Exercise actual UI callbacks with a fake clock and no desktop window."""

    def start_overlay(self, enabled=True):
        self.timers = {}
        self.bindings = {}
        self.alpha = 0
        self.sequence = 0
        self.root = Mock()

        def attributes(name, *values):
            if name == '-alpha':
                if values:
                    self.alpha = values[0]
                return self.alpha

        def after(delay, callback):
            self.sequence += 1
            self.timers[self.sequence] = (delay, callback)
            return self.sequence

        self.root.attributes.side_effect = attributes
        self.root.after.side_effect = after
        self.root.after_cancel.side_effect = lambda timer: self.timers.pop(timer, None)
        self.root.bind.side_effect = lambda event, callback: self.bindings.update({event: callback})
        self.root.winfo_screenwidth.return_value = 1920
        self.root.winfo_screenheight.return_value = 1080
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch('stream_caption.overlay._load_state', return_value=None))
        stack.enter_context(patch('stream_caption.overlay.tk.Tk', return_value=self.root))
        text = stack.enter_context(patch('stream_caption.overlay.tk.Text')).return_value
        text.yview.return_value = (0, 1)
        stack.enter_context(patch('stream_caption.overlay.tk.Label'))
        self.overlay = SubtitleOverlay(OverlaySettings(auto_hide_enabled=enabled))
        self.overlay._run()
        return text

    def fire(self, delay):
        timer = next(key for key, value in self.timers.items() if value[0] == delay)
        _, callback = self.timers.pop(timer)
        callback()

    def hide_timers(self):
        return [callback for delay, callback in self.timers.values() if delay == 8000]

    def test_enabled_by_default_and_hides_after_timeout(self):
        self.start_overlay()
        self.assertEqual(self.alpha, 0)
        self.overlay.push('source', 'translation')
        self.fire(100)
        self.assertEqual(self.alpha, 0.88)
        self.fire(8000)
        self.assertEqual(self.alpha, 0)

    def test_switch_off_cancels_timer_and_switch_on_restarts(self):
        self.start_overlay()
        self.overlay.push('source', 'translation')
        self.fire(100)
        old_callback = self.hide_timers()[0]
        self.overlay.toggle_auto_hide()
        self.fire(100)
        self.assertFalse(self.hide_timers())
        old_callback()  # Even a late callback must respect the disabled switch.
        self.assertEqual(self.alpha, 0.88)
        self.overlay.toggle_auto_hide()
        self.fire(100)
        self.assertEqual(len(self.hide_timers()), 1)
        self.fire(8000)
        self.assertEqual(self.alpha, 0)

    def test_disabled_start_stays_visible_but_manual_hide_still_works(self):
        text = self.start_overlay(enabled=False)
        self.assertEqual(self.alpha, 0.88)
        self.overlay.toggle()
        self.fire(100)
        self.assertEqual(self.alpha, 0)
        self.overlay.push('new source', 'new translation')
        self.fire(100)
        self.assertEqual(self.alpha, 0)
        self.overlay.toggle_auto_hide()
        self.fire(100)
        self.assertEqual(self.alpha, 0)
        self.overlay.toggle()
        self.fire(100)
        self.assertEqual(self.alpha, 0.88)
        text.insert.assert_any_call('end', 'new translation', 'zh')

    def test_mouse_hover_suppresses_timer_and_disabled_leave_does_not_schedule(self):
        self.start_overlay()
        self.overlay.push('source', 'translation')
        self.fire(100)
        self.bindings['<Enter>'](None)
        self.assertFalse(self.hide_timers())
        self.overlay.toggle_auto_hide()
        self.fire(100)
        self.bindings['<Leave>'](None)
        self.assertFalse(self.hide_timers())
        self.overlay.toggle_auto_hide()
        self.fire(100)
        self.assertEqual(len(self.hide_timers()), 1)

    def test_revision_updates_existing_history_entry_without_appending(self):
        self.start_overlay(enabled=False)
        self.overlay.upsert('caption-1', 'I can attend', 'can attend')
        self.fire(100)
        self.overlay.upsert('caption-1', 'I cannot attend', 'cannot attend')
        self.fire(100)
        self.assertEqual(self.overlay._pairs, [('I cannot attend', 'cannot attend')])
        self.overlay.upsert('caption-2', 'I cannot attend', 'cannot attend')
        self.fire(100)
        self.assertEqual(len(self.overlay._pairs), 2)

    def test_draft_is_marked_until_finalized(self):
        text = self.start_overlay(enabled=False)
        self.overlay.upsert('caption-1', 'draft', 'translation', final=False)
        self.fire(100)
        self.assertEqual(self.overlay._draft_indexes, {0})
        text.insert.assert_any_call('end', '[暫定] draft\n', 'ja')
        self.overlay.upsert('caption-1', 'final speech', 'final translation', final=True)
        self.fire(100)
        self.assertFalse(self.overlay._draft_indexes)
        text.insert.assert_any_call('end', 'final speech\n', 'ja')


if __name__ == '__main__':
    unittest.main()
