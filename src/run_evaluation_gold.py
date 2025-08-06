from __future__ import annotations

import json
import os
import platform
import re
import traceback
from argparse import ArgumentParser
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast
import random
from src.const import TEST_COMMANDS


def get_repo_directory(container):
    """
    Dynamically determine the repository directory from /workspace.
    Returns the only non-hidden directory in /workspace.
    """
    # List all directories in /workspace
    result = container.exec_run("ls -la /workspace")
    if result.exit_code != 0:
        raise Exception(f"Failed to list /workspace directory: {result.output.decode('utf-8')}")
    
    output = result.output.decode("utf-8")
    lines = output.strip().split('\n')
    
    # Find non-hidden directories (skip . and ..)
    repo_dirs = []
    for line in lines:
        if line.startswith('d') and not line.endswith('.') and not line.endswith('..'):
            # Extract directory name from ls output
            parts = line.split()
            if len(parts) >= 9:  # ls -la format: permissions links owner group size date time name
                dir_name = parts[-1]
                if not dir_name.startswith('.'):
                    repo_dirs.append(dir_name)
    
    if len(repo_dirs) != 1:
        raise Exception(f"Expected exactly one non-hidden directory in /workspace, found: {repo_dirs}")
    
    repo_dir = repo_dirs[0]
    return f"/workspace/{repo_dir}"

import docker
from datasets import Dataset, load_dataset, load_from_disk
from swebench.harness import run_evaluation
from swebench.harness import utils as harness_utils
from swebench.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    FAIL_TO_FAIL,
    FAIL_TO_PASS,
    INSTANCE_IMAGE_BUILD_DIR,
    KEY_INSTANCE_ID,
    MAP_REPO_VERSION_TO_SPECS,
    PASS_TO_FAIL,
    PASS_TO_PASS,
    RESET_FAILED,
    RUN_EVALUATION_LOG_DIR,
    TESTS_ERROR,
    TESTS_TIMEOUT,
    USE_X86,
    ResolvedStatus,
    SWEbenchInstance,
    TestStatus,
    NON_TEST_EXTS,
)
from swebench.harness.docker_build import BuildImageError, build_container, close_logger, setup_logger
from swebench.harness.docker_utils import cleanup_container, copy_to_container, exec_run_with_timeout, remove_image
from swebench.harness.grading import get_eval_report

# from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
from swebench.harness.run_evaluation import *
from swebench.harness.test_spec import TestSpec, make_env_script_list, make_repo_script_list

import yaml
from src.docker.log_parser import MAP_REPO_TO_PARSER
from src.docker.test_spec import make_env_script_list
from swesynth.mutation.validator.docker.build import build_container
from swesynth.mutation.validator.entities.status import TestStatus as SWESynthTestStatus

_instance: ContextVar[SWEbenchInstance] = ContextVar("instance")


