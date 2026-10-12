#!/usr/bin/env python3
"""Time each build and test phase on this machine and write one JSON result.

Phases (macOS): package tests, simulator build-for-testing (clean), an incremental rebuild after one
edit, a device build without signing, simulator boot, app unit tests and one UI test.
Phase (Linux): package tests only.

While a phase runs, a sampler records memory pressure and swap use every 2 seconds, so a runner that
is short of memory shows up as swap or pressure rather than only as a slow time.

Usage: python3 bench/run.py --label laptop [--generated generated] [--phases all|build|package] [--xcodebuild WRAPPER]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

IS_MAC = sys.platform == 'darwin'


def sh(cmd: list[str], cwd: Path | None = None, log: Path | None = None) -> tuple[int, float]:
    start = time.monotonic()
    with open(log, 'a') if log else open(os.devnull, 'w') as out:
        out.write(f'\n$ {" ".join(cmd)}\n')
        out.flush()
        code = subprocess.call(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT)
    return code, round(time.monotonic() - start, 1)


def text(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


class Sampler:
    """Swap growth (MB above what was in use when the phase began) and lowest free-memory percentage."""

    def __init__(self) -> None:
        self.start_swap_mb: float | None = None
        self.peak_swap_mb = 0.0
        self.min_free_pct: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self) -> None:
        if IS_MAC:
            swap = text(['sysctl', '-n', 'vm.swapusage'])
            m = re.search(r'used = ([\d.]+)M', swap)
            if m:
                self._swap(float(m.group(1)))
            pressure = text(['memory_pressure', '-Q'])
            m = re.search(r'free percentage: (\d+)%', pressure)
            free = float(m.group(1)) if m else None
        else:
            info = Path('/proc/meminfo').read_text()
            vals = {k: int(v) for k, v in re.findall(r'^(\w+):\s+(\d+)', info, re.M)}
            used_swap = (vals.get('SwapTotal', 0) - vals.get('SwapFree', 0)) / 1024
            self._swap(used_swap)
            free = 100 * vals.get('MemAvailable', 0) / max(vals.get('MemTotal', 1), 1)
        if free is not None:
            self.min_free_pct = free if self.min_free_pct is None else min(self.min_free_pct, free)

    def _swap(self, used: float) -> None:
        if self.start_swap_mb is None:
            self.start_swap_mb = used
        self.peak_swap_mb = max(self.peak_swap_mb, used - self.start_swap_mb)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(2)

    def __enter__(self) -> 'Sampler':
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def free_gb(path: Path) -> float:
    return round(shutil.disk_usage(path).free / 1e9, 1)


def machine() -> dict:
    info = {'platform': platform.platform(), 'cores': os.cpu_count()}
    if IS_MAC:
        info['cpu'] = text(['sysctl', '-n', 'machdep.cpu.brand_string'])
        info['memory_gb'] = round(int(text(['sysctl', '-n', 'hw.memsize']) or 0) / 2**30, 1)
        info['xcode'] = text(['xcodebuild', '-version']).replace('\n', ' ')
    else:
        m = re.search(r'MemTotal:\s+(\d+)', Path('/proc/meminfo').read_text())
        info['memory_gb'] = round(int(m.group(1)) / 2**20, 1) if m else None
    info['swift'] = text(['swift', '--version']).splitlines()[0] if text(['swift', '--version']) else ''
    return info


def pick_simulator() -> str | None:
    """Create a fresh iPhone simulator on the newest installed iOS runtime and return its id."""
    data = json.loads(text(['xcrun', 'simctl', 'list', '-j', 'runtimes', 'devicetypes']) or '{}')
    runtimes = [r for r in data.get('runtimes', []) if r.get('platform') == 'iOS' and r.get('isAvailable')]
    if not runtimes:
        return None
    runtime = max(runtimes, key=lambda r: [int(x) for x in r['version'].split('.')])
    types = [t for t in runtime.get('supportedDeviceTypes', []) if t.get('productFamily') == 'iPhone']
    if not types:
        return None
    device_type = types[-1]['identifier']
    return text(['xcrun', 'simctl', 'create', 'bench-runner', device_type, runtime['identifier']]) or None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--generated', default='generated')
    parser.add_argument('--phases', default='all', choices=['all', 'build', 'package'],
                        help='build = everything except the simulator phases')
    parser.add_argument('--out', default='results')
    parser.add_argument('--xcodebuild', default='xcodebuild', help='a wrapper to call instead, e.g. one that waits for a shared build slot')
    args = parser.parse_args()

    gen = Path(args.generated).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    log = out / f'{args.label}.log'
    dd = gen / '.dd'
    result = {'label': args.label, 'machine': machine(), 'disk_free_gb_start': free_gb(gen), 'phases': []}

    def phase(name: str, cmd: list[str], cwd: Path) -> int:
        with Sampler() as sampler:
            code, seconds = sh(cmd, cwd=cwd, log=log)
        entry = {'phase': name, 'seconds': seconds, 'exit': code,
                 'swap_growth_mb': round(sampler.peak_swap_mb), 'min_free_memory_pct': sampler.min_free_pct}
        result['phases'].append(entry)
        print(f'{name:28} {seconds:8.1f}s  exit {code}  swap +{entry["swap_growth_mb"]} MB  '
              f'min free {sampler.min_free_pct}%', flush=True)
        return code

    package = gen / 'Package'
    phase('package: build tests (clean)', ['swift', 'build', '--build-tests'], package)
    phase('package: run tests', ['swift', 'test', '--skip-build'], package)

    if IS_MAC and args.phases in ('all', 'build'):
        xb = [args.xcodebuild, '-project', 'BenchApp.xcodeproj', '-scheme', 'BenchApp', '-derivedDataPath', str(dd)]
        # arm64 only: a generic simulator build otherwise compiles x86_64 too, which no Apple silicon Mac runs.
        sim = ['-destination', 'generic/platform=iOS Simulator', 'ARCHS=arm64']
        if phase('app: build-for-testing (clean)', xb + sim + ['build-for-testing'], gen) != 0:
            result['disk_free_gb_end'] = free_gb(gen)
            (out / f'{args.label}.json').write_text(json.dumps(result, indent=2))
            sys.exit('App build failed; later app phases skipped so their times are not misleading.')
        edited = gen / 'Package/Sources/BenchKit0/File0.swift'
        edited.write_text(edited.read_text() + '\npublic let benchEdit = 1\n')
        phase('app: build-for-testing (1 edit)', xb + sim + ['build-for-testing'], gen)
        phase('app: device build (no signing)', xb + ['-destination', 'generic/platform=iOS',
              'CODE_SIGNING_ALLOWED=NO', 'build'], gen)
        device = pick_simulator() if args.phases == 'all' else None
        if device:
            phase('simulator: boot', ['xcrun', 'simctl', 'bootstatus', device, '-b'], gen)
            dest = ['-destination', f'id={device}']
            phase('app: unit tests', xb + dest + ['-only-testing:BenchAppTests', 'test-without-building'], gen)
            phase('app: one UI test', xb + dest + ['-only-testing:BenchAppUITests', 'test-without-building'], gen)
            subprocess.call(['xcrun', 'simctl', 'shutdown', device])
            subprocess.call(['xcrun', 'simctl', 'delete', device])
        elif args.phases == 'all':
            result['phases'].append({'phase': 'simulator: boot', 'seconds': None, 'exit': 'no iOS runtime'})

    result['disk_free_gb_end'] = free_gb(gen)
    (out / f'{args.label}.json').write_text(json.dumps(result, indent=2))
    failed = [p['phase'] for p in result['phases'] if p['exit'] not in (0,)]
    if failed:
        print('Failed phases:', ', '.join(failed))


if __name__ == '__main__':
    main()
