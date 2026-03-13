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

app = Flask(__name__, template_folder="templates", static_folder="frontend/static")
app.config["SECRET_KEY"] = "fdp-tester-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

device_manager = DeviceManager()
test_runner = TestRunner(socketio)


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
    run_id = test_runner.start_run(device, test_ids)
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
        ns_info = {"nsid": int(nsid)}
        id_result = driver.run_cmd(["id-ns", device, "-n", str(nsid)], json_out=True)
        if id_result["rc"] == 0:
            ns_data = id_result.get("data", {})
            if isinstance(ns_data, dict):
                nsze   = ns_data.get("nsze", 0)
                lbads  = ns_data.get("lbaf", [{}])[0].get("ds", 9) if ns_data.get("lbaf") else 9
                lba_sz = 2 ** int(lbads) if lbads else 512
                nsfeat = ns_data.get("nsfeat", 0)
                ns_info["size_gb"]  = round(int(nsze) * lba_sz / 1e9, 2)
                ns_info["lba_size"] = lba_sz
                ns_info["fdp"]      = bool(int(nsfeat) & (1 << 4))
        namespaces.append(ns_info)

    if not namespaces and result["stdout"].strip():
        return jsonify({"namespaces": [], "raw": result["stdout"].strip()})

    return jsonify({"namespaces": namespaces})


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
        nsid = int(nsid)
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
    data = request.json or {}
    device = data.get("device")
    if not device:
        return jsonify({"error": "No device specified"}), 400

    required = ["nsze", "ncap", "flbas"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    driver   = device_manager._make_driver(device)
    nsze     = int(data["nsze"])
    ncap     = int(data["ncap"])
    flbas    = int(data["flbas"])
    dps      = int(data.get("dps", 0))
    nmic     = int(data.get("nmic", 0))
    nphndls  = int(data.get("nphndls", 8))
    endg_id  = int(data.get("endg_id", 1))

    create_args = [
        "create-ns", device,
        f"--nsze={nsze}",
        f"--ncap={ncap}",
        f"--flbas={flbas}",
        f"--dps={dps}",
        f"--nmic={nmic}",
        f"--endg-id={endg_id}",
        f"--nphndls={nphndls}",
        "--anagrp-id=1",
    ]

    create_result = driver.run_cmd(create_args, json_out=False)
    commands = [" ".join(["nvme"] + create_args)]

    if create_result["rc"] != 0:
        stderr = create_result["stderr"].strip()
        stdout = create_result["stdout"].strip()
        return jsonify({
            "error":  f"create-ns failed: {stderr or stdout}",
            "detail": stdout,
            "commands": commands,
        })

    # Parse new NSID from output (nvme-cli prints "create-ns: Success, created nsid:<N>")
    import re
    nsid = None
    output = create_result["stdout"] + create_result["stderr"]
    match = re.search(r'nsid[:\s]+(\d+)', output, re.IGNORECASE)
    if match:
        nsid = int(match.group(1))
    else:
        # Fallback: find the highest nsid after creation
        list_result = driver.run_cmd(["list-ns", device, "--all"], json_out=True)
        ns_data = list_result.get("data", {})
        nsid_list = []
        if isinstance(ns_data, dict):
            nsid_list = ns_data.get("nsid_list", ns_data.get("NamespaceList", []))
        elif isinstance(ns_data, list):
            nsid_list = ns_data
        nsid = max((int(n) for n in nsid_list), default=1)

    # Attach the new namespace
    attach_args = [
        "attach-ns", device,
        f"--namespace-id={nsid}",
        "--controllers=0x1",
    ]
    attach_result = driver.run_cmd(attach_args, json_out=False)
    commands.append(" ".join(["nvme"] + attach_args))

    attach_ok  = attach_result["rc"] == 0 or "success" in attach_result["stdout"].lower()
    attach_msg = "Attached successfully" if attach_ok else attach_result["stderr"].strip()

    return jsonify({
        "nsid":           nsid,
        "attach_success": attach_ok,
        "attach_result":  attach_msg,
        "commands":       commands,
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