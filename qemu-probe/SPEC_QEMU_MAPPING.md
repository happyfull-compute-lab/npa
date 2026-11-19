# NPA on RISC-V interpreter — encoding & mapping

## Policy

- **RISC-V ISA**: decoder/executor only (ALU, load/store, branches).
- **Privilege & memory**: NPA (domains, DCB, memory manager).
- **`ecall`** = **`ascend`** (alias; no SBI).
- **`descend`** = custom instruction (below).
- **OpenSBI**: discarded. NPA **root domain** is first firmware.

## Custom instruction: DESCEND

Use RISC-V **custom-0** opcode space (`0x0B`):

```
31      25 24    20 19    15 14  12 11     7 6     0
+---------+--------+--------+------+--------+-------+
| funct7  |  rs2   |  rs1   |funct3|   rd   | 0x0B  |
+---------+--------+--------+------+--------+-------+

DESCEND   funct7=0000000  funct3=000
  rs1 = DCB byte address
  rs2 = entry (first PC; ignored on resume)
  rd  = status (0 ok, negative error)
```

Asm: `descend rd, rs1, rs2`  (tooling mnemonic; encoding as above)

## ECALL = ASCEND

Standard RISC-V `ecall` (`opcode=0x73`, imm=0):

| Reg | meaning |
|-----|---------|
| a0  | reason |
| a1  | x |

Handler path: **parent NPA exception entry** (not M/SBI vector).
Return: a0 = status.

## Memory manager ↔ PMP-style interface

QEMU load/store still walks translation via a **NPA memory manager**:

- DCB `ptb` / `ipa` drive allowed regions and VA→PA chain
- PMP-like API (if kept for tests) is a facade over NPA regions
- No default OpenSBI PMP layout

## Reset / root domain

- `-bios none` or NPA root as firmware image at RAM base
- CPU reset enters **root domain** context (lifecycle LIVE)
- Root creates DCBs, executes DESCEND to children

## Context (software / ISA)

- GPR/PC in CPU state (QEMU `CPURISCVState`)
- NPA stores only DCB; resume uses CPU state saved per-domain
