.section .init,"ax"
.globl _start
_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    li sp, 0xa000e000
#ifdef FFN1_USE_ITCM
    /* All stores use the CPU LSU-to-ITCM path; no external/backdoor access. */
    la t0, __itcm_load
    la t1, __itcm_start
    la t2, __itcm_end
copy_itcm:
    bgeu t1, t2, copy_done
    lw t3, 0(t0)
    sw t3, 0(t1)
    addi t0, t0, 4
    addi t1, t1, 4
    j copy_itcm
copy_done:
    fence iorw, iorw
    fence.i
#endif
    la t0, trap_entry
    csrw mtvec, t0
#ifdef FFN1_USE_ITCM
    li t0, 0xa000f008
    li t1, 0x4954434d
    sw t1, 0(t0)
    fence iorw, iorw
#endif
    call main
#ifdef FFN1_USE_ITCM
    j .
.section .text.trap_body,"ax"
#endif
trap:
    li t0, 0xa000f000
    li t1, 0xbad
    sw t1, 0(t0)
1:  j 1b

/* mtvec requires a four-byte-aligned base even when compressed ISA is enabled.
 * Keep this entry after normal text so the measured driver layout is unchanged. */
.section .trap,"ax"
.balign 4
trap_entry:
    j trap