def run_instance(
    test_spec: TestSpec,
    pred: dict,
    rm_image: bool,
    force_rebuild: bool,
    client: docker.DockerClient,
    run_id: str,
    timeout: int | None = None,
):
    """
    Run a single instance with the given prediction.

    Args:
        test_spec (TestSpec): TestSpec instance
        pred (dict): Prediction w/ model_name_or_path, model_patch, instance_id
        rm_image (bool): Whether to remove the image after running
        force_rebuild (bool): Whether to force rebuild the image
        client (docker.DockerClient): Docker client
        run_id (str): Run ID
        timeout (int): Timeout for running tests
    """
    # Set up logging directory
    pred[KEY_INSTANCE_ID] = pred[KEY_INSTANCE_ID].lower()
    instance_id = test_spec.instance_id
    model_name_or_path = pred.get("model_name_or_path", "None").replace("/", "__")
    log_dir = RUN_EVALUATION_LOG_DIR / run_id / model_name_or_path / instance_id
    log_dir.mkdir(parents=True, exist_ok=True)

    # Link the image build dir in the log dir
    build_dir = INSTANCE_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
    image_build_link = log_dir / "image_build_dir"
    if not image_build_link.exists():
        try:
            # link the image build dir in the log dir
            image_build_link.symlink_to(build_dir.absolute(), target_is_directory=True)
        except:
            # some error, idk why
            pass
    log_file = log_dir / "run_instance.log"

    # Set up report file + logger
    report_path = log_dir / "report.json"
    if report_path.exists():
        return instance_id, json.loads(report_path.read_text())
    logger = setup_logger(instance_id, log_file)

    # Run the instance
    container = None
    try:
        # Build + start instance container (instance image should already be built)
        class _TestSpec(TestSpec):
            def is_swebench_repo(self, repo):
                return repo.lower() in {
                    "astropy/astropy",
                    "django/django",
                    "matplotlib/matplotlib",
                    "mwaskom/seaborn",
                    "pallets/flask",
                    "psf/requests",
                    "pydata/xarray",
                    "pylint-dev/pylint",
                    "pytest-dev/pytest",
                    "scikit-learn/scikit-learn",
                    "sphinx-doc/sphinx",
                    "sympy/sympy",
                    "pvlib/pvlib-python",
                    "pydicom/pydicom",
                    "sqlfluff/sqlfluff",
                    "pylint-dev/astroid",
                    "pyvista/pyvista",
                    "marshmallow-code/marshmallow",
                }

            # https://stackoverflow.com/a/31591589
            @property
            def remote_instance_image_name(self):
                commit = self._instance["base_commit"]
                # return self._instance['image']
                # return f"sweworld/{self._instance['instance_id']}:latest"
                return f"swe-world_{self._instance['instance_id']}:latest"

                """
thaiminhpv/sweworld-pytest_8.3.5:latest
thaiminhpv/sweworld-scipy_v1.15.3:latest
thaiminhpv/sweworld-scipy_v1.15.0:latest
thaiminhpv/sweworld-qutip_v5.0.4:latest
thaiminhpv/sweworld-arrow_1.2.0:latest
thaiminhpv/sweworld-numpy_v2.2.6:latest
thaiminhpv/sweworld-graphene_v3.2.2:latest
thaiminhpv/sweworld-numpy_v2.1.3:latest
                """


                # if os.environ.get("SWESYNTH_USE_REMAP_IMAGE", "false").lower() == "true":
                #     res: str | None = RepoVersion.get_instance().mapping_from_repo_base_commit_to_docker_image[self.repo][commit]
                #     if res is None:
                #         raise Exception(f"Remote docker image for {self.repo} {commit} does not exist on Docker Hub")
                #     return res

                # if self.is_swebench_repo(self.repo):
                #     return "swebench/sweb.eval.x86_64." + self.instance_id.lower().replace("__", "_1776_") + ":latest"
                # else:
                #     # NOTE: SWE-Gym release all docker images under `xingyaoww/sweb.eval.x86_64` prefix at docker hub.
                #     return "xingyaoww/sweb.eval.x86_64." + self.instance_id.lower().replace("__", "_s_") + ":latest"

        test_spec.__class__ = _TestSpec
        container = build_container(test_spec, client, run_id, logger, rm_image, force_rebuild, num_cpus=2)
        container.start()
        logger.info(f"Container for {instance_id} started: {container.id}")

        # Copy model prediction as patch file to container
        patch_file = Path(log_dir / "patch.diff")
        # model_patch = pred["model_patch"] or ""
        model_patch = test_spec._instance["patch"]
        patch_file.write_text(model_patch or "")
        # ---
        test_patch = test_spec._test_patch
        (log_dir / "test_patch.diff").write_text(test_patch or "")  # for debugging only
        # (log_dir / "instance.yaml").write_text(yaml.dump_nice_yaml(test_spec._instance))
        (log_dir / "instance.json").write_text(json.dumps(test_spec._instance, indent=4, skipkeys=True))
        # ---
        logger.info(f"Intermediate patch for {instance_id} written to {patch_file}, now applying to container...")
        copy_to_container(container, patch_file, Path("/tmp/patch.diff"))

        # copy test patch to container
        copy_to_container(container, log_dir / "test_patch.diff", Path("/tmp/test_patch.diff"))

        repo_directory = get_repo_directory(container)

        # logger.info(f"Applying patch to container...")
        # # Attempt to apply patch to container
        # val = container.exec_run(
        #     "git apply --allow-empty -v /tmp/patch.diff",
        #     workdir=repo_directory,
        #     user="root",
        # )
        # if val.exit_code != 0:
        #     logger.info(f"Failed to apply patch to container, trying again...")

        #     # try "patch --batch --fuzz=5 -p1 -i {patch_path}" to try again
        #     val = container.exec_run(
        #         "patch --batch --fuzz=5 -p1 -i /tmp/patch.diff",
        #         workdir=repo_directory,
        #         user="root",
        #     )
        #     if val.exit_code != 0:
        #         logger.warning(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8', errors='ignore')}")
        #         # raise EvaluationError(
        #         #     instance_id,
        #         #     f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8', errors='ignore')}",
        #         #     logger,
        #         # )
        #     else:
        #         logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8', errors='ignore')}")
        # else:
        #     logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8', errors='ignore')}")

        # logger.info(f"Checkout gold version...")
        # output = container.exec_run(
        #     f"git reset --hard {test_spec._instance['end_version_commit']}",
        #     workdir=repo_directory,
        #     user="root",
        # )
        # logger.info(f"Checkout gold version output: {output.output.decode('utf-8', errors='ignore')}")
        # logger.info(f"Applying test patch to container...")
        # # apply test_patch.diff to container
        # val = container.exec_run(
        #     "git apply --allow-empty -v /tmp/test_patch.diff",
        #     workdir=repo_directory,
        #     user="root",
        # )
        # if val.exit_code != 0:
        #     logger.info(f"Failed to apply test patch to container, trying again...")

        #     # try "patch --batch --fuzz=5 -p1 -i {patch_path}" to try again
        #     val = container.exec_run(
        #         "patch --batch --fuzz=5 -p1 -i /tmp/test_patch.diff",
        #         workdir=repo_directory,
        #         user="root",
        #     )
        #     if val.exit_code != 0:
        #         logger.info(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8', errors='ignore')}")
        #         raise EvaluationError(
        #             instance_id,
        #             f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8', errors='ignore')}",
        #             logger,
        #         )
        #     else:
        #         logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8', errors='ignore')}")
        # else:
        #     logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8', errors='ignore')}")

        # Get git diff before running eval script
        git_diff_output_before = container.exec_run("git diff", workdir=repo_directory).output.decode("utf-8", errors="ignore").strip()
        logger.info(f"Git diff before:\n{git_diff_output_before}")

        eval_file = Path(log_dir / "eval.sh")
        # eval_script = test_spec.eval_script
        eval_script = f"""
#!/bin/bash
set -xo pipefail

source /opt/conda/bin/activate venv

cd {repo_directory}

git reset --hard {test_spec._instance['end_version']}

echo "==== Test begin ===="
{TEST_COMMANDS[test_spec.repo]}
echo "==== Test end ===="
"""
        # --- apply patch here
        _instance.set(test_spec._instance)

        eval_file.write_text(eval_script)
        logger.info(f"Eval script for {instance_id} written to {eval_file}; copying to container...")
        copy_to_container(container, eval_file, Path("/eval.sh"))

        timeout = 7200
        # Run eval script, write output to logs
        test_output, timed_out, total_runtime = exec_run_with_timeout(container, "/bin/bash /eval.sh", timeout)
        test_output_path = log_dir / "test_output.txt"
        logger.info(f"Test runtime: {total_runtime:_.2f} seconds")
        with open(test_output_path, "w") as f:
            f.write(test_output)
            logger.info(f"Test output for {instance_id} written to {test_output_path}")
            if timed_out:
                f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
                raise EvaluationError(
                    instance_id,
                    f"Test timed out after {timeout} seconds.",
                    logger,
                )

        # Get git diff after running eval script
        git_diff_output_after = container.exec_run("git diff", workdir=repo_directory).output.decode("utf-8").strip()

        # Check if git diff changed after running eval script
        logger.info(f"Git diff after:\n{git_diff_output_after}")
        if git_diff_output_after != git_diff_output_before:
            logger.info(f"Git diff changed after running eval script")

        # Get report from test output
        logger.info(f"Grading answer for {instance_id}...")
        report = get_eval_report(
            test_spec=test_spec,
            prediction=pred,
            log_path=test_output_path,
            include_tests_status=True,
        )
        logger.info(f"report: {report}\n" f"Result for {instance_id}: resolved: {report[instance_id]['resolved']}")

        # Write report to report.json
        with open(report_path, "w") as f:
            f.write(json.dumps(report, indent=4))
        
        # Convert TestStatus to SWESynthTestStatus
        status: SWESynthTestStatus = SWESynthTestStatus.parse_test_output(test_output, repo=test_spec.repo)
        logger.info(f"status: {status}")
        status.to_json_file(log_dir / "status.json")

        
        return instance_id, report
    except EvaluationError as e:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        print(e)
    except BuildImageError as e:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        print(e)
    except Exception as e:
        error_msg = (
            f"Error in evaluating model for {instance_id}: {e}\n" f"{traceback.format_exc()}\n" f"Check ({logger.log_file}) for more information."
        )
        logger.error(error_msg)
    finally:
        # Remove instance container + image, close logger
        cleanup_container(client, container, logger)
        if rm_image:
            remove_image(client, test_spec.instance_image_key, logger)
        close_logger(logger)
    return


