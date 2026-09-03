from PyQt6.QtCore import QTimer, QElapsedTimer, Qt
from ssz_config import CONFIG
from ssz_dialogs import OperationProgressDialog
from operations_log import log_operation


class WorkerController:
    """Единый контроллер фоновых QThread: прогресс, отмена, watchdog, heartbeat."""

    def __init__(self, window):
        self._window = window
        self._worker = None
        self._generation = 0
        self._progress_dlg = None
        self._on_done_cb = None
        self._on_error_cb = None
        self._cancelling = False
        self._base_status = ""
        self._last_msg = ""
        self._last_cur = 0
        self._last_tot = 0
        self._stale_seconds = 0
        self._progress_timer = QElapsedTimer()
        self._progress_timer.start()
        self._ui_throttle = QElapsedTimer()

        self._activity_timer = QTimer()
        self._activity_timer.setInterval(500)
        self._activity_timer.timeout.connect(self._on_activity_tick)

        self._cancel_watchdog = QTimer()
        self._cancel_watchdog.setInterval(500)
        self._cancel_watchdog.timeout.connect(self._on_cancel_watchdog_tick)
        self._cancel_elapsed_s = 0

    @property
    def worker(self):
        return self._worker

    def is_running(self):
        return self._worker is not None and self._worker.isRunning()

    def start(self, worker, title, on_done, on_error=None, error_title="Ошибка"):
        self.request_cancel_async()
        self._generation += 1
        gen = self._generation
        self._worker = worker
        self._on_done_cb = on_done
        self._on_error_cb = on_error
        self._cancelling = False
        self._cancel_elapsed_s = 0
        self._cancel_watchdog.stop()
        self._stale_seconds = 0
        self._progress_timer.restart()

        self._progress_dlg = OperationProgressDialog(title, self._window)
        self._progress_dlg.cancelled.connect(lambda: self.request_cancel())
        self._progress_dlg.show()

        self._window.set_busy(True)
        self._activity_timer.start()

        worker.progress.connect(
            lambda msg, cur, tot, g=gen: self._on_progress(g, msg, cur, tot),
            Qt.ConnectionType.QueuedConnection
        )
        worker.finished_ok.connect(
            lambda result, g=gen: self._on_finished_ok(g, result),
            Qt.ConnectionType.QueuedConnection
        )
        worker.error.connect(
            lambda msg, g=gen: self._on_error(g, msg, error_title),
            Qt.ConnectionType.QueuedConnection
        )
        worker.start()
        log_operation("worker_start", title)

    def request_cancel(self):
        if not self._worker or self._cancelling:
            return
        self._cancelling = True
        self._cancel_elapsed_s = 0
        if self._progress_dlg:
            self._progress_dlg.btn_cancel.setEnabled(False)
            self._progress_dlg.lbl.setText("Отмена…")
        self._window.set_status("Отмена операции…", 0, 0)
        if hasattr(self._worker, "cancel"):
            self._worker.cancel()
        self._cancel_watchdog.start()
        log_operation("cancel_requested", type(self._worker).__name__)

    def request_cancel_async(self):
        """Отменить предыдущий воркер без ожидания на UI."""
        w = self._worker
        if w and w.isRunning():
            if hasattr(w, "cancel"):
                w.cancel()
            w.wait(500)

    def force_stop(self):
        self._generation += 1
        w = self._worker
        if w and w.isRunning():
            if hasattr(w, "cancel"):
                w.cancel()
            w.wait(100)
            if w.isRunning():
                w.terminate()
                w.wait(1000)
        log_operation("force_stop", type(w).__name__ if w else "none")
        self._finish_ui(cancelled=True)

    def _on_progress(self, generation, msg, cur, tot):
        if generation != self._generation:
            return
        self._last_msg = msg
        self._last_cur = cur
        self._last_tot = tot
        self._stale_seconds = 0
        self._base_status = msg
        self._progress_timer.restart()
        if self._cancelling:
            return
        if self._ui_throttle.isValid() and self._ui_throttle.elapsed() < 150:
            return
        self._ui_throttle.restart()
        if self._progress_dlg:
            self._progress_dlg.update_progress(msg, cur, tot)
        self._window.set_status(msg, cur, tot)

    def _on_activity_tick(self):
        if not self._worker or not self._worker.isRunning():
            return
        stale_limit = float(CONFIG.get("progress_stale_s", 2.0))
        elapsed_ms = self._progress_timer.elapsed()
        if elapsed_ms < stale_limit * 1000:
            return
        self._stale_seconds = int(elapsed_ms // 1000)
        suffix = f" (работаю… {self._stale_seconds} с)"
        if self._cancelling:
            msg = f"Отмена… (ожидание {self._cancel_elapsed_s} с)"
        else:
            msg = self._base_status + suffix if self._base_status else f"Обработка{suffix}"
            base_lower = (self._base_status or "").lower()
            if "цвета excel" in base_lower or "ячейки" in base_lower:
                msg += " — долгий этап COM"
            elif "открываю" in base_lower and "excel" in base_lower:
                msg += " — открытие файла в Excel"
        if self._progress_dlg:
            self._progress_dlg.lbl.setText(msg)
            self._progress_dlg.bar.setRange(0, 0)
        self._window.lbl_status.setText(msg)
        self._window.progress_bar.setVisible(True)
        self._window.progress_bar.setRange(0, 0)

    def _on_cancel_watchdog_tick(self):
        self._cancel_elapsed_s += 0.5
        watchdog_s = int(CONFIG.get("cancel_watchdog_s", 15))
        if self._cancel_elapsed_s >= 3 and self._cancel_elapsed_s < watchdog_s:
            self._window.set_status(
                f"Принудительная остановка… ({int(self._cancel_elapsed_s)} с)", 0, 0
            )
        if self._cancel_elapsed_s >= watchdog_s:
            self._cancel_watchdog.stop()
            self.force_stop()

    def _on_finished_ok(self, generation, result):
        if generation != self._generation:
            return
        self._activity_timer.stop()
        self._cancel_watchdog.stop()
        cb = self._on_done_cb
        
        w = self._worker
        self._worker = None
        if w:
            w.wait(1000)
            w.deleteLater()
            
        self._on_done_cb = None
        self._cancelling = False
        
        dlg = self._progress_dlg
        self._progress_dlg = None
        if dlg:
            dlg.finish()
            dlg.close()
            dlg.deleteLater()
            
        self._window.set_busy(False)
        if cb:
            cb(result)

    def _on_error(self, generation, message, title):
        if generation != self._generation:
            return
        self._activity_timer.stop()
        self._cancel_watchdog.stop()
        
        w = self._worker
        self._worker = None
        if w:
            w.wait(1000)
            w.deleteLater()
            
        self._on_done_cb = None
        self._cancelling = False
        
        dlg = self._progress_dlg
        self._progress_dlg = None
        if dlg:
            dlg.finish()
            dlg.close()
            dlg.deleteLater()
            
        self._window.set_busy(False)
        if self._on_error_cb:
            self._on_error_cb(message, title)
        else:
            self._window._on_worker_error(message, title)

    def _finish_ui(self, cancelled=False):
        self._activity_timer.stop()
        self._cancel_watchdog.stop()
        
        w = self._worker
        self._worker = None
        if w:
            w.wait(1000)
            w.deleteLater()
            
        self._on_done_cb = None
        self._cancelling = False
        
        dlg = self._progress_dlg
        self._progress_dlg = None
        if dlg:
            dlg.finish()
            dlg.close()
            dlg.deleteLater()
            
        self._window.set_busy(False)
        if cancelled:
            self._window.set_status("Отменено", 0, 0)
        else:
            self._window.set_status("Готово", 0, 0)
