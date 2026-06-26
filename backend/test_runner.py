"""
Test Runner — orchestrates test execution and wires in RunLogger
for structured result logs and nvme-cli debug logs.
"""

import uuid
import threading
import time
from datetime import datetime
from backend.log_manager import RunLogger


class TestRunner:
    def __init__(self, socketio):
        self.socketio = socketio
        self.runs = {}

    def get_available_tests(self) -> list:
        try:
            from tests.registry import ALL_TESTS
            return [cls.meta() for cls in ALL_TESTS]
        except Exception as e:
            import traceback
            return [{"id": "__import_error__", "name": "Registry import failed",
                     "description": traceback.format_exc(),
                     "category": "General", "tags": []}]

    def start_run(self, device: str, test_ids: list, params: dict = None,
                  cycles: int = 1, stop_on_error: bool = False) -> str:
        run_id = datetime.now().strftime("%H%M%S")
        cycles = max(1, int(cycles))
        self.runs[run_id] = {
            "run_id":   run_id,
            "device":   device,
            "test_ids": test_ids,
            "status":   "running",
            "results":  [],
            "started_at": datetime.now().isoformat(),
        }
        t = threading.Thread(
            target=self._execute,
            args=(run_id, device, test_ids, params or {}, cycles, stop_on_error),
            daemon=True
        )
        t.start()
        return run_id

    def _execute(self, run_id: str, device: str, test_ids: list,
                 params: dict = None, cycles: int = 1, stop_on_error: bool = False):
        from backend.drivers.nvme_cli_driver import NVMeCliDriver
        from tests.registry import get_test_by_id

        driver     = NVMeCliDriver(device)
        run        = self.runs[run_id]
        run_logger = RunLogger(run_id, device, test_ids)

        self._emit(run_id, "run_start", {
            "run_id": run_id, "total": len(test_ids), "cycles": cycles
        })

        stopped = False
        for cycle in range(1, cycles + 1):
            if run.get("stop_requested"):
                stopped = True
                break

            # Emit cycle boundary event (only meaningful when cycles > 1)
            if cycles > 1:
                self._emit(run_id, "cycle_start", {
                    "run_id": run_id, "cycle": cycle, "total_cycles": cycles
                })

            for i, test_id in enumerate(test_ids):
                if run.get("stop_requested"):
                    stopped = True
                    break

                cls = get_test_by_id(test_id)
                if not cls:
                    res = {
                        "id": test_id, "name": test_id,
                        "status": "error", "message": "Test not found", "logs": []
                    }
                    run["results"].append(res)
                    run_logger.record_result(res)
                    self._emit(run_id, "test_result", res)
                    continue

                logs = []

                def log(msg, _l=logs, _tid=test_id, _rid=run_id):
                    _l.append(msg)
                    if isinstance(msg, str) and msg.strip() == "__E0_REMINDER__":
                        self.socketio.emit("e0_reminder", {"run_id": _rid})
                        return   # skip emitting this token as a log line
                    self.socketio.emit("test_log", {
                        "run_id": _rid, "test_id": _tid, "message": msg
                    })

                run_logger.log_test_start(test_id, cls.name)
                self._emit(run_id, "test_start", {
                    "test_id": test_id, "name": cls.name,
                    "index": i, "cycle": cycle, "total_cycles": cycles
                })

                try:
                    instance = cls()
                    if params and test_id in params:
                        instance.params = params[test_id]
                    tr = instance.run(driver, log)
                    res = {
                        "id":      test_id,
                        "name":    cls.name,
                        "status":  tr.status.value if hasattr(tr.status, "value") else tr.status,
                        "message": tr.message,
                        "details": (
                        {k: v for k, v in tr.details.items() if k != "html_summary"}
                        if isinstance(tr.details, dict) else str(tr.details)
                    ) if tr.details else None,
                    "html_summary": (
                        tr.details.get("html_summary")
                        if isinstance(tr.details, dict) else None
                    ),
                        "logs":    logs,
                    }
                except Exception as e:
                    res = {
                        "id":      test_id,
                        "name":    cls.name,
                        "status":  "error",
                        "message": str(e),
                        "logs":    logs,
                    }

                run_logger.log_test_end(test_id, res["status"], res["message"])
                run_logger.record_result(res)
                run["results"].append(res)
                self._emit(run_id, "test_result", res)
                time.sleep(0.2)

                if stop_on_error and res["status"] in ("fail", "error"):
                    stopped = True
                    break

            if stopped:
                break

        if stopped or run.get("stop_requested"):
            self._emit(run_id, "run_stopped", {"run_id": run_id})
            run["status"] = "stopped"
            run_logger.finalize("stopped")
            return

        result_path = run_logger.finalize("complete")
        run["status"] = "complete"
        run["log_path"] = result_path
        self._emit(run_id, "run_complete", {
            "run_id":   run_id,
            "results":  run["results"],
            "log_path": result_path,
        })

    def _emit(self, run_id, event, data):
        self.socketio.emit(event, {**data, "run_id": run_id})

    def get_run_status(self, run_id: str) -> dict:
        return self.runs.get(run_id, {"error": "Run not found"})

    def stop_run(self, run_id: str):
        if run_id in self.runs:
            self.runs[run_id]["stop_requested"] = True