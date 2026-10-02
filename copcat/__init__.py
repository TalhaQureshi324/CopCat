"""copcat — deterministic lab grading + multi-channel plagiarism detection.

M1 scope: `copcat audit <dir>` — ingest submissions, fingerprint 6 channels
(token, AST-canonical, comment, string-literal, shadow (commented-out code),
source-line), subtract starter/base code, cluster flagged pairs, write CSV +
TXT reports.
"""

__version__ = "0.1.0"
