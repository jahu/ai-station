# Capturing approved optional Python outputs

Current data workflows require directly requested files independently of the
model manifest (#385). Other creation wording still depends on that manifest;
a script can create a supported file that is discarded during collection. Extend
the existing typed Python contract rather than adding an execution engine.

The controller freezes required filenames plus a separate optional allowlist.
For data analysis, only the remaining supported chart.png/result.xlsx/report.txt
names may be optional, when both the native adapter and installed CPU image
advertise support. Models cannot select additional paths, directories or inputs.
The generic Python executor retains its existing canonical relative-name boundary.

Required files must all exist. After them, collect only existing optional files
in allowlist order. Only absence is ignored: symlinks, devices, directories,
hardlinks, mutation or size/total violations fail the execution and publish no
outputs. Required and optional lists are unique/disjoint and total at most eight.
Native transport and control-plane adoption independently validate the required
prefix and ordered optional subset, ownership, hashes and limits.

Omit an empty optional field from serialized requests and digests so existing
saved requests, replay and inspection retain their exact identity. Old images
continue handling ordinary requests; reject unsupported optional requests before
staging/dispatch. A separate installed-image feature label negotiates this
extension without changing existing protocol1 calls.

Data results validate every returned optional file with the existing inert export
policy before publication. Raw optional files remain internal; chart/table/file
presentation, provenance, repair, absolute deadline, Stop and recovery are shared.
No UI schema, database migration, permissions or model download is introduced.

Qualification: legacy serialization/digest/replay; missing required and absent
optional files; present optional files despite an empty model declaration;
duplicates, path escape, overlap, excessive count, wrong order/unapproved output;
source/hash mutation, symlink/FIFO/hardlink and size limits; cancellation/recovery;
old/new image capability negotiation. Run normal suites with fake inference and
temporary data, actual isolated CPU-container collection, and compiled desktop/
mobile checks. Review full diff and images, merge to develop only after local
checks, then perform an idle backed-up Runner/CPU-image upgrade preserving the
operator model. Qualify one actual local-model case without claiming unrun GPU work.
