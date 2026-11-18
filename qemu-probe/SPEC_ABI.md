# NPA probe ABI (firmware ecall) — draft

Status: working freeze for qemu-probe M4+. Not the final ISA encoding.

## Encoding

Guest executes `ecall` with:

| Reg | descend | ascend | reap |
|-----|---------|--------|------|
| a7  | EID     | EID    | EID  |
| a6  | FID=0   | FID=1  | FID=2|
| a0  | dcb_pa  | reason | dcb_pa |
| a1  | —       | x      | —    |
| a2  | —       | —      | —    |

- **EID** = `0x4E504100` (“NPA\\0”)
- Return in **a0**: `0` ok, negative = error (see below)
- `ascend` returns in a0/a1 only for probe; hardware return point is
  **Context**, not a Spec field (NPA I3/I18).

## reason (ascend a0 on entry)

| value | name | meaning |
|------:|------|---------|
| 0 | SERVICE | request parent service |
| 1 | RESULT  | normal completion, resumable |
| 2 | EXCEPTION | sync exception report |
| 3 | EXIT    | domain finished; not resumable |

## Semantics (must match SPEC_NPA_CORE)

### descend(dcb)

1. Validate `sz` and alignment.
2. lifecycle:
   - **FREE** → first: Context.pc ← `entry`, FREE→LIVE
   - **LIVE** → resume: restore Context
   - **TERM** → fail (parent must reap)
3. Parent Context = return after `descend` (saved by handler).
4. Parent `child` link = dcb (C1).

### ascend(reason, x)

1. Save child Context (pc = after ecall).
2. Parent resumes at saved descend site.
3. If reason==EXIT: child lifecycle → **TERM**; parent `child` cleared.
4. reason/x delivered to parent (probe: a0/a1 at resume).

### reap(dcb)

1. Only parent (or root) may reap.
2. Drop Context; lifecycle TERM→FREE (or FREE if never run).
3. Clear parent `child` if it points here.

## Error codes (a0)

| code | name | meaning |
|-----:|------|---------|
|  0 | OK | |
| -1 | EBADDCB | bad sz/align/addr |
| -2 | ETERM | descend to TERM |
| -3 | ENOROOT | ascend from root |
| -4 | ENOTCHILD | dcb not in tree |
| -5 | EPERM | caller is not parent |

## Probe vs hardware

This ABI is **implementation of NPA semantics** for QEMU/firmware bring-up.
Final encoding may become custom instructions; semantics above must hold (I1–I20).
