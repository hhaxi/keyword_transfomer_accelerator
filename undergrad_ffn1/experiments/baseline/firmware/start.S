.section .init,"ax"
.globl _start
_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    li sp, 0xa000e000
    la t0, trap_entry
    csrw mtvec, t0
    call main
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
