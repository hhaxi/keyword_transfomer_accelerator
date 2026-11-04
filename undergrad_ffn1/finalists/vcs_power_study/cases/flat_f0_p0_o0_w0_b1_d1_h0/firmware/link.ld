OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ram (rwx) : ORIGIN = 0xa0000000, LENGTH = 48K }
SECTIONS {
    .text : { KEEP(*(.init)) *(.text*) } > ram
    .rodata : { *(.rodata*) } > ram
    .data : { *(.data*) *(.sdata*) } > ram
    .bss : { *(.bss*) *(.sbss*) *(COMMON) } > ram
    .trap : ALIGN(4) { *(.trap) } > ram
    PROVIDE(__global_pointer$ = 0xa0000800);
}
