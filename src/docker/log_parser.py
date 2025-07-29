import re
from loguru import logger
from swebench.harness.constants import TestStatus
from swebench.harness.log_parsers import (
    parse_log_pytest,
    parse_log_pytest_options,
    parse_log_django,
    parse_log_matplotlib,
    parse_log_seaborn,
    parse_log_sympy,
)

__all__ = [
    "transform_django_test_directives",
    "MAP_REPO_TO_PARSER",
]


def parse_log_pytest_v2(log: str) -> dict[str, str]:
    """
    Parser for test logs generated with PyTest framework (Later Version)

    Args:
        log (str): log content
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}
    escapes = "".join([chr(char) for char in range(1, 32)])
    for line in log.split("\n"):
        line = re.sub(r"\[(\d+)m", "", line)
        translator = str.maketrans("", "", escapes)
        line = line.translate(translator)
        if any([line.startswith(x.value) for x in TestStatus]):
            if line.startswith(TestStatus.FAILED.value):
                line = line.replace(" - ", " ")
            test_case = line.split()
            test_status_map[test_case[1]] = test_case[0]
        # Support older pytest versions by checking if the line ends with the test status
        elif any([line.endswith(x.value) for x in TestStatus]):
            test_case = line.split()
            # --- Patch ---
            if len(test_case) != 2:
                # print(f"Invalid test case: '{line}'")
                continue
            # ---
            test_status_map[test_case[0]] = test_case[1]
    return test_status_map


def transform_django_test_directives(tests_to_run: set[str]) -> set[str]:
    """
    Don't confuse with this:
        from swebench.harness.utils import get_test_directives
    `swebench.harness.utils.get_test_directives` is used to get test directives from the test patch diff.

    This function is used to get test directives from the **test output** instead.
    """
    # For Django tests, remove extension + "tests/" prefix and convert slashes to dots (module referencing)
    """
    directives_transformed = []
    for d in tests_to_run:
        d = d[: -len(".py")] if d.endswith(".py") else d
        d = d[len("tests/") :] if d.startswith("tests/") else d
        d = d.replace("/", ".")
        directives_transformed.append(d)
    return set(directives_transformed)
    """
    # Use a list comprehension with regex to extract module names from each string in the set
    # matches = {re.search(r'\((.*?)\)', line).group(1) for line in input_set}
    matches: set[str] = set()
    for test in tests_to_run:
        match = re.search(r"\((.*?)\)", test)
        if match:
            matches.add(match.group(1))
        else:
            logger.warning(f"Failed to extract module name from test case: `{test}`")
    # remove the last part of the module name
    module_names = {".".join(match.split(".")[:-1]) for match in matches}
    module_names = {match for match in module_names if match}
    return module_names


def parse_log_pytest_pydantic(log: str) -> dict[str, str]:
    """
    Parser for test logs generated with PyTest framework (Later Version)

    Args:
        log (str): log content
    Returns:
        dict: test case to test status mapping
    """
    test_status_map = {}
    escapes = "".join([chr(char) for char in range(1, 32)])
    for line in log.split("\n"):
        line = re.sub(r"\[(\d+)m", "", line)
        translator = str.maketrans("", "", escapes)
        line = line.translate(translator)

        # --- Patch ---
        # additionally to pytest v2 we remove the [...] from FAILED
        line = re.sub(r"FAILED\s*\[.*?\]", "FAILED", line)
        # if "tests/test_main.py::test_model_post_init_supertype_private_attr" in line:
        #     print(line)
        # -------------

        if any([line.startswith(x.value) for x in TestStatus]):
            if line.startswith(TestStatus.FAILED.value):
                line = line.replace(" - ", " ")
            test_case = line.split()
            test_status_map[test_case[1]] = test_case[0]
        # Support older pytest versions by checking if the line ends with the test status
        elif any([line.endswith(x.value) for x in TestStatus]):
            test_case = line.split()
            test_status_map[test_case[0]] = test_case[1]
    return test_status_map


parse_log_astroid = parse_log_pytest
parse_log_flask = parse_log_pytest
parse_log_marshmallow = parse_log_pytest
parse_log_pvlib = parse_log_pytest
parse_log_pyvista = parse_log_pytest
parse_log_sqlfluff = parse_log_pytest
parse_log_xarray = parse_log_pytest

parse_log_pydicom = parse_log_pytest_options
parse_log_requests = parse_log_pytest_options
parse_log_pylint = parse_log_pytest_options

parse_log_astropy = parse_log_pytest_v2
parse_log_scikit = parse_log_pytest_v2
parse_log_sphinx = parse_log_pytest_v2


MAP_REPO_TO_PARSER = {
    # test set
    "astropy/astropy": parse_log_astropy,
    "django/django": parse_log_django,
    "matplotlib/matplotlib": parse_log_matplotlib,
    "mwaskom/seaborn": parse_log_seaborn,
    "pallets/flask": parse_log_flask,
    "psf/requests": parse_log_requests,
    "pydata/xarray": parse_log_xarray,
    "pylint-dev/pylint": parse_log_pylint,
    "pytest-dev/pytest": parse_log_pytest,
    "scikit-learn/scikit-learn": parse_log_scikit,
    "sphinx-doc/sphinx": parse_log_sphinx,
    "sympy/sympy": parse_log_sympy,
    # dev set
    "pvlib/pvlib-python": parse_log_pvlib,
    "pydicom/pydicom": parse_log_pydicom,
    "sqlfluff/sqlfluff": parse_log_sqlfluff,
    "pylint-dev/astroid": parse_log_astroid,
    "pyvista/pyvista": parse_log_pyvista,
    "marshmallow-code/marshmallow": parse_log_marshmallow,
}

# SWE-Gym
# From https://github.com/SWE-Gym/SWE-Bench-Fork/blob/242429c188fcfd06aad13fce9a54d450470bf0ac/swebench/harness/log_parsers.py
parse_log_mypy = parse_log_pytest
parse_log_moto = parse_log_pytest
parse_log_conan = parse_log_pytest
parse_log_modin = parse_log_pytest
parse_log_monai = parse_log_pytest
parse_log_dvc = parse_log_pytest
parse_log_dask = parse_log_pytest
parse_log_bokeh = parse_log_pytest
parse_log_mne = parse_log_pytest
parse_log_hypothesis = parse_log_pytest
parse_log_pydantic = parse_log_pytest_pydantic
parse_log_pandas = parse_log_pytest
parse_log_hydra = parse_log_pytest

MAP_REPO_TO_PARSER.update(
    {
        "python/mypy": parse_log_mypy,
        "getmoto/moto": parse_log_moto,
        "conan-io/conan": parse_log_conan,
        "modin-project/modin": parse_log_modin,
        "Project-MONAI/MONAI": parse_log_monai,
        "iterative/dvc": parse_log_dvc,
        "dask/dask": parse_log_dask,
        "bokeh/bokeh": parse_log_bokeh,
        # "mne-tools/mne-python": parse_log_mne,
        # "HypothesisWorks/hypothesis": parse_log_hypothesis,
        "pydantic/pydantic": parse_log_pydantic,
        "pandas-dev/pandas": parse_log_pandas,
        "facebookresearch/hydra": parse_log_hydra,
    }
)

MAP_REPO_TO_PARSER.update({k.lower(): v for k, v in MAP_REPO_TO_PARSER.items()})
