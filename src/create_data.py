#!/usr/bin/env python3
"""
CLI tool to extract release notes and diff from GitHub compare and release URLs, outputting a structured JSON file.
"""
import argparse
import os
import re
import requests
import json
from urllib.parse import urlparse
import yaml
import openai
from openai import OpenAI
from langchain_core.utils.json import parse_json_markdown
from loguru import logger
import unidiff

client = OpenAI()

def parse_args():
    parser = argparse.ArgumentParser(description="Extracts release notes and diff from GitHub and outputs a YAML file.")
    parser.add_argument('compare_url', type=str, help='GitHub compare URL (e.g., https://github.com/org/repo/compare/v1..v2)')
    parser.add_argument('--output-dir', type=str, required=True, help='Directory to output the YAML file')
    return parser.parse_args()

def extract_repo_and_commits(compare_url):
    match = re.match(r"https://github.com/([^/]+)/([^/]+)/compare/(.+)\.\.(.+)", compare_url)
    if not match:
        raise ValueError("Invalid compare URL format")
    owner, repo, base, end = match.groups()
    return owner, repo, base, end

def github_get(url):
    headers = {}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'token {token}'
    resp = requests.get(url, headers=headers)
    return resp

def fetch_compare_data(owner, repo, base, end):
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base}...{end}"
    resp = github_get(url)
    if resp.status_code == 403 and 'X-RateLimit-Remaining' in resp.headers and resp.headers['X-RateLimit-Remaining'] == '0':
        raise RuntimeError("GitHub API rate limit exceeded. Set a GITHUB_TOKEN environment variable for higher limits.")
    if resp.status_code == 401:
        raise RuntimeError("Unauthorized. Check your GitHub credentials or token.")
    resp.raise_for_status()
    return resp.json()

def fetch_release_note(owner, repo, tag):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    resp = github_get(url)
    if resp.status_code == 403 and 'X-RateLimit-Remaining' in resp.headers and resp.headers['X-RateLimit-Remaining'] == '0':
        raise RuntimeError("GitHub API rate limit exceeded. Set a GITHUB_TOKEN environment variable for higher limits.")
    if resp.status_code == 401:
        raise RuntimeError("Unauthorized. Check your GitHub credentials or token.")
    if resp.status_code == 404:
        return ""
    resp.raise_for_status()
    return resp.json().get('body', '')

def fetch_prs_from_commits(owner, repo, commits):
    prs = []
    for commit in commits:
        sha = commit['sha']
        # Search PRs associated with this commit
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}/pulls"
        resp = requests.get(url, headers={"Accept": "application/vnd.github.groot-preview+json"})
        if resp.status_code == 200:
            for pr in resp.json():
                prs.append({
                    "pr_number": pr["number"],
                    "pr_title": pr["title"],
                    "pr_url": pr["html_url"],
                    "pr_link": pr["_links"]["html"]["href"]
                })
    return prs

def split_patch_files(files):
    patch = []
    test_patch = []
    for f in files:
        filename = f['filename']
        patch_content = f.get('patch', '')
        if 'test' in filename.lower():
            test_patch.append(patch_content)
        else:
            patch.append(patch_content)
    return '\n'.join(patch), '\n'.join(test_patch)

def extract_test_cases_with_llm(test_patch, model="deepseek-v3-0324"):
    if not test_patch.strip():
        logger.info("[LLM] No test patch provided for extraction.")
        return []
    try:
        patch_set = unidiff.PatchSet.from_string(test_patch)
    except Exception as e:
        logger.error(f"[LLM] Failed to parse test_patch with unidiff: {e}")
        return []
    all_nodeids = []
    for patched_file in patch_set:
        file_diff = str(patched_file)
        prompt = f"""Given the following unified diff for a test file, extract the names of all test cases (functions or methods) that were changed, added, or removed.
For each test, output the full nodeid (file path and test name, separated by '::'), as used by pytest and similar frameworks.
Examples:
- Standalone function: 'tests/test_foo.py::test_bar'
- Inside a class: 'tests/test_foo.py::TestClass::test_bar'
Return a JSON array of nodeids only.

Diff:
```
{file_diff}
```"""
        logger.info("[LLM] Calling OpenAI with prompt for file {}:\n{}", patched_file.path, prompt)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=1024,
        )
        try:
            content = completion.choices[0].message.content
            logger.info("[LLM] Raw LLM output for file {}:\n{}", patched_file.path, content)
            result = parse_json_markdown(content)
            logger.info("[LLM] Parsed test case nodeids for file {}: {}", patched_file.path, result)
            all_nodeids.extend(result)
        except Exception as e:
            logger.error(f"[LLM] Failed to parse LLM output for file {patched_file.path}: {e}")
            continue
    return all_nodeids

def get_diff(pr_url: str) -> str:
    pr_number = pr_url.rstrip('/').split('/')[-1]
    repo_path = '/'.join(pr_url.split('/')[-4:-2])
    diff_url = f"https://github.com/{repo_path}/pull/{pr_number}.diff"
    logger.info(f"[PR] Downloading diff from: {diff_url}")
    response = requests.get(diff_url)
    response.raise_for_status()
    return response.text

