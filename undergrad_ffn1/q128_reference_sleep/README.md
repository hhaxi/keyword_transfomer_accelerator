# FFN1 Q128 reference with IRQ/WFI

The Q128 FFN1 SoC uses 128 MACs, an 8×8×2 tile, lossless W and X transport, raw bias, INT40 accumulation and INT16 writeback. The E203 uses WFI while waiting for Host and DMA events. The current RTL uses the upstream E203 `sirv_icb1to8_bus` behind KWT's CPU/Host/DMA arbiter. The original custom-bus variant had the lowest task energy in the matched 150 MHz server comparison.

- [Server DC and RTL-SAIF baseline before the bus replacement](reports/RESULTS.md)
- [12-layer local functional and cycle comparison](LOCAL_RESULTS.md)
- [Original custom-bus reference provenance](reference_binding.json)
- [Server synthesis, coverage and SpyGlass instructions](SERVER.md)

From a repository checkout on the EDA server, run the following with the same libraries and constraints as the comparison.

```bash
cd undergrad_ffn1/q128_reference_sleep
sha256sum -c --quiet SHA256SUMS
bash run_combined.sh --resume
bash run_combined.sh --report-only
```

The runner captures the included real `task00` using VCS and reports the clock-gated DC result in `comparison.md`. For a local 12-layer rerun, copy `environment/local_tools.example.json` to `cases/environment/local_tools.json`, enter the local tool paths, and run `python verify.py --tasks 12 --cycle-breakdown` from `cases/reference_sleep`. The local verification rebuilds its firmware and expected vectors. Run the repository checksum before that rebuild to check the delivered bytes.
