"""Run the Z100 build or behavioral simulation through the AMD Ross MCP server."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class Ross:
    def __init__(self, binary, log, build, env):
        self.proc = subprocess.Popen(
            [str(binary), "--stdio", f"--state-dir={build / 'ross-state'}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding="utf-8", env=env,
        )
        self.request = 0
        self.call("initialize", protocolVersion="2024-11-05", capabilities={},
                  clientInfo={"name": "kwt-z100", "version": "1"})
        self.send(method="notifications/initialized")

    def send(self, **message):
        self.proc.stdin.write(json.dumps(dict(jsonrpc="2.0", **message)) + "\n")
        self.proc.stdin.flush()

    def call(self, method, **params):
        self.request += 1
        self.send(id=self.request, method=method, params=params)
        for line in self.proc.stdout:
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if reply.get("id") == self.request:
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply["result"]
        raise RuntimeError("Ross MCP exited")

    def tool(self, name, **arguments):
        reply = self.call("tools/call", name=name, arguments=arguments)
        message = reply["content"][0]["text"]
        print(f"{name}: {message[-8000:]}", flush=True)
        if reply.get("isError"):
            raise RuntimeError(name)
        try:
            return json.loads(message)
        except ValueError:
            return {}

    def execute(self, session, command):
        result = self.tool("vivado_execute", session_id=session, command=command)
        while result.get("status") == "running" or result.get("is_command_running"):
            time.sleep(10)
            result = self.tool("vivado_status", session_id=session)
        if (result.get("last_completed_code", 0) != 0 or result.get("exit_code", 0) != 0 or
                result.get("return_code", 0) != 0 or result.get("status") == "error"):
            raise RuntimeError(command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["smoke", "kwt", "contest", "sim"])
    parser.add_argument("--mhz", type=int, choices=range(20, 101), metavar="{20..100}", default=25)
    parser.add_argument("--ethernet", action="store_true", help="Use the XC7Z035 Ethernet PS preset")
    parser.add_argument("--parallel-projection", action="store_true")
    parser.add_argument("--parallel-attention", action="store_true")
    parser.add_argument("--wide-encoder", action="store_true")
    parser.add_argument("--parallel-ffn", action="store_true")
    parser.add_argument("--stream-handoff", action="store_true")
    parser.add_argument("--held-gelu", action="store_true")
    parser.add_argument("--in-process", action="store_true", help="Run implementation in the Ross Vivado process")
    parser.add_argument("--bit-only", action="store_true", help="Skip XSA export")
    parser.add_argument("--build", type=Path, default=ROOT / "output" / "z100")
    parser.add_argument("--vivado", type=Path,
                        default=Path("D:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat"))
    parser.add_argument("--mcp", type=Path,
                        default=Path("D:/.codex/tools/amd-ross/vivado-mcp-server-windows-amd64-2026.10.1.exe"))
    args = parser.parse_args()
    if args.mode == "contest" and not args.ethernet:
        parser.error("contest uses the Z100 Ethernet loader; add --ethernet")
    if args.mode == "contest" and any((args.parallel_projection, args.parallel_attention,
                                       args.wide_encoder, args.parallel_ffn, args.stream_handoff,
                                       args.held_gelu)):
        parser.error("contest has a fixed SRAM-backed RTL configuration")
    if (args.stream_handoff or args.held_gelu) and not args.parallel_ffn:
        parser.error("--stream-handoff and --held-gelu require --parallel-ffn")
    build = args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(VIVADO_PATH=str(args.vivado), Z100_BUILD=build.as_posix(),
               Z100_KWT="1" if args.mode in ("kwt", "contest") else "0", Z100_FCLK_MHZ=str(args.mhz),
               Z100_CONTEST="1" if args.mode == "contest" else "0",
               Z100_ETHERNET="1" if args.ethernet else "0",
               Z100_FAST_ATTENTION="1" if args.parallel_attention else "0",
               Z100_WIDE_ENCODER="1" if args.wide_encoder else "0",
               Z100_FAST_FFN_ROWS="1" if args.parallel_ffn else "0",
               Z100_FAST_HANDOFF="1" if args.stream_handoff else "0",
               Z100_HELD_GELU="1" if args.held_gelu else "0",
               Z100_IN_PROCESS="1" if args.in_process else "0",
               Z100_BIT_ONLY="1" if args.bit_only else "0",
               Z100_FAST_PROJECTION="1" if args.parallel_projection else "0")
    script = HERE / ("sim_ffn.tcl" if args.mode == "sim" else "run_smoke.tcl")
    suffix = "bit" if args.bit_only else "xsa"
    artifact = (build / "sim-ffn" / "xsim.log" if args.mode == "sim" else
                build / (f"z100-smoke.{suffix}" if args.mode == "smoke" else f"z100-{args.mode}-{args.mhz}.{suffix}"))
    previous = artifact.stat().st_mtime_ns if artifact.exists() else 0
    with (build / f"ross-{args.mode}-{args.mhz}.log").open("w", encoding="utf-8") as log:
        ross = Ross(args.mcp, log, build, env)
        session = None
        try:
            session = ross.tool("vivado_start", working_dir=build.as_posix(),
                                session_type="general" if args.mode == "sim" else "ipi")["session_id"]
            ross.execute(session, "source {" + script.as_posix() + "}")
            if not artifact.exists() or artifact.stat().st_mtime_ns <= previous:
                raise RuntimeError(f"Ross did not produce {artifact}")
        finally:
            if session:
                ross.tool("vivado_stop", session_id=session)
            ross.proc.terminate()
    print(artifact)


if __name__ == "__main__":
    main()
