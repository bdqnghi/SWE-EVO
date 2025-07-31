#!/bin/bash

# bash eval.sh "output/preds/arrow-py__arrow_1.2.0_1.2.1.jsonl"

# Path to the full jsonl file
input_jsonl="$1"

# Temporary file to hold one-line predictions
# temp_jsonl="output/preds/tmp.jsonl"
temp_jsonl="output/preds/$(basename $input_jsonl .jsonl)_tmp.jsonl"

echo "temp_jsonl: $temp_jsonl"

# Loop over each line in patches.jsonl
while IFS= read -r line; do
    # Extract the model_name_or_path (used as run_id)
    run_id=$(echo "$line" | jq -r '.model_name_or_path')

    # Write the single line to abc.jsonl
    echo "$line" > "$temp_jsonl"

    echo "Running evaluation for $run_id..."

    # Call the Python evaluation script
    echo python -m src.run_evaluation_pred \
        --cache_level instance \
        --dataset_name ./output/exported_dataset \
        --predictions_path $temp_jsonl \
        --max_workers 1 \
        --split test \
        --run_id "$run_id"

    # Call the Python evaluation script
    python -m src.run_evaluation_pred \
        --cache_level instance \
        --dataset_name ./output/exported_dataset \
        --predictions_path $temp_jsonl \
        --max_workers 1 \
        --split test \
        --run_id "$run_id"

done < "$input_jsonl"