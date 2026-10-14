# GPU compute-process observation

System and the central workstation report can read bounded NVIDIA compute
process observations through a separate typed Runner GET. Records contain only
GPU UUID, PID, executable basename and reported GPU memory. No command line,
environment, credentials, ownership inference or process-control operation is
exposed. Graphics-only processes are outside this compute query.

The native query has a short deadline and bounded records/output. Failed or
unsupported reporting stays unavailable; partial/truncated observations are
explicit. Empty successful results mean no compute process was reported at that
sample, not proof that a GPU has no other memory use. GPU UUID maps records to
dynamically discovered devices. The live list is not added to frequent permanent
telemetry samples. An explicit assistant inspection saves a normal Run report
with observation time and status, using the existing permission/cancellation
contract. External runtimes remain outside AI Station control.
