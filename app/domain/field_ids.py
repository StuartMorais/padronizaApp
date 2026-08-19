from __future__ import annotations

import re

# Unicode-aware field IDs: letters (including accents) first, then letters,
# digits, underscore, dot or hyphen.
FIELD_ID_TOKEN_PATTERN = r"[^\W\d_][\w.-]*"
VALID_FIELD_ID = re.compile(rf"^{FIELD_ID_TOKEN_PATTERN}$", re.UNICODE)
