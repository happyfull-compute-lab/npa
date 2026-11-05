# NPA research

Research notes and executable probes for **Nested Privilege Architecture (NPA)**.

## Layout

```
notes/    design history, analysis, qemu plans
model/    executable specification probes
```

## Probes

```bash
python -m model.scenarios
python -m model.scale_probe
python -m model.memsec
python -m model.isolation
```

## Repos

| Repo | Role |
|------|------|
| **npa-spec** | Official Sphinx specification |
| **npa** (this) | Research + probes |
| rpa-paper | Pre-split workspace (legacy) |
| rpa-pysim / academic | Older tools & papers (legacy) |

Architecture name: **Nested Privilege Architecture (NPA)**, formerly RPA.
