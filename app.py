#!/usr/bin/env python3
"""
NVMe FDP Test Tool - Main Flask Application
"""

import os
import sys
import threading
import shlex
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from backend.test_runner import TestRunner
from backend.device_manager import DeviceManager
from backend import fio_registry

app = Flask(__name__, template_folder="templates", static_folder="frontend/static")
app.config["SECRET_KEY"] = "fdp-tester-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

device_manager = DeviceManager()
test_runner = TestRunner(socketio)


def _extract_nsid(raw) -> int:
    """
    Normalise a raw nsid value from nvme list-ns JSON output.
    nvme-cli may return each entry as a plain int (1), a string ("1"),
    or a dict ({"nsid": 1}) — handle all three.
    """
    if isinstance(raw, dict):
        return int(raw.get("nsid", raw.get("NSID", 0)))
    return int(raw)


def _attach_ns(driver, ctrl_dev, nsid, log_fn=None, cntlid: str = None):
    """
    Attach a namespace to the controller.
    Uses the queried cntlid (or falls back to 0x1 then no --controllers).
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    controllers = cntlid if cntlid else "0x1"
    r = driver.run_cmd(["attach-ns", ctrl_dev,
                        f"--namespace-id={nsid}",
                        f"--controllers={controllers}"], json_out=False)
    if r["rc"] == 0:
        return r
    # Fallback: some devices don't support --controllers at all
    _log(f"  attach-ns --controllers={controllers} failed "
         f"(rc={r['rc']}), retrying without --controllers...")
    r2 = driver.run_cmd(["attach-ns", ctrl_dev,
                         f"--namespace-id={nsid}"], json_out=False)
    return r2


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices", methods=["GET"])
def get_devices():
    devices = device_manager.list_devices()
    return jsonify({"devices": devices})


@app.route("/api/device/<path:device>/info", methods=["GET"])
def get_device_info(device):
    dev_path = f"/dev/{device}"
    info = device_manager.get_fdp_info(dev_path)
    return jsonify(info)


@app.route("/api/tests", methods=["GET"])
def get_tests():
    tests = test_runner.get_available_tests()
    return jsonify({"tests": tests})


@app.route("/api/run", methods=["POST"])
def run_tests():
    data = request.json or {}
    device = data.get("device")
    test_ids = data.get("tests", [])
    if not device:
        return jsonify({"error": "No device specified"}), 400
    if not test_ids:
        return jsonify({"error": "No tests specified"}), 400
    run_id = test_runner.start_run(
        device, test_ids,
        params=data.get("params", {}),
        cycles=int(data.get("cycles", 1)),
        stop_on_error=bool(data.get("stop_on_error", False)),
    )
    return jsonify({"run_id": run_id, "status": "started"})


@app.route("/api/run/<run_id>/status", methods=["GET"])
def get_run_status(run_id):
    return jsonify(test_runner.get_run_status(run_id))


@app.route("/api/run/<run_id>/stop", methods=["POST"])
def stop_run(run_id):
    test_runner.stop_run(run_id)
    return jsonify({"status": "stopping"})

@app.route("/api/ctrl/list-ns", methods=["POST"])
def ctrl_list_ns():
    data    = request.json or {}
    device  = data.get("device")
    if not device:
        return jsonify({"error": "No device specified"}), 400

    driver = device_manager._make_driver(device)
    result = driver.run_cmd(["list-ns", device, "--all"], json_out=True)

    if result["rc"] != 0:
        # Fallback: try id-ns for nsid 1
        return jsonify({"error": result["stderr"].strip() or "list-ns failed", "raw": result["stdout"]})

    data_out = result.get("data", {})
    namespaces = []

    # nvme list-ns returns a list of nsids; fetch details for each
    nsid_list = []
    if isinstance(data_out, dict):
        nsid_list = data_out.get("nsid_list", data_out.get("NamespaceList", []))
    elif isinstance(data_out, list):
        nsid_list = data_out

    for nsid in nsid_list[:32]:  # cap at 32 for safety
        nsid_int = _extract_nsid(nsid)
        ns_info = {"nsid": nsid_int}
        id_result = driver.run_cmd(["id-ns", device, "-n", str(nsid_int)], json_out=True)
        if id_result["rc"] == 0:
            ns_data = id_result.get("data", {})
            if isinstance(ns_data, dict):
                nsze   = ns_data.get("nsze", 0)
                # Resolve the active LBA format entry.
                # nvme-cli may return the format list under "lbafs" or "lbaf".
                # Each entry is a dict with keys: lbaf (index), ds, ms, rp, in_use.
                # The active entry is the one with in_use=1; fall back to the
                # entry whose "lbaf" index matches flbas bits[3:0].
                flbas_raw = ns_data.get("flbas", 0)
                flbas_idx = (int(flbas_raw) & 0xF) if not isinstance(flbas_raw, dict) else 0
                lbaf_list = ns_data.get("lbafs", ns_data.get("lbaf", [{}]))
                # Prefer the entry explicitly marked in_use=1
                active = next((e for e in lbaf_list
                               if isinstance(e, dict) and e.get("in_use", 0)), None)
                if active is None:
                    # Fall back to matching by lbaf index field, then by list position
                    active = next((e for e in lbaf_list
                                   if isinstance(e, dict) and int(e.get("lbaf", -1)) == flbas_idx),
                                  lbaf_list[flbas_idx] if flbas_idx < len(lbaf_list) else lbaf_list[0])
                lbads  = int(active.get("ds", 9)) if isinstance(active, dict) else 9
                lba_sz = 2 ** lbads if lbads else 512
                nsfeat = ns_data.get("nsfeat", 0)
                # nsfeat may be a dict of bitfields or a plain int depending on nvme-cli version
                if isinstance(nsfeat, dict):
                    fdp_bit = bool(nsfeat.get("fdp", nsfeat.get("FDP", 0)))
                else:
                    fdp_bit = bool(int(nsfeat) & (1 << 4))
                ns_info["size_gb"]  = round(int(nsze) * lba_sz / 1e9, 2)
                ns_info["lba_size"] = lba_sz
                ns_info["fdp"]      = fdp_bit
        namespaces.append(ns_info)

    if not namespaces and result["stdout"].strip():
        return jsonify({"namespaces": [], "raw": result["stdout"].strip()})

    return jsonify({"namespaces": namespaces})


@app.route("/api/ctrl/delete-ns", methods=["POST"])
def ctrl_delete_ns():
    """Delete a specific list of namespace IDs (detach then delete each)."""
    import re as _re
    data   = request.json or {}
    device = data.get("device")
    nsids  = data.get("nsids", [])
    if not device:
        return jsonify({"error": "No device specified"}), 400
    if not nsids:
        return jsonify({"error": "No namespace IDs specified"}), 400

    # Always use the controller device (/dev/nvme0) — once the first namespace
    # is deleted its device file (/dev/nvme0n1) disappears, so subsequent
    # delete-ns calls against it fail with "device not found".
    ctrl_dev = _re.sub(r"n\d+$", "", device)
    driver   = device_manager._make_driver(ctrl_dev)
    results  = []
    for nsid in nsids:
        nsid = int(nsid)
        driver.run_cmd(["detach-ns", ctrl_dev, f"--namespace-id={nsid}",
                        "--controllers=0x1"], json_out=False)
        del_res = driver.run_cmd(["delete-ns", ctrl_dev,
                                  f"--namespace-id={nsid}"], json_out=False)
        success = del_res["rc"] == 0 or "success" in del_res["stdout"].lower()
        results.append({
            "nsid":    nsid,
            "success": success,
            "message": "Deleted successfully" if success else del_res["stderr"].strip(),
        })
    deleted = sum(1 for r in results if r["success"])
    return jsonify({"deleted": deleted, "results": results})


@app.route("/api/ctrl/toggle-fdp", methods=["POST"])
def ctrl_toggle_fdp():
    """
    Enable or disable FDP on an endurance group.
    Sequence required by NVMe spec:
      1. Save NS geometry (list-ns + id-ns per NSID)
      2. Delete all namespaces (broadcast NSID 0xFFFFFFFF)
      3. Set Features FID 0x1D on the controller device
      4. Re-create and re-attach each namespace
    """
    import re as _re
    data    = request.json or {}
    device  = data.get("device")        # may be namespace or controller path
    enable  = bool(data.get("enable"))  # True = enable, False = disable
    endgrp  = int(data.get("endgrp", 1))

    if not device:
        return jsonify({"error": "No device specified"}), 400

    driver   = device_manager._make_driver(device)
    ctrl_dev = _re.sub(r"n\d+$", "", device)
    log_lines = []

    def step(msg):
        log_lines.append(msg)

    # ── Step 1: Save NS geometry ──────────────────────────────────────────────
    step("Saving namespace geometry...")
    ns_list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
    saved_ns  = []
    if ns_list_r["rc"] == 0:
        ns_data  = ns_list_r.get("data", {})
        raw_list = []
        if isinstance(ns_data, dict):
            raw_list = ns_data.get("nsid_list", ns_data.get("NamespaceList", []))
        elif isinstance(ns_data, list):
            raw_list = ns_data
        for raw in raw_list:
            nsid = int(raw["nsid"]) if isinstance(raw, dict) else int(raw)
            ns_info = {"nsid": nsid, "nsze": 0, "ncap": 0, "flbas": 0,
                       "nphndls": 0, "endg_id": endgrp}
            idr = driver.run_cmd(["id-ns", ctrl_dev, f"--namespace-id={nsid}"],
                                 json_out=True)
            if idr["rc"] == 0:
                d = idr.get("data", {})
                if isinstance(d, dict):
                    ns_info["nsze"]  = int(d.get("nsze", 0))
                    ns_info["ncap"]  = int(d.get("ncap", ns_info["nsze"]))
                    ns_info["flbas"] = int(d.get("flbas", 0)) & 0xF
            saved_ns.append(ns_info)
    step(f"  Found {len(saved_ns)} namespace(s)")

    # ── Step 2: Delete all namespaces ─────────────────────────────────────────
    step("Deleting all namespaces (broadcast NSID 0xFFFFFFFF)...")
    if saved_ns:
        del_r = driver.run_cmd(["delete-ns", ctrl_dev,
                                "--namespace-id=0xFFFFFFFF"], json_out=False)
        if del_r["rc"] != 0:
            return jsonify({
                "success": False,
                "error":   f"delete-ns failed: {del_r['stderr'].strip()}",
                "log":     log_lines,
            })
        step("  ✓ All namespaces deleted")
    else:
        step("  No namespaces to delete")

    # ── Step 3: Set Features FID 0x1D ─────────────────────────────────────────
    action = "Enabling" if enable else "Disabling"
    step(f"{action} FDP (Set Features FID 0x1D, endgrp={endgrp})...")
    cdw10   = 0x1D | 0x80000000        # FID with Save bit
    cdw11   = endgrp                   # Endurance Group Identifier
    cdw12   = 0x1 if enable else 0x0   # Feature value
    sf_r = driver.run_cmd([
        "admin-passthru", ctrl_dev,
        "--opcode=0x09",
        f"--cdw10={cdw10}",
        f"--cdw11={cdw11}",
        f"--cdw12={cdw12}",
    ], json_out=False)

    if sf_r["rc"] != 0:
        # Restore namespaces before returning failure
        step(f"  ✗ Set Features failed: {sf_r['stderr'].strip()}")
        step("Restoring namespaces after failed Set Features...")
        _restore_ns_list(driver, ctrl_dev, saved_ns, step)
        return jsonify({
            "success": False,
            "error":   f"Set Features FID 0x1D failed: {sf_r['stderr'].strip()}",
            "log":     log_lines,
        })
    step(f"  ✓ FDP {'enabled' if enable else 'disabled'}")

    # ── Step 4: Re-create and re-attach namespaces ────────────────────────────
    step("Restoring namespaces...")
    _restore_ns_list(driver, ctrl_dev, saved_ns, step)

    return jsonify({
        "success":    True,
        "fdp_enabled": enable,
        "log":        log_lines,
    })


def _restore_ns_list(driver, ctrl_dev, saved_ns, step):
    """Helper: re-create and re-attach a list of saved namespaces."""
    import re as _re
    for ns in saved_ns:
        args = [
            "create-ns", ctrl_dev,
            f"--nsze={ns['nsze']}",
            f"--ncap={ns['ncap']}",
            f"--flbas={ns['flbas']}",
            "--nmic=0",
            f"--endg-id={ns['endg_id']}",
        ]
        if ns["nphndls"] > 0:
            args.append(f"--nphndls={ns['nphndls']}")
        cr = driver.run_cmd(args, json_out=False)
        if cr["rc"] != 0:
            step(f"  ⚠ create-ns failed: {cr['stderr'].strip()}")
            continue
        out      = cr["stdout"] + cr["stderr"]
        m        = _re.search(r"nsid[:\s]+(\d+)", out, _re.IGNORECASE)
        new_nsid = int(m.group(1)) if m else ns["nsid"]
        at = _attach_ns(driver, ctrl_dev, new_nsid, step)
        if at["rc"] == 0:
            step(f"  ✓ Restored NSID {new_nsid}")
        else:
            step(f"  ⚠ attach-ns failed: {at['stderr'].strip()}")


@app.route("/api/ctrl/delete-all-ns", methods=["POST"])
def ctrl_delete_all_ns():
    data   = request.json or {}
    device = data.get("device")
    if not device:
        return jsonify({"error": "No device specified"}), 400

    driver = device_manager._make_driver(device)

    # Get list of all namespaces first
    list_result = driver.run_cmd(["list-ns", device, "--all"], json_out=True)
    ns_data = list_result.get("data", {})
    nsid_list = []
    if isinstance(ns_data, dict):
        nsid_list = ns_data.get("nsid_list", ns_data.get("NamespaceList", []))
    elif isinstance(ns_data, list):
        nsid_list = ns_data

    if not nsid_list:
        return jsonify({"deleted": 0, "results": []})

    results = []
    for nsid in nsid_list:
        nsid = _extract_nsid(nsid)
        # Detach first, then delete
        driver.run_cmd(["detach-ns", device, f"--namespace-id={nsid}", "--controllers=0x1"],
                       json_out=False)
        del_result = driver.run_cmd(
            ["delete-ns", device, f"--namespace-id={nsid}"], json_out=False
        )
        success = del_result["rc"] == 0 or "success" in del_result["stdout"].lower()
        results.append({
            "nsid":    nsid,
            "success": success,
            "message": "Deleted successfully" if success else del_result["stderr"].strip()
        })

    deleted = sum(1 for r in results if r["success"])
    return jsonify({"deleted": deleted, "results": results})


@app.route("/api/ctrl/create-ns", methods=["POST"])
def ctrl_create_ns():
    import re as _re, time as _time
    data = request.json or {}
    device = data.get("device")
    if not device:
        return jsonify({"error": "No device specified"}), 400

    required = ["nsze", "ncap"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    driver     = device_manager._make_driver(device)
    blk_device = _re.sub(r'n\d+$', '', device)   # controller dev (/dev/nvme0)
    nsze       = int(data["nsze"])
    ncap       = int(data["ncap"])
    block_size = int(data.get("block_size", 4096))
    nphndls    = int(data.get("nphndls", 8))
    phndls     = data.get("phndls", "").strip()
    endg_id    = int(data.get("endg_id", 1))

    # Always use the controller device for create-ns
    create_args = [
        "create-ns", blk_device,
        f"--nsze={nsze}",
        f"--ncap={ncap}",
        f"--block-size={block_size}",
        f"--endg-id={endg_id}",
        f"--nphndls={nphndls}",
    ]
    if phndls:
        create_args.append(f"--phndls={phndls}")

    create_result = driver.run_cmd(create_args, json_out=False)
    commands      = [" ".join(["nvme"] + create_args)]

    if create_result["rc"] != 0:
        stderr = create_result["stderr"].strip()
        stdout = create_result["stdout"].strip()
        return jsonify({
            "error":    f"create-ns failed: {stderr or stdout}",
            "detail":   stdout,
            "commands": commands,
        })

    # ── Parse NSID from create-ns output ─────────────────────────────────────
    output = create_result["stdout"] + create_result["stderr"]
    match  = _re.search(r'nsid[:\s]+(\d+)', output, _re.IGNORECASE)
    if match:
        nsid = int(match.group(1))
    else:
        # Fallback: give the kernel a moment to register the namespace,
        # then find the highest NSID (the one just created).
        _time.sleep(1)
        list_result = driver.run_cmd(
            ["list-ns", blk_device, "--all"], json_out=True)
        ns_data   = list_result.get("data", {})
        nsid_list = []
        if isinstance(ns_data, dict):
            nsid_list = ns_data.get("nsid_list",
                                    ns_data.get("NamespaceList", []))
        elif isinstance(ns_data, list):
            nsid_list = ns_data
        nsid = max((_extract_nsid(n) for n in nsid_list), default=1)

    # ── Attach the new namespace ──────────────────────────────────────────────
    # Brief pause so the kernel has time to register the new NSID before attach
    _time.sleep(0.5)

    # Query the actual controller ID instead of hard-coding 0x1
    cntlid = _get_cntlid(driver, blk_device)
    attach_result = _attach_ns(driver, blk_device, nsid, cntlid=cntlid)
    attach_cmd    = f"nvme attach-ns {blk_device} --namespace-id={nsid} --controllers={cntlid}"
    commands.append(attach_cmd)

    attach_ok  = (attach_result["rc"] == 0 or
                  "success" in attach_result["stdout"].lower())

    # Retry once on transient failure (device may still be processing create-ns)
    if not attach_ok:
        _time.sleep(2)
        attach_result = _attach_ns(driver, blk_device, nsid)
        attach_ok     = (attach_result["rc"] == 0 or
                         "success" in attach_result["stdout"].lower())

    attach_msg = ("Attached successfully" if attach_ok
                  else attach_result["stderr"].strip()
                       or attach_result["stdout"].strip())

    return jsonify({
        "nsid":           nsid,
        "attach_success": attach_ok,
        "attach_result":  attach_msg,
        "commands":       commands,
    })

@app.route("/api/ctrl/run-fio", methods=["POST"])
def ctrl_run_fio():
    """
    Build and execute a fio job from the GUI parameters.

    Request JSON fields:
      device         : NVMe device path (used for context / fallback)
      ioengine       : fio IO engine (default: io_uring_cmd)
      rw             : IO pattern (write, randwrite, read, randread, randrw)
      bs             : Block size string (e.g. "4k", "64k")
      iodepth        : IO queue depth (int)
      numjobs        : Number of worker threads (int)
      runtime        : Duration in seconds (int)
      fdp            : Enable FDP directives (bool)
      fdp_pli        : Placement List Index — single int or comma-separated list (e.g. "0,1,2,3")
      fdp_pli_select : PLI selection policy (roundrobin | random)
      filename       : Device file for fio (should be /dev/ngXnY for io_uring_cmd)
    """
    import subprocess, tempfile, os, json as _json
    data = request.json or {}

    device       = data.get("device")
    if not device:
        return jsonify({"error": "No device specified"}), 400

    ioengine     = data.get("ioengine",       "io_uring_cmd")
    direct       = int(data.get("direct",      1))
    rw           = data.get("rw",             "write")
    bs           = data.get("bs",             "4k")
    iodepth      = max(1, int(data.get("iodepth",   16)))
    numjobs      = max(1, int(data.get("numjobs",    1)))
    runtime      = max(1, int(data.get("runtime",    30)))
    fdp          = bool(data.get("fdp",       True))
    # If the client sends raw job file content (from the editable preview),
    # use it directly instead of building from individual params.
    job_file_content = data.get("job_file_content", "").strip()

    # fdp_pli may be a single int or a comma-separated list e.g. "0,1,2,3"
    fdp_pli      = str(data.get("fdp_pli", "0")).strip()
    fdp_pli_sel  = data.get("fdp_pli_select", "roundrobin")
    filename     = data.get("filename",       device)

    lines = [
        "[global]",
        f"ioengine={ioengine}",
        f"direct={direct}",
        f"rw={rw}",
        f"bs={bs}",
        f"iodepth={iodepth}",
        f"numjobs={numjobs}",
        f"runtime={runtime}",
        "time_based=1",
    ]
    if fdp:
        lines += [
            "fdp=1",
            f"fdp_pli={fdp_pli}",
            f"fdp_pli_select={fdp_pli_sel}",
        ]
    lines += ["", "[job]", f"filename={filename}", ""]
    job_text = "\n".join(lines)

    try:
        # Use raw content from the editable preview if provided
        final_job = job_file_content if job_file_content else job_text
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".fio", delete=False) as f_tmp:
            f_tmp.write(final_job)
            fio_path = f_tmp.name

        # Enable io_uring before running fio (required for io_uring_cmd engine)
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        proc = subprocess.Popen(
            ["fio", "--output-format=json", fio_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        fio_registry.set_fio_process(proc)
        try:
            fio_stdout, fio_stderr = proc.communicate(timeout=runtime + 60)
        except subprocess.TimeoutExpired:
            proc.kill()
            fio_stdout, fio_stderr = proc.communicate()
        fio_registry.set_fio_process(None)
        _fio_rc = proc.returncode

        class _R:
            def __init__(self, rc, out, err):
                self.returncode = rc
                self.stdout     = out
                self.stderr     = err
        result = _R(_fio_rc, fio_stdout, fio_stderr)
        os.unlink(fio_path)
    except FileNotFoundError:
        return jsonify({"error": "fio not found — install with: sudo apt install fio"})
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"fio timed out after {runtime + 60}s"})
    except Exception as e:
        return jsonify({"error": str(e)})

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        return jsonify({"error": stderr[:400] if stderr else "fio exited with non-zero status"})

    # Parse fio JSON output
    try:
        fio_data = _json.loads(result.stdout)
        jobs = fio_data.get("jobs", [])
        if not jobs:
            return jsonify({"error": "fio returned no job results"})
        key = "write" if rw in ("write", "randwrite") else "read"
        wr = jobs[0].get(key, {})
        return jsonify({
            "bw_mbs": round(wr.get("bw_bytes", 0) / 1e6, 2),
            "iops":   round(wr.get("iops", 0), 1),
            "lat_us": round(wr.get("lat_ns", {}).get("mean", 0) / 1000, 1),
            "io_mb":  round(wr.get("io_bytes", 0) / 1e6, 1),
        })
    except Exception:
        return jsonify({"error": "fio ran but output could not be parsed",
                        "raw": result.stdout[:500]})




def _get_cntlid(driver, ctrl_dev: str) -> str:
    """
    Query the actual controller ID via id-ctrl and return it as a hex string
    suitable for --controllers=<value>.  Falls back to "0x1" on any failure.
    """
    try:
        r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        if r["rc"] == 0:
            data = r.get("data", {})
            if isinstance(data, dict):
                cntlid = data.get("cntlid")
                if cntlid is not None:
                    return hex(int(cntlid))
        # Text fallback: parse "cntlid : <N>" from stdout
        import re as _re
        m = _re.search(r"cntlid\s*[:|]\s*(\d+)", r.get("stdout", ""))
        if m:
            return hex(int(m.group(1)))
    except Exception:
        pass
    return "0x1"


@app.route("/api/ctrl/fdp-stats", methods=["POST"])
def ctrl_fdp_stats():
    """Return live nvme fdp stats for the given device/endgrp."""
    data   = request.json or {}
    device = data.get("device")
    endgrp = int(data.get("endgrp", 1))
    if not device:
        return jsonify({"error": "No device specified"}), 400
    import re as _re
    ctrl_dev = _re.sub(r"n\d+$", "", device)
    driver   = device_manager._make_driver(ctrl_dev)
    r        = driver.fdp_stats(endgrp=endgrp)
    return jsonify({"rc": r["rc"], "data": r.get("data"), "stderr": r.get("stderr","")})


@app.route("/api/ctrl/fdp-usage", methods=["POST"])
def ctrl_fdp_usage():
    """Return live nvme fdp usage for the given device/endgrp."""
    data   = request.json or {}
    device = data.get("device")
    endgrp = int(data.get("endgrp", 1))
    if not device:
        return jsonify({"error": "No device specified"}), 400
    import re as _re
    ctrl_dev = _re.sub(r"n\d+$", "", device)
    driver   = device_manager._make_driver(ctrl_dev)
    r        = driver.fdp_usage(endgrp=endgrp)
    return jsonify({"rc": r["rc"], "data": r.get("data"), "stderr": r.get("stderr","")})


@app.route("/api/ctrl/update-ruh", methods=["POST"])
def ctrl_update_ruh():
    """
    Issue IO Management Send — Reclaim Unit Handle Update (RUHU) for the
    specified RUH IDs on the given namespace.

    Uses: nvme fdp update <ctrl_dev> -n <nsid> -p <ruh_ids,...>
    """
    import re as _re
    data    = request.json or {}
    device  = data.get("device")
    nsid    = int(data.get("nsid", 1))
    ruh_ids = data.get("ruh_ids", [])

    if not device:
        return jsonify({"error": "No device specified"}), 400
    if not ruh_ids:
        return jsonify({"error": "No RUH IDs specified"}), 400

    # nvme fdp update requires the namespace device (e.g. /dev/nvme0n1)
    # and PID numbers; build ns_dev from ctrl_dev + nsid
    ctrl_dev = _re.sub(r"n\d+$", "", device)
    ns_dev   = ctrl_dev + f"n{nsid}"
    driver   = device_manager._make_driver(ns_dev)

    pids = ",".join(str(p) for p in ruh_ids)
    r = driver.run_cmd([
        "fdp", "update", ns_dev,
        f"--namespace-id={nsid}",
        f"--pids={pids}",
    ], json_out=False)

    if r["rc"] != 0:
        return jsonify({
            "error":  r["stderr"].strip() or r["stdout"].strip() or f"rc={r['rc']}",
            "rc":     r["rc"],
        })
    return jsonify({"ok": True, "updated": ruh_ids, "cmd": r.get("cmd","")})


@app.route("/api/ctrl/ruh-read", methods=["POST"])
def ctrl_ruh_read():
    """
    Perform nvme read on the namespace device.
    Returns success/error and a hex preview of the first 64 bytes read.
    """
    import re as _re, tempfile, os
    data        = request.json or {}
    device      = data.get("device")
    nsid        = int(data.get("nsid", 1))
    start_block = data.get("start_block", 0)
    block_count = int(data.get("block_count", 0))
    block_size  = int(data.get("block_size", 4096))
    data_size   = int(data.get("data_size", 4096))

    if not device:
        return jsonify({"error": "No device specified"}), 400

    import re as _re2
    ctrl_dev = _re2.sub(r"n\d+$", "", device)
    ns_dev   = ctrl_dev + f"n{nsid}"
    driver   = device_manager._make_driver(ns_dev)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as fh:
        out_path = fh.name
    try:
        r = driver.run_cmd([
            "read", ns_dev,
            f"--namespace-id={nsid}",
            f"--start-block={start_block}",
            f"--block-count={block_count}",
            f"--block-size={block_size}",
            f"--data-size={data_size}",
            f"--data={out_path}",
        ], json_out=False)
        if r["rc"] != 0:
            return jsonify({
                "error": r["stderr"].strip() or r["stdout"].strip() or f"rc={r['rc']}",
                "rc": r["rc"],
            })
        with open(out_path, "rb") as fh:
            raw = fh.read(64)
        return jsonify({
            "ok":          True,
            "bytes_read":  data_size,
            "preview_hex": " ".join(f"{b:02x}" for b in raw),
        })
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


@app.route("/api/ctrl/kill-fio", methods=["POST"])
def ctrl_kill_fio():
    """Terminate the currently running fio process (GUI or E-test launched)."""
    result = fio_registry.kill_fio()
    return jsonify(result), (500 if not result["killed"] and "running" not in result["message"] else 200)


# ── LBA Map scan ──────────────────────────────────────────────────────────────
import threading as _threading
_lba_scan_stop = _threading.Event()

def _lba_scan_worker(device, mode, nsze, lba_size, socketio_ref):
    """
    Background LBA scan.  Reads the namespace directly via Python file I/O
    (no subprocess overhead).  Emits SocketIO events as each major cell
    (100 minor cells) completes so the frontend can fill the grid live.

    mode: 'sample'  → 1 read per minor cell  (~instant)
          'full'    → all reads in each minor cell range  (~minutes for 100 GB)
    """
    MAX_BYTES    = 100 * 1024 * 1024 * 1024          # 100 GiB hard cap
    max_lbas     = min(nsze, MAX_BYTES // lba_size)
    N_TOTAL      = 10_000                             # 100 major × 100 minor
    lbas_per_minor = max(1, max_lbas // N_TOTAL)
    CHUNK_LBAS   = 256                                # 256 × 4096 = 1 MiB per read

    results = []   # floats: 0.0 = empty, 0–1 = density, -1 = beyond capacity

    try:
        with open(device, 'rb', buffering=0) as f:
            for cell in range(N_TOTAL):
                if _lba_scan_stop.is_set():
                    socketio_ref.emit('lba_scan_stopped', {})
                    return

                start_lba = cell * lbas_per_minor
                end_lba   = min(start_lba + lbas_per_minor, max_lbas)

                if start_lba >= max_lbas:
                    results.append(-1.0)
                    # Still emit at major-cell boundaries
                    if (cell + 1) % 100 == 0:
                        maj = (cell + 1) // 100 - 1
                        socketio_ref.emit('lba_scan_progress', {
                            'major_idx': maj,
                            'cells': results[maj*100:(maj+1)*100],
                        })
                    continue

                if mode == 'sample':
                    buf1 = buf2 = b''
                    try:
                        f.seek(start_lba * lba_size)
                        buf1 = f.read(lba_size)
                        mid  = (start_lba + end_lba) // 2
                        f.seek(mid * lba_size)
                        buf2 = f.read(lba_size)
                    except OSError:
                        pass
                    density = 1.0 if (any(buf1) or any(buf2)) else 0.0
                else:
                    # Count non-zero LBAs individually within each read chunk.
                    # Counting only "any non-zero byte per chunk" is too coarse:
                    # random writes scattered across the namespace will make
                    # virtually every 1 MB chunk appear full even when only a
                    # fraction of LBAs have been written.
                    ZERO_LBA = b'\x00' * lba_size
                    filled_lbas = total_lbas = 0
                    f.seek(start_lba * lba_size)
                    lba = start_lba
                    while lba < end_lba:
                        n   = min(CHUNK_LBAS, end_lba - lba)
                        buf = f.read(n * lba_size)
                        if not buf:
                            break
                        actual = len(buf) // lba_size
                        for i in range(actual):
                            if buf[i * lba_size:(i + 1) * lba_size] != ZERO_LBA:
                                filled_lbas += 1
                        total_lbas += actual
                        lba += n
                    density = filled_lbas / total_lbas if total_lbas else 0.0

                results.append(density)

                if (cell + 1) % 100 == 0:
                    maj = (cell + 1) // 100 - 1
                    socketio_ref.emit('lba_scan_progress', {
                        'major_idx': maj,
                        'cells': results[maj*100:(maj+1)*100],
                    })

        socketio_ref.emit('lba_scan_complete', {
            'results':        results,
            'max_lbas':       max_lbas,
            'lba_size':       lba_size,
            'lbas_per_minor': lbas_per_minor,
            'mode':           mode,
        })

    except PermissionError:
        socketio_ref.emit('lba_scan_error',
            {'error': f'Permission denied reading {device}. Run the server as root.'})
    except Exception as e:
        socketio_ref.emit('lba_scan_error', {'error': str(e)})


@app.route("/api/ctrl/lba-scan", methods=["POST"])
def ctrl_lba_scan():
    """Start a background LBA scan on the selected namespace."""
    import re as _re
    data   = request.json or {}
    device = data.get("device")
    mode   = data.get("mode", "sample")   # 'sample' | 'full'
    if not device:
        return jsonify({"error": "No device specified"}), 400

    driver  = device_manager._make_driver(device)
    # Query nsze and lba_size from id-ns
    idr = driver.run_cmd(["id-ns", device], json_out=True)
    if idr["rc"] != 0:
        return jsonify({"error": f"id-ns failed: {idr['stderr'].strip()}"}), 500
    ns = idr.get("data", {})
    if not isinstance(ns, dict):
        return jsonify({"error": "Unexpected id-ns response"}), 500

    nsze     = int(ns.get("nsze", 0))
    flbas    = int(ns.get("flbas", 0)) & 0xF
    lbafs    = ns.get("lbafs") or ns.get("lbaf", [])
    lba_size = 4096
    if isinstance(lbafs, list) and flbas < len(lbafs):
        ds = lbafs[flbas].get("ds") or lbafs[flbas].get("lbads")
        if ds:
            lba_size = 1 << int(ds)

    if nsze == 0:
        return jsonify({"error": "Namespace size is 0"}), 500

    MAX_BYTES = 100 * 1024 * 1024 * 1024
    if nsze * lba_size > MAX_BYTES:
        nsze = MAX_BYTES // lba_size   # cap silently

    _lba_scan_stop.clear()
    t = _threading.Thread(
        target=_lba_scan_worker,
        args=(device, mode, nsze, lba_size, socketio),
        daemon=True
    )
    t.start()
    return jsonify({"started": True, "nsze": nsze, "lba_size": lba_size})


@app.route("/api/ctrl/lba-scan-stop", methods=["POST"])
def ctrl_lba_scan_stop():
    _lba_scan_stop.set()
    return jsonify({"stopped": True})


@app.route("/api/ctrl/upload-data-file", methods=["POST"])
def ctrl_upload_data_file():
    """
    Accept a file upload from the targeted-write modal browser button.
    Saves the file to a persistent temp directory and returns the server-side
    path so it can be passed directly to nvme write --data=<path>.
    """
    import tempfile, os
    if "file" not in request.files:
        return jsonify({"error": "No file in request"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    # Save into a dedicated upload dir next to app.py
    upload_dir = os.path.join(os.path.dirname(__file__), "uploaded_data_files")
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = os.path.basename(f.filename)   # strip any directory traversal
    dest_path = os.path.join(upload_dir, safe_name)
    f.save(dest_path)
    return jsonify({"path": dest_path, "filename": safe_name})


@app.route("/api/ctrl/targeted-write", methods=["POST"])
def ctrl_targeted_write():
    """
    Execute a targeted FDP write sequence from the GUI.
    Writes `num_writes` consecutive 4 KB blocks starting at a random LBA
    (0–1,000,000) to the specified placement handle (RUH index).

    Request JSON:
      device     : NVMe device path
      ruh        : Reclaim Unit Handle index (int, 0-based)
      num_writes : Number of consecutive writes (int, 1–1000)
      data_file  : Path to data source file (optional, defaults to /dev/zero)
    """
    import random
    data        = request.json or {}
    device      = data.get("device")
    ruh         = int(data.get("ruh", 0))
    num_writes  = max(1, min(int(data.get("num_writes", 10)), 1000))
    data_size   = int(data.get("data_size", 4096))
    block_count = int(data.get("block_count", 1))
    data_file   = data.get("data_file", "/dev/zero")
    fua         = bool(data.get("fua", False))
    # Use caller-supplied start LBA if provided, otherwise randomise
    raw_lba     = data.get("start_lba")
    start_lba   = int(raw_lba) if raw_lba is not None else random.randint(0, 1_000_000)

    if not device:
        return jsonify({"error": "No device specified"}), 400

    driver   = device_manager._make_driver(device)
    results  = []
    errors   = 0

    for i in range(num_writes):
        lba = start_lba + i
        res = driver.run_cmd([
            "write", device,
            f"--namespace-id=1",
            f"--start-block={lba}",
            f"--block-count={block_count - 1}",
            f"--data-size={data_size}",
            f"--data={data_file}",
            "--dir-type=2",
            f"--dir-spec={ruh}",
            *( ["--force-unit-access"] if fua else [] ),
        ], json_out=False)

        entry = {
            "write":   i + 1,
            "lba":     lba,
            "ruh":     ruh,
            "rc":      res["rc"],
            "success": res["rc"] == 0 or "success" in res["stdout"].lower(),
        }
        if not entry["success"]:
            entry["error"] = res["stderr"].strip() or res["stdout"].strip()
            errors += 1
        results.append(entry)

    return jsonify({
        "device":     device,
        "ruh":        ruh,
        "start_lba":  start_lba,
        "num_writes": num_writes,
        "completed":  len(results),
        "errors":     errors,
        "results":    results,
    })


@app.route("/api/ctrl/extract-fdp-config", methods=["POST"])
def ctrl_extract_fdp_config():
    """
    Run all FDP discovery commands against the selected device and store
    the results in the module-level dut_config singleton so that test
    scripts can access them via `from tests.dut_config import dut_config`.
    """
    data   = request.json or {}
    device = data.get("device")
    if not device:
        return jsonify({"error": "No device specified"}), 400

    from tests.dut_config import dut_config

    driver  = device_manager._make_driver(device)
    summary = dut_config.populate(driver)
    return jsonify(summary)


@socketio.on("connect")
def on_connect():
    emit("connected", {"message": "Connected to FDP Test Tool"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  NVMe FDP Test Tool  →  http://localhost:{port}\n")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)