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

def extract_test_cases_with_llm(test_patch, model="gpt-4-1106-preview"):
    if not test_patch.strip():
        logger.info("[LLM] No test patch provided for extraction.")
        return []
    client = OpenAI()
    prompt = (
        "Given the following unified diff for test files, extract the names of all test cases (functions or methods) that were changed, added, or removed. "
        "Return a JSON array of test case names only.\n\n"
        f"Diff:\n{test_patch}\n"
    )
    logger.info("[LLM] Calling OpenAI with prompt:\n{}", prompt)
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
        logger.info("[LLM] Raw LLM output:\n{}", content)
        result = parse_json_markdown(content)
        logger.info("[LLM] Parsed test case names: {}", result)
        return result
    except Exception as e:
        logger.error(f"[LLM] Failed to parse LLM output: {e}")
        return []

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
    # Find all #1234, PR 1234, (1234), and PR links
    pr_number_patterns = re.findall(r"#(\d+)|PR[ ]?(\d+)|\((\d+)\)", release_note, re.IGNORECASE)
    for match in pr_number_patterns:
        for num in match:
            if num and num not in pr_numbers_in_history:
                mentioned_prs.add(num)
    pr_link_patterns = re.findall(r"https://github.com/[^/]+/[^/]+/pull/(\d+)", release_note)
    for num in pr_link_patterns:
        if num and num not in pr_numbers_in_history:
            mentioned_prs.add(num)
    # Add these as minimal PRs
    for num in mentioned_prs:
        pr_url = f"https://github.com/{owner}/{repo}/pull/{num}"
        prs.append({
            "pr_number": int(num),
            "pr_title": None,
            "pr_url": pr_url,
            "pr_link": pr_url,
            "is_mentioned_in_release_note": True
        })
    # For each PR, extract changed test cases from its test_patch using LLM
    for pr in prs:
        pr_number = pr['pr_number']
        # Find test_patch for this PR (by commit)
        pr_test_patch = ''
        for commit in commits:
            if 'commit' in commit and 'sha' in commit['commit']:
                sha = commit['commit']['sha']
            else:
                sha = commit.get('sha')
            if not sha:
                continue
            # If PR is from commit history, match commit to PR
            if str(pr_number) in commit.get('commit', {}).get('message', '') or str(pr_number) in commit.get('commit', {}).get('url', ''):
                # Find test patch for this commit
                for f in files:
                    if 'test' in f['filename'].lower() and f.get('sha') == sha:
                        pr_test_patch += f.get('patch', '') + '\n'
        # If not found, fallback: try to find any test patch mentioning PR number
        if not pr_test_patch:
            for f in files:
                if 'test' in f['filename'].lower() and str(pr_number) in f.get('patch', ''):
                    pr_test_patch += f.get('patch', '') + '\n'
        logger.info(f"[PR {pr_number}] Extracting test cases from patch (length {len(pr_test_patch)}):\n{pr_test_patch[:500]}{'...' if len(pr_test_patch) > 500 else ''}")
        pr['changed_test_cases'] = extract_test_cases_with_llm(pr_test_patch)
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