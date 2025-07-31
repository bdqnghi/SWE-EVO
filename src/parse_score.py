from collections import defaultdict
from dataclasses import dataclass, field
import json
from pprint import pprint

import pandas as pd
from src.status import TestStatus, TestStatusDiff
from pathlib import Path
import yaml
from datasets import load_dataset, load_from_disk


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
        
        print("--------------------------------")
        print("PR_to_pass_percentage:")
        pprint(PR_to_pass_percentage)

        print("pass_PRs:")
        pprint(pass_PRs)
        print("fail_PRs:")
        pprint(fail_PRs)

        return cls(pass_PRs, fail_PRs, test_case_prefix_to_PRs_mapping, cared_tests)

    def calculate_score(self) -> float:
        try:
            return len(self.pass_PRs) / (len(self.pass_PRs) + len(self.fail_PRs))
        except ZeroDivisionError:
            return 0.0

    def __repr__(self) -> str:
        return f"TestStatusPR(pass_PRs={self.pass_PRs}, fail_PRs={self.fail_PRs}, score={self.calculate_score()})"

if __name__ == "__main__":
    preds_status: dict[str, TestStatus] = {}

    for line in Path("output/preds/arrow.jsonl").read_text().splitlines():
        try:
            pred_name = json.loads(line)["model_name_or_path"]
            pred_status = TestStatus.from_json_file(
                Path(
                    f"logs/run_evaluation/{pred_name}/{pred_name}/arrow-py__arrow_1.2.0_1.2.1/status.json"
                )
            )
            preds_status[pred_name] = pred_status
        except Exception as e:
            print(f"Error parsing {line}: {e}")
            continue

    test_case_to_PRs_mapping: dict[str, set[str]] = defaultdict(set)
    dataset = load_from_disk("./output/exported_dataset")["test"].to_pandas()
    data = dataset.query("instance_id == 'arrow-py__arrow_1.2.0_1.2.1'")["PRs"].iloc[0]

    for item in data:
        if "changed_test_cases" in item:
            for test_case in item["changed_test_cases"]:
                test_case = test_case.split("::")[0]
                test_case_to_PRs_mapping[test_case].add(item["pr_number"])

    test_case_to_PRs_mapping

    df = pd.read_json("output/test_status_changes.jsonl", lines=True)
    test_status_changes = df.query("instance_id == 'arrow-py__arrow_1.2.0_1.2.1'").iloc[0]

    cared_tests = (
        set(test_status_changes.PASS_TO_PASS) | set(test_status_changes.FAIL_TO_PASS)
    )

    prediction_scores = {}
    for pred_name, pred_status in preds_status.items():
        test_status_PR = TestStatusPR.from_test_status(
            pred_status, test_case_to_PRs_mapping, cared_tests
        )
        prediction_scores[pred_name] = test_status_PR.calculate_score()

    print(f"\nPrediction scores using OpenHands:")
    pprint(prediction_scores)