def make_eval_script_list(instance, specs, env_name, repo_directory, base_commit, test_patch):
    """
    Applies the test patch and runs the tests.
    """
    HEREDOC_DELIMITER = "EOF_114329324912"
    # test_files = re.findall(DIFF_MODIFIED_FILE_REGEX, test_patch)
    # Reset test files to the state they should be in before the patch.
    # reset_tests_command = f"git checkout {base_commit} {' '.join(test_files)}"
    apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{test_patch}\n{HEREDOC_DELIMITER}"
    test_command = " ".join(
        [
            MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]["test_cmd"],
            *get_test_directives(instance),
        ]
    )
    apply_patch_command = """
{
    git apply --allow-empty -v /tmp/patch.diff
} || {
    patch --batch --fuzz=5 -p1 -i /tmp/patch.diff
}
"""

    eval_commands = [
        apply_test_patch_command,
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
        f"cd {repo_directory}",
    ]
    if "eval_commands" in specs:
        eval_commands += specs["eval_commands"]
    eval_commands += [
        f"git config --global --add safe.directory {repo_directory}",  # for nonroot user
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        "git status",
        "git show",
        f"git diff {base_commit}",
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
    ]
    if "install" in specs:
        eval_commands.append(specs["install"])
    eval_commands += [
        # reset_tests_command,
        # apply_test_patch_command,
        apply_patch_command,
        test_command,
        # reset_tests_command,  # Revert tests after done, leave the repo in the same state as before
    ]
    return eval_commands


