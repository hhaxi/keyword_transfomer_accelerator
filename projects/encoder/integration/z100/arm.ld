ENTRY(_start)
_stack_end = 0x001c0000;
__undef_stack = 0x00200000;
SECTIONS {
    . = 0x00100000;
    .text : { KEEP(*(.text.start)) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    .bss : {
        . = ALIGN(4);
        __bss_start = .;
        *(.bss*) *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    }
}
