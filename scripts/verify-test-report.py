"""Reject empty, failed, or skipped required CPU partitions from pytest JUnit."""
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = list(root.iter("testsuite"))
assert suites, "No test suites reported"
assert sum(int(s.get("tests", 0)) for s in suites) > 0, "No tests executed"
for suite in suites:
    for kind in ("failures", "errors", "skipped"):
        assert int(suite.get(kind, 0)) == 0, f"Required partition has {kind}: {suite.attrib}"
print("Required CPU partition: nonempty, zero failures/errors/skips")