def load_swebench_dataset(name="princeton-nlp/SWE-bench", split="test", instance_ids=None) -> list[SWEbenchInstance]:
    """
    Load SWE-bench dataset from Hugging Face Datasets or local .json/.jsonl file
    """
    # check that all instance IDs are in the dataset
    if instance_ids:
        instance_ids = set(instance_ids)
    # Load from local .json/.jsonl file
    if name == "SWE-Gym/SWE-Gym":
        dataset: Dataset = load_dataset("SWE-Gym/SWE-Gym", split=split)
        dataset_ids = {instance[KEY_INSTANCE_ID] for instance in dataset}
    elif name.endswith(".json") or name.endswith(".jsonl"):
        dataset = json.loads(Path(name).read_text())
        dataset_ids = {instance[KEY_INSTANCE_ID] for instance in dataset}
    elif name.endswith(".parquet"):
        dataset: Dataset = load_dataset("parquet", data_files={"dev": name})["dev"]
        dataset_ids = {instance[KEY_INSTANCE_ID] for instance in dataset}
    elif "/" in name and "princeton-nlp/SWE-bench" not in name:
        dataset = cast(Dataset, load_from_disk(name)[split])
        dataset_ids = {instance[KEY_INSTANCE_ID] for instance in dataset}
    else:
        # Load from Hugging Face Datasets
        if name.lower() in {"swe-bench", "swebench", "swe_bench"}:
            name = "princeton-nlp/SWE-bench"
        elif name.lower() in {"swe-bench-lite", "swebench-lite", "swe_bench_lite", "swe-bench_lite", "lite"}:
            name = "princeton-nlp/SWE-bench_Lite"
        dataset = cast(Dataset, load_dataset(name, split=split))
        dataset_ids = {instance[KEY_INSTANCE_ID] for instance in dataset}

    if instance_ids:
        if instance_ids - dataset_ids:
            raise ValueError(("Some instance IDs not found in dataset!" f"\nMissing IDs:\n{' '.join(instance_ids - dataset_ids)}"))
        dataset = [instance for instance in dataset if instance[KEY_INSTANCE_ID] in instance_ids]

    _dataset = []
    for instance in dataset:
        instance[KEY_INSTANCE_ID] = instance[KEY_INSTANCE_ID].lower()
        _dataset.append(instance)
    dataset = _dataset

    return [cast(SWEbenchInstance, instance) for instance in dataset]


