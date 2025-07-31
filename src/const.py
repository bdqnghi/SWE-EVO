TEST_COMMANDS = {
    "graphql-python/graphene": "pytest -rA --continue-on-collection-errors",
    "arrow-py/arrow": r"""
sed -i '/^\s*pytest$/s/pytest/pytest -rA --continue-on-collection-errors/' Makefile
make test
""",
    "numpy/numpy": "python -m pip install -r requirements/all_requirements.txt\nspin test -v",
    "pytest-dev/pytest": "pytest -rA --continue-on-collection-errors",
    "scipy/scipy": "python dev.py test -v -v",
    "qutip/qutip": "pytest -rA --continue-on-collection-errors",
}
