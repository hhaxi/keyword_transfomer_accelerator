"""Check unmapped accelerator structure and native SRAM inventory."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BLACKBOXES = ROOT / "tests/sram_blackboxes.sv"


def check(case, yosys, env):
    out = case / "tmp/struct"
    out.mkdir(parents=True, exist_ok=True)
    sources = (case / "filelists/accelerator.f").read_text().splitlines()
    lines = [
        'read_verilog -sv -lib "{}"'.format(BLACKBOXES.as_posix()),
        "read_verilog -sv -defer -DSYNTHESIS -DDISABLE_SV_ASSERTION -Itests -Irtl "
        + " ".join(s for s in sources if s.strip() and not s.lstrip().startswith("#")),
        "hierarchy -check -top kwt_ffn1_top", "proc", "flatten", "opt", "check -assert",
        "write_json tmp/struct/netlist.json",
    ]
    (out / "run.ys").write_text("\n".join(lines) + "\n")
    with (out / "yosys.log").open("w") as log:
        result = subprocess.run([str(yosys), "-s", "tmp/struct/run.ys"], cwd=str(case),
                                env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError((out / "yosys.log").read_text(errors="replace").splitlines()[-12:])
    netlist = json.loads((out / "netlist.json").read_text())
    cells = list(netlist["modules"]["kwt_ffn1_top"]["cells"].values())
    macs = sum(cell["type"] == "$mul" and all(
        int(cell["parameters"][key], 2) == value
        for key, value in (("A_WIDTH", 16), ("B_WIDTH", 16), ("A_SIGNED", 1), ("B_SIGNED", 1))
    ) for cell in cells)
    macros = {kind: sum(c["type"] == kind for c in cells)
              for kind in ("RAMSP128X16", "RAMSP1024X16", "RAMSP4096X16")}
    bits = sum(len(c["connections"].get("Q", [])) for c in cells if "dff" in c["type"])
    assert macs == 128
    assert list(macros.values()) == [36, 16, 0]
    return dict(macs=macs, macros=macros, generic_register_bits=bits)


if __name__ == "__main__":
    cfg = json.loads((ROOT.parent / "environment/local_tools.json").read_text())
    yosys = Path(cfg["yosys"])
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(yosys.parent), str(yosys.parent.parent / "lib"), env["PATH"]))
    result = check(ROOT, yosys, env)
    (ROOT / "output/verification/structure.json").write_text(json.dumps(result, indent=2) + "\n")
    print("COMBO_STRUCTURE_PASS", result)
