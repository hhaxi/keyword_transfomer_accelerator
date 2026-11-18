"""Elaborate both Z100 row configurations and count the explicit accelerator SRAM cells."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

from run_design import CONFIG, E203_RTL, ROOT, SYSTEM_RTL
from run_encoder import ENC_BUS, ENC_RTL


def inventory(compact, directory):
    xml = directory / "hierarchy.xml"
    args = [CONFIG.get("wsl_verilator", "verilator"), "--xml-only", "--no-timing", "-Wno-fatal",
            "--xml-output", xml.relative_to(ROOT).as_posix(), "--top-module", "kwt_extended_system_bus",
            "-GWIDE_MACRO=1", "-DDISABLE_SV_ASSERTION", "-DKWT_SRAM_BLACKBOX", "-DKWT_CONTEST_ROW_FFN",
            "-I"+(E203_RTL/"core").relative_to(ROOT).as_posix(), "-Iundergrad_ffn1/rtl"]
    if compact:
        args.append("-DKWT_COMPACT="+str(compact))
    args += SYSTEM_RTL + ENC_RTL + ENC_BUS + ["integration/kwt_shared_sram.sv", "undergrad_ffn1/rtl/kwt_ffn1_core.sv",
                                             "integration/z100/z100_ffn2.sv", "integration/z100/z100_ffn_rows.sv"]
    if os.name == "nt":
        args = ["wsl", "-d", CONFIG.get("wsl_distro", "Ubuntu"), "--", *args]
    proc = subprocess.run(args, cwd=ROOT, capture_output=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace")[-3000:])
    tree = ET.parse(xml)
    depths = {}
    for module in tree.iter("module"):
        if module.get("origName") == "kwt_sram16":
            literal = module.find("var[@name='AW']/const").get("name")
            depths[module.get("name")] = 1 << int(literal.split("h")[-1], 16)
    scopes = {"encoder":Counter(), "ffn":Counter()}
    for cell in tree.iter("cell"):
        if cell.get("submodname") in depths:
            hierarchy = cell.get("hier")
            if ".encoder." in hierarchy:
                scope = "encoder"
            elif ".ffn." in hierarchy:
                scope = "ffn"
            else:
                raise ValueError(f"Unclassified SRAM instance: {hierarchy}")
            scopes[scope][depths[cell.get("submodname")]] += 1
    if not all(scopes.values()):
        raise RuntimeError("Incomplete accelerator hierarchy")
    total = scopes["encoder"] + scopes["ffn"]
    return dict(count_by_depth=total, scopes=scopes, bytes=sum(2*k*n for k,n in total.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    (ROOT/"output").mkdir(exist_ok=True)
    with TemporaryDirectory(dir=ROOT/"output") as temp:
        result = {name: inventory(compact, Path(temp)) for name,compact in [("seven_rows",0),("compact_one",1),("compact_two",2)]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+"\n")
