"""Run SpaceScout from a source checkout:  python run.py  [optional folder or drive]"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from spacescout.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
