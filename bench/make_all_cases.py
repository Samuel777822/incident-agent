"""Generate every benchmark case (Python, Java, JavaScript, TypeScript, static site) and bench/ANSWER_KEY.md.

    python bench/make_all_cases.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_cases
import make_cases_v2

if __name__ == "__main__":
    make_cases.main()
    make_cases_v2.main()
    print("\nDone. See bench/ANSWER_KEY.md for every planted bug.")
