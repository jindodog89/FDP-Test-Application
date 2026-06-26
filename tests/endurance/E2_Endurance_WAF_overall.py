"""
Test: E2. Endurance — WAF Calculation (All RUHs Concurrent)
Sequence:
  1. Delete all namespaces
  2. Disable FDP → Re-enable FDP  (clears hbmw / mbmw counters)
  3. Create a single namespace with 4 RUHs
  4. Run a single 48h 4k randwrite FIO workload across all 4 RUHs
     simultaneously (fdp_pli=0,1,2,3, fdp_pli_select=roundrobin)
  5. Poll nvme fdp stats every 30 min and record WAF samples
  6. Produce an HTML summary: WAF-over-time graph + performance charts
"""

import subprocess
import json
import tempfile
import os
import re as _re
import time
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestEnduranceWAFAllRUH(BaseTest):
    test_id  = "endurance_waf_all_ruh"
    name     = "E2. Endurance — WAF Calculation (All RUHs Concurrent)"
    description = (
        "Clears FDP stats by cycling FDP off/on and creating a fresh namespace "
        "with 4 RUHs. Runs a single 48-hour 4k randwrite FIO workload across "
        "all 4 RUHs concurrently (fdp_pli=0,1,2,3), polling WAF every 30 "
        "minutes. Produces a single WAF-over-time graph and performance summary."
    )
    category = "Endurance"
    tags     = ["fio", "waf", "endurance", "fdp-stats", "write-amplification",
                "long-running", "all-ruh"]

    DEFAULT_PARAMS = {
        "endgrp":            1,
        "fio_duration_sec":  48,         # hours (user input is in hours)
        "fio_block_size":    "4k",
        "fio_queue_depth":   64,
        "fio_num_jobs":      4,
    }

    def run(self, driver, log) -> TestResult:
        p      = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        # Convert user-supplied hours to seconds for internal use
        p["fio_duration_sec"] = int(p["fio_duration_sec"]) * 3600
        # poll_interval = duration / 20 (at least 5 s)
        p["poll_interval_sec"] = max(5, p["fio_duration_sec"] // 20)
        endgrp = p["endgrp"]
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)

        # ── Pre-flight ────────────────────────────────────────────────────────
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP,
                              "fio not found — install with: sudo apt install fio")
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

        # ══════════════════════════════════════════════════════════════════════
          # ── Validate existing device configuration ────────────────────────────
        log("Validating existing FDP configuration and namespace(s)...")
        list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        if list_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              f"list-ns failed: {list_r['stderr'].strip()}")
        ns_data  = list_r.get("data", {})
        raw_list = (ns_data.get("nsid_list") or ns_data.get("NamespaceList")
                    or (ns_data if isinstance(ns_data, list) else []))
        if not raw_list:
            return TestResult(TestStatus.FAIL,
                              "No namespaces found — run E0 first to set up the device.")
        first_nsid = int(raw_list[0]["nsid"] if isinstance(raw_list[0], dict)
                         else raw_list[0])
        ns_dev = ctrl_dev + f"n{first_nsid}"
        _m     = _re.search(r"nvme(\d+)n(\d+)", ns_dev)
        ng_dev = f"/dev/ng{_m.group(1)}n{_m.group(2)}" if _m else ns_dev
        log(f"  Using namespace: {ns_dev}  (generic: {ng_dev})")
        ruhs_r = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        if ruhs_r["rc"] != 0:
            return TestResult(TestStatus.FAIL,
                              "fdp status failed \u2014 FDP may not be enabled. Run E0 first.")
        ruhs   = driver.extract_ruhs(ruhs_r)
        if not ruhs:
            return TestResult(TestStatus.FAIL,
                              "No RU Handles found \u2014 FDP not configured. Run E0 first.")
        n_ruhs = len(ruhs)
        log(f"  FDP enabled  \u00b7  {n_ruhs} RU Handle(s) found")

        # Pre-conditioning reminder (emits special token caught by test_runner)
        log("__E0_REMINDER__")

      # Phase 2: Single 48h workload across all RUHs
        # ══════════════════════════════════════════════════════════════════════
        pli_str = ",".join(str(r) for r in range(n_ruhs))
        log(f"{'='*60}")
        log(f"Phase 2: {p['fio_duration_sec']//3600}h FIO workload — "
            f"fdp_pli={pli_str} (all RUHs concurrently)")
        log(f"{'='*60}")

        fio_job = self._build_fio_job(ng_dev, pli_str, p)
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".fio", delete=False) as ftmp:
            ftmp.write(fio_job)
            fio_path = ftmp.name

        # Baseline stats
        stats0 = self._read_fdp_stats(driver, log, ctrl_dev, endgrp)
        if stats0 is None:
            os.unlink(fio_path)
            return TestResult(TestStatus.FAIL,
                              "Cannot read FDP stats before FIO")
        log(f"  Baseline  hbmw={stats0['hbmw']:,}  mbmw={stats0['mbmw']:,}")

        # Launch fio in background
        log(f"  Starting FIO — polling every {p['poll_interval_sec']//60} min...")
        fio_proc = subprocess.Popen(
            ["fio", "--output-format=json", fio_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        fio_registry.set_fio_process(fio_proc)

        waf_series = []   # list of (elapsed_min, waf)
        start_time = time.time()
        poll_count = 0
        expected_polls = p["fio_duration_sec"] // p["poll_interval_sec"]

        try:
            while fio_proc.poll() is None:
                time.sleep(p["poll_interval_sec"])
                poll_count += 1
                elapsed_min = round((time.time() - start_time) / 60, 1)

                stats_now = self._read_fdp_stats(driver, log, ctrl_dev, endgrp)
                if stats_now is None:
                    log(f"  ⚠ Poll {poll_count}: stats read failed, skipping")
                    continue

                delta_h = stats_now["hbmw"] - stats0["hbmw"]
                delta_m = stats_now["mbmw"] - stats0["mbmw"]
                waf_val = round(delta_m / delta_h, 4) if delta_h > 0 else None

                log(f"  Poll {poll_count}/{expected_polls} @ {elapsed_min} min — "
                    f"Δhbmw={delta_h:,}  Δmbmw={delta_m:,}  "
                    f"WAF={waf_val if waf_val is not None else 'n/a'}")

                if waf_val is not None:
                    waf_series.append((elapsed_min, waf_val))

        finally:
            fio_registry.set_fio_process(None)
            if fio_proc.poll() is None:
                fio_proc.terminate()
                try:
                    fio_proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    fio_proc.kill()
            os.unlink(fio_path)

        stdout, stderr = fio_proc.communicate()
        log(f"  FIO exited (rc={fio_proc.returncode})")
        if fio_proc.returncode not in (0, -15):
            log(f"  ⚠ FIO stderr: {stderr.strip()[:300]}")

        # Final WAF sample
        stats_end = self._read_fdp_stats(driver, log, ctrl_dev, endgrp)
        if stats_end:
            delta_h = stats_end["hbmw"] - stats0["hbmw"]
            delta_m = stats_end["mbmw"] - stats0["mbmw"]
            elapsed_min = round((time.time() - start_time) / 60, 1)
            if delta_h > 0:
                waf_final = round(delta_m / delta_h, 4)
                waf_series.append((elapsed_min, waf_final))
                log(f"  Final WAF: {waf_final}")

        # Parse fio JSON for performance metrics
        perf = {}
        try:
            fio_json = json.loads(stdout)
            jobs = fio_json.get("jobs", [])
            if jobs:
                wr = jobs[0].get("write", {})
                perf = {
                    "bw_mbs": round(wr.get("bw_bytes", 0) / 1e6, 2),
                    "iops":   round(wr.get("iops", 0), 1),
                    "lat_us": round(wr.get("lat_ns", {}).get("mean", 0) / 1000, 1),
                    "io_mb":  round(wr.get("io_bytes", 0) / 1e6, 1),
                }
                log(f"  Perf — BW: {perf['bw_mbs']} MB/s  IOPS: {perf['iops']}  "
                    f"Lat: {perf['lat_us']} µs  Written: {perf['io_mb']} MB")
        except Exception as _e:
            log(f"  ⚠ Could not parse fio JSON: {_e}")

        # ══════════════════════════════════════════════════════════════════════
        # Phase 3: Build HTML summary
        # ══════════════════════════════════════════════════════════════════════
        log("\nPhase 3: Generating summary...")
        html_summary = self._build_html_summary(waf_series, perf, n_ruhs, p)

        # Verdict
        final_waf = waf_series[-1][1] if waf_series else None
        if final_waf is None:
            status = TestStatus.WARN
            msg    = "Workload completed but WAF could not be calculated"
        elif final_waf <= 1.5:
            status = TestStatus.PASS
            msg    = f"Excellent WAF {final_waf} across all {n_ruhs} RUHs"
        elif final_waf <= 3.0:
            status = TestStatus.WARN
            msg    = f"Acceptable WAF {final_waf} across all {n_ruhs} RUHs"
        else:
            status = TestStatus.WARN
            msg    = f"High WAF {final_waf} detected across all {n_ruhs} RUHs"

        self._save_html_summary(html_summary, log)
        return TestResult(status, msg, details={
            "waf_series":   waf_series,
            "perf":         perf,
            "html_summary": html_summary,
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_fio_job(self, ng_dev: str, pli_str: str, p: dict) -> str:
        lines = [
            "[global]",
            "ioengine=io_uring_cmd",
            "rw=randwrite",
            f"bs={p['fio_block_size']}",
            f"iodepth={p['fio_queue_depth']}",
            f"numjobs={p['fio_num_jobs']}",
            f"runtime={p['fio_duration_sec']}",
            "time_based=1",
            "fdp=1",
            f"fdp_pli={pli_str}",
            "fdp_pli_select=roundrobin",
            "",
            "[all_ruh_workload]",
            f"filename={ng_dev}",
            "",
        ]
        return "\n".join(lines)

    def _read_fdp_stats(self, driver, log, ctrl_dev: str,
                        endgrp: int = 1) -> dict | None:
        result = driver.run_cmd(
            ["fdp", "stats", ctrl_dev, f"--endgrp-id={endgrp}"],
            json_out=True
        )
        if result["rc"] != 0:
            log(f"  FDP stats error: {result['stderr'].strip()}")
            return None
        data = result.get("data", {})
        if not isinstance(data, dict):
            return None
        return {
            "hbmw": int(data.get("hbmw", 0)),
            "mbmw": int(data.get("mbmw", 0)),
        }

    def _build_html_summary(self, waf_series: list, perf: dict,
                             n_ruhs: int, p: dict) -> str:
        """Self-contained HTML: WAF-over-time line graph + performance charts."""
        duration_h = p["fio_duration_sec"] // 3600
        poll_min   = p["poll_interval_sec"] // 60
        color      = "#0d6efd"

        # WAF series data
        xs = "[" + ",".join(str(x) for x, _ in waf_series) + "]" \
             if waf_series else "[]"
        ys = "[" + ",".join(str(y) for _, y in waf_series) + "]" \
             if waf_series else "[]"
        final_waf = waf_series[-1][1] if waf_series else "N/A"

        # Performance metric cards (inline HTML, no chart needed for scalars)
        def metric_card(label, value, unit):
            return (f'<div class="card">'
                    f'<div class="card-val">{value}</div>'
                    f'<div class="card-lbl">{label}</div>'
                    f'<div class="card-unit">{unit}</div>'
                    f'</div>')

        perf_cards = (
            metric_card("Throughput",   perf.get("bw_mbs", "—"), "MB/s") +
            metric_card("IOPS",         perf.get("iops",   "—"), "") +
            metric_card("Avg Latency",  perf.get("lat_us", "—"), "µs") +
            metric_card("Total Written",perf.get("io_mb",  "—"), "MB")
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>E2 Endurance Summary</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body  {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#f8f9fa;color:#212529;margin:0;padding:24px;}}
  h1    {{font-size:20px;margin-bottom:4px;}}
  h2    {{font-size:15px;margin:28px 0 10px;color:#495057;
          border-bottom:1px solid #dee2e6;padding-bottom:6px;}}
  .meta {{font-size:12px;color:#6c757d;margin-bottom:20px;}}
  .graph-wrap{{background:#fff;border:1px solid #dee2e6;border-radius:8px;padding:18px 20px;}}
  .graph-title{{font-size:13px;font-weight:600;margin-bottom:10px;
                display:flex;align-items:center;gap:8px;}}
  .badge{{font-size:11px;font-weight:500;background:#e9ecef;border-radius:4px;
          padding:2px 8px;color:#495057;}}
  .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:8px;}}
  .card {{background:#fff;border:1px solid #dee2e6;border-radius:8px;
          padding:16px 18px;text-align:center;}}
  .card-val  {{font-size:26px;font-weight:700;color:#0d6efd;}}
  .card-lbl  {{font-size:12px;color:#6c757d;margin-top:4px;}}
  .card-unit {{font-size:11px;color:#adb5bd;}}
</style>
</head>
<body>
<h1>E2 Endurance Workload Summary — All RUHs Concurrent</h1>
<div class="meta">
  4k randwrite · {duration_h}h · fdp_pli=0,1,2,3 (roundrobin) ·
  WAF polled every {poll_min} min · FDP enabled · 1 NS · {n_ruhs} RUHs
</div>

<h2>Performance Metrics</h2>
<div class="cards">
{perf_cards}
</div>

<h2>WAF over Time (entire drive)</h2>
<div class="graph-wrap">
  <div class="graph-title">Write Amplification Factor
    <span class="badge">Final WAF: {final_waf}</span>
  </div>
  <canvas id="wafchart" height="120"></canvas>
  <script>(function(){{
    new Chart(document.getElementById('wafchart').getContext('2d'),{{
      type:'line',
      data:{{
        labels:{xs},
        datasets:[{{
          label:'WAF',
          data:{ys},
          borderColor:'{color}',
          backgroundColor:'{color}22',
          fill:true,tension:0.3,pointRadius:4,
        }}]
      }},
      options:{{
        responsive:true,
        plugins:{{legend:{{display:false}}}},
        scales:{{
          x:{{title:{{display:true,text:'Elapsed (min)'}},ticks:{{maxTicksLimit:16}}}},
          y:{{title:{{display:true,text:'WAF'}},min:1,suggestedMax:4}}
        }}
      }}
    }});
  }})();</script>
</div>
</body>
</html>"""

    def _save_html_summary(self, html: str, log) -> str | None:
        """
        Save the HTML summary to  <project_root>/Endurance Results/
        Returns the saved file path, or None on failure.
        """
        import os as _os
        from pathlib import Path as _Path
        from datetime import datetime as _dt
        # PROJECT_ROOT = tests/endurance/../../  →  fdp-tester/
        proj_root   = _Path(__file__).resolve().parent.parent.parent
        out_dir     = proj_root / "Endurance Results"
        out_dir.mkdir(exist_ok=True)
        ts        = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self.test_id.replace(" ", "_")
        filename  = f"{safe_name}_{ts}.html"
        out_path  = out_dir / filename
        try:
            out_path.write_text(html, encoding="utf-8")
            log(f"  ✓ Summary saved: {out_path}")
            return str(out_path)
        except Exception as _e:
            log(f"  ⚠ Could not save summary: {_e}")
            return None