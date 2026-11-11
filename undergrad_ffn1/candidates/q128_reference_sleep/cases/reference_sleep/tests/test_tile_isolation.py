"""Check all 128 multiplier inputs in active, idle and fused-seed states."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp/tile_isolation"


def main():
    cfg = json.loads((ROOT.parent / "environment/local_tools.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = env["TMP"] = str(OUT)
    sources = ["tests/macro_fixtures.sv"]
    if (ROOT / "tech/kwt_sram_clock_gate.sv").exists():
        sources.append("tech/kwt_sram_clock_gate.sv")
    sources += ["tech/kwt_sram16.sv", "rtl/kwt_tile_mac.sv",
                "rtl/kwt_int16_result_queue.sv", "rtl/kwt_tile_core.sv",
                "tests/tb_tile_isolation.sv"]
    executable = OUT / "tb_tile_isolation.vvp"
    commands = [
        [cfg["iverilog"], "-g2012", "-Itests", "-Irtl", "-s", "tb_tile_isolation",
         "-o", str(executable)] + sources,
        [str(Path(cfg["iverilog"]).with_name("vvp.exe")), str(executable)],
    ]
    for name, command in zip(("compile", "run"), commands):
        result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (OUT / f"{name}.log").write_text(result.stdout)
        print(result.stdout, end="")
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
