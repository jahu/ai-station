"""Typed transient native verification; HTTP callers retain the existing 409 contract."""

from fastapi import HTTPException


class CapabilityChecking(HTTPException):
    def __init__(self, capability, reason):
        super().__init__(409, reason)
        self.capability = capability


def reject_checking(report, capability):
    if report.get("available") is not True and report.get("readiness") == "checking":
        raise CapabilityChecking(capability, report.get("reason") or "Verifying installed model files")
