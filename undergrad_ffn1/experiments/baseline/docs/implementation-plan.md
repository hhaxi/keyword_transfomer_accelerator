# Independent undergraduate submission baseline

Authorized scope: isolate FFN1 from the existing complete encoder project.
Keep integer arithmetic, 16 MACs, packed input/weight DMA, 64-bit output transport,
shared SRAM, real pinned E203 and current task timer. Remove optional arithmetic
and memories rather than merely selecting mode=0 in software.

- [x] Freeze parent source/artifact fingerprints and add isolation checks.
- [x] Copy only required vendor, platform, firmware, model and vector sources.
- [x] Specialize the core/DMA to FFN1, keep the tested scheduling unchanged.
- [x] Build independent firmware and real E203 simulation; test 12 parameter
  sets, component edge cases and parameter replacement without reset.
- [x] Check macro inventory/hierarchy and native single-port mapping boundaries.
- [x] Adapt DC scripts for FFN1 SoC/accelerator scopes and Desktop-relative libs.
- [x] Produce self-contained server archive and reproducibility receipts.
- [x] Explain planned optimizations using the user's four-field format; keep
  performance optimizations out of this structural baseline.

Expected accelerator inventory: 18x1024x16 + 2x4096x16 = 52 KiB, 20 macros.
SoC includes an additional 64 shared + 16 TCM 4096x16 macros: 100 total, 692 KiB.
Actual foundry mapping/PPA requires server DC and the supplied DB libraries.
