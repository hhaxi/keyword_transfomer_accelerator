"""Require useful E203 WFI and complete strict timing for every recorded task."""
import argparse
from pathlib import Path
import re


def check_activity(log, tasks):
    activity = re.findall(
        r"^SOC_ACTIVITY task=(\d+) wfi_cycles=(\d+) cpu_clock_edges=(\d+)"
        r"(?: ifu_clock_edges=(\d+) exu_clock_edges=(\d+))?$", log, re.M
    )
    if [int(row[0]) for row in activity] != list(range(tasks)):
        raise ValueError("missing or duplicate per-task activity")
    edges = []
    for task, wfi, root, ifu, exu in activity:
        if not int(wfi):
            raise ValueError("task {} never entered WFI".format(task))
        if not ifu or not exu or not 0 < int(ifu) < int(root) or not 0 < int(exu) <= int(root):
            raise ValueError("task {} has invalid or ungated IFU/EXU activity".format(task))
        bounds = re.findall(
            r"^POWER_(BEGIN|END) task=" + task + r" time_fs=\d+ cycle=(\d+)$", log, re.M
        )
        if [event for event, _ in bounds] != ["BEGIN", "END"]:
            raise ValueError("task {} is missing a strict window".format(task))
        cycles = int(bounds[1][1]) - int(bounds[0][1])
        if abs(cycles - int(root)) > 1 or int(wfi) > int(root):
            raise ValueError("task {} has activity outside the strict window".format(task))
        edges.append(tuple(map(int, (wfi, root, ifu, exu))))
    return edges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--tasks", type=int, default=12)
    args = parser.parse_args()
    for path in args.logs:
        try:
            edges = check_activity(path.read_text(), args.tasks)
        except ValueError as error:
            parser.exit(1, "{}: {}\n".format(path, error))
        means = [sum(column) / len(column) for column in zip(*edges)]
        print("WFI_ACTIVITY_PASS {} tasks={} mean_wfi={:.1f} mean_root={:.1f} "
              "mean_ifu={:.1f} mean_exu={:.1f}".format(path.name, args.tasks, *means))


if __name__ == "__main__":
    main()
