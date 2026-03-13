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

    def start_run(self, device: str, test_ids: list) -> str:
        run_id = str(uuid.uuid4())[:8]
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
            args=(run_id, device, test_ids),
            daemon=True
        )
        t.start()
        return run_id

    def _execute(self, run_id: str, device: str, test_ids: list):
        from backend.drivers.nvme_cli_driver import NVMeCliDriver
        from tests.registry import get_test_by_id

        driver     = NVMeCliDriver(device)
        run        = self.runs[run_id]
        run_logger = RunLogger(run_id, device, test_ids)

        self._emit(run_id, "run_start", {"run_id": run_id, "total": len(test_ids)})

        for i, test_id in enumerate(test_ids):
            if run.get("stop_requested"):
                self._emit(run_id, "run_stopped", {"run_id": run_id})
                run["status"] = "stopped"
                run_logger.finalize("stopped")
                return

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
                self.socketio.emit("test_log", {
                    "run_id": _rid, "test_id": _tid, "message": msg
                })

            run_logger.log_test_start(test_id, cls.name)
            self._emit(run_id, "test_start", {
                "test_id": test_id, "name": cls.name, "index": i
            })

            try:
                tr = cls().run(driver, log)
                res = {
                    "id":      test_id,
                    "name":    cls.name,
                    "status":  tr.status.value if hasattr(tr.status, "value") else tr.status,
                    "message": tr.message,
                    "details": str(tr.details) if tr.details else None,
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