def make_test_spec(instance: SWEbenchInstance) -> TestSpec:
    if isinstance(instance, TestSpec):
        return instance
    instance_id = instance[KEY_INSTANCE_ID].lower()
    repo = instance["repo"].lower()
    # version = instance["version"]
    base_commit = instance["base_commit"]
    problem_statement = instance["problem_statement"]
    # hints_text = instance["hints_text"]  # Unused
    test_patch = instance["test_patch"]

    def _from_json_or_obj(key: str) -> Any:
        """If key points to string, load with json"""
        if isinstance(instance[key], str):
            return json.loads(instance[key])
        return instance[key]

    # pass_to_pass = _from_json_or_obj(PASS_TO_PASS)
    # fail_to_pass = _from_json_or_obj(FAIL_TO_PASS)

    pass_to_pass = []
    fail_to_pass = []

    env_name = "testbed"
    repo_directory = f"/{env_name}"
    # specs = MAP_REPO_VERSION_TO_SPECS[repo][version]

    # repo_script_list = make_repo_script_list(specs, repo, repo_directory, base_commit, env_name)
    # env_script_list = make_env_script_list(instance, specs, env_name)
    # eval_script_list = make_eval_script_list(instance, specs, env_name, repo_directory, base_commit, test_patch)
    repo_script_list = ""
    env_script_list = ""
    eval_script_list = ""
    version = ""
    if platform.machine() in {"aarch64", "arm64"}:
        # use arm64 unless explicitly specified
        arch = "arm64" if instance_id not in USE_X86 else "x86_64"
    else:
        arch = "x86_64"

    obj = TestSpec(
        instance_id=instance_id,
        repo=repo,
        env_script_list=env_script_list,
        repo_script_list=repo_script_list,
        eval_script_list=eval_script_list,
        version=version,
        arch=arch,
        FAIL_TO_PASS=fail_to_pass,
        PASS_TO_PASS=pass_to_pass,
    )

    # ---
    obj._test_patch = test_patch
    obj._instance = instance
    # ---

    return obj


def get_logs_eval(log_fp: str) -> tuple[dict[str, str], bool]:
    """
    Retrieve evaluation results for a task instance from its corresponding log file

    Args:
        log_fp (str): path to log file
    Returns:
        bool: whether the patch applied successfully
        dict: status map
    """
    # Convert e.g. "logs/scikit-learn__scikit-learn-12421/test_output.txt" to "scikit-learn/scikit-learn"
    sample_id = str(Path(log_fp).parent.stem)  # e.g. scikit-learn__scikit-learn-12421
    # repo = "-".join(sample_id.replace("__", "/").split("-")[:-1])  # e.g. scikit-learn/scikit-learn
    repo = _instance.get()["repo"]
    log_parser = MAP_REPO_TO_PARSER[repo]

    with open(log_fp) as f:
        content = f.read()
        if (
            any(
                [
                    x in content
                    for x in [
                        APPLY_PATCH_FAIL,
                        RESET_FAILED,
                        TESTS_ERROR,
                        TESTS_TIMEOUT,
                        "Failed to reset task environment",
                    ]
                ]
            )
            or "applied patch" not in content.lower()
        ):
            # Eval patch was not applied successfully
            return {}, False

        # Get status map of evaluation results
        content = content.split(f"{APPLY_PATCH_PASS} (pred)")[-1]
        return log_parser(content), True


