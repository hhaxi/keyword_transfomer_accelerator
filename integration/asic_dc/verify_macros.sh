#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
e203=assets/references/e203_hbirdv2-9f3e34f337f5d0a1236a285871ffa2032491617a/rtl/e203
tech=undergrad_ffn1/tech
fixtures=undergrad_ffn1/tests
output=output/encoder-dc
mkdir -p "$output"
mapfile -t encoder < <(tr -d '\r' < integration/asic_dc/encoder.f)
upstream=()
for file in "$e203"/{core,general}/*.v; do
    [[ ${file##*/} == sirv_gnrl_ram.v ]] || upstream+=("$file")
done
upstream+=("$e203/subsys/e203_subsys_nice_core.v")
macros=("$tech/kwt_sram16.sv" "$tech/kwt_banked_sram.sv" "$tech/kwt_shared_sram.sv" "$tech/sirv_gnrl_ram.sv")
includes=("+incdir+$e203/core" "+incdir+$fixtures")
verilator --binary --timing --build-jobs "${KWT_SIM_JOBS:-4}" -Wno-fatal \
    --top-module tb_encoder_soc --Mdir "$output/sim" \
    +define+DISABLE_SV_ASSERTION +define+KWT_CONTEST_PROJECTION +define+ENCODER_PHASE_METRICS \
    "${includes[@]}" +incdir+output/encoder-design/firmware \
    "${upstream[@]}" "${encoder[@]}" "${macros[@]}" "$fixtures/macro_fixtures.sv" \
    integration/kwt_encoder_soc.sv tests/tb_encoder_soc.sv > "$output/sim-build.log" 2>&1
"$output/sim/Vtb_encoder_soc" +first=0 "+tasks=${1:-1}" +transport=2 +input_stream=1 +layers=12 \
    > "$output/sim-task.log" 2>&1
grep 'ENC_SOC_.*PASS' "$output/sim-task.log"
