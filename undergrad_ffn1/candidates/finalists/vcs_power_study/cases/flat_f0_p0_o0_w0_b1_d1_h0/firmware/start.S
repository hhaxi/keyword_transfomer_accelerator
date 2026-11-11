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
#if defined(FFN1_WAIT_MODE) && FFN1_WAIT_MODE == 2
    j irq_trap_body
#else
    li t0, 0xa000f000
    li t1, 0xbad
    sw t1, 0(t0)
1:  j 1b
#endif

/* mtvec requires a four-byte-aligned base even when compressed ISA is enabled.
 * Keep this entry after normal text so the measured driver layout is unchanged. */
.section .trap,"ax"
.balign 4
trap_entry:
    j trap

#if defined(FFN1_WAIT_MODE) && FFN1_WAIT_MODE == 2
.section .text.irq_trap_body,"ax"
.balign 4
irq_trap_body:
    addi sp,sp,-128
    sw ra,0(sp)
    sw gp,4(sp)
    sw tp,8(sp)
    sw t0,12(sp)
    sw t1,16(sp)
    sw t2,20(sp)
    sw s0,24(sp)
    sw s1,28(sp)
    sw a0,32(sp)
    sw a1,36(sp)
    sw a2,40(sp)
    sw a3,44(sp)
    sw a4,48(sp)
    sw a5,52(sp)
    sw a6,56(sp)
    sw a7,60(sp)
    sw s2,64(sp)
    sw s3,68(sp)
    sw s4,72(sp)
    sw s5,76(sp)
    sw s6,80(sp)
    sw s7,84(sp)
    sw s8,88(sp)
    sw s9,92(sp)
    sw s10,96(sp)
    sw s11,100(sp)
    sw t3,104(sp)
    sw t4,108(sp)
    sw t5,112(sp)
    sw t6,116(sp)
    call kwt_trap_handler
    lw ra,0(sp)
    lw gp,4(sp)
    lw tp,8(sp)
    lw t0,12(sp)
    lw t1,16(sp)
    lw t2,20(sp)
    lw s0,24(sp)
    lw s1,28(sp)
    lw a0,32(sp)
    lw a1,36(sp)
    lw a2,40(sp)
    lw a3,44(sp)
    lw a4,48(sp)
    lw a5,52(sp)
    lw a6,56(sp)
    lw a7,60(sp)
    lw s2,64(sp)
    lw s3,68(sp)
    lw s4,72(sp)
    lw s5,76(sp)
    lw s6,80(sp)
    lw s7,84(sp)
    lw s8,88(sp)
    lw s9,92(sp)
    lw s10,96(sp)
    lw s11,100(sp)
    lw t3,104(sp)
    lw t4,108(sp)
    lw t5,112(sp)
    lw t6,116(sp)
    addi sp,sp,128
    mret
#endif
