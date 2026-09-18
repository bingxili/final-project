# Experiment Artefacts

This folder contains the **final run artefacts used for the 
evaluation in the project**, uploaded here purely **for reference** (i.e. for the
supervisors to inspect).

Normally, every pipeline run is written to `runs/<task_id>_<timestamp>/`,
but that whole `runs/` folder is git-ignored (see `.gitignore`) since it
accumulates many exploratory/repeated runs during development. The two
runs copied here are the specific ones whose `generated_project/` output
was used as the multi-agent side of the maintainability comparison in
`evaluation/data/multi_agent_output/`:

```
experiment_artefacts/
├── task_1_20260912_163930/
│   ├── run_meta.json          # task, model, status, revision_count, timing
│   ├── workflow_log.jsonl      # append-only event log, one JSON object per line
│   ├── artifacts/               # every intermediate artifact, one JSON file per step/revision
│   └── generated_project/        # final generated source code for task_1
└── task_2_20260912_162237/
    └── ... (same structure, for task_2)
```

These are read-only snapshots kept for traceability/reproducibility of
the results reported in the dissertation; they are not read or written
to by any code in this repository (see `src/runner.py` and
`evaluation/compare.py` for the actual live paths used, `runs/` and
`evaluation/data/`, respectively).

