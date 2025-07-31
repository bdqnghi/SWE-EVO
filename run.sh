#!/bin/bash

# python -m src.create_data https://github.com/graphql-python/graphene/compare/v3.2.2..v3.3.0 --output-dir output/new-data4
# python -m src.create_data https://github.com/arrow-py/arrow/compare/1.2.0..1.2.1 --output-dir output/new-data4
# python -m src.create_data https://github.com/qutip/qutip/compare/v5.0.4..v5.1.0 --output-dir output/new-data4

mkdir -p output/new-data5
python -m src.create_data https://github.com/numpy/numpy/compare/v2.1.3..v2.2.0 --output-dir output/new-data5
python -m src.create_data https://github.com/numpy/numpy/compare/v2.2.6..v2.3.0 --output-dir output/new-data5
python -m src.create_data https://github.com/graphql-python/graphene/compare/v3.2.2..v3.3.0 --output-dir output/new-data5
python -m src.create_data https://github.com/arrow-py/arrow/compare/1.2.0..1.2.1 --output-dir output/new-data5
python -m src.create_data https://github.com/qutip/qutip/compare/v5.0.4..v5.1.0 --output-dir output/new-data5
python -m src.create_data https://github.com/scipy/scipy/compare/v1.15.3..v1.16.0 --output-dir output/new-data5

docker tag base_env:numpy_v2.1.3 thaiminhpv/numpy__numpy_v2.1.3_v2.2.0:latest
docker tag base_env:numpy_v2.2.6 thaiminhpv/numpy__numpy_v2.2.6_v2.3.0:latest
docker tag base_env:graphene_v3.2.2 thaiminhpv/graphql-python__graphene_v3.2.2_v3.3.0:latest
docker tag base_env:arrow_1.2.0 thaiminhpv/arrow-py__arrow_1.2.0_1.2.1:latest
docker tag base_env:qutip_v5.0.4 thaiminhpv/qutip__qutip_v5.0.4_v5.1.0:latest
docker tag base_env:scipy_v1.15.3 thaiminhpv/scipy__scipy_v1.15.3_v1.16.0:latest

docker push thaiminhpv/numpy__numpy_v2.1.3_v2.2.0:latest
docker push thaiminhpv/numpy__numpy_v2.2.6_v2.3.0:latest
docker push thaiminhpv/graphql-python__graphene_v3.2.2_v3.3.0:latest
docker push thaiminhpv/arrow-py__arrow_1.2.0_1.2.1:latest
docker push thaiminhpv/qutip__qutip_v5.0.4_v5.1.0:latest
docker push thaiminhpv/scipy__scipy_v1.15.3_v1.16.0:latest

base_env                                      arrow_1.2.0                                    33a1b7549d52   26 hours ago   4.38GB
base_env                                      pytest_8.3.5                                   13ee44a1ad09   7 days ago     4.37GB
base_env                                      scipy_v1.15.3                                  74f46acf18cd   7 days ago     10.5GB
base_env                                      scipy_v1.15.0                                  ba7bc5c822d0   8 days ago     11.3GB
base_env                                      qutip_v5.0.4                                   c2350f07177c   8 days ago     4.34GB
base_env                                      numpy_v2.2.6                                   61676f260665   8 days ago     13GB
base_env                                      graphene_v3.2.2                                23e9f83974f6   12 days ago    3.97GB
base_env                                      numpy_v2.1.3                                   6e4c6f278cdf   12 days ago    12.7GB

	repo_name	tag_name	base_name	Setup	release_url
0	numpy/numpy	v2.2.0	v.2.1.3	✅	https://github.com/numpy/numpy/releases/tag/v2.2.0
1	numpy/numpy	v2.3.0	v.2.2.6	✅	https://github.com/numpy/numpy/releases/tag/v2.3.0
2	graphql-python/graphene	v3.3.0	v3.2.2	✅	https://github.com/graphql-python/graphene/releases/tag/v3.3.0
3	crsmithdev/arrow	1.2.1	1.2.0	✅	https://github.com/crsmithdev/arrow/releases/tag/1.2.1
5	qutip/qutip	v5.1.0	v5.0.4	✅	https://github.com/qutip/qutip/releases/tag/v5.0.4
6	scipy/scipy	v1.16.0	v.1.15.3	✅	https://github.com/scipy/scipy/releases/tag/v1.16.0


