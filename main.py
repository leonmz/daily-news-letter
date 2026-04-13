"""
Daily Market Newsletter - Main Runner (thin shim)

Usage:
    python main.py              # Run once (generate today's digest)
    python main.py --bot        # Run Telegram bot (commands + daily schedule)
    python main.py --schedule   # Run on schedule only (10AM PT daily)
    python main.py --test       # Dry run with mock data

Delegates to scripts/run_newsletter.py. Kept at root for backwards compatibility
with the Dockerfile ENTRYPOINT and any existing cron jobs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scripts.run_newsletter import main

if __name__ == "__main__":
    main()
