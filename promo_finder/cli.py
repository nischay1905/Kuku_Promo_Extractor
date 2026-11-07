import argparse
from pathlib import Path

def build_parser():
    parser = argparse.ArgumentParser(description="Kuku Promo Extractor")
    parser.add_argument("command", choices=["run", "cost", "eval"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--strategy", 
        choices=["baseline", "semantic", "hybrid"], 
        default="baseline",
        help="baseline: pure rules. semantic: event-anchored. hybrid: union pipeline."
    )
    # Existing flags preserved
    parser.add_argument("--per-ep", type=int, default=2)
    parser.add_argument("--min-score", type=float, default=0.60)
    parser.add_argument("--top", type=int, default=10)
    return parser