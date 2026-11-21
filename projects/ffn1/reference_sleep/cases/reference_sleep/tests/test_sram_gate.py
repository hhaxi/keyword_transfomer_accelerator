"""Run local SRAM gate edge, glitch, latency and default-clock checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp/sram_gate"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-gate-api", action="store_true", help="test original wrapper before GATE_CLK exists")
    parser.add_argument("--prove-glitch-check", action="store_true",
                        help="require the bench to reject an unsafe clk & cs mutant")
    args = parser.parse_args()
    if args.pre_gate_api and args.prove_glitch_check:
        parser.error("choose one negative-check mode")
    cfg = json.loads((ROOT.parent / "environment/local_tools.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = env["TMP"] = str(OUT)
    executable = OUT / "tb_sram_gate.vvp"
    sources = ["tests/macro_fixtures.sv"]
    if args.prove_glitch_check:
        mutant = OUT / "unsafe_combinational_gate.sv"
        mutant.write_text("module kwt_sram_clock_gate(input clk,enable, output gated_clk); "
                          "assign gated_clk=clk & enable; endmodule\n")
        sources.append(str(mutant))
    elif (ROOT / "tech/kwt_sram_clock_gate.sv").exists():
        sources.append("tech/kwt_sram_clock_gate.sv")
    sources += ["tech/kwt_sram16.sv", "tests/tb_sram_gate.sv"]
    commands = [
        [cfg["iverilog"], "-g2012", "-Itests", "-s", "tb_sram_gate", "-o", str(executable)] + sources,
        [str(Path(cfg["iverilog"]).with_name("vvp.exe")), str(executable)],
    ]
    if args.pre_gate_api:
        commands[0].insert(1, "-DKWT_TEST_PRE_GATE_API")
    for name, command in zip(("compile", "run"), commands):
        result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        suffix = "_pre_gate" if args.pre_gate_api else "_unsafe_mutant" if args.prove_glitch_check else ""
        (OUT / f"{name}{suffix}.log").write_text(result.stdout)
        print(result.stdout, end="")
        if name == "run" and args.prove_glitch_check:
            assert result.returncode != 0, "unsafe clock gate was not rejected"
            assert "high-phase CS glitch generated an edge" in result.stdout
            assert "clock high pulse was truncated" in result.stdout
            print("SRAM_GATE_UNSAFE_MUTANT_REJECTED")
        elif result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
