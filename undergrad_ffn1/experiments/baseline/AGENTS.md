# Undergraduate FFN1 workspace

All undergraduate optimization work belongs in this directory. Do not edit the
parent project or its backend/archive when working on this version.

The hardware scope is E203 + existing shared SRAM + one 99x64 by 64x256 biased
linear engine. No Attention, GELU, FFN2 or encoder scheduling in submitted RTL.
Preserve the frozen numerical contract until a numerical change is explicitly
chosen. Test all 12 layer parameter sets and record reproducible task timing.

Before each optimization explain: old behavior, proposed implementation, metrics
expected to improve, and metrics/risks that may worsen. Change one optimization
at a time and compare with verification/baseline.json. Capacity is not area;
cycle estimates at 150 MHz are not proof of timing closure.

User decisions (2026-11-01): ITCM instruction fetch, small-X DMA ping-pong
buffers, bias SRAM downsizing, and continuous Host loading are approved but
explicitly deferred for a later coding batch. Record/design discussion now;
do not begin implementation
until that batch is requested. PE-array restructuring and lossless packed40
output, plus interrupt-driven waiting with WFI, are candidates only. Other
proposed optimizations are not approved.
See docs/optimization-roadmap.md for scope and tradeoffs.

Tool executables may be read/executed from configured external locations; all
generated files must stay here. Vendor E203 sources retain their license and
revision. Local Host/mailbox protocol is not an official-platform certification.
