TEST_COMMANDS = {
    "graphql-python/graphene": "pytest -rA --continue-on-collection-errors",
    "arrow-py/arrow": r"""
sed -i '/^\s*pytest$/s/pytest/pytest -rA --continue-on-collection-errors/' Makefile
make test
""",
    "numpy/numpy": r"""
python -m pip install -r requirements/all_requirements.txt
spin test -- -rA
""",
    "pytest-dev/pytest": r"""
pytest -rA --continue-on-collection-errors
""",
    "scipy/scipy": r"""
git submodule update --init --recursive
python dev.py test -- -rA
""",
    "qutip/qutip": r"""
python setup.py develop
pytest -rA --continue-on-collection-errors
""",

}
