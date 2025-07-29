import os
import glob
import argparse
import yaml
from datasets import Dataset, DatasetDict


def load_yaml_files(input_dir):
    yaml_files = glob.glob(os.path.join(input_dir, '*.yaml'))
    data = []
    for file_path in yaml_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Each file is a single document
            doc = yaml.safe_load(f)
            doc['version'] = ''
            doc['hints_text'] = ''
            data.append(doc)
    return data


def main():
    parser = argparse.ArgumentParser(description='Export YAML files as a HuggingFace dataset.')
    parser.add_argument('--input_dir', type=str, default='output', help='Directory containing YAML files')
    parser.add_argument('--output_dir', type=str, required=True, help='Directory to save the HuggingFace dataset (required)')
    args = parser.parse_args()

    data = load_yaml_files(args.input_dir)
    if not data:
        print(f'No YAML files found in {args.input_dir}')
        return

    dataset = Dataset.from_list(data)
    print(f'Loaded {len(dataset)} records from {args.input_dir}')

    dataset = DatasetDict({'test': dataset})

    os.makedirs(args.output_dir, exist_ok=True)
    dataset.save_to_disk(args.output_dir)
    print(f'Dataset saved to {args.output_dir} using HuggingFace save_to_disk.')


if __name__ == '__main__':
    main()
