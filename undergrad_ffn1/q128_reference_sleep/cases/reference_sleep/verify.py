"""Build and test the INT16 SoC candidate with the workspace toolchain."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "output/verification"
FIRMWARE = ROOT / "output/firmware"
TASKS = 12
RESULTS = 99 * 256
WORDS = RESULTS // 2


def prepare_expected():
    shift = json.loads((ROOT / "case.json").read_text())["output_format"]["shift"]
    step = 1 << shift
    halfway = step // 2
    expected_dir = ROOT / "output/expected_q16"
    expected_dir.mkdir(parents=True, exist_ok=True)
    saturation = max_error = sum_error_sq = sum_value_sq = 0
    low, high = 32767, -32768
    for task in range(TASKS):
        raw = [
            int(word, 16) for word in
            (ROOT / f"vectors/task_{task:02d}/expected.hex").read_text().split()
        ]
        assert len(raw) == RESULTS
        quantized = []
        for bits in raw:
            value = (bits & ((1 << 39) - 1)) - (bits & (1 << 39))
            magnitude, remainder = divmod(abs(value), step)
            magnitude += remainder > halfway or (remainder == halfway and magnitude % 2 == 1)
            rounded = -magnitude if value < 0 else magnitude
            q = min(32767, max(-32768, rounded))
            saturation += q != rounded
            low, high = min(low, q), max(high, q)
            error = abs(q * step - value)
            max_error = max(max_error, error)
            sum_error_sq += error * error
            sum_value_sq += value * value
            quantized.append(q & 65535)
        with (expected_dir / f"task_{task:02d}.hex").open("w") as out:
            for a, b in zip(quantized[::2], quantized[1::2]):
                out.write(f"{(b << 16) | a:08x}\n")
    return dict(shift=shift, saturation=saturation, range=[low, high], max_raw_error=max_error,
                relative_l2=math.sqrt(sum_error_sq / sum_value_sq))


def run(command, log_name, env):
    log = REPORT / log_name
    print("Running", log.name, flush=True)
    with log.open("w") as output:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=output,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        print("\n".join(log.read_text(errors="replace").splitlines()[-35:]), flush=True)
        raise SystemExit(f"{log}: exit code {result.returncode}")
    return log.read_text(errors="replace")


def build(cfg, env):
    gcc = Path(cfg["gcc"])
    FIRMWARE.mkdir(parents=True, exist_ok=True)
    run([str(gcc), "-march=rv32imac_zicsr_zifencei", "-mabi=ilp32", "-O2", "-ffreestanding",
         "-fno-builtin", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
         "-DFFN1_USE_ITCM=1", "-DFFN1_WAIT_MODE=2", "-DFFN1_POLL_PAUSE=64",
         "-T", "firmware/link_itcm.ld", "firmware/start.S", "firmware/main.c",
         "firmware/kwt_driver.c", "firmware/kwt_irq.c", "-o", "output/firmware/kwt.elf"],
        "firmware_build.log", env)
    objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
    run([str(objcopy), "-O", "binary", "output/firmware/kwt.elf", "output/firmware/kwt.bin"],
        "firmware_objcopy.log", env)
    firmware = (FIRMWARE / "kwt.bin").read_bytes()
    firmware += bytes(-len(firmware) % 4)
    with (FIRMWARE / "kwt.hex").open("w") as out:
        for offset in range(0, len(firmware), 4):
            out.write(f"{int.from_bytes(firmware[offset:offset + 4], 'little'):08x}\n")
    (FIRMWARE / "size.vh").write_text(f"`define FW_WORDS {len(firmware) // 4}\n")
    sources = [
        line.strip() for line in (ROOT / "filelists/soc.f").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    run([cfg["verilator"], "--cc", "--exe", "--main", "--timing", "-Wno-fatal",
         "--top-module", "tb_soc", "--Mdir", "tmp/sim", "-DDISABLE_SV_ASSERTION",
         "-Ivendor/e203/rtl/e203/core", "-Ioutput/firmware", "-Itests", "-Irtl"]
        + sources + ["tests/macro_fixtures.sv", "tests/tb_soc_power.sv"], "verilate.log", env)
    run([cfg["make"], "-C", "tmp/sim", "-f", "Vtb_soc.mk", "-j1"], "make.log", env)


def summarize(log, tasks):
    assert re.search(rf"^SOC_PASS tasks={tasks} ", log, re.M)
    bounds = {(int(task), event): (int(time_fs), int(cycle))
              for event, task, time_fs, cycle in re.findall(
                  r"^POWER_(BEGIN|END) task=(\d+) time_fs=(\d+) cycle=(\d+)$", log, re.M)}
    counters = {(int(task), int(index)): int(value) for task, index, value in re.findall(
        r"^SOC_PROFILE task=(\d+) index=(\d+) value=(\d+)$", log, re.M)}
    host = {int(task): (int(accepted), int(retired), int(overlap))
            for task, accepted, retired, overlap in re.findall(
                r"^SOC_HOST task=(\d+) accepted=(\d+) retired=(\d+) overlaps=(\d+)$", log, re.M)}
    passed = {int(task) for task in re.findall(
        rf"^SOC_TASK_PASS task=(\d+) cycles=\d+ outputs={RESULTS}$", log, re.M)}
    assert passed == set(range(tasks))
    tile = json.loads((ROOT / "case.json").read_text())["tile"]
    active_cycles = math.ceil(99 / tile["rows"]) * (256 // tile["columns"]) * (64 // tile["k_parallel"])
    records = []
    for task in range(tasks):
        begin, begin_cycle = bounds[task, "BEGIN"]
        end, end_cycle = bounds[task, "END"]
        elapsed = end - begin
        assert elapsed == (end_cycle - begin_cycle) * 6666667 + 3333333
        weight_words = json.loads((ROOT / "weight_transport.json").read_text())["layers"][task]["words"]
        config=json.loads((ROOT / "case.json").read_text())
        x_words=json.loads((ROOT / "x_transport.json").read_text())["layers"][task]["words"] if config.get("x_delta",False) else 3168
        bus_reads = weight_words + x_words + 256
        profile = [counters[task, i] for i in range(15)]
        assert profile[4] == active_cycles and profile[9:11] == [bus_reads, WORDS]
        assert profile[0] == sum(profile[1:4])
        accepted, retired, overlaps = host[task]
        assert accepted == retired == bus_reads and overlaps > 0
        records.append(dict(task=task, elapsed_fs=elapsed, cycles=elapsed / 6666667,
                            profile=profile, host_overlaps=overlaps))
    total = sum(record["elapsed_fs"] for record in records)
    return dict(tasks=tasks, outputs_checked=tasks * RESULTS, cycles_per_task=total / tasks / 6666667,
                tasks_per_second=tasks * 1e15 / total, records=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, choices=range(1, TASKS + 1), default=TASKS)
    parser.add_argument("--reuse-build", action="store_true")
    parser.add_argument("--cycle-breakdown", action="store_true", help="Emit disjoint bus-cycle accounting")
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT.parent / "environment/local_tools.json").read_text())
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(str(Path(cfg[k]).parent) for k in ("make", "verilator", "gcc")) + os.pathsep + env["PATH"]
    env["VERILATOR_ROOT"] = (Path(cfg["verilator"]).parent.parent / "share/verilator").as_posix()
    temp = ROOT / "tmp/temp"
    temp.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = str(temp)
    quantization = prepare_expected()
    if not args.reuse_build:
        build(cfg, env)
    exe = str(ROOT / ("tmp/sim/Vtb_soc.exe" if os.name == "nt" else "tmp/sim/Vtb_soc"))
    report = dict(quantization=quantization, modes={})
    for mode in ("reset_each_task", "continuous"):
        plusargs = [f"+tasks={args.tasks}", "+profile", "+fast_checks", "+host_continuous"]
        if args.cycle_breakdown:
            plusargs.append("+cycle_breakdown")
        if mode == "continuous":
            plusargs.append("+continuous")
        report["modes"][mode] = summarize(run([exe] + plusargs, f"{mode}.log", env), args.tasks)
        result = report["modes"][mode]
        print(f"{mode}: {result['cycles_per_task']:.3f} cycles/task, {result['tasks_per_second']:.3f} tasks/s")
    (REPORT / ("functional.json" if args.tasks == TASKS else "smoke.json")).write_text(
        json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
