# NPA Research

Research notes and executable probes for **Nested Privilege Architecture
(NPA)**.

## Layout

```
notes/    design history and analysis (some notes are Chinese)
model/    executable specification probes
```

Living spec volumes: `notes/SPEC_NPA_CORE.md`, `SPEC_A_D_*`, `SPEC_B_*`,
`SPEC_MEM_SEC.md`, `NPA_SPEC_DRAFT.html`. The published site is `npa-spec`.

## Probes

```bash
python -m model.scenarios
python -m model.scale_probe
python -m model.memsec
python -m model.isolation
```

## Related repositories

| Repository | Role |
|------------|------|
| **npa-spec** | Official Sphinx specification |
| **npa** (this) | Research notes and probes |
| rpa-paper | Pre-split workspace (legacy) |
| rpa-pysim, academic | Older tools and papers (legacy) |

Name: **Nested Privilege Architecture (NPA)**; formerly RPA.

## Author

Git identity: `arthurdev000 <arthur.dev@happyfull.tech>`.
Documentation signature: **Arthur Dev**.

---

This work was completed with AI assistance.
