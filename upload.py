#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Markdown to Remote Image URLs & Footnote Converter
---------------------------------------------------
This script converts:
1. Local image paths to Git remote raw URLs
2. Markdown footnotes [^id] to:
   - Standard: HTML anchors + ordered list at end (default)
   - Native: <sup data-text="..." data-numero="...">[num]</sup> (Zhihu native style)

The original file is never modified; output is written to a new file.
"""

import os
import re
import argparse
import subprocess
from pathlib import Path
from collections import OrderedDict


# ================== Git Helper Functions ==================

def get_git_root() -> Path:
    """Return absolute path to the root of the Git repository."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        return Path(root)
    except subprocess.CalledProcessError:
        raise SystemExit("Error: Not inside a Git repository.")


def get_current_branch() -> str:
    """Return the current branch name."""
    try:
        branch = subprocess.check_output(
            ["git", "symbolic-ref", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        return branch
    except subprocess.CalledProcessError:
        for ref in ["master", "main"]:
            if Path(".git/refs/heads", ref).exists():
                return ref
        raise SystemExit("Error: Unable to determine current branch.")


def parse_remote_url(remote_name: str = "origin") -> str:
    """
    Parse the remote URL and return a raw base URL (without trailing slash).
    Supports GitHub, GitLab, Gitee, Bitbucket.
    """
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", remote_name],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        raise SystemExit(f"Error: Remote '{remote_name}' not found.")

    if url.startswith("git@"):
        url = url.replace(":", "/").replace("git@", "https://")
    elif url.startswith("http://"):
        url = url.replace("http://", "https://")

    if url.endswith(".git"):
        url = url[:-4]

    if "github.com" in url:
        return url.replace("github.com", "raw.githubusercontent.com")
    elif "gitlab.com" in url or "gitee.com" in url or "bitbucket.org" in url:
        return url + "/raw"
    else:
        print(f"Warning: Unknown platform for {url}. Using /raw suffix.")
        return url + "/raw"


def is_inside_repo(file_path: Path, repo_root: Path) -> bool:
    """Check if the file is inside the Git repository."""
    try:
        file_path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


# ================== Image Processing ==================

def extract_local_images(content: str) -> list:
    """
    Extract all local image references from Markdown.
    Returns list of (full_match, raw_path_str).
    Supports ![]() and <img src="...">
    """
    matches = []
    pattern1 = r"!\[.*?\]\((.*?)\)"
    for m in re.finditer(pattern1, content):
        path = m.group(1).strip()
        if path and not path.startswith(("http://", "https://", "data:")):
            matches.append((m.group(0), path))
    pattern2 = r'<img\s+[^>]*src=["\'](.*?)["\'][^>]*>'
    for m in re.finditer(pattern2, content):
        path = m.group(1).strip()
        if path and not path.startswith(("http://", "https://", "data:")):
            matches.append((m.group(0), path))
    return matches


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    """Resolve a possibly relative path to absolute."""
    p = Path(raw_path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def convert_to_remote_url(abs_path: Path, repo_root: Path, raw_base: str, branch: str) -> str:
    """Convert local absolute path to remote raw URL."""
    rel = abs_path.relative_to(repo_root)
    return f"{raw_base}/{branch}/{rel.as_posix()}"


# ================== Footnote Processing ==================

def extract_footnote_definitions(content: str) -> tuple[str, dict]:
    """
    Remove footnote definitions [^id]: content from the content,
    and return a dict mapping id -> content (preserving multi-line definitions).
    """
    lines = content.splitlines(keepends=True)
    new_lines = []
    footnotes = OrderedDict()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^\[\^([^\]]+)\]:\s*(.*)', line)
        if match:
            fn_id = match.group(1)
            content_parts = [match.group(2).strip()]
            i += 1
            while i < len(lines) and (lines[i].startswith(' ') or lines[i].startswith('\t')):
                content_parts.append(lines[i].strip())
                i += 1
            footnotes[fn_id] = ' '.join(content_parts)
            continue
        else:
            new_lines.append(line)
            i += 1
    return ''.join(new_lines), footnotes


def replace_footnote_references(content: str, footnotes: dict, mode: str = 'standard') -> str:
    """
    Replace [^id] in content with appropriate markup.
    mode: 'standard' -> anchor links + ordered list at end
          'native'   -> <sup data-text="..." data-numero="...">[num]</sup> (Zhihu native)
    """
    if not footnotes:
        return content

    # Collect references in order
    ref_pattern = r'\[\^([^\]]+)\]'
    ids_in_order = [m.group(1) for m in re.finditer(ref_pattern, content)]
    seen = set()
    unique_ids = []
    for fid in ids_in_order:
        if fid not in seen:
            seen.add(fid)
            unique_ids.append(fid)

    id_to_num = {fid: i+1 for i, fid in enumerate(unique_ids)}

    if mode == 'native':
        # Native Zhihu style: <sup data-text="content" data-numero="num">[num]</sup>
        def replace_ref(m):
            fid = m.group(1)
            num = id_to_num.get(fid)
            if num is not None:
                text = footnotes.get(fid, '').strip()
                # Escape double quotes in text to avoid breaking attribute
                text_escaped = text.replace('"', '&quot;')
                return f'<sup data-text="{text_escaped}" data-numero="{num}">[{num}]</sup>'
            else:
                return m.group(0)
        new_content = re.sub(ref_pattern, replace_ref, content)
        # Do NOT append a footnote list
        return new_content
    else:
        # Standard mode: anchor links + ordered list at end
        def replace_ref(m):
            fid = m.group(1)
            num = id_to_num.get(fid)
            if num is not None:
                return f'<sup><a href="#fn-{fid}" id="ref-{fid}">[{num}]</a></sup>'
            else:
                return m.group(0)
        new_content = re.sub(ref_pattern, replace_ref, content)
        # Append list
        if unique_ids:
            footer = '\n\n<hr />\n<ol>\n'
            for fid in unique_ids:
                text = footnotes.get(fid, '').strip()
                footer += f'  <li id="fn-{fid}">{text} <a href="#ref-{fid}">↩</a></li>\n'
            footer += '</ol>\n'
            new_content += footer
        return new_content


# ================== Output Path Resolution ==================

def resolve_output_path(input_path: Path, output_arg: Path | None) -> Path:
    """
    Determine output file path.
    - If output_arg is None: use default naming.
    - If output_arg is an existing directory or ends with / or \: treat as directory.
    - Otherwise treat as file path (parent directories created).
    """
    if output_arg is None:
        return input_path.parent / (input_path.stem + "_remote" + input_path.suffix)

    if output_arg.exists() and output_arg.is_dir():
        return output_arg / (input_path.stem + "_remote" + input_path.suffix)

    if str(output_arg).endswith(('/', '\\')):
        output_arg.mkdir(parents=True, exist_ok=True)
        return output_arg / (input_path.stem + "_remote" + input_path.suffix)

    output_arg.parent.mkdir(parents=True, exist_ok=True)
    return output_arg


# ================== Main ==================

def main():
    parser = argparse.ArgumentParser(
        description="Convert local images to remote URLs and transform footnotes for platforms."
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        type=Path,
        help="Input Markdown file path"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output file or directory. If omitted, uses '<input_stem>_remote<input_suffix>'"
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="File encoding (default: utf-8)"
    )
    parser.add_argument(
        "--branch",
        help="Override Git branch name (default: current branch)"
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote name (default: origin)"
    )
    parser.add_argument(
        "--footnote-mode",
        choices=['standard', 'native'],
        default='standard',
        help="Footnote conversion mode: 'standard' (anchors + list) or 'native' (Zhihu native <sup> tags without list)"
    )
    args = parser.parse_args()

    # Git info
    repo_root = get_git_root()
    branch = args.branch or get_current_branch()
    raw_base = parse_remote_url(args.remote)

    print(f"Repository root: {repo_root}")
    print(f"Branch: {branch}")
    print(f"Remote raw base: {raw_base}")

    # Read input
    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Error: Input file not found: {input_path}")

    with open(input_path, "r", encoding=args.encoding) as f:
        content = f.read()

    # ---- Process footnotes first ----
    content_no_defs, footnotes = extract_footnote_definitions(content)
    if footnotes:
        content = replace_footnote_references(content_no_defs, footnotes, args.footnote_mode)
        print(f"Found {len(footnotes)} footnote definitions. Mode: {args.footnote_mode}")
    else:
        content = content_no_defs

    # ---- Process images ----
    image_refs = extract_local_images(content)
    if image_refs:
        new_content = content
        for full_match, raw_path in image_refs:
            abs_path = resolve_path(input_path.parent, raw_path)
            if not abs_path.exists():
                print(f"Warning: Image file not found: {abs_path} (skipping)")
                continue
            if not is_inside_repo(abs_path, repo_root):
                raise SystemExit(
                    f"Error: Image '{abs_path}' is not inside the Git repository.\n"
                    f"All images must be versioned in the repo."
                )
            remote_url = convert_to_remote_url(abs_path, repo_root, raw_base, branch)
            new_match = full_match.replace(raw_path, remote_url)
            new_content = new_content.replace(full_match, new_match)
        content = new_content
        print(f"Replaced {len(image_refs)} local image references.")
    else:
        print("No local image references found.")

    # ---- Write output ----
    output_path = resolve_output_path(input_path, args.output)
    with open(output_path, "w", encoding=args.encoding) as f:
        f.write(content)

    print(f"Conversion complete. Output written to: {output_path}")


if __name__ == "__main__":
    main()
