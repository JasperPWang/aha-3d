# Runs

New scene outputs use `SCENE/RUN_ID/{run.json,snapshot,stages,logs}`. Cross-scene
checks use `_tools/TOOL/RUN_ID`; managed batches use `_batches/BATCH_ID`.
Existing immutable runs remain in place. See [result management](../docs/RESULTS.md).