def get_test_directives(instance: SWEbenchInstance) -> list:
    """
    Get test directives from the test_patch of a task instance

    Args:
        instance (dict): task instance
    Returns:
        directives (list): List of test directives
    """
    # For seq2seq code repos, testing command is fixed
    if instance["repo"] == "swe-bench/humaneval":
        return ["test.py"]

    if instance["repo"] == "django/django":
        # Get test directives from test patch and remove non-test files
        diff_pat = r"diff --git a/.* b/(.*)"
        test_patch = instance["test_patch"]
        directives = re.findall(diff_pat, test_patch)
        directives = [d for d in directives if not any(d.endswith(ext) for ext in NON_TEST_EXTS)]

        directives_transformed = []
        for d in directives:
            d = d[: -len(".py")] if d.endswith(".py") else d
            d = d[len("tests/") :] if d.startswith("tests/") else d
            d = d.replace("/", ".")
            directives_transformed.append(d)
        directives = directives_transformed
        return directives

    if instance["repo"] == "sympy/sympy":
        # Get test directives from test patch and remove non-test files
        diff_pat = r"diff --git a/.* b/(.*)"
        test_patch = instance["test_patch"]
        directives = re.findall(diff_pat, test_patch)
        directives = [d for d in directives if not any(d.endswith(ext) for ext in NON_TEST_EXTS)]
        return directives

    pass_to_pass = instance["PASS_TO_PASS"]
    fail_to_pass = instance["FAIL_TO_PASS"]

    if isinstance(pass_to_pass, str):
        pass_to_pass = json.loads(pass_to_pass)
    if isinstance(fail_to_pass, str):
        fail_to_pass = json.loads(fail_to_pass)

    fail_to_pass = set(fail_to_pass)
    pass_to_pass = set(pass_to_pass)

    if instance["repo"] not in {"django/django", "sympy/sympy"}:
        # this assumes that non-pytest project do not have "::" in their test names
        fail_to_pass = {test_file.split("::")[0] for test_file in fail_to_pass if "::" in test_file}
        pass_to_pass = {test_file.split("::")[0] for test_file in pass_to_pass if "::" in test_file}

    return list(fail_to_pass | pass_to_pass)

    # Get test directives from test patch and remove non-test files
    diff_pat = r"diff --git a/.* b/(.*)"
    test_patch = instance["test_patch"]
    directives = re.findall(diff_pat, test_patch)
    directives = [d for d in directives if not any(d.endswith(ext) for ext in NON_TEST_EXTS)]

    # For Django tests, remove extension + "tests/" prefix and convert slashes to dots (module referencing)
    if instance["repo"] == "django/django":
        raise NotImplementedError
        directives_transformed = []
        for d in directives:
            d = d[: -len(".py")] if d.endswith(".py") else d
            d = d[len("tests/") :] if d.startswith("tests/") else d
            d = d.replace("/", ".")
            directives_transformed.append(d)
        directives = directives_transformed

    return directives


def get_empty_predictions(dataset_name: str, split: str) -> dict:
    """
    Create empty predictions for a given dataset.
    """
    dataset = load_swebench_dataset(dataset_name, split)
    return [
        {
            KEY_INSTANCE_ID: datum[KEY_INSTANCE_ID],
            KEY_PREDICTION: "",
            KEY_MODEL: "empty",
        }
        for datum in dataset
    ]

