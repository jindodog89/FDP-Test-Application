"""
Test: B6. FDP Update Command
Issues 'nvme fdp update' against a randomly selected namespace and placement
handle. Pass criteria: the command completes without error.
"""
import random
from tests.base_test import BaseTest, TestResult, TestStatus


class TestFDPUpdate(BaseTest):
    test_id = "fdp_update"
    name = "B6. FDP Update Command"
    description = (
        "Issues 'nvme fdp update' targeting a randomly selected namespace "
        "and placement handle. Verifies the command completes successfully."
    )
    category = "Basic"
    tags = ["fdp-update", "basic", "command"]

    def run(self, driver, log) -> TestResult:

        # ── Step 1: Pick a namespace ──────────────────────────────────────────
        log("Step 1: Enumerating namespaces...")
        import re as _re
        ctrl_dev = _re.sub(r'n\d+$', '', driver.device)
        list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)

        nsid = 1  # default
        if list_r["rc"] == 0:
            data = list_r.get("data", {})
            raw_list = []
            if isinstance(data, dict):
                raw_list = data.get("nsid_list", data.get("NamespaceList", []))
            elif isinstance(data, list):
                raw_list = data
            if raw_list:
                raw = random.choice(raw_list)
                nsid = int(raw["nsid"]) if isinstance(raw, dict) else int(raw)

        ns_dev = ctrl_dev + f"n{nsid}"
        log(f"  Selected namespace: NSID {nsid}  ({ns_dev})")

        # ── Step 2: Pick a placement handle ───────────────────────────────────
        log("Step 2: Enumerating placement handles...")
        pli = 0  # default
        ruhs_r = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        if ruhs_r["rc"] == 0:
            ruhs = driver.extract_ruhs(ruhs_r)
            if ruhs:
                ruh = random.choice(ruhs)
                pli = ruh.get("pid", ruh.get("ruhid", 0))

        log(f"  Selected placement handle (PID): {pli}")

        # ── Step 3: Run nvme fdp update ───────────────────────────────────────
        log(f"Step 3: Running 'nvme fdp update {ns_dev} --namespace-id={nsid} "
            f"--pil=1 --update-pih={pli}'...")
        result = driver.run_cmd([
            "fdp", "update", ns_dev,
            f"--namespace-id={nsid}",
            "--pil=1",
            f"--update-pih={pli}",
        ], json_out=False)

        log(f"  Return code: {result['rc']}")
        if result["stdout"].strip():
            log(f"  stdout: {result['stdout'].strip()}")
        if result["stderr"].strip():
            log(f"  stderr: {result['stderr'].strip()}")

        if result["rc"] == 0:
            log("✓ nvme fdp update completed successfully.")
            return TestResult(
                TestStatus.PASS,
                f"fdp update succeeded on NSID {nsid}, PID {pli}."
            )

        return TestResult(
            TestStatus.FAIL,
            f"fdp update failed (rc={result['rc']}): "
            f"{result['stderr'].strip() or result['stdout'].strip()}"
        )