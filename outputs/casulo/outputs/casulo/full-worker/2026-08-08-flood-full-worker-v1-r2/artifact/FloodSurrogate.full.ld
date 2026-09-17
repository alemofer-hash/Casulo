ENTRY(casulo_learn_entry)
SECTIONS
{
  . = 0x1000;
  .text : ALIGN(16) { KEEP(*(.text.entry)) *(.text .text.*) }
  .rodata : ALIGN(16) { *(.rodata .rodata.*) }
  .data : ALIGN(16) { *(.data .data.*) }
  .got : ALIGN(8) { *(.got .got.*) }
  .plt : ALIGN(16) { *(.plt .plt.*) }
  /DISCARD/ : { *(.eh_frame*) *(.comment*) *(.note*) }
}
