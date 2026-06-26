"""
fio_registry.py — shared module for tracking the currently running fio process.

Both app.py (GUI-launched FIO) and E-category tests register their fio
Popen objects here so the /api/ctrl/kill-fio endpoint can terminate them
regardless of which code path launched the process.
"""
import threading

_lock        = threading.Lock()
_fio_process = None


def set_fio_process(proc):
    """Register a running fio Popen object (or None to clear)."""
    global _fio_process
    with _lock:
        _fio_process = proc


def get_fio_process():
    """Return the current fio Popen object, or None if not running."""
    with _lock:
        return _fio_process


def kill_fio() -> dict:
    """
    Terminate the registered fio process.
    Returns {"killed": bool, "message": str}.
    """
    global _fio_process
    with _lock:
        proc = _fio_process
    if proc is None or proc.poll() is not None:
        return {"killed": False, "message": "No fio process is running"}
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        with _lock:
            _fio_process = None
        return {"killed": True, "message": "fio process terminated"}
    except Exception as e:
        return {"killed": False, "message": str(e)}