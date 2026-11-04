OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
    boot (rwx) : ORIGIN = 0xa0000000, LENGTH = 48K
    itcm (rwx) : ORIGIN = 0x80000000, LENGTH = 64K
}
SECTIONS {
    .boot : { KEEP(*(.init)) } > boot
    .text : ALIGN(4) {
        __itcm_start = .;
        *(.text*) *(.rodata*) *(.trap)
        . = ALIGN(4);
        __itcm_end = .;
    } > itcm AT> boot
    __itcm_load = LOADADDR(.text);
    .data : { *(.data*) *(.sdata*) } > boot
    .bss : { *(.bss*) *(.sbss*) *(COMMON) } > boot
    PROVIDE(__global_pointer$ = 0xa0000800);
    ASSERT(SIZEOF(.text) <= 65536, "ITCM overflow")
}
