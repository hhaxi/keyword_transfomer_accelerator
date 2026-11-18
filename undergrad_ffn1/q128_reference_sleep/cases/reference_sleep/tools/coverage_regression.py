"""Run Q128 SoC RTL coverage with VCS and merge passing runs with URG."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from gate_activity import ROOT, run


METRICS = "line+cond+fsm+tgl+branch"
MODES = ("reset_each_task", "continuous")


def functional_counts(log, tasks):
    completed = [int(task) for task in re.findall(
        r"^SOC_TASK_PASS task=(\d+) cycles=\d+ outputs=25344$", log, re.M)]
    if completed != list(range(tasks)) or not re.search(r"^SOC_PASS tasks={} ".format(tasks), log, re.M):
        raise ValueError("SoC regression did not pass every requested task")
    rows = re.findall(r"^KWT_COV (\w+) (\d+)$", log, re.M)
    counts = {name: int(count) for name, count in rows}
    required = {"same_cycle_refill", "sram_to_register", "register_to_sram",
                "response_stall", "error_response", "reset_with_pending"}
    paths = {"{}_{}_{}".format(m, t, op) for m in ("cpu", "host", "dma")
             for t in ("sram", "register", "denied") for op in ("read", "write")}
    if (len(counts) != len(rows) or set(counts) != required | paths or
            any(not counts.get(name) for name in required) or "KWT_COVERAGE_PROTOCOL_PASS" not in log):
        raise ValueError("missing or incomplete functional coverage and protocol results")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, choices=range(1, 13), default=12)
    args = parser.parse_args()
    for tool in ("vcs", "urg"):
        if not shutil.which(tool):
            parser.error(tool + " missing from PATH")
    for name in ("output/firmware/kwt.hex", "output/firmware/size.vh"):
        if not (ROOT / name).is_file():
            parser.error("firmware input missing: " + name)

    parent = ROOT / "run/coverage"
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt_", dir=str(parent)))
    print("Q128_COVERAGE_RUN", attempt, flush=True)
    hier = attempt / "dut.hier"
    hier.write_text("+tree tb_soc.dut\n", encoding="ascii")
    simv = attempt / "simv"
    vdb = attempt / "soc.vdb"
    env = os.environ.copy()
    run(["vcs", "-full64", "-sverilog", "-timescale=1ns/1fs",
         "-cm", METRICS, "-cm_hier", hier, "-cm_dir", vdb,
         "+define+DISABLE_SV_ASSERTION+KWT_COVERAGE", "+incdir+vendor/e203/rtl/e203/core+output/firmware+tests+rtl",
         "-f", "filelists/soc.f", "tests/macro_fixtures.sv", "tests/tb_soc_power.sv",
         "-top", "tb_soc", "-o", simv, "-Mdir=" + str(attempt / "csrc")],
        attempt / "compile.log", env)

    results = {}
    for mode in MODES:
        command = [simv, "-cm", METRICS, "-cm_dir", vdb, "-cm_name", mode,
                   "+tasks=" + str(args.tasks), "+profile", "+fast_checks", "+host_continuous"]
        if mode == "continuous":
            command.append("+continuous")
        log = attempt / (mode + ".log")
        try:
            results[mode] = functional_counts(run(command, log, env), args.tasks)
        except ValueError as error:
            raise SystemExit("{}: {}".format(log, error))
    report = attempt / "urg_report"
    run(["urg", "-full64", "-dir", vdb, "-show", "tests", "-report", report, "-format", "both"],
        attempt / "urg.log", env)
    if not (report / "dashboard.html").is_file():
        raise SystemExit("URG dashboard missing; inspect " + str(attempt / "urg.log"))
    (attempt / "functional.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Q128 SoC functional coverage", "", "| Scenario | Reset per task | Continuous |",
             "|---|---:|---:|"]
    lines += ["| {} | {} | {} |".format(key, results[MODES[0]][key], results[MODES[1]][key])
              for key in sorted(results[MODES[0]])]
    (attempt / "functional.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Q128_COVERAGE_COMPLETE", attempt)


if __name__ == "__main__":
    main()
