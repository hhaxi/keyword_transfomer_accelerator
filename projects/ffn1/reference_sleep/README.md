# FFN1 Q128 reference with IRQ/WFI

This is the lowest-energy variant in the matched 150 MHz task00 server comparison. The reference's 128 MACs, 8×8×2 tile, lossless W and X transport, raw bias, INT40 accumulation and INT16 writeback are preserved. The SoC enables the existing interrupt path and uses WFI while waiting for Host and DMA events.

- [Server DC and RTL-SAIF results](reports/RESULTS.md)
- [12-layer local functional and cycle comparison](LOCAL_RESULTS.md)
- [Source and vector provenance](reference_binding.json)
- [Server instructions](SERVER.md)

From a repository checkout on the EDA server, run the following with the same libraries and constraints as the comparison.

```bash
cd undergrad_ffn1/candidates/q128_reference_sleep
sha256sum -c --quiet SHA256SUMS
bash run_combined.sh --resume
bash run_combined.sh --report-only
```

The runner captures the included real `task00` using VCS and reports the clock-gated DC result in `comparison.md`. For a local 12-layer rerun, copy `environment/local_tools.example.json` to `cases/environment/local_tools.json`, enter the local tool paths, and run `python verify.py --tasks 12 --cycle-breakdown` from `cases/reference_sleep`. The local verification rebuilds its firmware and expected vectors. Run the repository checksum before that rebuild to check the delivered bytes.
