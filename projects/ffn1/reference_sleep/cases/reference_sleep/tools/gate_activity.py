"""Compare one FFN1 task on the baseline and clock-gated DC netlists."""
import argparse
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

# The upload package vendors these existing helpers alongside this script.
if not Path(__file__).with_name("power_vcd.py").is_file():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from power_server import check_saif, parse_power, sha
from power_vcd import build_native_exporter, export_windows

ROOT = Path(__file__).resolve().parents[1]


def run(command, log, env, cwd=ROOT):
    print("Q128_VCS_STAGE", log, flush=True)
    with log.open("w", encoding="utf-8") as output, subprocess.Popen(
        [str(part) for part in command], cwd=str(cwd), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True, errors="replace",
    ) as process:
        for line in process.stdout:
            output.write(line)
            output.flush()
        status = process.wait()
    if status:
        raise SystemExit("command failed ({}) in {}".format(status, log))
    return log.read_text(encoding="utf-8", errors="replace")


def validate_task(log):
    if re.findall(r"^SOC_PASS tasks=(\d+) ", log, re.M) != ["1"] or len(re.findall(
        r"^SOC_TASK_PASS task=0 cycles=\d+ outputs=25344\s*$", log, re.M
    )) != 1:
        raise ValueError("VCS did not pass all 25344 INT16 results")
    markers = re.findall(r"^POWER_(BEGIN|END) task=0 time_fs=(\d+) cycle=(\d+)\s*$", log, re.M)
    if [marker[0] for marker in markers] != ["BEGIN", "END"]:
        raise ValueError("VCS strict task window missing or ambiguous")
    (_, start, start_cycle), (_, end, end_cycle) = markers
    duration = int(end) - int(start)
    if duration <= 0 or duration != (int(end_cycle) - int(start_cycle)) * 6666667 + 3333333:
        raise ValueError("VCS strict task duration and cycle markers disagree")
    profiles = dict(re.findall(r"^SOC_PROFILE task=0 index=(\d+) value=(\d+)\s*$", log, re.M))
    tile = json.loads((ROOT / "case.json").read_text())["tile"]
    active_cycles = math.ceil(99 / tile["rows"]) * (256 // tile["columns"]) * (64 // tile["k_parallel"])
    weight_words = json.loads((ROOT / "weight_transport.json").read_text())["layers"][0]["words"]
    config=json.loads((ROOT / "case.json").read_text())
    x_words=json.loads((ROOT / "x_transport.json").read_text())["layers"][0]["words"] if config.get("x_delta",False) else 3168
    if [profiles.get(str(i)) for i in (4, 9, 10)] != [str(active_cycles), str(weight_words + x_words + 256), "12672"]:
        raise ValueError("VCS MAC or DMA counts differ from the q128 task")
    return dict(task=0, start_fs=int(start), end_fs=int(end), duration_fs=duration)


def capture_saif(simv, folder, env, executable):
    raw = folder / "soc.vcd"
    simulation = run([simv, "+tasks=1", "+profile", "+fast_checks", "+host_continuous",
                      "+maxcycles=500000", "+vcd", "+vcd_path=" + str(raw)],
                     folder / "vcs_simulation.log", env)
    window = validate_task(simulation)
    row, = export_windows(raw, [window], folder, native_executable=executable)
    if row["duration_fs"] != window["duration_fs"]:
        raise ValueError("exported VCD duration differs from the VCS window")
    plain = folder / "task_00.vcd"
    saif = folder / "task_00.saif"
    with gzip.open(str(folder / row["file"]), "rb") as source, plain.open("wb") as target:
        shutil.copyfileobj(source, target, 1048576)
    run(["vcd2saif", "-input", plain, "-output", saif], folder / "convert.log", env, cwd=folder)
    check_saif(saif, window["duration_fs"])
    plain.unlink()
    raw.unlink()
    return saif, window["duration_fs"]


def power_row(mode, report, duration, dc_run):
    power = parse_power(report.read_text(errors="replace"))
    fields = [power[name + "_power_w"] for name in ("dynamic", "leakage", "total")]
    if any(value is None or not math.isfinite(value) or value < 0 for value in fields):
        raise ValueError("DC did not report complete activity power for " + mode)
    dynamic, leakage, total = fields
    return (mode, duration / 6666667, dynamic * 1e3, leakage * 1e3, total * 1e3,
            total * duration * 1e-9, str(dc_run))


def analyze(mode, folder, args, env, executable):
    folder.mkdir()
    if args.dc_run:
        dc_run = args.dc_run
    else:
        launch = run(["bash", "run_dc.sh", mode], folder / "dc.log", env)
        matches = re.findall(r"^KWT_DC_COMPLETED: (.+)$", launch, re.M)
        if len(matches) != 1:
            raise ValueError("DC run directory missing; inspect {}".format(folder / "dc.log"))
        dc_run = Path(matches[0].strip())
    settings = (dc_run / "report/run_settings.txt").read_text(encoding="ascii", errors="replace")
    if not re.search(r"^clock_gating_mode\s*=\s*{}\s*$".format(mode), settings, re.M):
        raise ValueError("DC mode mismatch in {}".format(dc_run))
    if not re.search(r"^clock_period_ns\s*=\s*6\.666667\s*$", settings, re.M):
        raise ValueError("DC run must use the 6.666667 ns task clock")
    netlist = dc_run / "netlist/kwt_ffn1_soc.v"
    ddc = dc_run / "netlist/kwt_ffn1_soc.ddc"
    signature = [sha(netlist), sha(ddc)]
    simv = folder / "simv"
    model_args = ["-f", args.models_filelist]
    if args.sram_models_filelist:
        model_args += ["-f", args.sram_models_filelist]
    else:
        model_args += [ROOT / "tests/macro_fixtures.sv"]
    run(["vcs", "-full64", "-sverilog", "-debug_access+all", "-debug_region=cell+lib",
         "-timescale=1ns/1fs", "+delay_mode_zero", "+notimingcheck", "+define+KWT_GATE_LEVEL_POWER",
         "+incdir+" + "+".join(str(ROOT / directory) for directory in ("rtl", "tests", "output/firmware")),
         "-top", "tb_soc", "-Mdir=" + str(folder / "csrc"), "-o", simv, netlist,
         ROOT / "tests/tb_soc_power.sv"] + model_args, folder / "vcs_compile.log", env, cwd=folder)
    saif, duration = capture_saif(simv, folder, env, executable)
    if signature != [sha(netlist), sha(ddc)]:
        raise ValueError("saved DC netlist or DDC changed after starting VCS")
    annotation_env = dict(env, KWT_ACTIVITY_DDC=str(ddc), KWT_ACTIVITY_SAIF=str(saif),
                          KWT_ACTIVITY_REPORT=str(folder), KWT_SYNTHESIS_SCOPE="soc")
    log = run(["dc_shell", "-f", ROOT / "script/gate_activity_power.tcl"], folder / "annotate.log",
              annotation_env, cwd=folder)
    if "KWT_GATE_ACTIVITY_COMPLETED" not in log.splitlines():
        raise ValueError("DC gate activity completion marker missing")
    return power_row(mode, folder / "power.rpt", duration, dc_run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["baseline", "clock_gate", "both"], nargs="?", default="both")
    parser.add_argument("--models-filelist", required=True, type=Path)
    parser.add_argument("--sram-models-filelist", type=Path)
    parser.add_argument("--dc-run", type=Path, help="Reuse an existing run for one mode")
    args = parser.parse_args()
    if args.dc_run and args.mode == "both":
        parser.error("--dc-run requires a single mode")
    for field in ("models_filelist", "sram_models_filelist", "dc_run"):
        path = getattr(args, field)
        if path is not None:
            if not (path.is_dir() if field == "dc_run" else path.is_file()):
                parser.error("missing path: " + str(path))
            setattr(args, field, path.resolve())
    for tool in ("bash", "vcs", "dc_shell", "vcd2saif", "g++"):
        if not shutil.which(tool):
            parser.error(tool + " missing from PATH")
    parent = ROOT / "run/vcs_power"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt_", dir=str(parent)))
    print("Q128_VCS_POWER_RUN", attempt, flush=True)
    env = os.environ.copy()
    executable = build_native_exporter(shutil.which("g++"), attempt / "exporter")
    modes = ("baseline", "clock_gate") if args.mode == "both" else (args.mode,)
    header = "Mode | Strict cycles | Dynamic mW | Leakage mW | Total mW | Energy uJ/task | DC run"
    note = ("VCS mapped-netlist SAIF, task 00, zero delay, coverage review required. SRAM simulation: "
            + ("vendor models" if args.sram_models_filelist else "behavioral fixtures") + ".")
    lines = [note, "", header, " | ".join(["---"] * 7)]
    for mode in modes:
        result = analyze(mode, attempt / mode, args, env, executable)
        lines.append("{} | {:.3f} | {:.5f} | {:.5f} | {:.5f} | {:.5f} | {}".format(*result))
        (attempt / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
