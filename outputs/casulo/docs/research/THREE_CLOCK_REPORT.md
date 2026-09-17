# Full-worker three-clock synchronization

Every run records:

1. parent `perf_counter_ns` around the synchronous child process;
2. child `QueryPerformanceCounter` around training and result persistence;
3. child main-thread cycles from `QueryThreadCycleTime`.

The worker interval ends only after all cases, parameter/prediction output,
receipt source data, and file flush are complete. The parent observes process
completion. Both workers pin their main training thread to logical CPU 4 and
use one computation thread.

Across all 28 validation runs, the maximum relative disagreement between child
monotonic time and QPC was `0.000299991`; all cycle counts were positive and
every parent interval enclosed the child interval. The three-clock gate passed.
Importation and process initialization remain visible in parent end-to-end time
but are excluded from the steady worker interval.