def get_dataset_from_preds(
        dataset_name: str,
        split: str,
        instance_ids: list,
        predictions: dict,
        run_id: str,
        exclude_completed: bool = True
    ):
    """
    Return only instances that have predictions and are in the dataset.
    If instance_ids is provided, only return instances with those IDs.
    If exclude_completed is True, only return instances that have not been run yet.
    """
    # load dataset
    dataset = load_swebench_dataset(dataset_name, split)
    dataset_ids = {i[KEY_INSTANCE_ID] for i in dataset}

    gold_predictions = get_gold_predictions(dataset_name, split)
    predictions.update({pred[KEY_INSTANCE_ID]: pred for pred in gold_predictions})

    if instance_ids:
        # check that all instance IDs have predictions
        missing_preds = set(instance_ids) - set(predictions.keys())
        if missing_preds:
            print(f"Warning: Missing predictions for {len(missing_preds)} instance IDs.")
    
    # check that all prediction IDs are in the dataset
    prediction_ids = set(predictions.keys())
    if prediction_ids - dataset_ids:
        raise ValueError(
            (
                "Some prediction IDs not found in dataset!"
                f"\nMissing IDs:\n{' '.join(prediction_ids - dataset_ids)}"
            )
        )
    if instance_ids:
        dataset = [i for i in dataset if i[KEY_INSTANCE_ID] in instance_ids]

    # check which instance IDs have already been run
    completed_ids = set()
    for instance in dataset:
        if instance[KEY_INSTANCE_ID] not in prediction_ids:
            # skip instances without predictions
            continue
        prediction = predictions[instance[KEY_INSTANCE_ID]]
        report_file = (
            RUN_EVALUATION_LOG_DIR
            / run_id
            / prediction[KEY_MODEL].replace("/", "__")
            / prediction[KEY_INSTANCE_ID]
            / LOG_REPORT
        )
        if report_file.exists():
            completed_ids.add(instance[KEY_INSTANCE_ID])

    if completed_ids and exclude_completed:
        # filter dataset to only instances that have not been run
        print(f"{len(completed_ids)} instances already run, skipping...")
        dataset = [i for i in dataset if i[KEY_INSTANCE_ID] not in completed_ids]

    empty_patch_ids = {k for k, v in predictions.items() if v[KEY_PREDICTION] == "" or v[KEY_PREDICTION] is None}

    # filter dataset to only instances with predictions
    # dataset = [i for i in dataset if i[KEY_INSTANCE_ID] in prediction_ids and i[KEY_INSTANCE_ID] not in empty_patch_ids]
    dataset = [i for i in dataset if i[KEY_INSTANCE_ID] in prediction_ids]
    return dataset

def run_instances(
        predictions: dict,
        instances: list,
        cache_level: str,
        clean: bool,
        force_rebuild: bool,
        max_workers: int,
        run_id: str,
        timeout: int,
    ):
    """
    Run all instances for the given predictions in parallel.

    Args:
        predictions (dict): Predictions dict generated by the model
        instances (list): List of instances
        cache_level (str): Cache level
        clean (bool): Clean images above cache level
        force_rebuild (bool): Force rebuild images
        max_workers (int): Maximum number of workers
        run_id (str): Run ID
        timeout (int): Timeout for running tests
    """
    client = docker.from_env()
    test_specs = list(map(make_test_spec, instances))

    # print number of existing instance images
    instance_image_ids = {x.instance_image_key for x in test_specs}
    existing_images = {
        tag for i in client.images.list(all=True)
        for tag in i.tags if tag in instance_image_ids
    }
    if not force_rebuild and len(existing_images):
        print(f"Found {len(existing_images)} existing instance images. Will reuse them.")

    # run instances in parallel
    print(f"Running {len(instances)} instances...")
    with tqdm(total=len(instances), smoothing=0) as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a future for running each instance
            futures = {
                executor.submit(
                    run_instance,
                    test_spec,
                    predictions[test_spec.instance_id],
                    should_remove(
                        test_spec.instance_image_key,
                        cache_level,
                        clean,
                        existing_images,
                    ),
                    force_rebuild,
                    client,
                    run_id,
                    timeout,
                ): None
                for test_spec in test_specs
            }
            # Wait for each future to complete
            for future in as_completed(futures):
                pbar.update(1)
                try:
                    # Update progress bar, check if instance ran successfully
                    future.result()
                except Exception as e:
                    traceback.print_exc()
                    continue
    print("All instances run.")

