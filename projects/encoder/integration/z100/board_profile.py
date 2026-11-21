"""Extract the PS configuration from the Z100 XC7Z035 Hello World block design."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("block_design", type=Path)
    parser.add_argument("output_tcl", type=Path)
    args = parser.parse_args()
    design = json.loads(args.block_design.read_text(encoding="utf-8"))
    ps = design["design"]["components"]["processing_system7_0"]
    parameters = {key: entry["value"] for key, entry in ps["parameters"].items()}
    if parameters["PCW_UART0_UART0_IO"] != "MIO 14 .. 15":
        raise ValueError("Expected the XC7Z035 Z100 UART0 board configuration")
    fields = ["set z100_ps_config [list \\\n"]
    for key, value in sorted(parameters.items()):
        # The MIO tree strings are GUI summaries derived from individual MIO settings.
        if key.startswith("PCW_MIO_TREE_"):
            continue
        if not key.isidentifier() or any(char in value for char in "{}\\\n\r"):
            raise ValueError(f"Unexpected Tcl value for {key}")
        fields.append(f"    CONFIG.{key} {{{value}}} \\\n")
    fields.append("]\n")
    args.output_tcl.write_text("".join(fields), encoding="ascii")


if __name__ == "__main__":
    main()
