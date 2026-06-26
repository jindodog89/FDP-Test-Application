"""
tests/utils.py — shared utility helpers used across multiple test cases.
"""


def _get_cntlid(driver, ctrl_dev: str) -> str:
    """Query the actual controller ID from id-ctrl. Falls back to '0x1'."""
    import re as _re
    try:
        r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        if r["rc"] == 0:
            data = r.get("data", {})
            if isinstance(data, dict):
                cntlid = data.get("cntlid")
                if cntlid is not None:
                    return hex(int(cntlid))
        # Text fallback
        m = _re.search(r"cntlid\s*[:|]\s*(\d+)", r.get("stdout", ""))
        if m:
            return hex(int(m.group(1)))
    except Exception:
        pass
    return "0x1"


def attach_ns(driver, ctrl_dev: str, nsid: int, log=None) -> dict:
    """
    Attach a namespace using the actual controller ID queried from id-ctrl.
    Falls back to omitting --controllers if the device rejects that option,
    since some drives do not support the --controllers parameter.

    Returns the result dict from driver.run_cmd().
    """
    def _log(msg):
        if log:
            log(msg)

    cntlid = _get_cntlid(driver, ctrl_dev)
    _log(f"  attach-ns --controllers={cntlid}")

    r = driver.run_cmd(
        ["attach-ns", ctrl_dev,
         f"--namespace-id={nsid}",
         f"--controllers={cntlid}"],
        json_out=False
    )
    if r["rc"] == 0:
        return r

    # Fallback: retry without --controllers
    _log(f"  attach-ns --controllers={cntlid} failed (rc={r['rc']}), "
         f"retrying without --controllers...")
    r2 = driver.run_cmd(
        ["attach-ns", ctrl_dev,
         f"--namespace-id={nsid}"],
        json_out=False
    )
    return r2