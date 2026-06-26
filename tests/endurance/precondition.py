"""
Shared pre-conditioning helper used by both E0 and E1.

run_precondition(ng_dev, passes, bs, iodepth, numjobs, log)
  → (success: bool, message: str)

Runs `passes` sequential full-device 4k write passes via fio
(ioengine=io_uring_cmd, rw=write, size=100%).
"""

import subprocess
import tempfile
import os


def run_precondition(
    ng_dev:   str,
    passes:   int  = 2,
    bs:       str  = "4k",
    iodepth:  int  = 16,
    numjobs:  int  = 1,
    n_ruhs:   int  = 1,
    log       = None,
) -> tuple:
    """
    Fill `ng_dev` to capacity `passes` times with sequential 4k writes.
    n_ruhs controls how many placement handles to write through (0 or 1 →
    only PID 0; >1 → all PIDs 0..n_ruhs-1 round-robin for full RUH coverage).
    Returns (True, success_msg) or (False, error_msg).
    """

    def _log(msg):
        if log:
            log(msg)

    _log(f"Pre-conditioning: {passes} sequential fill pass(es) on {ng_dev}")
    _log(f"  Settings: bs={bs}  iodepth={iodepth}  numjobs={numjobs}")

    for i in range(1, passes + 1):
        _log(f"\n  Pass {i}/{passes}: sequential write, size=100%...")

        # Build fdp_pli list to write through all available RUHs so the
        # entire device is preconditioned across every reclaim unit.
        pli_list = ",".join(str(x) for x in range(max(1, n_ruhs)))
        job_lines = [
            "[global]",
            "ioengine=io_uring_cmd",
            "rw=write",
            f"bs={bs}",
            f"iodepth={iodepth}",
            f"numjobs={numjobs}",
            "size=100%",
            "fdp=1",
            f"fdp_pli={pli_list}",
            "fdp_pli_select=roundrobin",
            "",
            f"[precondition_pass_{i}]",
            f"filename={ng_dev}",
            "",
        ]
        job_text = "\n".join(job_lines)

        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".fio", delete=False) as f:
            f.write(job_text)
            fio_path = f.name

        try:
            result = subprocess.run(
                ["fio", "--output-format=normal", fio_path],
                capture_output=True, text=True,
                timeout=7 * 24 * 3600,   # 7-day hard ceiling per pass
            )
        finally:
            os.unlink(fio_path)

        if result.returncode != 0:
            err = (result.stderr or result.stdout).strip()[:400]
            _log(f"  ✗ Pass {i} failed (rc={result.returncode}): {err}")
            return False, f"Pre-conditioning pass {i}/{passes} failed: {err}"

        _log(f"  ✓ Pass {i}/{passes} complete")

    return True, f"Pre-conditioning complete — {passes} sequential fill pass(es) finished successfully"