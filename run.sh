#!/bin/bash

python -m src.create_data https://github.com/graphql-python/graphene/compare/v3.2.2..v3.3.0 --output-dir output/
python -m src.create_data https://github.com/arrow-py/arrow/compare/1.2.0..1.2.1 --output-dir output/
python -m src.create_data https://github.com/qutip/qutip/compare/v5.0.4..v5.1.0 --output-dir output/
python -m src.create_data https://github.com/numpy/numpy/compare/v2.2.0rc1..v2.2.0 --output-dir output/