def extract_code_changes_from_diff(diff_content: str) -> str:
    try:
        patch_set = unidiff.PatchSet.from_string(diff_content)
        code_changes = []
        for patched_file in patch_set:
            file_path = patched_file.path.lower()
            if not any(pattern in file_path for pattern in ["test", "spec", "_test", ".test"]):
                code_changes.append(str(patched_file))
        if not code_changes:
            return ""
        return "\n".join(code_changes)
    except Exception as e:
        logger.error(f"Failed to parse code diff: {e}")
        return ""

def extract_test_changes_from_diff(diff_content: str) -> str:
    try:
        patch_set = unidiff.PatchSet.from_string(diff_content)
        test_changes = []
        for patched_file in patch_set:
            file_path = patched_file.path.lower()
            if any(pattern in file_path for pattern in ["test", "spec", "_test", ".test"]):
                test_changes.append(str(patched_file))
        if not test_changes:
            return ""
        return "\n".join(test_changes)
    except Exception as e:
        logger.error(f"Failed to parse diff: {e}")
        return ""

def main():
    args = parse_args()
    owner, repo, base, end = extract_repo_and_commits(args.compare_url)
    compare_data = fetch_compare_data(owner, repo, base, end)
    base_commit = compare_data['base_commit']['sha']
    end_commit = compare_data['merge_base_commit']['sha'] if 'merge_base_commit' in compare_data else compare_data['commits'][-1]['sha'] if compare_data['commits'] else None
    environment_setup_commit = base_commit  # Placeholder, can be customized
    files = compare_data.get('files', [])
    patch, test_patch = split_patch_files(files)
    commits = compare_data.get('commits', [])
    release_note = fetch_release_note(owner, repo, end)
    prs = fetch_prs_from_commits(owner, repo, commits)
    # Add is_mentioned_in_release_note for each PR
    pr_numbers_in_history = set()
    for pr in prs:
        pr_number = pr['pr_number']
        pr_url = pr['pr_url']
        pr_numbers_in_history.add(str(pr_number))
        # Look for #1234, PR 1234, (1234), or direct PR link in release note
        pattern = rf"(#[ ]?{pr_number}\b|PR[ ]?{pr_number}\b|\({pr_number}\)|{re.escape(pr_url)})"
        pr['is_mentioned_in_release_note'] = bool(re.search(pattern, release_note, re.IGNORECASE))

    # Find PRs mentioned in release note but not in commit history
    mentioned_prs = set()
    # Find all #1234, PR 1234, (1234), and PR/issue links for this repo only
    pr_number_patterns = re.findall(r"#(\d+)|PR[ ]?(\d+)|\((\d+)\)", release_note, re.IGNORECASE)
    for match in pr_number_patterns:
        for num in match:
            if num and num not in pr_numbers_in_history:
                mentioned_prs.add(num)
    repo_link_pattern = rf"https://github.com/{re.escape(owner)}/{re.escape(repo)}/(?:pull|issues)/(\d+)"
    pr_link_patterns = re.findall(repo_link_pattern, release_note)
    for num in pr_link_patterns:
        if num and num not in pr_numbers_in_history:
            mentioned_prs.add(num)
    # Add these as minimal PRs
    for num in mentioned_prs:
        pr_url = f"https://github.com/{owner}/{repo}/pull/{num}"
        pr_dict = {
            "pr_number": int(num),
            "pr_title": None,
            "pr_url": pr_url,
            "pr_link": pr_url,
            "is_mentioned_in_release_note": True
        }
        prs.append(pr_dict)
    # For each PR, fetch diff from GitHub and extract test_patch and patch using API
    for pr in prs:
        pr_url = pr['pr_url']
        try:
            diff_content = get_diff(pr_url)
            pr['patch_without_test'] = extract_code_changes_from_diff(diff_content)
            pr['test_patch'] = extract_test_changes_from_diff(diff_content)
            logger.info(f"[PR {pr['pr_number']}] Downloaded diff length: {len(diff_content)}, test_patch length: {len(pr['test_patch'])}, patch_without_test length: {len(pr['patch_without_test'])}")
        except Exception as e:
            logger.error(f"[PR {pr['pr_number']}] Failed to fetch or parse diff: {e}")
            pr['patch_without_test'] = ''
            pr['test_patch'] = ''
        # If both are empty, mark as issue and update URLs
        if not pr['patch_without_test'] and not pr['test_patch']:
            pr['is_issue'] = True
            num = pr['pr_number']
            issue_url = f"https://github.com/{owner}/{repo}/issues/{num}"
            pr['pr_url'] = issue_url
            pr['pr_link'] = issue_url
        else:
            pr['is_issue'] = False
        pr['changed_test_cases'] = extract_test_cases_with_llm(pr['test_patch'])

    repo_full = f"{owner}/{repo}"
    instance_id = f"{owner}__{repo}_{base}_{end}"
    output = {
        "repo": repo_full,
        "instance_id": instance_id,
        "base_commit": base_commit,
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": release_note,
        "FAIL_TO_PASS": "...",
        "PASS_TO_PASS": "...",
        "environment_setup_commit": environment_setup_commit,
        "PRs": prs,
        "start_version": base,
        "end_version": end,
        "end_version_commit": end_commit,
    }
    output_filename = f"{owner}__{repo}_{base}_{end}.yaml"
    output_path = os.path.join(args.output_dir, output_filename)
    with open(output_path, 'w') as f:
        out = yaml.dump_nice_yaml(output)
        f.write(out)
    print(f"Output written to {output_path}")

if __name__ == "__main__":
    main() 