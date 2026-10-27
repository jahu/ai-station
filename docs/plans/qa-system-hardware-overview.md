# System hardware overview

Browser SYSTEM-001 found CPU utilization, RAM usage and full GPU telemetry on
Home but not System. Show those existing native observations in System as well.
Reuse the existing GPU card implementation on both pages; retain dynamic device
indexes, keyboard navigation and explicit unavailable sensor values. Do not add
another sampler or invent zero readings for unsupported hardware.

System's CPU/RAM metrics use the existing hardware query and shared Meter. Its
six compact metric cards use three desktop columns and the existing mobile
two-column layout. Runtime/process ownership and controls are unchanged.

Acceptance: inspect the real System page on desktop and LAN mobile widths,
compare it with the actual hardware response, check both detected GPUs, CPU/RAM,
VRAM/temperature/power/fan availability, and verify no horizontal overflow or
workload execution. Home retains its original GPU cards and keyboard behavior.
