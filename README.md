# GitHub Release Diff Extractor

## Usage

```
python -m src.create_data https://github.com/graphql-python/graphene/compare/v3.2.2..v3.3.0 --output-dir output/
```

- Requires Python 3.7+
- Install dependencies: `pip install -r requirements.txt`
- Optionally set a `GITHUB_TOKEN` environment variable for higher API rate limits.

The output will be a JSON file in the output directory with the extracted data. 