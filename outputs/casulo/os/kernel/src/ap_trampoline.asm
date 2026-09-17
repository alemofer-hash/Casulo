; Casulo bounded INIT-SIPI trampoline. Runtime patch field offsets are frozen:
; 8=CR3, 16=stack top, 24=Rust AP entry, 34=GDTR base,
; 48=32-bit code descriptor, 56=32-bit data descriptor,
; 165=long-mode far target.
bits 16
org 0

    jmp short trampoline_start
    times 8-($-$$) db 0
cr3_value: dq 0
stack_top: dq 0
rust_entry: dq 0
gdtr:
    dw gdt_end - gdt - 1
    dd 0
    times 40-($-$$) db 0
gdt:
    dq 0x0000000000000000
    ; 32-bit executable/readable; base is patched at bytes 58..61.
    dq 0x00cf9a000000ffff
    ; 32-bit data, base is patched at bytes 66..69.
    dq 0x00cf92000000ffff
    dq 0x00af9a000000ffff
    dq 0x00af92000000ffff
gdt_end:

trampoline_start:
    cli
    mov ax, cs
    mov ds, ax
    mov es, ax
    mov ss, ax
    lgdt [gdtr]
    mov eax, cr0
    or eax, 1
    mov cr0, eax
    jmp dword 0x08:protected_mode

bits 32
protected_mode:
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov eax, cr4
    or eax, 1 << 5
    mov cr4, eax
    mov eax, [cr3_value]
    mov cr3, eax
    mov ecx, 0xc0000080
    rdmsr
    or eax, (1 << 8) | (1 << 11)
    wrmsr
    mov eax, cr0
    or eax, 1 << 31
    mov cr0, eax
    db 0xea
long_target: dd 0
    dw 0x18

bits 64
long_mode:
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov rsp, [rel stack_top]
    mov rax, [rel rust_entry]
    call rax
.halt:
    cli
    hlt
    jmp .halt

times 512-($-$$) db 0
