"""
Test: E3. Endurance — Single RUH (RUH0) Isolation
Sequence:
  1. Read total NVM capacity from id-ctrl (tnvmcap) and divide equally across
     the requested number of namespaces.
  2. Delete all existing namespaces.
  3. Create N namespaces each using ONLY RUH0 (nphndls=1, phndls=0).
  4. Run 4k randwrite FIO across all created namespaces targeting RUH0
     (fdp_pli=0) for the configured duration.
  5. Poll nvme fdp stats every (duration / 20) seconds to track WAF over time.
  6. Produce an HTML summary: WAF-over-time graph + performance metric cards.

User-configurable parameters:
  n_namespaces       : Number of namespaces to create (default: 1)
  fio_duration_sec   : FIO run time in hours         (default: 24)
"""

import subprocess
import json
import tempfile
import os
import re as _re
import time
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestEnduranceSingleRUH(BaseTest):
    test_id  = "endurance_single_ruh"
    name     = "E3. Endurance — Single RUH (RUH0) Isolation"
    description = (
        "Creates N namespaces each mapped exclusively to RUH0. Runs 4k "
        "randwrite FIO targeting RUH0 for a configurable duration, polling "
        "WAF every (duration / 20) seconds. Produces a WAF-over-time graph "
        "and performance summary."
    )
    category = "Endurance"
    tags     = ["fio", "waf", "endurance", "single-ruh", "ruh0", "isolation",
                "long-running"]

    DEFAULT_PARAMS = {
        "n_namespaces":      1,
        "fio_duration_sec":  24,        # hours (user input is in hours)
        "endgrp":            1,
        "lba_size_bytes":    4096,
        "fio_block_size":    "4k",
        "fio_queue_depth":   64,
        "fio_num_jobs":      4,
    }

    def run(self, driver, log) -> TestResult:
        p           = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        n_ns        = max(1, int(p["n_namespaces"]))
        duration    = int(p["fio_duration_sec"]) * 3600  # convert hours → seconds
        endgrp      = p["endgrp"]
        lba_sz      = int(p["lba_size_bytes"])
        poll_sec    = max(5, duration // 20)   # at least 5 s between polls
        ctrl_dev    = _re.sub(r"n\d+$", "", driver.device)

        log(f"Configuration: {n_ns} namespace(s), {duration}s FIO, "
            f"poll every {poll_sec}s ({poll_sec//60:.1f} min)")

        # ── Pre-flight ────────────────────────────────────────────────────────
        if subprocess.run(["which", "fio"], capture_output=True).returncode != 0:
            return TestResult(TestStatus.SKIP,
                              "fio not found — install with: sudo apt install fio")
        subprocess.run(["sysctl", "-w", "kernel.io_uring_disabled=0"],
                       capture_output=True)

          # ── Validate existing configuration ─────────────────────────────
        log("Validating existing FDP configuration and namespace(s)...")
        idctrl_r = driver.run_cmd(["id-ctrl", ctrl_dev], json_out=True)
        if idctrl_r["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"id-ctrl failed: {idctrl_r['stderr'].strip()}")
        idctrl = idctrl_r.get("data", {})
        tnvmcap_bytes = int(idctrl.get("tnvmcap", 0)) if isinstance(idctrl, dict) else 0
        if tnvmcap_bytes == 0:
            return TestResult(TestStatus.FAIL, "tnvmcap is 0 \u2014 cannot determine capacity")
        total_lbas = tnvmcap_bytes // lba_sz
        ns_lbas    = total_lbas // n_ns
        if ns_lbas == 0:
            return TestResult(TestStatus.FAIL, "Namespace size rounds to 0 LBAs")
        log(f"  tnvmcap: {tnvmcap_bytes:,} bytes  \u2192  {total_lbas:,} LBAs total")
        log(f"  Per-namespace: {ns_lbas:,} LBAs  \u2248 {ns_lbas*lba_sz/1e12:.3f} TB")
        list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        if list_r["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"list-ns failed: {list_r['stderr'].strip()}")
        ns_data  = list_r.get("data", {})
        raw_list = (ns_data.get("nsid_list") or ns_data.get("NamespaceList")
                    or (ns_data if isinstance(ns_data, list) else []))
        if not raw_list:
            return TestResult(TestStatus.FAIL, "No namespaces found \u2014 run E0 first.")
        ng_devs  = []
        ns_nsids = []
        for raw in raw_list[:n_ns]:
            nsid    = int(raw["nsid"] if isinstance(raw, dict) else raw)
            ns_dev2 = ctrl_dev + f"n{nsid}"
            _m2     = _re.search(r"nvme(\d+)n(\d+)", ns_dev2)
            ng_dev2 = f"/dev/ng{_m2.group(1)}n{_m2.group(2)}" if _m2 else ns_dev2
            if not ng_devs:
                ruhs_r = driver.run_cmd(["fdp", "status", ns_dev2], json_out=True)
                if ruhs_r["rc"] != 0 or not driver.extract_ruhs(ruhs_r):
                    return TestResult(TestStatus.FAIL,
                                      f"FDP not configured on {ns_dev2} \u2014 run E0 first.")
            ns_nsids.append(nsid)
            ng_devs.append(ng_dev2)
            log(f"  NSID {nsid}  \u2192  {ns_dev2}  (generic: {ng_dev2})")
        if len(ng_devs) < n_ns:
            return TestResult(TestStatus.FAIL,
                              f"Requested {n_ns} namespace(s) but only {len(ng_devs)} exist.")

        # Pre-conditioning reminder
        log("__E0_REMINDER__")

      # Phase 2: FIO workload — all namespaces, RUH0 only
        # ══════════════════════════════════════════════════════════════════════
        log(f"\nPhase 4: {duration}s FIO workload — {n_ns} namespace(s), "
            f"fdp_pli=0 (RUH0 only), polling every {poll_sec}s...")

        fio_job = self._build_fio_job(ng_devs, duration, p)
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".fio", delete=False) as ftmp:
            ftmp.write(fio_job)
            fio_path = ftmp.name

        # Baseline stats
        stats0 = self._read_fdp_stats(driver, log, ctrl_dev, endgrp)
        if stats0 is None:
            os.unlink(fio_path)
            return TestResult(TestStatus.FAIL, "Cannot read FDP stats before FIO")
        log(f"  Baseline  hbmw={stats0['hbmw']:,}  mbmw={stats0['mbmw']:,}")

        fio_proc = subprocess.Popen(
            ["fio", "--output-format=json", fio_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        fio_registry.set_fio_process(fio_proc)

        waf_series = []
        start_time = time.time()
        poll_count = 0
        expected_polls = max(1, duration // poll_sec)

        try:
            while fio_proc.poll() is None:
                time.sleep(poll_sec)
                poll_count  += 1
                elapsed_min  = round((time.time() - start_time) / 60, 1)

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
        log("\nPhase 5: Generating summary...")
        html_summary = self._build_html_summary(
            waf_series, perf, n_ns, ns_nsids, duration, poll_sec, p)
        self._save_html_summary(html_summary, log)

        # Verdict
        final_waf = waf_series[-1][1] if waf_series else None
        if final_waf is None:
            status = TestStatus.WARN
            msg    = "Workload completed but WAF could not be calculated"
        elif final_waf <= 1.5:
            status = TestStatus.PASS
            msg    = f"Excellent WAF {final_waf} — {n_ns} NS, RUH0 only"
        elif final_waf <= 3.0:
            status = TestStatus.WARN
            msg    = f"Acceptable WAF {final_waf} — {n_ns} NS, RUH0 only"
        else:
            status = TestStatus.WARN
            msg    = f"High WAF {final_waf} — {n_ns} NS, RUH0 only"

        return TestResult(status, msg, details={
            "waf_series":   waf_series,
            "perf":         perf,
            "html_summary": html_summary,
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_fio_job(self, ng_devs: list, duration: int, p: dict) -> str:
        lines = [
            "[global]",
            "ioengine=io_uring_cmd",
            "rw=randwrite",
            f"bs={p['fio_block_size']}",
            f"iodepth={p['fio_queue_depth']}",
            f"numjobs={p['fio_num_jobs']}",
            f"runtime={duration}",
            "time_based=1",
            "fdp=1",
            "fdp_pli=0",           # always RUH0
            "fdp_pli_select=roundrobin",
            "",
        ]
        for i, ng_dev in enumerate(ng_devs):
            lines += [f"[ruh0_ns{i+1}]", f"filename={ng_dev}", ""]
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
                             n_ns: int, ns_nsids: list,
                             duration: int, poll_sec: int,
                             p: dict) -> str:
        duration_h = duration / 3600
        poll_min   = poll_sec / 60
        color      = "#0d6efd"
        nsid_str   = ", ".join(f"NSID {n}" for n in ns_nsids)

        xs = ("[" + ",".join(str(x) for x, _ in waf_series) + "]"
              if waf_series else "[]")
        ys = ("[" + ",".join(str(y) for _, y in waf_series) + "]"
              if waf_series else "[]")
        final_waf = waf_series[-1][1] if waf_series else "N/A"

        def metric_card(label, value, unit):
            return (f'<div class="card">'
                    f'<div class="card-val">{value}</div>'
                    f'<div class="card-lbl">{label}</div>'
                    f'<div class="card-unit">{unit}</div>'
                    f'</div>')

        perf_cards = (
            metric_card("Throughput",    perf.get("bw_mbs", "—"), "MB/s") +
            metric_card("IOPS",          perf.get("iops",   "—"), "")    +
            metric_card("Avg Latency",   perf.get("lat_us", "—"), "µs")  +
            metric_card("Total Written", perf.get("io_mb",  "—"), "MB")
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>E3 Endurance Summary</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body  {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#f8f9fa;color:#212529;margin:0;padding:24px;}}
  h1    {{font-size:20px;margin-bottom:4px;}}
  h2    {{font-size:15px;margin:28px 0 10px;color:#495057;
          border-bottom:1px solid #dee2e6;padding-bottom:6px;}}
  .meta {{font-size:12px;color:#6c757d;margin-bottom:20px;}}
  .graph-wrap{{background:#fff;border:1px solid #dee2e6;border-radius:8px;
               padding:18px 20px;}}
  .graph-title{{font-size:13px;font-weight:600;margin-bottom:10px;
                display:flex;align-items:center;gap:8px;}}
  .badge{{font-size:11px;font-weight:500;background:#e9ecef;border-radius:4px;
          padding:2px 8px;color:#495057;}}
  .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;
          margin-bottom:8px;}}
  .card {{background:#fff;border:1px solid #dee2e6;border-radius:8px;
          padding:16px 18px;text-align:center;}}
  .card-val  {{font-size:26px;font-weight:700;color:#0d6efd;}}
  .card-lbl  {{font-size:12px;color:#6c757d;margin-top:4px;}}
  .card-unit {{font-size:11px;color:#adb5bd;}}
</style>
</head>
<body>
<h1>E3 Endurance Summary — Single RUH (RUH0) Isolation</h1>
<div class="meta">
  4k randwrite · {duration_h:.1f}h · {n_ns} namespace(s) ({nsid_str}) ·
  fdp_pli=0 (RUH0 only) ·
  WAF polled every {poll_min:.1f} min · FDP enabled
</div>

<h2>Performance Metrics</h2>
<div class="cards">
{perf_cards}
</div>

<h2>WAF over Time (RUH0)</h2>
<div class="graph-wrap">
  <div class="graph-title">Write Amplification Factor — RUH0
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
        import os as _os
        from pathlib import Path as _Path
        from datetime import datetime as _dt
        proj_root = _Path(__file__).resolve().parent.parent.parent
        out_dir   = proj_root / "Endurance Results"
        out_dir.mkdir(exist_ok=True)
        ts       = _dt.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.test_id}_{ts}.html"
        out_path = out_dir / filename
        try:
            out_path.write_text(html, encoding="utf-8")
            log(f"  ✓ Summary saved: {out_path}")
            return str(out_path)
        except Exception as _e:
            log(f"  ⚠ Could not save summary: {_e}")
            return None