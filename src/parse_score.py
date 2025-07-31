from collections import defaultdict
from dataclasses import dataclass, field
import json
from pprint import pprint

import pandas as pd
from src.status import TestStatus, TestStatusDiff
from pathlib import Path
import yaml
from datasets import load_dataset, load_from_disk
import argparse
import sys


@dataclass
class TestStatusPR:
    pass_PRs: set[str]
    fail_PRs: set[str]
    test_case_to_PRs_mapping: dict[str, set[str]] = field(repr=False)
    cared_tests: set[str] = field(repr=False)

    @classmethod
    def from_test_status(
        cls,
        prediction_test_status: TestStatus,
        test_case_prefix_to_PRs_mapping: dict[str, set[str]],
        cared_tests: set[str],
    ) -> "TestStatusPR":
        """
        Calculate the PRs that pass or fail the test cases in the test status.
        A PR is considered to pass if all the test cases in the PR pass in the test status.
        A PR is considered to fail if any of the test cases in the PR fail in the test status.

        """
        pass_PRs: set[str] = set()
        fail_PRs: set[str] = set()

        prediction_test_status = prediction_test_status.shrink_to(cared_tests)
        prediction_test_status = prediction_test_status.fill_missing_test_cases_from(
            TestStatus(
                passed_test_cases=cared_tests,
                failed_test_cases=set()
            ),
            as_failed=True
        )

        # Create reverse mapping from PR to test cases
        PR_to_test_cases_mapping: dict[str, set[str]] = defaultdict(set)
        
        # Build the reverse mapping using startswith to match prefixes
        for test_case in cared_tests:
            for prefix, PRs in test_case_prefix_to_PRs_mapping.items():
                if test_case.startswith(prefix):
                    for PR in PRs:
                        PR_to_test_cases_mapping[PR].add(test_case)

        # print("PR_to_test_cases_mapping:")
        # pprint(PR_to_test_cases_mapping)
        
        # Determine which PRs pass or fail
        PR_to_pass_percentage = {}
        for PR, test_cases in PR_to_test_cases_mapping.items():
            passed_count = 0
            failed_count = 0
            total_count = len(test_cases)
            
            for test_case in test_cases:
                if test_case in prediction_test_status.passed_test_cases:
                    passed_count += 1
                elif test_case in prediction_test_status.failed_test_cases:
                    failed_count += 1
            
            pass_percentage = (passed_count / total_count) * 100 if total_count > 0 else 0
            PR_to_pass_percentage[PR] = pass_percentage
            
            # A PR passes only if ALL its test cases pass (no failures)
            PR_passed = failed_count == 0
            
            if PR_passed:
                pass_PRs.add(PR)
            else:
                fail_PRs.add(PR)
        
        print("PR_to_pass_percentage:")
        pprint(PR_to_pass_percentage)

        total_count = len(pass_PRs) + len(fail_PRs)
        print(f"pass_PRs: {len(pass_PRs)}/{total_count}")
        print(f"fail_PRs: {len(fail_PRs)}/{total_count}")

        return cls(pass_PRs, fail_PRs, test_case_prefix_to_PRs_mapping, cared_tests)

    def calculate_score(self) -> float:
        try:
            return len(self.pass_PRs) / (len(self.pass_PRs) + len(self.fail_PRs))
        except ZeroDivisionError:
            return 0.0

    def __repr__(self) -> str:
        return f"TestStatusPR(pass_PRs={self.pass_PRs}, fail_PRs={self.fail_PRs}, score={self.calculate_score()})"

def parse_scores(
    instance_id: str,
    prediction_file: str,
    dataset_path: str,
    test_status_changes_path: str,
) -> dict[str, float]:
    """
    Parse prediction scores for a given instance.
    
    Args:
        instance_id: The instance ID to analyze
        prediction_file: Path to the prediction JSONL file
        dataset_path: Path to the exported dataset
        test_status_changes_path: Path to the test status changes JSONL file
    
    Returns:
        Dictionary mapping prediction names to their scores
    """
    preds_status: dict[str, TestStatus] = {}

    # Load prediction statuses
    for line in Path(prediction_file).read_text().splitlines():
        try:
            pred_name = json.loads(line)["model_name_or_path"]
            pred_status = TestStatus.from_json_file(
                Path(
                    f"logs/run_evaluation/{pred_name}/{pred_name}/{instance_id}/status.json"
                )
            )
            preds_status[pred_name] = pred_status
        except Exception as e:
            # print(f"Error parsing {line}: {e}")
            print(f"Error parsing {pred_name}: {e}")
            continue
 
    # Load dataset and create test case to PRs mapping
    test_case_to_PRs_mapping: dict[str, set[str]] = defaultdict(set)
    dataset = load_from_disk(dataset_path)["test"].to_pandas()
    data = dataset.query(f"instance_id == '{instance_id}'")["PRs"].iloc[0]

    for item in data:
        if "changed_test_files" in item:
            for test_case in item["changed_test_files"]:
                test_case = test_case.split("::")[0]
                test_case_to_PRs_mapping[test_case].add(item["pr_number"])

    # Load test status changes
    df = pd.read_json(test_status_changes_path, lines=True)
    test_status_changes = df.query(f"instance_id == '{instance_id}'").iloc[0]

    cared_tests = (
        set(test_status_changes.PASS_TO_PASS) | set(test_status_changes.FAIL_TO_PASS)
    )

    # Calculate prediction scores
    prediction_scores = {}
    for pred_name, pred_status in preds_status.items():
        print("--------------------------------")
        print(f"Calculating score for {pred_name}: {pred_status}")
        test_status_PR = TestStatusPR.from_test_status(
            pred_status, test_case_to_PRs_mapping, cared_tests
        )
        prediction_scores[pred_name] = test_status_PR.calculate_score()

    return prediction_scores

def main():
    parser = argparse.ArgumentParser(
        description="Parse prediction scores for test status analysis"
    )
    parser.add_argument(
        "--instance-id",
        required=True,
        help="The instance ID to analyze (e.g., 'arrow-py__arrow_1.2.0_1.2.1')"
    )
    parser.add_argument(
        "--prediction-file",
        required=True,
        help="Path to the prediction JSONL file"
    )
    parser.add_argument(
        "--dataset-path",
        required=True,
        help="Path to the exported dataset directory"
    )
    parser.add_argument(
        "--test-status-changes-path",
        required=True,
        help="Path to the test status changes JSONL file"
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "pretty"],
        default="pretty",
        help="Output format for the results (default: pretty)"
    )

    args = parser.parse_args()

    try:
        prediction_scores = parse_scores(
            args.instance_id,
            args.prediction_file,
            args.dataset_path,
            args.test_status_changes_path,
        )

        if args.output_format == "json":
            print(json.dumps(prediction_scores, indent=2))
        else:
            print(f"\nPrediction scores for instance '{args.instance_id}':")
            pprint(prediction_scores)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
