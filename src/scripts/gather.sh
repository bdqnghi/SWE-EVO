#!/bin/bash
# bash ../agg.sh "arrow-py__arrow_1.2.0_1.2.1" arrow_1.2.0

# instance_id="arrow-py__arrow_1.2.0_1.2.1"
instance_id="$1"
output_file="$instance_id.jsonl"

echo -n "" > "$output_file"  # Clear the output file if it exists

# Loop through all submission.diff files
find $2 -type f -name "submission.diff" | while read -r diff_file; do
    # Get the parent folder and timestamp (e.g., qwen3-235b-a22b__20250722162209)
    parent_dir=$(basename "$(dirname "$diff_file")")
    model_dir=$(basename "$(dirname "$(dirname "$diff_file")")")
    model_name_or_path="${model_dir}__${parent_dir}"

    # Create JSON entry
    jq -n -c --arg inst "$instance_id" \
              --rawfile patch "$diff_file" \
              --arg model "$model_name_or_path" \
              '{instance_id: $inst, model_name_or_path: $model, model_patch: $patch}' >> "$output_file"
done
