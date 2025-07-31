#!/usr/bin/env python3
"""
CLI script to export test status changes and append to a JSONL file.

python -m src.export_test_status_changes \
    --empty-status-path logs/run_evaluation/begin_version/empty/arrow-py__arrow_1.2.0_1.2.1/status.json \
    --gold-status-path logs/run_evaluation/gold/empty/arrow-py__arrow_1.2.0_1.2.1/status.json \
    --instance-id arrow-py__arrow_1.2.0_1.2.1 \
    --output-file output/test_status_changes.jsonl
"""

import argparse
import json
import sys
from pathlib import Path
from src.status import TestStatus, TestStatusDiff


def main():
    parser = argparse.ArgumentParser(
        description="Export test status changes and append to JSONL file"
    )
    parser.add_argument(
        "--empty-status-path",
        type=str,
        required=True,
        help="Path to the empty prediction status JSON file"
    )
    parser.add_argument(
        "--gold-status-path", 
        type=str,
        required=True,
        help="Path to the gold prediction status JSON file"
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        required=True,
        help="Instance ID for the test case"
    )
    parser.add_argument(
        "--output-file",
        type=str,
        required=True,
        help="Path to the JSONL output file to append to"
    )
    
    args = parser.parse_args()
    
    try:
        # Load status files
        try:
            empty_pred_status = TestStatus.from_json_file(Path(args.empty_status_path))
        except Exception as e:
            print(f"Error: {e}")
            print(f"Empty status file not found: {args.empty_status_path}")
            print(f"Using empty status")
            empty_pred_status = TestStatus(set(), set())

        try:
            gold_pred_status = TestStatus.from_json_file(Path(args.gold_status_path))
        except Exception as e:
            print(f"Error: {e}")
            print(f"Gold status file not found: {args.gold_status_path}")
            print(f"Using empty status")
            gold_pred_status = TestStatus(set(), set())
        
        # Calculate status changes
        test_status_changes: TestStatusDiff = empty_pred_status >> gold_pred_status
        
        # Prepare data
        data = {
            "instance_id": args.instance_id,
            **test_status_changes.to_dict(),
        }
        
        # Append to JSONL file
        output_path = Path(args.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "a") as f:
            f.write(json.dumps(data) + "\n")
            
        print(f"Successfully appended data for instance '{args.instance_id}' to {args.output_file}")
        
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()