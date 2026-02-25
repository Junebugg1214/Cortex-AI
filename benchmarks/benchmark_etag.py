#!/usr/bin/env python3
"""
ETag cache hit rate measurement.

Sends repeated requests to the CaaS API and measures how often
If-None-Match produces a 304 Not Modified response.

Usage::

    # Start server first:
    cortex serve context.json

    # Then run:
    python3 benchmarks/benchmark_etag.py
    python3 benchmarks/benchmark_etag.py --url http://127.0.0.1:8421 --requests 200
    python3 benchmarks/benchmark_etag.py --token YOUR_GRANT_TOKEN
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description="Benchmark ETag cache hit rate")
    parser.add_argument("--url", default="http://127.0.0.1:8421", help="CaaS base URL")
    parser.add_argument("--requests", type=int, default=100, help="Number of requests")
    parser.add_argument("--endpoint", default="/context", help="Endpoint to test")
    parser.add_argument("--token", default="", help="Bearer token for auth")
    args = parser.parse_args()

    url = f"{args.url}{args.endpoint}"
    total = args.requests
    hits_304 = 0
    hits_200 = 0
    errors = 0
    etag = None
    latencies_200: list[float] = []
    latencies_304: list[float] = []

    print(f"Benchmarking ETag hit rate: {url}")
    print(f"Requests: {total}\n")

    for i in range(total):
        headers = {}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"
        if etag:
            headers["If-None-Match"] = etag

        req = urllib.request.Request(url, headers=headers)
        start = time.perf_counter()
        try:
            resp = urllib.request.urlopen(req)
            elapsed = (time.perf_counter() - start) * 1000
            status = resp.status
            new_etag = resp.headers.get("ETag")
            if new_etag:
                etag = new_etag
            hits_200 += 1
            latencies_200.append(elapsed)
        except urllib.error.HTTPError as e:
            elapsed = (time.perf_counter() - start) * 1000
            if e.code == 304:
                hits_304 += 1
                latencies_304.append(elapsed)
            else:
                errors += 1

        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{total} done...")

    print(f"\nResults:")
    print(f"  200 OK:           {hits_200}")
    print(f"  304 Not Modified: {hits_304}")
    print(f"  Errors:           {errors}")
    if total > 0:
        hit_rate = hits_304 / total * 100
        print(f"  Cache hit rate:   {hit_rate:.1f}%")
    if latencies_200:
        avg_200 = sum(latencies_200) / len(latencies_200)
        print(f"  Avg 200 latency:  {avg_200:.1f} ms")
    if latencies_304:
        avg_304 = sum(latencies_304) / len(latencies_304)
        print(f"  Avg 304 latency:  {avg_304:.1f} ms")
    if latencies_200 and latencies_304:
        savings = (1 - sum(latencies_304) / len(latencies_304) / (sum(latencies_200) / len(latencies_200))) * 100
        print(f"  Latency savings:  {savings:.1f}% (304 vs 200)")


if __name__ == "__main__":
    main()