git diff "$START_TAG..$commit" --binary > "$COMMIT_DIR/submission.diff"
git diff "$START_TAG..$commit" --binary -- ':(exclude)*test*' > "$COMMIT_DIR/submission_without_test.diff"


git diff "v3.2.2..v3.3.0" --binary > "../graphql-python__graphene_v3.2.2_v3.3.0.diff"
git diff "v3.2.2..v3.3.0" --binary -- ':(exclude)*test*' > "../graphql-python__graphene_v3.2.2_v3.3.0_without_test.diff"

git diff "v3.2.2..v3.3.0" > "../graphql-python__graphene_v3.2.2_v3.3.0.diff"

python src/export_data.py --input_dir output/new-data4 --output_dir output/exported_dataset

python -m src.run_evaluation_begin \
    --cache_level instance \
    --dataset_name ./output/exported_dataset \
    --predictions_path ./output/preds/empty.jsonl \
    --max_workers 6 \
    --split test \
    --run_id empty

python -m src.run_evaluation_gold \
    --cache_level instance \
    --dataset_name ./output/exported_dataset \
    --predictions_path ./output/preds/empty.jsonl \
    --max_workers 6 \
    --split test \
    --run_id gold

# python -m src.export_test_status_changes \
#     --empty-status-path logs/run_evaluation/empty/empty/arrow-py__arrow_1.2.0_1.2.1/status.json \
#     --gold-status-path logs/run_evaluation/gold/empty/arrow-py__arrow_1.2.0_1.2.1/status.json \
#         --instance-id arrow-py__arrow_1.2.0_1.2.1 \
#         --output-file output/test_status_changes.jsonl
# done

instance_ids=(
    "arrow-py__arrow_1.2.0_1.2.1"
    "graphql-python__graphene_v3.2.2_v3.3.0"
    "numpy__numpy_v2.1.3_v2.2.0"
    "numpy__numpy_v2.2.6_v2.3.0"
    "qutip__qutip_v5.0.4_v5.1.0"
    "scipy__scipy_v1.15.3_v1.16.0"
)

for instance_id in "${instance_ids[@]}"; do

python -m src.export_test_status_changes \
    --empty-status-path logs/run_evaluation/empty/empty/${instance_id}/status.json \
    --gold-status-path logs/run_evaluation/gold/gold/${instance_id}/status.json \
        --instance-id ${instance_id} \
        --output-file output/test_status_changes.jsonl

done

bash ../agg.sh "arrow-py__arrow_1.2.0_1.2.1" arrow_1.2.0
bash ../agg.sh "graphql-python__graphene_v3.2.2_v3.3.0" graphene_v3.2.2
bash ../agg.sh "numpy__numpy_v2.1.3_v2.2.0" numpy_v2.1.3

bash eval.sh "output/preds/arrow-py__arrow_1.2.0_1.2.1.jsonl"
bash eval.sh "output/preds/graphql-python__graphene_v3.2.2_v3.3.0.jsonl"
bash eval.sh "output/preds/numpy__numpy_v2.1.3_v2.2.0.jsonl"

python -m src.parse_score \
  --instance-id "arrow-py__arrow_1.2.0_1.2.1" \
  --prediction-file "output/preds/arrow-py__arrow_1.2.0_1.2.1.jsonl" \
  --dataset-path "./output/exported_dataset" \
  --test-status-changes-path "output/test_status_changes.jsonl"

python -m src.parse_score \
  --instance-id "graphql-python__graphene_v3.2.2_v3.3.0" \
  --prediction-file "output/preds/graphql-python__graphene_v3.2.2_v3.3.0.jsonl" \
  --dataset-path "./output/exported_dataset" \
  --test-status-changes-path "output/test_status_changes.jsonl"

python -m src.parse_score \
  --instance-id "numpy__numpy_v2.1.3_v2.2.0" \
  --prediction-file "output/preds/numpy__numpy_v2.1.3_v2.2.0.jsonl" \
  --dataset-path "./output/exported_dataset" \
  --test-status-changes-path "output/test_status_changes.jsonl"