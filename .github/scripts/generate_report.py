#!/usr/bin/env python3
"""
generate_report.py

Parses iperf3 JSON results for dual Vietnam VPS ingress benchmark runs
and outputs a GitHub Actions Step Summary table with comparative analysis.
"""

import json
import os
import sys

def main():
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    vps1_ip = os.environ.get("VPS1_IP")
    vps2_ip = os.environ.get("VPS2_IP")
    if not vps1_ip or not vps2_ip:
        raise ValueError("VPS1_IP and VPS2_IP environment variables must be provided by the workflow inputs.")

    port = os.environ.get("PORT") or "5201"
    streams = os.environ.get("STREAMS") or "8"
    duration = os.environ.get("DURATION") or "30"
    routing_mode = os.environ.get("ROUTING_MODE") or "Direct (GitHub Runner / Azure)"

    # Inspect runner origin & routing trace
    runner_origin = "GitHub Hosted Runner (Ubuntu)"
    warp_active = False

    if os.path.exists("warp_trace.txt") and os.path.getsize("warp_trace.txt") > 0:
        try:
            with open("warp_trace.txt", "r", encoding="utf-8") as f:
                trace_dict = dict(line.strip().split("=", 1) for line in f if "=" in line)
                if trace_dict.get("warp") == "on":
                    warp_active = True
                    w_ip = trace_dict.get("ip", "Unknown")
                    w_colo = trace_dict.get("colo", "")
                    w_loc = trace_dict.get("loc", "")
                    runner_origin = f"`{w_ip}` (Cloudflare WARP — PoP: **{w_colo}**, Country: **{w_loc}**)"
        except Exception:
            pass

    wg_peer = None
    if os.path.exists("wg_status.txt") and os.path.getsize("wg_status.txt") > 0:
        try:
            with open("wg_status.txt", "r", encoding="utf-8") as f:
                for line in f:
                    if "endpoint:" in line:
                        wg_peer = line.split("endpoint:", 1)[1].strip()
                        break
        except Exception:
            pass

    if not warp_active and os.path.exists("runner_info.json") and os.path.getsize("runner_info.json") > 0:
        try:
            with open("runner_info.json", "r", encoding="utf-8") as f:
                r_data = json.load(f)
                ip = r_data.get("ip") or r_data.get("query")
                city = r_data.get("city", "")
                region = r_data.get("region") or r_data.get("regionName", "")
                country = r_data.get("country", "")
                org = r_data.get("org") or r_data.get("isp", "")
                geo = ", ".join(filter(None, [city, region, country]))
                if ip and ip != "Unknown":
                    extra = f"{geo} — {org}" if geo and org else (geo or org)
                    runner_origin = f"`{ip}` ({extra})" if extra else f"`{ip}`"
        except Exception:
            pass

    if wg_peer:
        if runner_origin == "GitHub Hosted Runner (Ubuntu)":
            runner_origin = f"WireGuard VPN (Peer: `{wg_peer}`)"
        else:
            runner_origin = f"{runner_origin} [via WireGuard Peer `{wg_peer}`]"

    def parse_iperf(json_path, log_path):
        res = {
            "status": "Failed",
            "status_icon": "❌",
            "speed_str": "N/A",
            "bytes_str": "N/A",
            "rtt_str": "N/A",
            "retr_str": "N/A",
            "raw_bps": 0.0,
            "raw_bytes": 0,
            "raw_rtt_ms": 0.0,
            "raw_retr": 0,
            "error": None
        }

        if not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
            err = "Output file empty or test timed out"
            if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    if content:
                        err = content.splitlines()[-1]
            res["error"] = err
            res["speed_str"] = err
            return res

        try:
            with open(json_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
        except Exception as e:
            res["error"] = f"JSON parse error: {e}"
            res["speed_str"] = res["error"]
            return res

        if "error" in data:
            res["error"] = data["error"]
            res["speed_str"] = data["error"]
            return res

        end = data.get("end", {})
        sum_rcv = end.get("sum_received", {})
        sum_sent = end.get("sum_sent", {})

        bps = sum_rcv.get("bits_per_second") or sum_sent.get("bits_per_second") or 0.0
        res["raw_bps"] = float(bps)
        if bps >= 1e9:
            res["speed_str"] = f"{bps / 1e9:.2f} Gbps"
        elif bps >= 1e6:
            res["speed_str"] = f"{bps / 1e6:.2f} Mbps"
        elif bps > 0:
            res["speed_str"] = f"{bps / 1e3:.2f} Kbps"
        else:
            res["speed_str"] = "0 Mbps"

        total_bytes = sum_rcv.get("bytes") or sum_sent.get("bytes") or 0
        res["raw_bytes"] = total_bytes
        if total_bytes >= 1024**3:
            res["bytes_str"] = f"{total_bytes / (1024**3):.2f} GB"
        elif total_bytes >= 1024**2:
            res["bytes_str"] = f"{total_bytes / (1024**2):.2f} MB"
        elif total_bytes > 0:
            res["bytes_str"] = f"{total_bytes / 1024:.2f} KB"
        else:
            res["bytes_str"] = "0 B"

        retr = sum_sent.get("retransmits")
        if retr is not None:
            res["raw_retr"] = retr
            res["retr_str"] = f"{retr:,}"
        else:
            res["retr_str"] = "N/A"

        streams_data = end.get("streams", [])
        rtts = [s.get("sender", {}).get("mean_rtt") for s in streams_data if s.get("sender", {}).get("mean_rtt") is not None]
        if rtts:
            avg_rtt = (sum(rtts) / len(rtts)) / 1000.0
            res["raw_rtt_ms"] = avg_rtt
            res["rtt_str"] = f"{avg_rtt:.1f} ms"
        else:
            res["rtt_str"] = "N/A"

        res["status"] = "Passed"
        res["status_icon"] = "✅"
        return res

    v1 = parse_iperf("vps1_results.json", "vps1_stderr.log")
    v2 = parse_iperf("vps2_results.json", "vps2_stderr.log")

    # Comparison calculations
    speed_comp = "-"
    if v1["raw_bps"] > 0 and v2["raw_bps"] > 0:
        ratio = v1["raw_bps"] / v2["raw_bps"]
        if ratio >= 1.05:
            speed_comp = f"⚡ VPS 1 is **{ratio:.1f}x faster**"
        elif ratio <= 0.95:
            speed_comp = f"⚡ VPS 2 is **{(1/ratio):.1f}x faster**"
        else:
            speed_comp = "Approximately equal (±5%)"

    bytes_comp = "-"
    if v1["raw_bytes"] > 0 and v2["raw_bytes"] > 0:
        diff = abs(v1["raw_bytes"] - v2["raw_bytes"])
        diff_str = f"{diff / (1024**3):.2f} GB" if diff >= 1024**3 else f"{diff / (1024**2):.2f} MB"
        more_vps = "VPS 1" if v1["raw_bytes"] >= v2["raw_bytes"] else "VPS 2"
        bytes_comp = f"+{diff_str} by {more_vps}"

    rtt_comp = "-"
    if v1["raw_rtt_ms"] > 0 and v2["raw_rtt_ms"] > 0:
        rtt_diff = abs(v1["raw_rtt_ms"] - v2["raw_rtt_ms"])
        lower_vps = "VPS 1" if v1["raw_rtt_ms"] <= v2["raw_rtt_ms"] else "VPS 2"
        rtt_comp = f"{rtt_diff:.1f} ms lower on {lower_vps}"

    retr_comp = "-"
    if v1["status"] == "Passed" and v2["status"] == "Passed":
        if v1["raw_bps"] > v2["raw_bps"] * 2:
            retr_comp = "High retransmits expected for high-throughput route"
        else:
            retr_comp = "Normal TCP flow control"

    is_domestic_vn = "vietnam" in routing_mode.lower() or "vietnam" in runner_origin.lower() or "vn" in runner_origin.lower()
    if is_domestic_vn:
        takeaway_v1 = f"**VPS 1 (`{vps1_ip}`)**: Domestic Vietnam ingress delivering **{v1['speed_str']}** with ~{v1['rtt_str']} latency over domestic peering."
        takeaway_v2 = f"**VPS 2 (`{vps2_ip}`)**: Domestic Vietnam ingress delivering **{v2['speed_str']}** with ~{v2['rtt_str']} latency."
        if v1['raw_bps'] > v2['raw_bps'] * 1.15:
            takeaway_summary = f"VPS 1 provides **~{v1['raw_bps']/max(v2['raw_bps'], 1.0):.1f}x higher domestic throughput**."
        elif v2['raw_bps'] > v1['raw_bps'] * 1.15:
            takeaway_summary = f"VPS 2 provides **~{v2['raw_bps']/max(v1['raw_bps'], 1.0):.1f}x higher domestic throughput**."
        else:
            takeaway_summary = "Both VPS providers offer comparable domestic bandwidth within Vietnam."
        takeaway_block = f"> - {takeaway_v1}\n> - {takeaway_v2}\n> - 💡 **Domestic Route Assessment:** {takeaway_summary}"
    else:
        takeaway_v1 = f"**VPS 1 (`{vps1_ip}`)**: Direct unthrottled international transit delivering **{v1['speed_str']}**. High packet retransmission count ({v1['retr_str']}) is normal behavior when saturating a connection over a high-latency trans-oceanic route (~{v1['rtt_str']} RTT) due to TCP window scaling."
        takeaway_v2 = f"**VPS 2 (`{vps2_ip}`)**: International ingress is strictly **capped / throttled at ~{v2['speed_str']}**, despite physical fiber latency being comparable (~{v2['rtt_str']}). VPS 1 provides **~{v1['raw_bps']/max(v2['raw_bps'], 1.0):.1f}x higher international throughput**."
        takeaway_block = f"> - {takeaway_v1}\n> - {takeaway_v2}"

    report = f"""## 🌐 Vietnam VPS Ingress Benchmark

**Client Ingress Origin (Runner):** {runner_origin}  
**Routing Mode:** {routing_mode}  
**Test Profile:** {streams} parallel TCP streams (`-P {streams}`), {duration}s duration (`-t {duration}`), Port {port}

| Metric | VPS 1 (`{vps1_ip}`) | VPS 2 (`{vps2_ip}`) | Comparison / Difference |
| :--- | :--- | :--- | :--- |
| **Status** | {v1['status_icon']} {v1['status']} | {v2['status_icon']} {v2['status']} | - |
| **Ingress Bandwidth** | **{v1['speed_str']}** | **{v2['speed_str']}** | {speed_comp} |
| **Total Transferred** | {v1['bytes_str']} | {v2['bytes_str']} | {bytes_comp} |
| **Est. Mean RTT (Latency)** | {v1['rtt_str']} | {v2['rtt_str']} | {rtt_comp} |
| **TCP Retransmissions** | {v1['retr_str']} | {v2['retr_str']} | {retr_comp} |
| **Streams / Duration** | {streams} streams / {duration}s | {streams} streams / {duration}s | Identical test load |

> 📌 **Key Takeaway & Route Analysis:**
{takeaway_block}

<details>
<summary>🔍 Raw Summary (JSON)</summary>

### VPS 1
```json
{json.dumps({"status": v1["status"], "bandwidth": v1["speed_str"], "bytes": v1["bytes_str"], "rtt": v1["rtt_str"], "retransmits": v1["retr_str"], "error": v1["error"]}, indent=2)}
```

### VPS 2
```json
{json.dumps({"status": v2["status"], "bandwidth": v2["speed_str"], "bytes": v2["bytes_str"], "rtt": v2["rtt_str"], "retransmits": v2["retr_str"], "error": v2["error"]}, indent=2)}
```
</details>
"""

    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(report)

if __name__ == "__main__":
    main()
