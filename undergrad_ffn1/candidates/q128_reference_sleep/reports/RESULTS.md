# Matched FFN1 SoC server results

The table transcribes the supplied server summaries for real nonzero `task00`, with the strict interval from the first Host data request through the final DMA write response. Each result uses the 150 MHz synthesis target and RTL-SAIF activity estimation. Areas are in linked-library units. These are single-task synthesis estimates. The source server logs and raw EDA artifacts are outside this snapshot.

| Candidate | Added area | SoC area | Cycles | task/s | Dynamic mW | Leakage mW | µJ/task | Setup WNS ns | SS hold WNS ns | Seq SAIF % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| reference | 504210 | 2736900 | 32738 | 4581.9 | 33.877 | 4.41 | 8.3561 | 0 | -0.14 | 68.42 |
| compact | 510900 | 2743600 | 32924 | 4556 | 34.190 | 4.41 | 8.4723 | 0 | -0.11 | 67.71 |
| dense | 517180 | 2749800 | 32528 | 4611.3 | 34.595 | 4.42 | 8.4607 | 0 | -0.12 | 67.54 |
| dense_sleep | 518090 | 2750800 | 32644 | 4595.1 | 32.532 | 4.42 | 8.0416 | 0 | -0.12 | 67.66 |
| dense_sched | 517390 | 2750000 | 32450 | 4622.4 | 34.938 | 4.42 | 8.5146 | 0 | -0.11 | 67.54 |
| **reference_sleep** | **505560** | **2738200** | **32960** | **4551** | **31.908** | **4.41** | **7.9802** | **0** | **-0.17** | **68.53** |

`reference_sleep` is selected for the lowest task energy. Compared with `reference`, it reduces dynamic power by 5.81% and task energy by 4.50%, with 0.27% more added area and 0.67% lower throughput. `reference` has the least added area, while `dense_sched` has the highest task00 throughput. The SS hold slack of the selected variant is -0.17 ns. The 68.53% figure is sequential activity annotation coverage. Actual clock-gating coverage is reported separately by DC.

The separate [local RTL regression](../LOCAL_RESULTS.md) covers all 12 layers in two execution modes. Its 4,686.50 task/s value is calculated from the mean of 12 continuous tasks. The table above reports the server's single task00 result.
