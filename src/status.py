from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from swebench.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    RESET_FAILED,
    TESTS_ERROR,
    TESTS_TIMEOUT,
)
from swebench.harness.constants import TestStatus as TestStatusEnum

from swesynth.mutation.validator.docker.test_log_parser import MAP_REPO_TO_PARSER


@dataclass
class TestStatusDiff:
    PASS_TO_PASS: set[str]
    PASS_TO_FAIL: set[str]
    FAIL_TO_PASS: set[str]
    FAIL_TO_FAIL: set[str]

    def to_dict(self) -> dict:
        return {
            "PASS_TO_PASS": list(self.PASS_TO_PASS),
            "PASS_TO_FAIL": list(self.PASS_TO_FAIL),
            "FAIL_TO_PASS": list(self.FAIL_TO_PASS),
            "FAIL_TO_FAIL": list(self.FAIL_TO_FAIL),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestStatusDiff":
        return cls(
            PASS_TO_PASS=set(data["PASS_TO_PASS"]),
            PASS_TO_FAIL=set(data["PASS_TO_FAIL"]),
            FAIL_TO_PASS=set(data["FAIL_TO_PASS"]),
            FAIL_TO_FAIL=set(data["FAIL_TO_FAIL"]),
        )

    def __repr__(self) -> str:
        return f"""TestStatusDiff(
    PASS_TO_PASS={len(self.PASS_TO_PASS)},
    PASS_TO_FAIL={len(self.PASS_TO_FAIL)},
    FAIL_TO_PASS={len(self.FAIL_TO_PASS)},
    FAIL_TO_FAIL={len(self.FAIL_TO_FAIL)},
)"""

    def __bool__(self) -> bool:
        return not (len(self.PASS_TO_PASS) == 0 and len(self.PASS_TO_FAIL) == 0 and len(self.FAIL_TO_PASS) == 0 and len(self.FAIL_TO_FAIL) == 0)

    @property
    def score(self) -> float:
        """
        Get ranking metric. This only make sense if TestStatusDiff is computed using subset of test cases.
        """
        total_passed_tests = len(self.PASS_TO_PASS) + len(self.PASS_TO_FAIL)
        total_failed_tests = len(self.FAIL_TO_PASS) + len(self.FAIL_TO_FAIL)
        total_tests = total_passed_tests + total_failed_tests

        return len(self.PASS_TO_FAIL) / total_tests if total_tests > 0 else -1

    @property
    def all_tests(self) -> set[str]:
        return self.PASS_TO_PASS | self.PASS_TO_FAIL | self.FAIL_TO_PASS | self.FAIL_TO_FAIL

    def get_related_test_files(self) -> set[str]:
        """
        NOTE: this only support pytest (nodeid format)
        """
        all_tests = self.PASS_TO_FAIL | self.FAIL_TO_PASS
        return {test_file.split("::")[0] for test_file in all_tests}

    def __eq__(self, value):
        if not isinstance(value, TestStatusDiff):
            return False
        if (
            self.PASS_TO_PASS == value.PASS_TO_PASS
            and self.PASS_TO_FAIL == value.PASS_TO_FAIL
            and self.FAIL_TO_PASS == value.FAIL_TO_PASS
            and self.FAIL_TO_FAIL == value.FAIL_TO_FAIL
        ):
            return True

        return False

    def __ne__(self, value):
        return not (self == value)


@dataclass
class TestStatus:
    passed_test_cases: set[str]
    failed_test_cases: set[str]

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, TestStatus):
            return False
        if self.passed_test_cases == value.passed_test_cases and self.failed_test_cases == value.failed_test_cases:
            return True

        return False

    def __ne__(self, value: object) -> bool:
        return not (self == value)

    def __rshift__(self, other: object) -> TestStatusDiff:
        # >>
        if not isinstance(other, TestStatus):
            raise TypeError
        return TestStatusDiff(
            PASS_TO_PASS=self.passed_test_cases & other.passed_test_cases,
            PASS_TO_FAIL=self.passed_test_cases & other.failed_test_cases,
            FAIL_TO_PASS=self.failed_test_cases & other.passed_test_cases,
            FAIL_TO_FAIL=self.failed_test_cases & other.failed_test_cases,
        )

    def __bool__(self) -> bool:
        return not (self == TestStatus(set(), set()))

    def shrink_to(self, test_subset: set[str]) -> "TestStatus":
        return TestStatus(
            passed_test_cases=self.passed_test_cases & test_subset,
            failed_test_cases=self.failed_test_cases & test_subset,
        )

    def fill_missing_test_cases_from(self, other: "TestStatus", as_failed: bool = True) -> "TestStatus":
        """
        https://github.com/princeton-nlp/SWE-bench/blob/9da193f72e42c6012a1444a73dd080b7dcea8644/swebench/harness/grading.py#L28

        Missing test cases from test log should be considered as failed.
        """
        assert as_failed, "Only support as_failed=True"
        all_test_cases: set[str] = other.passed_test_cases | other.failed_test_cases
        return TestStatus(
            passed_test_cases=self.passed_test_cases,
            failed_test_cases=self.failed_test_cases | (all_test_cases - self.passed_test_cases),
        )

    def to_dict(self) -> dict:
        return {
            "PASS": list(self.passed_test_cases),
            "FAIL": list(self.failed_test_cases),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestStatus":
        return cls(
            passed_test_cases=set(data["PASS"]),
            failed_test_cases=set(data["FAIL"]),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> "TestStatus":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))

    def to_json_file(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=4))

    def __repr__(self) -> str:
        return f"TestStatus(num_pass={len(self.passed_test_cases)}, num_fail={len(self.failed_test_cases)})"

    @classmethod
    def parse_test_output(cls, output: str, repo: str) -> "TestStatus":
        if (
            any(
                [
                    x in output
                    for x in [
                        APPLY_PATCH_FAIL,
                        RESET_FAILED,
                        TESTS_ERROR,
                        TESTS_TIMEOUT,
                        "Failed to reset task environment",
                    ]
                ]
            )
            # or "applied patch" not in output.lower()
        ):
            # Eval patch was not applied successfully
            raise Exception(f"Cannot parse test output of '{repo}'")
        # Get status map of evaluation results
        output = output.split(f"{APPLY_PATCH_PASS} (pred)")[-1]
        log_parser: Callable[[str], dict[str, TestStatusEnum]] = MAP_REPO_TO_PARSER[repo]
        test_case_name_to_status: dict[str, str] = log_parser(output)
        passed_test_cases: set[str] = {
            test_case
            for test_case, status in test_case_name_to_status.items()
            if status == TestStatusEnum.PASSED.value or status == TestStatusEnum.XFAIL.value
        }
        failed_test_cases: set[str] = {
            test_case
            for test_case, status in test_case_name_to_status.items()
            if status == TestStatusEnum.FAILED.value or status == TestStatusEnum.ERROR.value
        }
        return cls(passed_test_cases=passed_test_cases, failed_test_cases=failed_test_cases)

    def all_tests(self) -> set[str]:
        return self.passed_test_cases | self.failed_test_cases

    def get_all_tests_from_files(self, files: set[str]) -> set[str]:
        return {test for test in self.all_tests() if any(file in test for file in files)}