def main(
    dataset_name: str,
    split: str,
    instance_ids: list,
    predictions_path: str,
    max_workers: int,
    force_rebuild: bool,
    cache_level: str,
    clean: bool,
    open_file_limit: int,
    run_id: str,
    timeout: int,
    report_only: bool = False,
):
    """
    Run evaluation harness for the given dataset and predictions.
    """
    # set open file limit
    assert len(run_id) > 0, "Run ID must be provided"
    if platform.system() == "Linux":
        resource.setrlimit(resource.RLIMIT_NOFILE, (open_file_limit, open_file_limit))
    client = docker.from_env()

    # load predictions as map of instance_id to prediction
    if predictions_path == "gold":
        print("Using gold predictions - ignoring predictions_path")
        predictions = get_gold_predictions(dataset_name, split)
    elif predictions_path == "empty":
        print("Using empty predictions - ignoring predictions_path")
        predictions = get_empty_predictions(dataset_name, split)
    else:
        if predictions_path.endswith(".json"):
            with open(predictions_path, "r") as f:
                predictions = json.load(f)
        elif predictions_path.endswith(".jsonl"):
            with open(predictions_path, "r") as f:
                predictions = [json.loads(line) for line in f]
        else:
            raise ValueError('Predictions path must be "gold", .json, or .jsonl')

    # predictions = {pred[KEY_INSTANCE_ID]: pred for pred in predictions}
    predictions = {pred[KEY_INSTANCE_ID].lower(): pred for pred in predictions}

    # get dataset from predictions
    dataset = get_dataset_from_preds(dataset_name, split, instance_ids, predictions, run_id, exclude_completed=True)
    # random.shuffle(dataset)
    full_dataset = load_swebench_dataset(dataset_name, split, instance_ids)
    if report_only:
        make_run_report(predictions, full_dataset, client, run_id)
        return
    existing_images = list_images(client)
    print(f"Running {len(dataset)} unevaluated instances...")
    if not dataset:
        print("No instances to run.")
    else:
        # build environment images + run instances
        # build_env_images(client, dataset, force_rebuild, max_workers)
        run_instances(predictions, dataset, cache_level, clean, force_rebuild, max_workers, run_id, timeout)

    # clean images + make final report
    clean_images(client, existing_images, cache_level, clean)
    make_run_report(predictions, full_dataset, client, run_id)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--dataset_name", default="princeton-nlp/SWE-bench_Lite", type=str, help="Name of dataset or path to JSON file.")
    parser.add_argument("--split", type=str, default="test", help="Split of the dataset")
    parser.add_argument("--instance_ids", nargs="+", type=str, help="Instance IDs to run (space separated)")
    parser.add_argument("--predictions_path", type=str, help="Path to predictions file - if 'gold', uses gold predictions", required=True)
    parser.add_argument("--max_workers", type=int, default=4, help="Maximum number of workers (should be <= 75%% of CPU cores)")
    parser.add_argument("--open_file_limit", type=int, default=4096, help="Open file limit")
    parser.add_argument("--timeout", type=int, default=1_800, help="Timeout (in seconds) for running tests for each instance")
    parser.add_argument("--force_rebuild", type=harness_utils.str2bool, default=False, help="Force rebuild of all images")
    parser.add_argument(
        "--cache_level",
        type=str,
        choices=["none", "base", "env", "instance"],
        help="Cache level - remove images above this level",
        default="env",
    )
    # if clean is true then we remove all images that are above the cache level
    # if clean is false, we only remove images above the cache level if they don't already exist
    parser.add_argument("--clean", type=harness_utils.str2bool, default=False, help="Clean images above cache level")
    parser.add_argument("--run_id", type=str, required=True, help="Run ID - identifies the run")
    parser.add_argument("--report_only", action="store_true", help="Only generate report from existing logs")
    args = parser.parse_args()

    harness_utils.load_swebench_dataset = load_swebench_dataset
    harness_utils.get_test_directives = get_test_directives
    run_evaluation.run_instance = run_instance
    run_evaluation.make_test_spec = make_test_spec

    from unittest.mock import patch

    with patch("swebench.harness.run_evaluation.run_instance", run_instance), patch(
        "swebench.harness.run_evaluation.load_swebench_dataset", load_swebench_dataset
    ), patch("swebench.harness.run_evaluation.make_test_spec", make_test_spec), patch("swebench.harness.grading.get_logs_eval", get_logs_eval), patch(
        "swebench.harness.test_spec.get_test_directives", get_test_directives
    ), patch(
        "swebench.harness.test_spec.make_eval_script_list", make_eval_script_list
    ), patch(
        "swebench.harness.test_spec.make_env_script_list", make_env_script_list
    ):
        main(**vars(args))
