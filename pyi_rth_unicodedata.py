"""Runtime hook to force-load unicodedata and encodings before IDNA imports them."""

import sys

# Force import unicodedata before IDNA tries to use it
try:
    import unicodedata
    sys.modules['unicodedata'] = unicodedata
except Exception as e:
    print(f"[WARNING] Failed to preload unicodedata: {e}")

# Force import encodings modules that IDNA needs
try:
    import encodings
    import encodings.idna
    import encodings.utf_8
    import encodings.ascii
except Exception as e:
    print(f"[WARNING] Failed to preload encodings: {e}")
