"""Capture one FFN1 RTL task with VCS and compare two DC clock-gating modes."""
import argparse
import os
from pathlib import Path
import re
import shutil
import tempfile

from gate_activity import ROOT, build_native_exporter, capture_saif, power_row, run, sha


def compile_rtl(folder, env):
    simv = folder / "simv"
    run(["vcs", "-full64", "-sverilog", "-debug_access+all", "-timescale=1ns/1fs",
         "+define+DISABLE_SV_ASSERTION", "+incdir+vendor/e203/rtl/e203/core+output/firmware+tests+rtl",
         "-f", "filelists/soc.f", "tests/macro_fixtures.sv", "tests/tb_soc_power.sv",
         "-top", "tb_soc", "-o", simv, "-Mdir=" + str(folder / "csrc")],
        folder / "vcs_compile.log", env)
    return simv


def compare(attempt, modes, env, executable):
    capture = attempt / "capture"
    capture.mkdir()
    simv = compile_rtl(capture, env)
    saif, duration = capture_saif(simv, capture, env, executable)
    digest = sha(saif)
    dc_env = dict(env, KWT_RTL_SAIF=str(saif))
    lines = ["VCS RTL SAIF, task 00. DC estimates mapped activity, including inserted clocks.",
             "", "Mode | Strict cycles | Dynamic mW | Leakage mW | Total mW | Energy uJ/task | DC run",
             " | ".join(["---"] * 7)]
    for mode in modes:
        log_path = attempt / (mode + "_dc.log")
        log = run(["bash", "run_dc.sh", mode], log_path, dc_env)
        run_dirs = re.findall(r"^KWT_DC_COMPLETED: (.+)$", log, re.M)
        reports = re.findall(r"^KWT_RTL_SAIF_POWER_COMPLETED: (.+)$", log, re.M)
        if len(run_dirs) != 1 or len(reports) != 1 or sha(saif) != digest:
            raise ValueError("missing DC report marker or changed task SAIF; see " + str(log_path))
        row = power_row(mode, Path(reports[0].strip()) / "power.rpt", duration, run_dirs[0].strip())
        lines.append("{} | {:.3f} | {:.5f} | {:.5f} | {:.5f} | {:.5f} | {}".format(*row))
        (attempt / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["baseline", "clock_gate", "both"], nargs="?", default="both")
    args = parser.parse_args()
    for tool in ("bash", "vcs", "dc_shell", "vcd2saif", "g++"):
        if not shutil.which(tool):
            parser.error(tool + " missing from PATH")
    parent = ROOT / "run/vcs_rtl_power"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt_", dir=str(parent)))
    print("Q128_VCS_RTL_POWER_RUN", attempt, flush=True)
    executable = build_native_exporter(shutil.which("g++"), attempt / "exporter")
    modes = ("baseline", "clock_gate") if args.mode == "both" else (args.mode,)
    compare(attempt, modes, os.environ.copy(), executable)


if __name__ == "__main__":
    main()
