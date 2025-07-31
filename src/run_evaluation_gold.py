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
from src.run_evaluation import *
from src.run_evaluation import _instance

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
                return f"thaiminhpv/{self._instance['instance_id']}:latest"

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

        logger.info(f"Applying patch to container...")
        # Attempt to apply patch to container
        val = container.exec_run(
            "git apply --allow-empty -v /tmp/patch.diff",
            workdir=repo_directory,
            user="root",
        )
        if val.exit_code != 0:
            logger.info(f"Failed to apply patch to container, trying again...")

            # try "patch --batch --fuzz=5 -p1 -i {patch_path}" to try again
            val = container.exec_run(
                "patch --batch --fuzz=5 -p1 -i /tmp/patch.diff",
                workdir=repo_directory,
                user="root",
            )
            if val.exit_code != 0:
                logger.info(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}")
                raise EvaluationError(
                    instance_id,
                    f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}",
                    logger,
                )
            else:
                logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
        else:
            logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")

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
        #         logger.info(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}")
        #         raise EvaluationError(
        #             instance_id,
        #             f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}",
        #             logger,
        #         )
        #     else:
        #         logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
        # else:
        #     logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")

        # Get git diff before running eval script
        git_diff_output_before = container.exec_run("git diff", workdir=repo_directory).output.decode("utf-8").strip()
        logger.info(f"Git diff before:\n{git_diff_output_before}")

        test_command = {
            "graphql-python/graphene": "pytest -rA --continue-on-collection-errors",
            "arrow-py/arrow": "make test",
            "numpy/numpy": "spin test -v",
            "pytest-dev/pytest": "pytest -rA --continue-on-collection-errors",
            "scipy/scipy": "python dev.py test -v -v",
            "qutip/qutip": "pytest -rA --continue-on-collection-errors",
        }

        eval_file = Path(log_dir / "eval.sh")
        # eval_script = test_spec.eval_script
        eval_script = f"""
#!/bin/bash
set -uxo pipefail

source /opt/conda/bin/activate venv

cd {repo_directory}
echo "==== Test begin ===="
{test_command[test_spec.repo]}
echo "==== Test end ===="
"""
        # --- apply patch here
        _instance.set(test_spec._instance)

        eval_file.write_text(eval_script)
        logger.info(f"Eval script for {instance_id} written to {eval_file}; copying to container...")
        copy_to_container(container, eval_file, Path("/eval.sh"))

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
