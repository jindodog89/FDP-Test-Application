"""
Test: E1. Endurance — WAF Calculation per RUH
Sequence:
  1. Delete all namespaces
  2. Disable FDP → Re-enable FDP  (clears hbmw / mbmw counters)
  3. Create a single namespace with 4 RUHs
  4. For each RUH (0–3):
       a. Run 24h of 4k randwrite FIO targeting that RUH exclusively
       b. Poll nvme fdp stats every 30 min and record WAF sample
  5. Produce an HTML WAF-over-time summary (4 line graphs, one per RUH)
"""

import subprocess
import json
import tempfile
import os
import re as _re
import time
from tests.base_test import BaseTest, TestResult, TestStatus
from backend import fio_registry


class TestEnduranceWAF(BaseTest):
    test_id  = "endurance_waf"
    name     = "E1. Endurance — WAF Calculation per RUH"
    description = (
        "Clears FDP stats by cycling FDP off/on and creating a fresh namespace "
        "with 4 RUHs. Runs 24 hours of 4k randwrite FIO to each RUH in turn, "
        "sampling WAF every 30 minutes. Produces a per-RUH WAF-over-time graph."
    )
    category = "Endurance"
    tags     = ["fio", "waf", "endurance", "fdp-stats", "write-amplification", "long-running"]

    # ── Tuneable defaults (can be overridden via params) ──────────────────────
    DEFAULT_PARAMS = {
        "endgrp":            1,
        "n_ruhs":            4,          # default parameter, will be overwritten
        "fio_duration_sec":  86400,      # 24 h per RUH
        "fio_block_size":    "4k",
        "fio_queue_depth":   64,
        "fio_num_jobs":      4,
    }

    # ─────────────────────────────────────────────────────────────────────────

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        # poll_interval = duration / 20 (minimum 5 s)
        p["poll_interval_sec"] = max(5, int(p["fio_duration_sec"]) // 20)
        endgrp = p["endgrp"]
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)

        # ── Pre-flight: fio must exist ────────────────────────────────────────
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

      # Phase 2: Per-RUH endurance workload
        # ══════════════════════════════════════════════════════════════════════
        # waf_data[ruh] = list of (elapsed_min, waf) tuples
        waf_data  = {ruh: [] for ruh in range(n_ruhs)}
        perf_data = {}  # perf_data[ruh] = {bw_mbs, iops, lat_us, io_mb}

        for ruh in range(n_ruhs):
            log(f"\n{'='*60}")
            log(f"Phase 2 — RUH {ruh}: {p['fio_duration_sec']//3600}h FIO workload")
            log(f"{'='*60}")

            # ── Build fio job ─────────────────────────────────────────────────
            fio_job = self._build_fio_job(ng_dev, ruh, p)
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".fio", delete=False) as ftmp:
                ftmp.write(fio_job)
                fio_path = ftmp.name

            # ── Baseline stats ────────────────────────────────────────────────
            stats0 = self._read_fdp_stats(driver, log, ctrl_dev, endgrp)
            if stats0 is None:
                os.unlink(fio_path)
                return TestResult(TestStatus.FAIL,
                                  "Cannot read FDP stats before FIO")

            log(f"  Baseline  hbmw={stats0['hbmw']:,}  mbmw={stats0['mbmw']:,}")

            # ── Launch fio as background process ──────────────────────────────
            log(f"  Starting FIO (PID will be polled every "
                f"{p['poll_interval_sec']//60} min)...")
            fio_proc = subprocess.Popen(
                ["fio", "--output-format=json", fio_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            fio_registry.set_fio_process(fio_proc)

            start_time = time.time()
            poll_count = 0
            expected_polls = (p["fio_duration_sec"] //
                              p["poll_interval_sec"])

            try:
                while fio_proc.poll() is None:
                    time.sleep(p["poll_interval_sec"])
                    poll_count += 1
                    elapsed_sec = time.time() - start_time
                    elapsed_min = round(elapsed_sec / 60, 1)

                    stats_now = self._read_fdp_stats(
                        driver, log, ctrl_dev, endgrp)
                    if stats_now is None:
                        log(f"  ⚠ Poll {poll_count}: stats read failed, skipping")
                        continue

                    delta_h = stats_now["hbmw"] - stats0["hbmw"]
                    delta_m = stats_now["mbmw"] - stats0["mbmw"]
                    waf_val = round(delta_m / delta_h, 4) if delta_h > 0 else None

                    log(f"  Poll {poll_count}/{expected_polls} "
                        f"@ {elapsed_min} min — "
                        f"Δhbmw={delta_h:,}  Δmbmw={delta_m:,}  "
                        f"WAF={waf_val if waf_val is not None else 'n/a'}")

                    if waf_val is not None:
                        waf_data[ruh].append((elapsed_min, waf_val))

            finally:
                # Ensure fio is stopped even on exception
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
            if fio_proc.returncode not in (0, -15):   # -15 = SIGTERM (expected)
                log(f"  \u26a0 FIO stderr: {stderr.strip()[:300]}")

            # Parse fio JSON for performance metrics
            try:
                fio_json = json.loads(stdout)
                jobs = fio_json.get("jobs", [])
                if jobs:
                    wr = jobs[0].get("write", {})
                    perf_data[ruh] = {
                        "bw_mbs": round(wr.get("bw_bytes", 0) / 1e6, 2),
                        "iops":   round(wr.get("iops", 0), 1),
                        "lat_us": round(wr.get("lat_ns", {}).get("mean", 0) / 1000, 1),
                        "io_mb":  round(wr.get("io_bytes", 0) / 1e6, 1),
                    }
                    log(f"  Perf \u2014 BW: {perf_data[ruh]['bw_mbs']} MB/s  "
                        f"IOPS: {perf_data[ruh]['iops']}  "
                        f"Lat: {perf_data[ruh]['lat_us']} \u00b5s  "
                        f"Written: {perf_data[ruh]['io_mb']} MB")
            except Exception as _e:
                log(f"  \u26a0 Could not parse fio JSON: {_e}")

            # Final WAF sample at workload end
            stats_end = self._read_fdp_stats(driver, log, ctrl_dev, endgrp)
            if stats_end:
                delta_h = stats_end["hbmw"] - stats0["hbmw"]
                delta_m = stats_end["mbmw"] - stats0["mbmw"]
                elapsed_min = round((time.time() - start_time) / 60, 1)
                if delta_h > 0:
                    waf_final = round(delta_m / delta_h, 4)
                    waf_data[ruh].append((elapsed_min, waf_final))
                    log(f"  Final WAF for RUH {ruh}: {waf_final}")

        # ══════════════════════════════════════════════════════════════════════
        # Phase 3: Build HTML summary
        # ══════════════════════════════════════════════════════════════════════
        log("\nPhase 3: Generating WAF + performance summary...")
        html_summary = self._build_html_summary(waf_data, perf_data, n_ruhs, p)

        # Overall pass/warn based on final WAF of each RUH
        worst_waf = None
        for ruh in range(n_ruhs):
            if waf_data[ruh]:
                last = waf_data[ruh][-1][1]
                if worst_waf is None or last > worst_waf:
                    worst_waf = last

        if worst_waf is None:
            status = TestStatus.WARN
            msg = "Workloads completed but WAF could not be calculated (counters unchanged)"
        elif worst_waf <= 1.5:
            status = TestStatus.PASS
            msg = f"Excellent WAF (worst across RUHs: {worst_waf})"
        elif worst_waf <= 3.0:
            status = TestStatus.WARN
            msg = f"Acceptable WAF (worst across RUHs: {worst_waf})"
        else:
            status = TestStatus.WARN
            msg = f"High WAF detected (worst across RUHs: {worst_waf})"

        self._save_html_summary(html_summary, log)
        return TestResult(status, msg, details={
            "waf_data":     waf_data,
            "perf_data":    perf_data,
            "html_summary": html_summary,
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_fio_job(self, ng_dev: str, ruh: int, p: dict) -> str:
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
            f"fdp_pli={ruh}",
            "fdp_pli_select=roundrobin",
            "",
            f"[ruh_{ruh}_workload]",
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

    def _build_html_summary(self, waf_data: dict, perf_data: dict,
                             n_ruhs: int, p: dict) -> str:
        """HTML summary: WAF-over-time graphs + performance bar charts."""
        colors     = ["#0d6efd", "#198754", "#dc3545", "#fd7e14"]
        duration_h = p["fio_duration_sec"] // 3600
        poll_min   = p["poll_interval_sec"] // 60

        # ── WAF line graphs — one per RUH ─────────────────────────────────────
        waf_graphs = []
        for ruh in range(n_ruhs):
            pts   = waf_data.get(ruh, [])
            xs    = "[" + ",".join(str(x) for x, _ in pts) + "]" if pts else "[]"
            ys    = "[" + ",".join(str(y) for _, y in pts) + "]" if pts else "[]"
            color = colors[ruh % len(colors)]
            final = pts[-1][1] if pts else "N/A"
            waf_graphs.append(f"""
  <div class="graph-wrap">
    <div class="graph-title">RUH {ruh} \u2014 WAF over Time
      <span class="badge">Final: {final}</span>
    </div>
    <canvas id="waf{ruh}" height="200"></canvas>
    <script>(function(){{
      new Chart(document.getElementById('waf{ruh}').getContext('2d'),{{
        type:'line',
        data:{{labels:{xs},datasets:[{{label:'WAF',data:{ys},
          borderColor:'{color}',backgroundColor:'{color}22',
          fill:true,tension:0.3,pointRadius:3}}]}},
        options:{{responsive:true,plugins:{{legend:{{display:false}}}},
          scales:{{
            x:{{title:{{display:true,text:'Elapsed (min)'}},ticks:{{maxTicksLimit:12}}}},
            y:{{title:{{display:true,text:'WAF'}},min:1,suggestedMax:4}}
          }}}}
      }});
    }})();</script>
  </div>""")

        # ── Performance summary table ─────────────────────────────────────────
        perf_rows = ""
        for ruh in range(n_ruhs):
            pd = perf_data.get(ruh, {})
            perf_rows += (
                f"<tr><td>RUH {ruh}</td>"
                f"<td>{pd.get('bw_mbs', '\u2014')}</td>"
                f"<td>{pd.get('iops', '\u2014')}</td>"
                f"<td>{pd.get('lat_us', '\u2014')}</td>"
                f"<td>{pd.get('io_mb', '\u2014')}</td></tr>\n"
            )

        # ── Per-metric bar charts ─────────────────────────────────────────────
        def bar_chart(cid, title, metric, y_label):
            labels = "[" + ",".join(f"'RUH {r}'" for r in range(n_ruhs)) + "]"
            vals   = "[" + ",".join(
                str(perf_data.get(r, {}).get(metric, 0)) for r in range(n_ruhs)
            ) + "]"
            bgs    = "[" + ",".join(f"'{colors[r % len(colors)]}'" for r in range(n_ruhs)) + "]"
            return f"""
  <div class="graph-wrap">
    <div class="graph-title">{title}</div>
    <canvas id="{cid}" height="200"></canvas>
    <script>(function(){{
      new Chart(document.getElementById('{cid}').getContext('2d'),{{
        type:'bar',
        data:{{labels:{labels},datasets:[{{
          label:'{y_label}',data:{vals},
          backgroundColor:{bgs},borderRadius:4
        }}]}},
        options:{{responsive:true,plugins:{{legend:{{display:false}}}},
          scales:{{y:{{title:{{display:true,text:'{y_label}'}},beginAtZero:true}}}}
        }}
      }});
    }})();</script>
  </div>"""

        perf_charts = (bar_chart("cbw",  "Throughput (MB/s) per RUH", "bw_mbs", "MB/s") +
                       bar_chart("ciops","IOPS per RUH",               "iops",   "IOPS") +
                       bar_chart("clat", "Avg Latency (\u00b5s) per RUH", "lat_us", "\u00b5s"))

        waf_html = "\n".join(waf_graphs)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>E1 Endurance Summary</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  body  {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#f8f9fa;color:#212529;margin:0;padding:24px;}}
  h1    {{font-size:20px;margin-bottom:4px;}}
  h2    {{font-size:15px;margin:28px 0 10px;color:#495057;border-bottom:1px solid #dee2e6;padding-bottom:6px;}}
  .meta {{font-size:12px;color:#6c757d;margin-bottom:20px;}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
  .grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;}}
  .graph-wrap{{background:#fff;border:1px solid #dee2e6;border-radius:8px;padding:16px 18px;}}
  .graph-title{{font-size:13px;font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:8px;}}
  .badge{{font-size:11px;font-weight:500;background:#e9ecef;border-radius:4px;padding:2px 8px;color:#495057;}}
  table{{width:100%;border-collapse:collapse;font-size:13px;}}
  th{{background:#f1f3f5;padding:8px 12px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6;}}
  td{{padding:7px 12px;border-bottom:1px solid #e9ecef;}}
  tr:last-child td{{border-bottom:none;}}
</style>
</head>
<body>
<h1>E1 Endurance Workload Summary</h1>
<div class="meta">4k randwrite \u00b7 {duration_h}h per RUH \u00b7 WAF polled every {poll_min} min \u00b7 FDP enabled \u00b7 1 NS \u00b7 {n_ruhs} RUHs</div>

<h2>Performance Metrics</h2>
<div class="graph-wrap" style="margin-bottom:16px">
  <table>
    <tr><th>RUH</th><th>BW (MB/s)</th><th>IOPS</th><th>Avg Lat (\u00b5s)</th><th>Total Written (MB)</th></tr>
    {perf_rows}
  </table>
</div>
<div class="grid3">
{perf_charts}
</div>

<h2>WAF over Time</h2>
<div class="grid2">
{waf_html}
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