#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Wood
r"""
LaTeX Structure Summariser

Reads one or more LaTeX files and extracts all sections, subsections, theorems,
definitions, and other structural elements, outputting them with proper indentation,
colors, cross-reference analysis, and citation display.

Uses an orthogonal two-dimensional filtering model:
  - Structural dimension: which section levels to show
  - Content dimension: which theorem/remark/proof types to show
  --only-* flags create whitelists; --hide-* flags subtract from them.

Usage:
    latexnav file1.tex [file2.tex ...] [OPTIONS]

Options:
    -o, --output FILE              Output file (default: stdout)
    -v, --verbose                  Show cross-references
    -d, --different-level          Only show refs from different structural level
    -c, --compact                  Output compact tab-separated format
    --refs-per-section             Show refs at section level (default with -v)
    --refs-per-subsection          Show refs at subsection level
    --refs-per-chapter             Show refs at chapter level (one summary per file)
    --refs-per-file                Show refs at file level (same as --refs-per-chapter)
    --refs-per-document            Show refs for entire document
    --refs-per-theorem             Show refs for each theorem/lemma/etc
    --refs-type TYPE[,TYPE...]     Filter refs (theorem,lemma,definition,etc)
    --refs-group-by-type           Group refs by element type
    --no-color                     Disable terminal colors

Citation Analysis:
    --cites-per-section            Show citations at section level
    --cites-per-subsection         Show citations at subsection level
    --cites-per-theorem            Show citations for each theorem/lemma/etc
    --cites-per-document           Show citations for entire document
    --resolve-cites                Resolve cite keys to author/year from bibliography.tex

Scope Filtering:
    --scope LABEL_OR_TITLE         Restrict output to a labelled section (exact label
                                   match first; falls back to case-insensitive title search)
    --depth N                      Limit structural depth below scope (requires --scope)
    --line-range START:END         Restrict output to elements within line range

Status Overlay Options:
    --status [FILE]                Overlay status from FILE (default: MANUSCRIPT_STATUS_SUMMARY.tsv)
    --status-filter STATUS[,...]   Show only elements with these statuses
    --hide-ready                   Hide elements marked READY

Dependency Analysis:
    --stats                        Show element type frequency table
    --per-chapter                  Break statistics down by chapter (requires --stats)
    --reverse-refs LABEL[,...]     Find all elements that reference the given label(s)
    --deps-matrix                  Show chapter x chapter cross-reference dependency matrix
    --include-self                 Include intra-chapter refs on diagonal (with --deps-matrix)
    --resolve-refs                 Resolve \ref{label} to element display names
    --head N                       Limit output to first N lines
    --json                         Export full parsed structure as JSON
    -q, --quiet                    Suppress stderr warnings

Display Filtering Options:
    --only-sections                Show only sections (content still shown)
    --only-subsections             Show only subsections
    --only-theorems                Show only theorems
    --only-numbered-results        Show theorem/lemma/proposition/corollary/definition
    --only-structural              Show section/subsection/subsubsection only (hides content)
    --show-non-numbered-results    Include starred environments (theorem*, lemma*, etc.)
    --hide-subsections             Hide subsections AND subsubsections (cascade)
    --hide-subsubsections          Hide subsubsections only
    --hide-supporting              Hide proof/remark/example/note/claim
    --hide-definitions             Hide definitions (can subtract from --only-numbered-results)
    (and more --only-* and --hide-* for all element types)

Parsed Environment Types:
    Standard:  theorem, definition, lemma, proposition, corollary
    Supporting: proof, remark, example, note, claim
    Research:  assumption, conjecture, hypothesis, question, problem,
               interpretation, setup, addendum, openproblem, false_conjecture
    Starred variants (theorem*, lemma*, etc.) are parsed but hidden by default.
    Custom \\newtheorem declarations are auto-detected; use --extra-env for
    environments defined in .sty files or other non-scanned locations.

Examples:
    # Basic usage
    latexnav chapter*.tex

    # Combined filtering: numbered results minus definitions
    latexnav --only-numbered-results --hide-definitions chapter*.tex

    # Scope to a specific section with theorem dependencies
    latexnav --scope sec:results --only-theorems --refs-per-theorem chapter2.tex

    # Scope by title (fuzzy matching — no need to know the exact label)
    latexnav --scope "index theory" chapter1.tex

    # Citations with author/year resolution
    latexnav --cites-per-section --resolve-cites chapter1.tex

    # Elements in a line range
    latexnav --line-range 100:200 chapter3.tex

    # With status overlay
    latexnav --status --hide-ready main.tex

    # Transitive dependency chain
    latexnav --reverse-refs thm:main_result --transitive main.tex

    # Compact output with size annotations
    latexnav --compact --sizes chapter1.tex
"""

import re
import sys
import argparse
import os
import json
import signal
import bisect
import textwrap
from collections import Counter, OrderedDict

# Optional YAML support for paper manifest
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Handle SIGPIPE for piping large output
try:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
except AttributeError:
    # Windows doesn't have SIGPIPE
    pass

_AUX_CACHE: dict = {}

# Default environments recognised by the parser.  Auto-detected \newtheorem
# names are added to _active_environments at runtime (see scan_newtheorem_declarations).
_DEFAULT_ENVIRONMENTS = [
    'theorem', 'definition', 'lemma', 'proposition', 'corollary',
    'proof', 'example', 'remark', 'note', 'claim', 'assumption',
    'conjecture', 'hypothesis', 'false_conjecture', 'openproblem',
    'question', 'interpretation', 'problem', 'addendum', 'setup',
    'draftingnote', 'reasoning',
]

# Mutable set — extended by main() after scanning for \newtheorem declarations.
_active_environments = set(_DEFAULT_ENVIRONMENTS)

# Sort key for structure elements: (source_file, char_start)
_SORT_KEY = lambda x: (x[6], x[7])

# Compiled ref pattern for \ref, \cref, \Cref, \eqref (used across many functions)
_REF_PATTERN = re.compile(r'\\(?:ref|cref|Cref|eqref)\{([^}]*)\}')


def _extract_ref_labels(text):
    r"""Extract all ref labels from text, handling comma-separated \cref{a,b} syntax."""
    labels = []
    for match in _REF_PATTERN.finditer(text):
        for part in match.group(1).split(','):
            part = part.strip()
            if part:
                labels.append(part)
    return labels


# Module-level warning controls (set by main() from --warnings flag)
_warn_errors = True   # Show error-level warnings (file not found, parse failures)
_warn_info = False    # Show info-level warnings (loading messages, processing)


def scan_newtheorem_declarations(filenames):
    r"""Scan files (following \input chains) for \newtheorem declarations.

    Returns a set of environment names found in the scanned files.
    Both \newtheorem{NAME}{...} and \newtheorem*{NAME}{...} are detected.
    """
    newtheorem_re = re.compile(r'\\newtheorem\*?\{(\w+)\}')
    input_re = re.compile(r'\\input\{([^}]*)\}')

    names = set()
    visited = set()

    def _scan(path, base):
        abs_path = os.path.abspath(path)
        if abs_path in visited:
            return
        visited.add(abs_path)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except (FileNotFoundError, IOError):
            return

        for m in newtheorem_re.finditer(content):
            names.add(m.group(1))

        file_dir = os.path.dirname(abs_path)
        for m in input_re.finditer(content):
            input_file = m.group(1).strip()
            if not input_file.endswith('.tex'):
                input_file += '.tex'
            full = os.path.join(file_dir, input_file)
            if os.path.exists(full):
                _scan(full, file_dir)

    for fn in filenames:
        _scan(fn, os.path.dirname(os.path.abspath(fn)))

    return names


# ANSI color codes for terminal output
class Colors:
    """ANSI color codes similar to Claude Code conversation style"""
    RESET = '\033[0m'
    BOLD = '\033[1m'

    # Structure elements
    FILE_HEADER = '\033[1;36m'      # Bold cyan for file headers
    SECTION = '\033[1;34m'          # Bold blue for sections
    SUBSECTION = '\033[1;35m'       # Bold magenta for subsections
    SUBSUBSECTION = '\033[1;33m'    # Bold yellow for subsubsections

    # Theorem-like environments
    THEOREM = '\033[1;32m'          # Bold green for theorems
    DEFINITION = '\033[1;36m'       # Bold cyan for definitions
    LEMMA = '\033[1;32m'            # Bold green for lemmas
    PROPOSITION = '\033[1;32m'      # Bold green for propositions
    PROOF = '\033[0;37m'            # Gray for proofs
    REMARK = '\033[0;33m'           # Yellow for remarks
    EXAMPLE = '\033[0;35m'          # Magenta for examples

    # Special elements
    LABEL = '\033[0;36m'            # Cyan for labels
    REF = '\033[0;32m'              # Green for references
    INPUT = '\033[0;34m'            # Blue for \input commands
    DIVIDER = '\033[0;90m'          # Dark gray for dividers
    TEXT_MUTED = '\033[0;90m'       # Light gray for secondary text
    FILENAME = '\033[1;37m'         # Bold white for filenames

    # Status indicators
    STATUS_READY = '\033[1;32m'           # Bold green for READY
    STATUS_MINOR = '\033[1;33m'           # Bold yellow for MINOR_REVISION
    STATUS_MAJOR = '\033[1;38;5;208m'     # Bold orange for MAJOR_REVISION
    STATUS_CRITICAL = '\033[1;31m'        # Bold red for CRITICAL_REVISION
    STATUS_NOT_READY = '\033[1;35m'       # Bold magenta for NOT_READY

    @staticmethod
    def disable():
        """Disable all colors"""
        for attr in dir(Colors):
            if not attr.startswith('_') and attr.isupper() and attr not in ['disable']:
                setattr(Colors, attr, '')

    @staticmethod
    def get_color_for_type(element_type):
        """Get color for a specific element type"""
        # Strip star for color lookup (theorem* uses same color as theorem)
        base_type = element_type.rstrip('*').lower()

        color_map = {
            'section': Colors.SECTION,
            'subsection': Colors.SUBSECTION,
            'subsubsection': Colors.SUBSUBSECTION,
            'theorem': Colors.THEOREM,
            'definition': Colors.DEFINITION,
            'lemma': Colors.LEMMA,
            'proposition': Colors.PROPOSITION,
            'corollary': Colors.PROPOSITION,
            'proof': Colors.PROOF,
            'remark': Colors.REMARK,
            'note': Colors.REMARK,
            'example': Colors.EXAMPLE,
            'claim': Colors.PROPOSITION,
        }
        return color_map.get(base_type, Colors.RESET)

    @staticmethod
    def get_status_color(status):
        """Get color for a specific status value"""
        status_map = {
            'READY': Colors.STATUS_READY,
            'MINOR_REVISION': Colors.STATUS_MINOR,
            'MAJOR_REVISION': Colors.STATUS_MAJOR,
            'CRITICAL_REVISION': Colors.STATUS_CRITICAL,
            'NOT_READY': Colors.STATUS_NOT_READY,
        }
        return status_map.get(status, Colors.TEXT_MUTED)

    @staticmethod
    def get_dot_fillcolor(element_type):
        """Hex fill color for DOT node by element type."""
        colors = {
            'theorem': '#e8f5e9', 'lemma': '#e8f5e9',
            'proposition': '#e8f5e9', 'corollary': '#e8f5e9',
            'definition': '#e3f2fd',
            'section': '#fffde7', 'subsection': '#fffde7', 'subsubsection': '#fffde7',
            'assumption': '#fce4ec', 'conjecture': '#fce4ec', 'hypothesis': '#fce4ec',
        }
        return colors.get(element_type.rstrip('*').lower(), '#f5f5f5')

    @staticmethod
    def get_dot_shape(element_type):
        """DOT shape for element type."""
        formal = {'theorem', 'lemma', 'proposition', 'corollary', 'definition',
                  'assumption', 'conjecture', 'hypothesis'}
        return 'box' if element_type.rstrip('*').lower() in formal else 'ellipse'


def load_status_file(status_file_path):
    """
    Load status information from TSV file.

    Returns dict mapping (file, label) -> status_info
    where status_info is dict with keys: STATUS, MATH_ISSUES, LAST_REVIEWED, REVIEW_DEPTH,
    DESCRIPTION, AFFECTED_ELEMENTS

    Handles both old (7-column) and new (9-column) TSV formats via header detection.
    """
    status_map = {}

    try:
        with open(status_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if not lines:
            return status_map

        # Detect column layout from header
        header = lines[0].strip().split('\t')
        col_index = {name: i for i, name in enumerate(header)}

        # Required columns
        file_col = col_index.get('FILE', 0)
        type_col = col_index.get('TYPE', 1)
        label_col = col_index.get('LABEL', 2)
        status_col = col_index.get('STATUS', 3)
        issues_col = col_index.get('MATH_ISSUES', 4)

        # New columns (may not exist in old format)
        reviewed_col = col_index.get('LAST_REVIEWED')
        depth_col = col_index.get('REVIEW_DEPTH')

        # Description and affected elements (position depends on format)
        desc_col = col_index.get('DESCRIPTION', 5)
        affected_col = col_index.get('AFFECTED_ELEMENTS', 6)

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) <= issues_col:
                continue

            file_name = parts[file_col]
            element_type = parts[type_col]
            label = parts[label_col]
            status = parts[status_col]
            math_issues = parts[issues_col]

            last_reviewed = parts[reviewed_col] if reviewed_col is not None and len(parts) > reviewed_col else ""
            review_depth = parts[depth_col] if depth_col is not None and len(parts) > depth_col else ""
            description = parts[desc_col] if len(parts) > desc_col else ""
            affected_elements = parts[affected_col] if len(parts) > affected_col else ""

            # Skip entries without labels
            if label == "(no label)":
                continue

            status_map[(file_name, label)] = {
                'STATUS': status,
                'MATH_ISSUES': math_issues,
                'LAST_REVIEWED': last_reviewed,
                'REVIEW_DEPTH': review_depth,
                'DESCRIPTION': description,
                'AFFECTED_ELEMENTS': affected_elements,
                'ELEMENT_TYPE': element_type
            }

    except FileNotFoundError:
        print(f"Warning: Status file '{status_file_path}' not found", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error reading status file: {e}", file=sys.stderr)

    return status_map


def load_manifest(manifest_path):
    """
    Load paper manifest (YAML or JSON, auto-detected by extension).

    Returns:
        papers: dict of paper_name -> {title, abbrev, shell, sources}
        label_to_papers: dict of label -> set of paper abbrevs
        tag_to_papers: dict of tag_name -> set of paper_names
    """
    papers = {}
    label_to_papers = {}
    tag_to_papers = {}

    try:
        ext = os.path.splitext(manifest_path)[1].lower()
        if ext in ('.yaml', '.yml'):
            if not HAS_YAML:
                print("Error: PyYAML not installed. Install with 'pip install pyyaml' "
                      "or use a .json manifest.", file=sys.stderr)
                return papers, label_to_papers, tag_to_papers
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        else:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

        if not data or 'papers' not in data:
            print(f"Warning: No 'papers' key in manifest '{manifest_path}'", file=sys.stderr)
            return papers, label_to_papers, tag_to_papers

        for paper_name, paper_info in data['papers'].items():
            abbrev = paper_info.get('abbrev', paper_name[:2].upper())
            papers[paper_name] = {
                'title': paper_info.get('title', ''),
                'abbrev': abbrev,
                'shell': paper_info.get('shell', ''),
                'sources': paper_info.get('sources', []),
            }
            # Build reverse indexes
            for source in paper_info.get('sources', []):
                for tag in source.get('tags', []):
                    # tag_to_papers
                    tag_to_papers.setdefault(tag, set()).add(paper_name)
                    # label_to_papers: tag name typically matches label name
                    label_to_papers.setdefault(tag, set()).add(abbrev)

    except FileNotFoundError:
        print(f"Warning: Manifest file '{manifest_path}' not found", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error reading manifest: {e}", file=sys.stderr)

    return papers, label_to_papers, tag_to_papers


def format_tags(tag_index, compact=False):
    """Format tag listing for --tags output."""
    if not tag_index:
        return "No tags found."

    if compact:
        lines = ["FILE\tTAG\tSTART\tEND\tLABELS"]
        for tag_name in sorted(tag_index.keys()):
            info = tag_index[tag_name]
            labels = ','.join(info['labels']) if info['labels'] else ''
            lines.append(f"{info['file']}\t{tag_name}\t{info['start_line']}\t{info['end_line']}\t{labels}")
        return '\n'.join(lines)
    else:
        # Group by file
        by_file = {}
        for tag_name, info in tag_index.items():
            by_file.setdefault(info['file'], []).append((tag_name, info))

        lines = []
        for fname in sorted(by_file.keys()):
            lines.append(f"{Colors.BOLD}{fname}{Colors.RESET}:")
            for tag_name, info in sorted(by_file[fname], key=lambda x: x[1]['start_line']):
                labels_str = ', '.join(info['labels']) if info['labels'] else '(no labels)'
                line_range = f"L{info['start_line']}-L{info['end_line']}"
                lines.append(f"  {Colors.LABEL}{tag_name}{Colors.RESET}  {line_range:>12s}   labels: {labels_str}")
            lines.append("")
        return '\n'.join(lines)


def get_status_badge(status, math_issues):
    """
    Get colored status badge for terminal output.

    Returns formatted string like "[🔴 CRITICAL]" or None if no status
    """
    if not status:
        return None

    # Emoji mapping for visual indicators
    emoji_map = {
        'READY': '🟢',
        'MINOR_REVISION': '🟡',
        'MAJOR_REVISION': '🟡',
        'CRITICAL_REVISION': '🔴',
        'NOT_READY': '🔴',
    }

    # Short status labels for display
    short_status = {
        'READY': 'READY',
        'MINOR_REVISION': 'MINOR',
        'MAJOR_REVISION': 'MAJOR',
        'CRITICAL_REVISION': 'CRITICAL',
        'NOT_READY': 'NOT READY',
    }

    emoji = emoji_map.get(status, '⚪')
    short_label = short_status.get(status, status)
    color = Colors.get_status_color(status)

    # Include math issues if CRITICAL/MAJOR
    if math_issues and math_issues != 'NONE':
        return f"{color}[{emoji} {short_label}/{math_issues}]{Colors.RESET}"
    else:
        return f"{color}[{emoji} {short_label}]{Colors.RESET}"


def extract_tags_from_content(content, source_file):
    r"""
    Extract %<*tag> / %</tag> docstrip-style markers from raw LaTeX content.

    Scans the raw content (before comment stripping) for tag open/close markers.
    For each completed tag, finds all \label{} commands within the tagged region.

    Returns dict: tag_name -> {
        'file': source_file,
        'start_line': int,  # line of %<*tag>
        'end_line': int,    # line of %</tag>
        'start_char': int,  # char position of %<*tag> line start
        'end_char': int,    # char position after %</tag> line end
        'labels': [str],    # \label{} found between tags
    }
    """
    tag_open_re = re.compile(r'^%<\*([^>]+)>\s*$')
    tag_close_re = re.compile(r'^%</([^>]+)>\s*$')
    label_re = re.compile(r'\\label\{([^}]*)\}')

    tags = {}
    open_tags = {}  # tag_name -> {start_line, start_char}
    char_pos = 0

    for line_num, line in enumerate(content.split('\n'), start=1):
        line_start = char_pos
        char_pos += len(line) + 1  # +1 for newline

        stripped = line.strip()
        m_open = tag_open_re.match(stripped)
        if m_open:
            tag_name = m_open.group(1)
            open_tags[tag_name] = {
                'start_line': line_num,
                'start_char': line_start,
            }
            continue

        m_close = tag_close_re.match(stripped)
        if m_close:
            tag_name = m_close.group(1)
            if tag_name in open_tags:
                start_info = open_tags.pop(tag_name)
                # Extract the region text to find labels
                region_text = content[start_info['start_char']:char_pos]
                labels = label_re.findall(region_text)
                tags[tag_name] = {
                    'file': source_file,
                    'start_line': start_info['start_line'],
                    'end_line': line_num,
                    'start_char': start_info['start_char'],
                    'end_char': char_pos,
                    'labels': labels,
                }

    return tags


def extract_latex_structure(filename, base_dir=None, file_contents=None, processed_files=None,
                            tag_index=None, file_structures=None):
    r"""
    Extract sections, subsections, theorems, definitions, etc. from a LaTeX file.
    Recursively processes \input{} and \ExecuteMetaData commands.

    Args:
        tag_index: If a dict is passed, populated with tag_name -> tag info from
                   %<*tag> / %</tag> markers. Backward-compatible (default None).
        file_structures: If a dict is passed, populated with source_file -> list of
                         structure elements. Used for \ExecuteMetaData region lookups.

    Returns a tuple: (structure, file_contents_dict)
    - structure: list of tuples (level, element_type, content, optional_text, label, line_number, source_file, char_start, char_end)
    - file_contents_dict: mapping from source_file to full file content string
    """

    if file_contents is None:
        file_contents = {}

    if processed_files is None:
        processed_files = set()

    if file_structures is None:
        file_structures = {}
    
    # Determine base directory for resolving relative paths
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(filename))
    
    # Define regex patterns to match various LaTeX structures
    section_pattern = r'\\(section|subsection|subsubsection)\*?\s*\{([^}]*)\}'
    label_pattern = r'\\label\{([^}]*)\}'
    input_pattern = r'\\input\{([^}]*)\}'

    # Build environment/command patterns dynamically from _active_environments
    env_alt = '|'.join(sorted(_active_environments))
    environment_pattern = r'\\begin\{(' + env_alt + r')(\*)?\}\s*(?:\[([^\]]*)\])?'
    command_pattern = r'\\(' + env_alt + r')(?:\s*\[([^\]]*)\])?\s*\{([^}]*)\}'

    # Build hierarchy levels dynamically
    hierarchy = {'section': 1, 'subsection': 2, 'subsubsection': 3}
    for env in _active_environments:
        hierarchy[env] = 4
        hierarchy[env + '*'] = 4
    
    structure = []

    # Get the display name for this file (just the filename)
    display_filename = os.path.basename(filename)

    # Check if we've already processed this file (avoid duplicates from \input{})
    abs_filename = os.path.abspath(filename)
    if abs_filename in processed_files:
        return [], file_contents
    processed_files.add(abs_filename)

    # Read the file
    try:
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return None

    # Join all lines into one string for pattern matching
    content = ''.join(lines)

    # Extract tags from raw content (before comment stripping)
    if tag_index is not None:
        file_tags = extract_tags_from_content(content, display_filename)
        tag_index.update(file_tags)

    # Store the file content (with comments replaced by spaces) for later reference.
    # Replacing with spaces (not removing) preserves character positions for tag lookups.
    content_no_comments = ''
    in_comment = False

    for i, char in enumerate(content):
        if char == '%' and (i == 0 or content[i-1] != '\\'):
            in_comment = True
            content_no_comments += ' '
        elif char == '\n':
            in_comment = False
            content_no_comments += char
        elif not in_comment:
            content_no_comments += char
        else:
            content_no_comments += ' '

    # Store this file's content
    file_contents[display_filename] = content_no_comments
    
    # Pre-build line-start offset array for O(log n) line lookups
    _newline_offsets = [i for i, c in enumerate(content_no_comments) if c == '\n']

    def get_line_number(start_pos):
        """Calculate line number from character position using binary search."""
        return bisect.bisect_right(_newline_offsets, start_pos) + 1
    
    # Build boundary pattern for tracked environments + sections (used by find_label_after)
    _tracked_envs = '|'.join(re.escape(e) for e in _active_environments)
    _boundary_pattern = re.compile(
        r'\\begin\{(' + _tracked_envs + r')\*?\}'
        r'|\\(?:section|subsection|subsubsection)\*?\s*\{'
    )

    def find_label_after(start_pos, max_distance=500):
        """Find the nearest label command after a given position.
        Stops at the next tracked \\begin{env} or \\section{} to avoid
        assigning a label that belongs to a subsequent environment."""
        search_text = content_no_comments[start_pos:start_pos+max_distance]
        label_match = re.search(label_pattern, search_text)
        if label_match:
            # Only stop at environments the parser tracks (not equation, enumerate, etc.)
            boundary = _boundary_pattern.search(search_text)
            if boundary and boundary.start() < label_match.start():
                return None  # label belongs to the next environment
            return label_match.group(1)
        return None

    # Find all section/subsection commands
    for match in re.finditer(section_pattern, content_no_comments):
        element_type = match.group(1)
        content_text = match.group(2).strip()
        line_num = get_line_number(match.start())
        level = hierarchy[element_type]
        label = find_label_after(match.end())
        structure.append((level, element_type, content_text, None, label, line_num, display_filename, match.start(), match.end()))
    
    # Find environment-style theorems/definitions (\begin{theorem}...\end{theorem})
    for match in re.finditer(environment_pattern, content_no_comments):
        base_type = match.group(1)  # theorem, lemma, etc
        star = match.group(2)  # * or None
        optional_text = match.group(3) if match.group(3) else None  # [optional title]

        # Construct element type (e.g., "theorem" or "theorem*")
        element_type = base_type + (star if star else "")

        line_num = get_line_number(match.start())
        level = hierarchy[element_type]
        label = find_label_after(match.end())
        # For environments, use optional text if provided, otherwise use element type
        content_text = optional_text if optional_text else element_type.capitalize()
        structure.append((level, element_type, content_text, optional_text, label, line_num, display_filename, match.start(), match.end()))

    # Find command-style theorems/definitions (\theorem[...]{...})
    for match in re.finditer(command_pattern, content_no_comments):
        element_type = match.group(1)
        optional_text = match.group(2) if match.group(2) else None  # [optional title]
        content_text = match.group(3).strip()
        line_num = get_line_number(match.start())
        level = hierarchy[element_type]
        label = find_label_after(match.end())
        structure.append((level, element_type, content_text, optional_text, label, line_num, display_filename, match.start(), match.end()))
    
    # Find and process \input{} commands
    for match in re.finditer(input_pattern, content_no_comments):
        input_filename = match.group(1).strip()

        # Add .tex extension if not present
        if not input_filename.endswith('.tex'):
            input_filename += '.tex'

        # Get just the base filename for display
        input_display_name = os.path.basename(input_filename)
        line_num = get_line_number(match.start())

        # Add input command as a special structure element (level 0 for special)
        structure.append((0, 'input', input_display_name, None, None, line_num, display_filename, match.start(), match.end()))

        # Resolve the full path relative to the current file's directory
        full_input_path = os.path.join(base_dir, input_filename)

        # Check if file exists
        if os.path.exists(full_input_path):
            if _warn_info:
                print(f"Processing included file: {full_input_path}", file=sys.stderr)
            # Recursively extract from the input file (resolve nested \input from included file's dir)
            input_result = extract_latex_structure(full_input_path, os.path.dirname(os.path.abspath(full_input_path)), file_contents,
                                                    processed_files, tag_index, file_structures)
            if input_result and input_result[0]:
                structure.extend(input_result[0])
            # file_contents and processed_files are already updated by reference
        else:
            if _warn_errors:
                print(f"Warning: Included file not found: {full_input_path}", file=sys.stderr)

    # Find and process \ExecuteMetaData[file]{tag} commands
    executemeta_pattern = r'\\ExecuteMetaData\[([^\]]*)\]\{([^}]*)\}'
    for match in re.finditer(executemeta_pattern, content_no_comments):
        source_path_raw = match.group(1).strip()
        tag_name = match.group(2).strip()
        line_num = get_line_number(match.start())

        # Resolve source file path relative to current file's directory
        full_source_path = os.path.normpath(os.path.join(base_dir, source_path_raw))
        source_display = os.path.basename(full_source_path)

        if os.path.exists(full_source_path):
            source_abs = os.path.abspath(full_source_path)
            # Parse source file if not yet processed (populates file_contents, tag_index, file_structures)
            if source_abs not in processed_files:
                if _warn_info:
                    print(f"Processing ExecuteMetaData source: {full_source_path}", file=sys.stderr)
                src_result = extract_latex_structure(full_source_path, os.path.dirname(full_source_path),
                                                     file_contents, processed_files, tag_index, file_structures)
                # Store source structure for later lookups
                if src_result and src_result[0]:
                    file_structures[source_display] = src_result[0]

            # Look up the tag in tag_index to get char range
            if tag_index and tag_name in tag_index:
                tag_info = tag_index[tag_name]
                tag_start = tag_info['start_char']
                tag_end = tag_info['end_char']
                tag_file = tag_info['file']

                # Filter source file's structure to elements within the tagged region
                source_elems = file_structures.get(tag_file, [])
                for elem in source_elems:
                    # elem[6] = source_file, elem[7] = char_start, elem[8] = char_end
                    if elem[6] == tag_file and elem[7] >= tag_start and elem[8] <= tag_end and elem[1] != 'input':
                        structure.append(elem)
            else:
                if _warn_errors:
                    print(f"Warning: tag '{tag_name}' not found in {source_display}", file=sys.stderr)
        else:
            if _warn_errors:
                print(f"Warning: ExecuteMetaData source not found: {full_source_path}", file=sys.stderr)

    # Remove duplicates that might occur from overlapping patterns
    structure = list({(level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end)
                     for level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end in structure})

    # Sort by source file and then line number
    structure.sort(key=lambda x: (x[6], x[5]))

    # Store this file's structure for ExecuteMetaData lookups
    if file_structures is not None:
        file_structures[display_filename] = list(structure)

    return structure, file_contents


def extract_refs_from_element(sorted_structure, element_idx, file_contents, label_map, ref_types_filter=None, group_by_type=False, current_section=None, current_chapter=None, current_level=None, all_levels=None, different_level=False, known_labels=None):
    """
    Extract all \ref{...} commands from an element's content.

    For theorems/lemmas/etc, includes content from following proofs/remarks until next numbered result.
    For sections, includes all content until next same-or-higher-level section.

    Args:
        sorted_structure: List of structure elements sorted by file and position
        element_idx: Index of the current element in sorted_structure
        file_contents: Dict mapping source_file to full file content
        label_map: Dict mapping label to (element_type, content, source_file, section_context, chapter_context)
        ref_types_filter: Optional list of element types to include (e.g., ['theorem', 'lemma'])
        group_by_type: If True, group references by element type
        current_section: Current section name for context comparison
        current_chapter: Current chapter name for context comparison
        current_level: The level at which refs are being displayed ('section', 'theorem', etc.)
        all_levels: List of all requested levels (for determining theorem fallback)
        different_level: If True, only show refs from different structural level

    Returns:
        Formatted string of references or dict of references grouped by type
    """
    level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end = sorted_structure[element_idx]

    # Determine the end of this element's content
    element_end = None

    # Numbered result types (standard + custom manuscript environments)
    _numbered = {'theorem', 'lemma', 'proposition', 'corollary', 'definition',
                 'assumption', 'conjecture', 'hypothesis', 'false_conjecture',
                 'openproblem', 'question', 'interpretation', 'problem',
                 'addendum', 'setup'}
    _structural = {'section', 'subsection', 'subsubsection'}

    # For theorems/lemmas/etc, include following proofs/remarks until next numbered result or section
    if element_type in _numbered:
        for i in range(element_idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file != source_file:
                break
            # Stop at next numbered result or section
            if next_type in _numbered | _structural:
                element_end = next_start
                break
    # For sections/subsections, include until next same-or-higher-level section
    elif element_type in ['section', 'subsection', 'subsubsection']:
        for i in range(element_idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file != source_file:
                break
            # Stop at next section of same or higher level
            if next_type in ['section', 'subsection', 'subsubsection'] and next_level <= level:
                element_end = next_start
                break
    else:
        # For other elements, just use their immediate content
        element_end = None
        for i in range(element_idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file == source_file:
                element_end = next_start
                break

    # If no end found, use end of file
    if element_end is None and source_file in file_contents:
        element_end = len(file_contents[source_file])

    # Extract the element content
    if element_end and source_file in file_contents:
        element_content = file_contents[source_file][char_end:element_end]
    else:
        return "" if not group_by_type else {}

    # Find all \ref{...}, \cref{...}, \Cref{...}, \eqref{...} commands
    refs_found = _extract_ref_labels(element_content)

    # Remove duplicates while preserving order
    seen = set()
    unique_refs = []
    for ref in refs_found:
        if ref not in seen:
            seen.add(ref)
            unique_refs.append(ref)

    # Build reference descriptions with type filtering and context
    refs_list = []
    for ref in unique_refs:
        if ref in label_map:
            ref_element_type, ref_content, ref_source_file, ref_section, ref_chapter = label_map[ref]

            # Apply type filter if specified
            if ref_types_filter and ref_element_type.lower() not in [t.lower() for t in ref_types_filter]:
                continue

            # Apply different-level filter if specified
            if different_level and current_level:
                # Determine what level to compare for filtering
                if current_level == 'theorem':
                    # For theorem level, use different section (default) or other specified level
                    compare_level = 'section'  # default
                    if all_levels:
                        # Use most granular non-theorem level if available
                        for level_option in ['subsection', 'section', 'chapter', 'file']:
                            if level_option in all_levels:
                                compare_level = level_option
                                break
                else:
                    # For other levels, compare at that level
                    compare_level = current_level

                # Perform the comparison
                skip_ref = False
                if compare_level == 'subsection':
                    # For subsection comparison, we need to track subsection context
                    # For now, we don't have subsection tracking, so fall back to section
                    if ref_section == current_section:
                        skip_ref = True
                elif compare_level == 'section':
                    if ref_section == current_section:
                        skip_ref = True
                elif compare_level in ['chapter', 'file']:
                    if ref_chapter == current_chapter:
                        skip_ref = True

                if skip_ref:
                    continue

            # Format description with colors
            # Label in muted text, element type and content in appropriate color
            ref_color = Colors.get_color_for_type(ref_element_type)
            desc = f"{Colors.TEXT_MUTED}{ref} ({Colors.RESET}"
            desc += f"{ref_color}{ref_element_type.capitalize()}: {ref_content}{Colors.RESET}"

            # Add context information if from different section/chapter
            # Don't repeat section name if the reference IS to a section
            if ref_element_type != 'section':
                if ref_section and ref_section != current_section:
                    desc += f"{Colors.TEXT_MUTED} from {Colors.RESET}"
                    desc += f"{Colors.SECTION}Section: {ref_section}{Colors.RESET}"
                elif ref_chapter and ref_chapter != current_chapter:
                    desc += f"{Colors.TEXT_MUTED} from {Colors.RESET}"
                    desc += f"{Colors.SECTION}Chapter: {ref_chapter}{Colors.RESET}"

            if ref_source_file != source_file:
                desc += f"{Colors.TEXT_MUTED} in {Colors.RESET}{Colors.FILENAME}{ref_source_file}{Colors.RESET}"

            desc += f"{Colors.TEXT_MUTED}){Colors.RESET}"
            refs_list.append(desc)
        else:
            # Reference not found or out of scope
            if known_labels and ref in known_labels:
                refs_list.append(f"{Colors.TEXT_MUTED}{ref} (out of scope){Colors.RESET}")
            else:
                refs_list.append(f"{Colors.TEXT_MUTED}{ref} (not found){Colors.RESET}")

    if group_by_type:
        # Group by type
        refs_by_type = {}
        for desc in refs_list:
            # Extract type from description
            match = re.search(r'\((\w+):', desc)
            if match:
                type_key = match.group(1).capitalize()
            else:
                type_key = 'Unknown'

            if type_key not in refs_by_type:
                refs_by_type[type_key] = []
            refs_by_type[type_key].append(desc)
        return refs_by_type
    else:
        return refs_list


def format_output(structure, file_contents=None, ref_options=None, filter_config=None, status_map=None, status_filter=None, cite_options=None, label_registry=None, known_labels=None, sizes=False, aux_map=None, label_to_papers=None):
    """
    Format the structure for output with colors, proper indentation, and references.

    Args:
        structure: List of tuples (level, element_type, content, optional_text, label, line_number, source_file, char_start, char_end)
        file_contents: Dict mapping source_file to full file content (for refs)
        ref_options: Dict with keys:
            - 'enabled': bool
            - 'levels': list of levels (e.g., ['section', 'theorem'])
            - 'types_filter': list of types or None
            - 'group_by_type': bool
        filter_config: Dict with keys:
            - 'mode': 'inclusive', 'exclusive', or 'none'
            - 'allowed_types': set of types to show (inclusive mode)
            - 'hidden_types': set of types to hide (exclusive mode)
            - 'hierarchy_handling': 'smart' for hierarchy preservation
        status_map: Dict mapping (file, label) -> status info (optional)
        status_filter: Set of status values to show (None = show all)
        label_registry: Dict mapping label -> metadata (from build_label_registry)

    Returns:
        Formatted string ready for output
    """
    if ref_options is None:
        ref_options = {'enabled': False}

    if filter_config is None:
        filter_config = _default_filter_config()

    if cite_options is None:
        cite_options = {'enabled': False}

    output_lines = []
    current_file = None
    current_chapter = None

    # Build label_map from registry for backward compatibility with extract_refs_from_element
    label_map = {}
    if ref_options.get('enabled') and file_contents:
        if label_registry is None:
            label_registry = build_label_registry(structure)
        for lbl, info in label_registry.items():
            label_map[lbl] = (info['type'], info['content'], info['file'], info['section'], info['chapter'])

    # Sort structure by file and position
    sorted_structure = structure  # expects pre-sorted input

    # Compute visibility map for display filtering
    visibility_map = compute_visibility_map(sorted_structure, filter_config)

    # Track refs for different grouping levels
    file_refs = []
    chapter_refs = []
    document_refs = []

    # Track cites for different grouping levels
    document_cites = []

    # Track current section/chapter context for reference display
    current_section_context = None
    current_chapter_context = None

    for idx, (level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end) in enumerate(sorted_structure):

        # Check visibility - skip elements filtered out by display filtering
        visibility_info = visibility_map[idx]
        if not visibility_info['visible']:
            continue

        # Check status filter if applicable
        if status_map and status_filter and label:
            status_key = (source_file, label)
            if status_key in status_map:
                element_status = status_map[status_key]['STATUS']
                if element_status not in status_filter:
                    continue

        # Handle file transitions
        if source_file != current_file:
            # Output chapter-level refs if needed (chapter = file)
            if current_file and ref_options.get('enabled') and 'chapter' in ref_options.get('levels', []) and chapter_refs:
                output_lines.append("")
                output_lines.extend(format_ref_summary(chapter_refs, ref_options.get('group_by_type', False), "Chapter"))
                output_lines.append(f"{Colors.DIVIDER}{'─' * 80}{Colors.RESET}")
                chapter_refs = []

            # Output file-level refs if needed
            if current_file and ref_options.get('enabled') and 'file' in ref_options.get('levels', []) and file_refs:
                output_lines.append("")
                output_lines.extend(format_ref_summary(file_refs, ref_options.get('group_by_type', False), "File"))
                output_lines.append(f"{Colors.DIVIDER}{'─' * 80}{Colors.RESET}")
                file_refs = []

            # Add visual separator before filename
            if output_lines:
                output_lines.append("")
            output_lines.append("---")
            output_lines.append("")
            output_lines.append(f"{Colors.FILE_HEADER}## {Colors.FILENAME}{source_file}{Colors.RESET}")
            output_lines.append("")
            current_file = source_file
            current_chapter = source_file  # Track chapter name for summaries

        # Update section/chapter context tracking
        if element_type == 'section' and level == 1:
            current_chapter_context = content
            current_section_context = content
            # Note: current_chapter is updated at file transitions for chapter-level ref summaries
        elif element_type == 'section':
            current_section_context = content

        # Format the element line
        color = Colors.get_color_for_type(element_type)

        # Handle input commands specially
        if element_type == 'input':
            indent = "  " * level
            line = f"{indent}{Colors.INPUT}→ Input: {Colors.BOLD}{content}{Colors.RESET} {Colors.LABEL}(line {line_num}){Colors.RESET}"
            output_lines.append(line)
            continue

        # Standard element formatting
        indent = "  " * (level - 1) if level > 0 else ""
        formatted_type = element_type.capitalize()
        if element_type.endswith('*'):
            formatted_type = element_type[:-1].capitalize() + '* [lit]'

        # Build display text
        display_text = None
        if optional_text:
            display_text = optional_text
        elif content and content.lower() != formatted_type.lower():
            display_text = content

        # Get status badge if available
        status_badge = None
        status_value = None
        math_issues_value = None
        status_description = None
        status_affected = None
        if status_map and label:
            status_key = (source_file, label)
            if status_key in status_map:
                status_info = status_map[status_key]
                status_badge = get_status_badge(status_info['STATUS'], status_info['MATH_ISSUES'])
                status_value = status_info['STATUS']
                math_issues_value = status_info['MATH_ISSUES']
                status_description = status_info.get('DESCRIPTION', '').strip()
                status_affected = status_info.get('AFFECTED_ELEMENTS', '').strip()

        if display_text:
            line = f"{indent}{color}{Colors.BOLD}{formatted_type}:{Colors.RESET}{color} {display_text}{Colors.RESET}"
        else:
            line = f"{indent}{color}{Colors.BOLD}{formatted_type}{Colors.RESET}"

        # Add status badge before label
        if status_badge:
            line += f" {status_badge}"

        # Add paper badge
        if label_to_papers and label and label in label_to_papers:
            abbrevs = ','.join(sorted(label_to_papers[label]))
            line += f" {Colors.LABEL}[{abbrevs}]{Colors.RESET}"

        # Add label
        if label:
            line += f" {Colors.LABEL}[{label}]{Colors.RESET}"
            if aux_map and label:
                rendered = format_rendered_ref(label, aux_map)
                if rendered:
                    line += f" {Colors.TEXT_MUTED}\u2192 {rendered}{Colors.RESET}"

        # Add line number (with optional size annotation)
        if sizes and file_contents:
            el_line_end = compute_line_end(sorted_structure, idx, file_contents)
            if el_line_end:
                el_size = el_line_end - line_num + 1
                line += f" {Colors.LABEL}(line {line_num}, {el_size} lines){Colors.RESET}"
            else:
                line += f" {Colors.LABEL}(line {line_num}){Colors.RESET}"
        else:
            line += f" {Colors.LABEL}(line {line_num}){Colors.RESET}"

        output_lines.append(line)

        # Add status details, description and affected elements if available
        if status_value or status_description or status_affected:
            status_indent = indent + "  "
            if status_value:
                output_lines.append(f"{status_indent}{Colors.TEXT_MUTED}→ Status: {status_value}{Colors.RESET}")
            if math_issues_value:
                output_lines.append(f"{status_indent}{Colors.TEXT_MUTED}→ Math issues: {math_issues_value}{Colors.RESET}")
            # Show review tracking info if available
            last_reviewed = status_info.get('LAST_REVIEWED', '').strip() if status_info else ''
            review_depth = status_info.get('REVIEW_DEPTH', '').strip() if status_info else ''
            if last_reviewed or review_depth:
                review_parts = []
                if last_reviewed:
                    review_parts.append(last_reviewed)
                if review_depth:
                    review_parts.append(review_depth)
                output_lines.append(f"{status_indent}{Colors.TEXT_MUTED}→ Last reviewed: {', '.join(review_parts)}{Colors.RESET}")
            if status_description:
                output_lines.append(f"{status_indent}{Colors.TEXT_MUTED}→ {status_description}{Colors.RESET}")
            if status_affected:
                output_lines.append(f"{status_indent}{Colors.TEXT_MUTED}→ Affects: {status_affected}{Colors.RESET}")

        # Handle element-level refs (sections, subsections, or theorems)
        if ref_options.get('enabled'):
            show_refs_here = False
            current_display_level = None
            levels = ref_options.get('levels', [])

            if 'section' in levels and element_type == 'section':
                show_refs_here = True
                current_display_level = 'section'
            elif 'subsection' in levels and element_type == 'subsection':
                show_refs_here = True
                current_display_level = 'subsection'
            elif 'theorem' in levels and element_type in ['theorem', 'lemma', 'proposition', 'corollary', 'definition']:
                show_refs_here = True
                current_display_level = 'theorem'

            if show_refs_here:
                refs = extract_refs_from_element(sorted_structure, idx, file_contents, label_map,
                                                 ref_options.get('types_filter'),
                                                 ref_options.get('group_by_type', False),
                                                 current_section_context, current_chapter_context,
                                                 current_display_level, levels, ref_options.get('different_level', False),
                                                 known_labels=known_labels)
                if refs:
                    output_lines.append("")
                    if ref_options.get('group_by_type'):
                        for type_name, type_refs in refs.items():
                            output_lines.append(f"{indent}  {Colors.REF}→ {type_name}:{Colors.RESET}")
                            for ref_desc in type_refs:
                                output_lines.append(f"{indent}    {ref_desc}")
                    else:
                        output_lines.append(f"{indent}  {Colors.REF}→ References:{Colors.RESET}")
                        for ref_desc in refs:
                            output_lines.append(f"{indent}    {ref_desc}")
                    output_lines.append("")

            # Accumulate refs for higher-level summaries
            # Only extract from sections (not subsections/theorems) to avoid duplicate extraction
            levels = ref_options.get('levels', [])
            if any(l in levels for l in ['chapter', 'file', 'document']) and element_type == 'section':
                refs = extract_refs_from_element(sorted_structure, idx, file_contents, label_map,
                                                 ref_options.get('types_filter'),
                                                 ref_options.get('group_by_type', False),
                                                 current_section_context, current_chapter_context,
                                                 None, levels, ref_options.get('different_level', False),
                                                 known_labels=known_labels)
                if isinstance(refs, dict):
                    for type_name, type_refs in refs.items():
                        if 'chapter' in levels or 'file' in levels:
                            # chapter and file are equivalent (one chapter per file)
                            chapter_refs.extend(type_refs)
                            file_refs.extend(type_refs)
                        if 'document' in levels:
                            document_refs.extend(type_refs)
                elif refs:
                    # refs is now a list, not a semicolon-separated string
                    if 'chapter' in levels or 'file' in levels:
                        # chapter and file are equivalent (one chapter per file)
                        chapter_refs.extend(refs)
                        file_refs.extend(refs)
                    if 'document' in levels:
                        document_refs.extend(refs)

        # Handle element-level citations
        if cite_options.get('enabled'):
            show_cites_here = False
            cite_levels = cite_options.get('levels', [])

            if 'section' in cite_levels and element_type == 'section':
                show_cites_here = True
            elif 'subsection' in cite_levels and element_type == 'subsection':
                show_cites_here = True
            elif 'theorem' in cite_levels and element_type in ['theorem', 'lemma', 'proposition', 'corollary', 'definition']:
                show_cites_here = True

            if show_cites_here:
                cites = extract_cites_from_element(sorted_structure, idx, file_contents)
                if cites:
                    cite_map = cite_options.get('cite_map', {})
                    cite_display = []
                    for key in cites:
                        if cite_map and key in cite_map:
                            cite_display.append(f"{Colors.TEXT_MUTED}{key}{Colors.RESET} ({cite_map[key]})")
                        else:
                            cite_display.append(f"{Colors.TEXT_MUTED}{key}{Colors.RESET}")
                    output_lines.append(f"{indent}  {Colors.REF}→ Cites:{Colors.RESET} {', '.join(cite_display)}")

            # Accumulate for document-level summary
            if 'document' in cite_levels and element_type == 'section':
                cites = extract_cites_from_element(sorted_structure, idx, file_contents)
                document_cites.extend(cites)

    # Output final summaries
    if ref_options.get('enabled'):
        levels = ref_options.get('levels', [])
        if 'chapter' in levels and chapter_refs:
            output_lines.append("")
            output_lines.extend(format_ref_summary(chapter_refs, ref_options.get('group_by_type', False), "Chapter"))
            output_lines.append(f"{Colors.DIVIDER}{'─' * 80}{Colors.RESET}")

        if 'file' in levels and file_refs:
            output_lines.append("")
            output_lines.extend(format_ref_summary(file_refs, ref_options.get('group_by_type', False), "File"))
            output_lines.append(f"{Colors.DIVIDER}{'─' * 80}{Colors.RESET}")

        if 'document' in levels and document_refs:
            output_lines.append("")
            output_lines.extend(format_ref_summary(document_refs, ref_options.get('group_by_type', False), "Document"))
            output_lines.append(f"{Colors.DIVIDER}{'─' * 80}{Colors.RESET}")

    # Document-level citation summary
    if cite_options.get('enabled') and 'document' in cite_options.get('levels', []) and document_cites:
        # Deduplicate
        seen = set()
        unique_cites = []
        for c in document_cites:
            if c not in seen:
                seen.add(c)
                unique_cites.append(c)
        cite_map = cite_options.get('cite_map', {})
        output_lines.append("")
        output_lines.append(f"{Colors.BOLD}=== Document Citations ({len(unique_cites)}) ==={Colors.RESET}")
        for key in unique_cites:
            if cite_map and key in cite_map:
                output_lines.append(f"  {Colors.TEXT_MUTED}{key}{Colors.RESET} — {cite_map[key]}")
            else:
                output_lines.append(f"  {Colors.TEXT_MUTED}{key}{Colors.RESET}")
        output_lines.append(f"{Colors.DIVIDER}{'─' * 80}{Colors.RESET}")

    return "\n".join(output_lines)


def format_ref_summary(refs_list, group_by_type, summary_title):
    """Format a reference summary with optional grouping"""
    lines = []
    lines.append(f"{Colors.BOLD}=== {summary_title} References ==={Colors.RESET}")

    if group_by_type:
        # Group by extracting type from description
        by_type = {}
        for ref in refs_list:
            # Extract type from "(Type: ...)" pattern
            match = re.search(r'\((\w+):', ref)
            if match:
                ref_type = match.group(1)
                if ref_type not in by_type:
                    by_type[ref_type] = []
                by_type[ref_type].append(ref)
            else:
                if 'Other' not in by_type:
                    by_type['Other'] = []
                by_type['Other'].append(ref)

        for type_name in sorted(by_type.keys()):
            lines.append(f"{Colors.REF}→ {type_name}:{Colors.RESET}")
            for ref in by_type[type_name]:
                lines.append(f"  {ref}")
    else:
        lines.append(f"{Colors.REF}→ All references:{Colors.RESET}")
        # Remove duplicates while preserving order
        seen = set()
        for ref in refs_list:
            if ref not in seen:
                seen.add(ref)
                lines.append(f"  {ref}")

    return lines


def get_element_text_range(sorted_structure, element_idx, file_contents):
    """
    Get the text range for an element's content.

    For theorems/lemmas/etc, includes content up to next numbered result or section.
    For sections, includes content up to next same-or-higher-level section.
    For other elements, includes content up to next element.

    Returns (text, char_start, char_end) or (None, None, None) if not available.
    """
    level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end = sorted_structure[element_idx]

    element_end = None

    # Numbered result types (standard + custom manuscript environments)
    _numbered_types = {'theorem', 'lemma', 'proposition', 'corollary', 'definition',
                       'assumption', 'conjecture', 'hypothesis', 'false_conjecture',
                       'openproblem', 'question', 'interpretation', 'problem',
                       'addendum', 'setup'}
    _structural_types = {'section', 'subsection', 'subsubsection'}

    if element_type in _numbered_types:
        for i in range(element_idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file != source_file:
                break
            if next_type in _numbered_types | _structural_types:
                element_end = next_start
                break
    elif element_type in _structural_types:
        for i in range(element_idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file != source_file:
                break
            if next_type in ['section', 'subsection', 'subsubsection'] and next_level <= level:
                element_end = next_start
                break
    else:
        for i in range(element_idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file == source_file:
                element_end = next_start
                break

    if element_end is None and source_file in file_contents:
        element_end = len(file_contents[source_file])

    if element_end and source_file in file_contents:
        return file_contents[source_file][char_end:element_end], char_end, element_end
    return None, None, None


def extract_cites_from_text(text):
    """
    Extract citation keys from a LaTeX text string.

    Parses \\cite{key}, \\cite[opt]{key}, \\cite{key1,key2,...}.
    Deduplicates while preserving first-occurrence order.
    Does NOT match \\nocite.

    Returns list of unique citation keys.
    """
    # Match \cite with optional argument, but not \nocite
    cite_pattern = r'(?<!\\no)\\cite(?:\[[^\]]*\])?\{([^}]*)\}'
    all_keys = []
    for match in re.finditer(cite_pattern, text):
        keys_str = match.group(1)
        for key in keys_str.split(','):
            key = key.strip()
            if key:
                all_keys.append(key)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for key in all_keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def extract_cites_from_element(sorted_structure, element_idx, file_contents):
    """
    Extract citation keys from an element's content range.

    Uses the same text range logic as extract_refs_from_element.

    Returns list of unique citation keys.
    """
    text, _, _ = get_element_text_range(sorted_structure, element_idx, file_contents)
    if text is None:
        return []
    return extract_cites_from_text(text)


def parse_bibliography(bib_text):
    r"""
    Parse bibliography.tex content and build a cite_map.

    Looks for \bibitem{key} or \bibitem[display]{key} entries.
    Extracts a short display label from the entry text (first author + year).

    Returns dict mapping key -> display string.
    """
    cite_map = {}
    # Match \bibitem with optional display text and required key
    bibitem_pattern = r'\\bibitem(?:\[([^\]]*)\])?\{([^}]+)\}\s*([^\n\\]+)?'
    for match in re.finditer(bibitem_pattern, bib_text):
        display = match.group(1)  # optional [display] text
        key = match.group(2)
        entry_start = match.group(3)  # beginning of the entry text

        if display:
            cite_map[key] = display
        elif entry_start:
            # Try to extract "Author (Year)" or "Author, Year" from the entry
            # Common patterns: "A. Author, Title..., Journal, Year" or "Author (Year)."
            entry_text = entry_start.strip()
            # Try to find year in entry
            year_match = re.search(r'\((\d{4})\)', entry_text)
            if not year_match:
                year_match = re.search(r'(\d{4})', entry_text)

            # Extract first author (up to first comma or period)
            author_match = re.match(r'([^,\.]+)', entry_text)
            author = author_match.group(1).strip() if author_match else entry_text[:30]
            year = year_match.group(1) if year_match else ''

            if year:
                cite_map[key] = f"{author} ({year})"
            else:
                cite_map[key] = author
        else:
            cite_map[key] = key  # fallback to key itself

    return cite_map


def parse_aux_file(path: str) -> dict:
    """Parse a LaTeX .aux file into {label: (number, page, title, env_type)}.
    Results are cached by absolute path."""
    abs_path = os.path.abspath(path)
    if abs_path in _AUX_CACHE:
        return _AUX_CACHE[abs_path]
    result = {}
    try:
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        _AUX_CACHE[abs_path] = result
        return result
    # First pass: base newlabel entries
    base_re = re.compile(
        r'\\newlabel\{([^@}]+)\}\{\{([^}]*)\}\{([^}]*)\}\{((?:[^{}]|\{[^{}]*\})*)\}'
    )
    for m in base_re.finditer(text):
        label, number, page, title = m.group(1), m.group(2), m.group(3), m.group(4)
        result[label] = (number, page, title, '')
    # Second pass: @cref entries to extract env_type
    cref_re = re.compile(r'\\newlabel\{([^}]+)@cref\}\{\{\[([^\]]+)\]')
    for m in cref_re.finditer(text):
        base_label = m.group(1)
        env_type = m.group(2)
        if base_label in result:
            old = result[base_label]
            result[base_label] = (old[0], old[1], old[2], env_type)
    _AUX_CACHE[abs_path] = result
    return result


def format_rendered_ref(label: str, aux_map: dict):
    """Return 'Theorem I.3.2 (p.14)' or None if label absent from aux_map."""
    if label not in aux_map:
        return None
    number, page, title, env_type = aux_map[label]
    type_display_map = {
        'theorem': 'Theorem',
        'lemma': 'Lemma',
        'definition': 'Definition',
        'section': 'Section',
        'subsection': 'Section',
        'subsubsection': 'Section',
        'corollary': 'Corollary',
        'proposition': 'Proposition',
        'remark': 'Remark',
        'example': 'Example',
        'assumption': 'Assumption',
        'conjecture': 'Conjecture',
        'hypothesis': 'Hypothesis',
        'equation': 'Equation',
        'figure': 'Figure',
        'table': 'Table',
    }
    if env_type:
        type_display = type_display_map.get(env_type.lower(), env_type.capitalize())
        return f"{type_display} {number} (p.{page})"
    else:
        return f"{number} (p.{page})"


def _resolve_aux_path(aux_file_arg, input_files) -> str:
    """Resolve .aux file path with priority: explicit --aux-file arg > same-stem > None."""
    if aux_file_arg:
        return aux_file_arg if os.path.exists(aux_file_arg) else None
    if input_files:
        first = input_files[0]
        stem_aux = os.path.splitext(first)[0] + '.aux'
        if os.path.exists(stem_aux):
            return stem_aux
    return None


def build_label_registry(structure):
    """
    Build a centralised label-to-element mapping from parsed structure.

    Walks the structure (sorted by file and position), tracks current
    section/chapter context, and returns a dict mapping each label to its
    metadata.

    Returns:
        dict mapping label -> {
            'type': element_type,
            'content': display text,
            'file': source filename,
            'line': line number,
            'char_start': character offset start,
            'char_end': character offset end,
            'section': nearest parent section label or content,
            'chapter': source filename (one chapter per file),
            'level': hierarchy level (1-4),
        }
    """
    registry = {}
    current_section_context = None
    current_chapter_context = None

    sorted_struct = structure  # expects pre-sorted input

    for level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end in sorted_struct:
        # Update context tracking
        if element_type == 'section' and level == 1:
            current_chapter_context = content
            current_section_context = content
        elif element_type == 'section':
            current_section_context = content

        if label:
            registry[label] = {
                'type': element_type,
                'content': content,
                'file': source_file,
                'line': line_num,
                'char_start': char_start,
                'char_end': char_end,
                'section': current_section_context,
                'chapter': current_chapter_context,
                'level': level,
            }

    return registry


def build_forward_ref_graph(structure, file_contents, label_registry):
    """Returns {from_label: set(to_labels)} for all labelled elements with refs."""
    graph = {}
    sorted_struct = structure  # expects pre-sorted input
    for idx, elem in enumerate(sorted_struct):
        if elem[1] == 'input':
            continue
        label = elem[4]
        if not label:
            continue
        text, _, _ = get_element_text_range(sorted_struct, idx, file_contents)
        if text:
            targets = _extract_ref_labels(text)
            refs = {t for t in targets if t in label_registry and t != label}
            if refs or label in graph:
                existing = graph.get(label, set())
                graph[label] = existing | refs
    return graph


def find_duplicate_labels(structure):
    """
    Find labels that appear more than once (same file or across files).

    Returns list of dicts with 'label' and 'locations' keys.
    """
    label_locations = {}  # label -> list of (file, line)
    for elem in structure:
        label = elem[4]
        if label:
            label_locations.setdefault(label, []).append((elem[6], elem[5]))

    duplicates = []
    for label, locations in label_locations.items():
        if len(locations) > 1:
            duplicates.append({
                'label': label,
                'locations': [{'file': f, 'line': l} for f, l in locations]
            })

    return duplicates


def _char_to_line(file_contents, source_file, char_pos):
    """Convert character position to line number."""
    if source_file not in file_contents:
        return None
    return file_contents[source_file][:char_pos].count('\n') + 1


def _find_environment_end(file_contents, source_file, element_type, char_start):
    r"""Find the matching \end{...} for an environment starting at char_start,
    correctly handling nested environments of the same type."""
    if source_file not in file_contents:
        return None

    base_type = element_type.rstrip('*')

    if base_type not in _active_environments:
        return None

    content = file_contents[source_file]
    begin_pattern = re.compile(r'\\begin\{' + re.escape(base_type) + r'[\}\[]')
    end_pattern = re.compile(r'\\end\{' + re.escape(base_type) + r'\}')

    search_start = char_start
    first_begin = begin_pattern.search(content[search_start:])
    if first_begin:
        search_start += first_begin.end()

    depth = 1
    pos = search_start
    while pos < len(content) and depth > 0:
        next_begin = begin_pattern.search(content[pos:])
        next_end = end_pattern.search(content[pos:])

        if next_end is None:
            break

        begin_pos = pos + next_begin.start() if next_begin else len(content)
        end_pos = pos + next_end.start()

        if begin_pos < end_pos:
            depth += 1
            pos = pos + next_begin.end()
        else:
            depth -= 1
            if depth == 0:
                return pos + next_end.end()
            pos = pos + next_end.end()

    return None


def compute_line_end(sorted_structure, idx, file_contents):
    """
    Compute line_end for a single element in the structure.

    For environments: finds the matching \\end{...}.
    For sections: finds the next same-or-higher-level section, or end of file.
    For other elements: uses the next element's start position.

    Returns line number or None.
    """
    level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end = sorted_structure[idx]

    if element_type == 'input':
        return None

    line_end = None
    base_type = element_type.rstrip('*')

    if base_type in _active_environments:
        end_char = _find_environment_end(file_contents, source_file, element_type, char_start)
        if end_char:
            line_end = _char_to_line(file_contents, source_file, end_char)
    elif element_type in ('section', 'subsection', 'subsubsection'):
        # For sections, find the next section at the same or higher level
        for i in range(idx + 1, len(sorted_structure)):
            next_level, next_type, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file != source_file:
                break
            if next_type in ('section', 'subsection', 'subsubsection') and next_level <= level:
                line_end = _char_to_line(file_contents, source_file, next_start) - 1
                break
        # If no same-or-higher section follows, use end of file
        if not line_end and source_file in file_contents:
            line_end = file_contents[source_file].count('\n') + 1

    # For non-structural elements without line_end, use next element's start
    if not line_end and element_type not in ('section', 'subsection', 'subsubsection'):
        for i in range(idx + 1, len(sorted_structure)):
            _, _, _, _, _, _, next_file, next_start, _ = sorted_structure[i]
            if next_file != source_file:
                break
            if next_start > char_start:
                line_end = _char_to_line(file_contents, source_file, next_start) - 1
                break

    # Final fallback: end of file
    if not line_end and source_file in file_contents:
        line_end = file_contents[source_file].count('\n') + 1

    return line_end


def apply_scope_filter(structure, scope_label, file_contents):
    """
    Filter structure to only elements within the scope of a labelled section.

    Finds the element with the given label, determines its extent (from its
    start to the next same-or-higher-level section), and returns only elements
    within that range.

    Returns filtered structure list.  If *scope_label* matches an existing
    label exactly, that element is used (backward-compatible).  Otherwise a
    case-insensitive substring search is run against titles, optional text,
    and labels.  A unique match is used; multiple matches print an error and
    return an empty list; no matches print a warning and return the original
    structure.
    """
    # Sort by file and position
    sorted_struct = sorted(structure, key=_SORT_KEY)

    # Step 1: exact label match
    scope_idx = None
    for idx, elem in enumerate(sorted_struct):
        if elem[4] == scope_label:
            scope_idx = idx
            break

    # Step 2: fuzzy title/label substring match
    if scope_idx is None:
        pattern = scope_label.lower()
        matches = []
        for idx, elem in enumerate(sorted_struct):
            title = (elem[2] or '').lower()
            optional = (elem[3] or '').lower()
            label = (elem[4] or '').lower()
            if pattern in title or pattern in optional or pattern in label:
                matches.append(idx)

        if len(matches) == 1:
            scope_idx = matches[0]
            matched = sorted_struct[scope_idx]
            if _warn_info:
                label_str = f" [{matched[4]}]" if matched[4] else ""
                print(f"Matched: {matched[1]}: {matched[2]}{label_str} ({matched[6]}:{matched[5]})", file=sys.stderr)
        elif len(matches) > 1:
            if _warn_errors:
                print(f"Error: '{scope_label}' matches {len(matches)} elements:", file=sys.stderr)
                for idx in matches:
                    elem = sorted_struct[idx]
                    label_str = f" [{elem[4]}]" if elem[4] else ""
                    print(f"  {elem[1]}: {elem[2]}{label_str} ({elem[6]}:{elem[5]})", file=sys.stderr)
                print("Use a more specific term or an exact label.", file=sys.stderr)
            return []

    if scope_idx is None:
        if _warn_errors:
            print(f"Warning: '{scope_label}' not found as label or title", file=sys.stderr)
        return structure

    scope_level = sorted_struct[scope_idx][0]
    scope_type = sorted_struct[scope_idx][1]
    scope_file = sorted_struct[scope_idx][6]
    scope_start = sorted_struct[scope_idx][7]

    # Find extent end
    scope_end = len(file_contents.get(scope_file, ''))
    if scope_type in ('section', 'subsection', 'subsubsection'):
        for i in range(scope_idx + 1, len(sorted_struct)):
            next_level = sorted_struct[i][0]
            next_type = sorted_struct[i][1]
            next_file = sorted_struct[i][6]
            next_start = sorted_struct[i][7]
            if next_file != scope_file:
                break
            if next_type in ('section', 'subsection', 'subsubsection') and next_level <= scope_level:
                scope_end = next_start
                break

    # Filter to elements within scope
    return [elem for elem in sorted_struct
            if elem[6] == scope_file and elem[7] >= scope_start and elem[7] < scope_end]


def apply_depth_filter(structure, max_depth):
    """
    Filter structural elements by depth relative to the first element.

    Only affects structural elements (section/subsection/subsubsection).
    Content elements (theorems, proofs, etc.) are always kept.

    max_depth=0 means only the scoped element itself.
    max_depth=1 means one level below (e.g., subsections within a section).
    """
    STRUCTURAL = {'section', 'subsection', 'subsubsection'}
    if not structure:
        return structure
    base_level = structure[0][0]
    return [elem for elem in structure
            if elem[1] not in STRUCTURAL or (elem[0] - base_level) <= max_depth]


def apply_line_range_filter(structure, line_range_str):
    """
    Filter elements to those within a line range.

    Format: "START:END", ":END" (from start), "START:" (to end).
    """
    parts = line_range_str.split(':')
    start = int(parts[0]) if parts[0] else 1
    end = int(parts[1]) if len(parts) > 1 and parts[1] else float('inf')
    return [elem for elem in structure if start <= elem[5] <= end]


def get_paper_labels(manifest, paper_name):
    """Get set of all labels tagged for a named paper."""
    labels = set()
    paper = manifest.get(paper_name)
    if not paper:
        return labels
    for source in paper.get('sources', []):
        for tag in source.get('tags', []):
            labels.add(tag)
    return labels


def apply_paper_filter(structure, paper_labels):
    """
    Filter structure to elements tagged for a paper, preserving section hierarchy.

    Keeps elements whose label is in paper_labels, plus ancestor section/subsection
    elements for context.
    """
    STRUCTURAL = {'section', 'subsection', 'subsubsection'}

    sorted_struct = sorted(structure, key=_SORT_KEY)

    # First pass: find which structural parents have matching descendants
    # Track the most recent section/subsection/subsubsection by file
    needed_indices = set()

    # Forward scan to find matching elements
    for idx, elem in enumerate(sorted_struct):
        if elem[4] in paper_labels:
            needed_indices.add(idx)

    if not needed_indices:
        return []

    # Second pass: find ancestor structural elements for each needed element
    result_indices = set(needed_indices)
    for idx in needed_indices:
        elem = sorted_struct[idx]
        elem_file = elem[6]
        elem_pos = elem[7]
        elem_level = elem[0]

        # Walk backward to find ancestor sections
        for i in range(idx - 1, -1, -1):
            ancestor = sorted_struct[i]
            if ancestor[6] != elem_file:
                break
            if ancestor[1] in STRUCTURAL and ancestor[0] < elem_level:
                result_indices.add(i)
                # Keep searching for higher-level ancestors
                elem_level = ancestor[0]

    return [sorted_struct[i] for i in sorted(result_indices)]


def validate_paper(paper_name, manifest, tag_index, structure, file_contents, label_registry):
    """
    Validate a paper's manifest against the actual source files.

    Returns a structured report dict.
    """
    paper = manifest.get(paper_name)
    if not paper:
        return {'error': f"Paper '{paper_name}' not found in manifest"}

    paper_tags = []
    for source in paper.get('sources', []):
        for tag in source.get('tags', []):
            paper_tags.append((tag, source.get('file', '')))

    paper_labels = get_paper_labels(manifest, paper_name)

    # 1. Check tag existence
    missing_tags = []
    found_tags = []
    for tag, expected_file in paper_tags:
        if tag in tag_index:
            found_tags.append(tag)
        else:
            missing_tags.append((tag, expected_file))

    # 2. Find refs within tagged regions
    internal_refs = []
    external_refs = []
    unresolved_refs = []
    ref_re = re.compile(r'\\(?:ref|cref|Cref|eqref)\{([^}]*)\}')

    for tag in found_tags:
        tag_info = tag_index[tag]
        tag_file = tag_info['file']
        tag_content = file_contents.get(tag_file, '')
        # Use raw char range from tag_info
        region_start = tag_info['start_char']
        region_end = tag_info['end_char']
        # Search for refs in the file content around the tag region
        # We need to search the original content, but file_contents has comments stripped
        # So use a broader search on file_contents within approximate range
        # Actually, labels in \ref are not in comments, so file_contents works
        region_text = tag_content[region_start:region_end] if region_end <= len(tag_content) else ''
        for ref_match in ref_re.finditer(region_text):
            ref_label = ref_match.group(1)
            if ref_label in paper_labels:
                internal_refs.append((ref_label, tag))
            elif ref_label in label_registry:
                external_refs.append((ref_label, tag, label_registry[ref_label].get('file', '')))
            else:
                unresolved_refs.append((ref_label, tag))

    # 3. Find suggested additions (referenced by >=2 tagged results but not tagged)
    external_counts = {}
    for ref_label, referencing_tag, ref_file in external_refs:
        external_counts.setdefault(ref_label, set()).add(referencing_tag)
    suggested = [(label, refs) for label, refs in external_counts.items() if len(refs) >= 2]

    # 4. Find orphan tags (in source files but not in any paper)
    all_manifest_tags = set()
    for p_name, p_info in manifest.items():
        for source in p_info.get('sources', []):
            for tag in source.get('tags', []):
                all_manifest_tags.add(tag)
    orphan_tags = [(tag, info['file']) for tag, info in tag_index.items() if tag not in all_manifest_tags]

    # Determine status
    if missing_tags or unresolved_refs:
        status = 'FAIL'
    elif external_refs:
        status = 'WARN'
    else:
        status = 'PASS'

    return {
        'paper_name': paper_name,
        'abbrev': paper.get('abbrev', ''),
        'total_tags': len(paper_tags),
        'found_tags': found_tags,
        'missing_tags': missing_tags,
        'internal_refs': internal_refs,
        'external_refs': external_refs,
        'unresolved_refs': unresolved_refs,
        'suggested': suggested,
        'orphan_tags': orphan_tags,
        'status': status,
    }


def format_paper_check(report, compact=False):
    """Format paper validation report."""
    if 'error' in report:
        return report['error']

    name = report['paper_name']

    if compact:
        lines = []
        lines.append(f"PAPER_CHECK\t{name}\tSTATUS\t{report['status']}")
        lines.append(f"PAPER_CHECK\t{name}\tTAGS_FOUND\t{len(report['found_tags'])}/{report['total_tags']}")
        for tag, expected_file in report['missing_tags']:
            lines.append(f"PAPER_CHECK\t{name}\tMISSING_TAG\t{tag}\t{expected_file}")
        for ref_label, src_tag, ref_file in report['external_refs']:
            lines.append(f"PAPER_CHECK\t{name}\tEXTERNAL_REF\t{ref_label}\t{ref_file}\t{src_tag}")
        for ref_label, src_tag in report['unresolved_refs']:
            lines.append(f"PAPER_CHECK\t{name}\tUNRESOLVED_REF\t{ref_label}\t{src_tag}")
        for tag, tag_file in report['orphan_tags']:
            lines.append(f"PAPER_CHECK\t{name}\tORPHAN_TAG\t{tag}\t{tag_file}")
        for label, refs in report['suggested']:
            lines.append(f"PAPER_CHECK\t{name}\tSUGGESTED\t{label}\t{','.join(sorted(refs))}")
        return '\n'.join(lines)

    # Terminal mode
    lines = []
    lines.append(f"{Colors.BOLD}Paper: {name} ({report['total_tags']} tags){Colors.RESET}")
    lines.append("")

    # Tag existence
    if not report['missing_tags']:
        lines.append(f"  \u2713 All {len(report['found_tags'])} tags found in source files")
    else:
        lines.append(f"  \u2717 {len(report['missing_tags'])} tags missing from source files:")
        for tag, expected_file in report['missing_tags']:
            lines.append(f"    {tag} (expected in {expected_file})")

    # Internal refs
    if report['internal_refs']:
        lines.append(f"  \u2713 {len(report['internal_refs'])} internal references resolved")

    # External refs
    if report['external_refs']:
        lines.append("")
        lines.append(f"  \u26a0 {len(report['external_refs'])} external references (need xr or manual resolution):")
        seen = set()
        for ref_label, src_tag, ref_file in report['external_refs']:
            key = (ref_label, src_tag)
            if key not in seen:
                seen.add(key)
                lines.append(f"    {ref_label} ({ref_file}) \u2190 referenced by {src_tag}")

    # Unresolved refs
    if report['unresolved_refs']:
        lines.append("")
        lines.append(f"  \u2717 {len(report['unresolved_refs'])} unresolved references:")
        for ref_label, src_tag in report['unresolved_refs']:
            lines.append(f"    {ref_label} \u2190 referenced by {src_tag}")

    # Suggested additions
    if report['suggested']:
        lines.append("")
        lines.append(f"  \u2139 {len(report['suggested'])} suggested additions (referenced by \u22652 tagged results):")
        for label, refs in sorted(report['suggested'], key=lambda x: -len(x[1])):
            lines.append(f"    {label} \u2190 referenced by {', '.join(sorted(refs))}")

    # Orphan tags
    if report['orphan_tags']:
        lines.append("")
        lines.append(f"  \u2139 {len(report['orphan_tags'])} orphan tags (in source files, not in any paper):")
        for tag, tag_file in report['orphan_tags']:
            lines.append(f"    {tag} ({tag_file})")

    lines.append("")
    lines.append(f"  Status: {Colors.BOLD}{report['status']}{Colors.RESET}")

    return '\n'.join(lines)


def warn_unlabelled_sections(structure):
    """
    Emit warnings for sections/subsections/subsubsections without labels.
    """
    STRUCTURAL = {'section', 'subsection', 'subsubsection'}
    for elem in structure:
        level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end = elem
        if element_type in STRUCTURAL and not label:
            print(f"Warning: {element_type} '{content}' at {source_file}:{line_num} has no label",
                  file=sys.stderr)


def _default_filter_config():
    """Return a permissive filter config that shows everything."""
    return {
        'mode': 'orthogonal',
        'structural': {
            'has_whitelist': False,
            'allowed': set(),
            'hidden': set(),
        },
        'content': {
            'has_whitelist': False,
            'allowed': set(),
            'hidden': set(),
        },
        'hierarchy_handling': 'smart'
    }


def build_filter_config(args):
    """
    Build filter configuration using an orthogonal two-dimensional model.

    Two independent dimensions:
      - Structural: which section levels to show (section/subsection/subsubsection)
      - Content: which theorem/remark/proof types to show

    Each dimension has:
      1. An optional whitelist (from --only-* flags)
      2. A blacklist (from --hide-* flags), applied subtractively after the whitelist

    Cascade rules for structural --hide-*:
      - --hide-sections cascades to subsection + subsubsection
      - --hide-subsections cascades to subsubsection
      - --hide-subsubsections does not cascade
    """

    # Element type groups
    NUMBERED_RESULTS = {'theorem', 'lemma', 'proposition', 'corollary', 'definition'}
    NON_NUMBERED_RESULTS = {'theorem*', 'lemma*', 'proposition*', 'corollary*', 'definition*', 'example*', 'remark*', 'note*', 'claim*', 'proof*'}
    SUPPORTING = {'proof', 'remark', 'example', 'note', 'claim'}
    STRUCTURAL = {'section', 'subsection', 'subsubsection'}
    SPECULATIVE = {'assumption', 'conjecture', 'hypothesis', 'question',
                   'problem', 'openproblem', 'false_conjecture'}

    # --- Structural dimension ---
    structural_only = set()
    if args.only_sections:
        structural_only.add('section')
    if args.only_subsections:
        structural_only.add('subsection')
    if args.only_subsubsections:
        structural_only.add('subsubsection')
    if args.only_structural:
        structural_only = STRUCTURAL.copy()

    structural_hidden = set()
    if args.hide_sections:
        structural_hidden |= {'section', 'subsection', 'subsubsection'}  # cascade
    if args.hide_subsections:
        structural_hidden |= {'subsection', 'subsubsection'}  # cascade
    if args.hide_subsubsections:
        structural_hidden.add('subsubsection')
    if args.hide_structural:
        structural_hidden |= STRUCTURAL

    has_structural_whitelist = bool(structural_only)

    # Apply blacklist subtractively from whitelist
    if has_structural_whitelist:
        structural_only -= structural_hidden

    # --- Content dimension ---
    content_only = set()
    if args.only_numbered_results:
        content_only |= NUMBERED_RESULTS
    if args.only_non_numbered_results:
        content_only |= NON_NUMBERED_RESULTS
    if args.only_supporting:
        content_only |= SUPPORTING
    # Individual --only-* flags
    if args.only_theorems:
        content_only.add('theorem')
    if args.only_lemmas:
        content_only.add('lemma')
    if args.only_propositions:
        content_only.add('proposition')
    if args.only_corollaries:
        content_only.add('corollary')
    if args.only_definitions:
        content_only.add('definition')
    if args.only_proofs:
        content_only.add('proof')
    if args.only_remarks:
        content_only.add('remark')
    if args.only_examples:
        content_only.add('example')
    if args.only_notes:
        content_only.add('note')
    if args.only_claims:
        content_only.add('claim')
    if args.only_speculative:
        content_only |= SPECULATIVE

    # If --show-non-numbered-results in whitelist mode, add starred types
    if args.show_non_numbered_results and content_only:
        content_only |= NON_NUMBERED_RESULTS

    content_hidden = set()
    # Default: hide starred environments unless explicitly shown or whitelisted
    if not args.show_non_numbered_results:
        content_hidden |= NON_NUMBERED_RESULTS
    # --only-structural means "show ONLY structural" — hide all content
    # (unless a content whitelist is also active, e.g. --only-structural --only-theorems)
    if args.only_structural and not content_only:
        content_hidden |= NUMBERED_RESULTS | SUPPORTING
    # Grouped --hide-*
    if args.hide_numbered_results:
        content_hidden |= NUMBERED_RESULTS
    if args.hide_supporting:
        content_hidden |= SUPPORTING
    # Individual --hide-*
    if args.hide_theorems:
        content_hidden.add('theorem')
    if args.hide_lemmas:
        content_hidden.add('lemma')
    if args.hide_propositions:
        content_hidden.add('proposition')
    if args.hide_corollaries:
        content_hidden.add('corollary')
    if args.hide_definitions:
        content_hidden.add('definition')
    if args.hide_proofs:
        content_hidden.add('proof')
    if args.hide_remarks:
        content_hidden.add('remark')
    if args.hide_examples:
        content_hidden.add('example')
    if args.hide_notes:
        content_hidden.add('note')
    if args.hide_claims:
        content_hidden.add('claim')

    has_content_whitelist = bool(content_only)

    # Apply blacklist subtractively from whitelist
    if has_content_whitelist:
        content_only -= content_hidden

    return {
        'mode': 'orthogonal',
        'structural': {
            'has_whitelist': has_structural_whitelist,
            'allowed': structural_only,       # used if has_whitelist
            'hidden': structural_hidden,       # used if not has_whitelist
        },
        'content': {
            'has_whitelist': has_content_whitelist,
            'allowed': content_only,           # used if has_whitelist
            'hidden': content_hidden,          # used if not has_whitelist
        },
        'hierarchy_handling': 'smart'
    }


def validate_filter_config(args, filter_config):
    """Validate filter configuration and warn about conflicts."""

    # Check for direct conflicts (same element type with both --only and --hide)
    conflicts = []

    element_types = [
        ('sections', 'section'),
        ('subsections', 'subsection'),
        ('subsubsections', 'subsubsection'),
        ('theorems', 'theorem'),
        ('lemmas', 'lemma'),
        ('propositions', 'proposition'),
        ('corollaries', 'corollary'),
        ('definitions', 'definition'),
        ('proofs', 'proof'),
        ('remarks', 'remark'),
        ('examples', 'example'),
        ('notes', 'note'),
        ('claims', 'claim'),
    ]

    for flag_name, element_type in element_types:
        only_flag = getattr(args, f'only_{flag_name}', False)
        hide_flag = getattr(args, f'hide_{flag_name}', False)

        if only_flag and hide_flag:
            conflicts.append(f'--only-{flag_name} and --hide-{flag_name}')

    if conflicts:
        print(f"Warning: Conflicting flags detected: {', '.join(conflicts)}",
              file=sys.stderr)
        print(f"         Using inclusive (--only-*) flags with precedence",
              file=sys.stderr)


def should_display_element(element_type, filter_config):
    """
    Determine if element should be displayed based on filters.

    Uses the orthogonal two-dimensional model: structural elements are checked
    against the structural dimension, content elements against the content dimension.
    """
    STRUCTURAL = {'section', 'subsection', 'subsubsection'}

    if filter_config['mode'] == 'orthogonal':
        structural_dim = filter_config['structural']
        content_dim = filter_config['content']

        if element_type in STRUCTURAL:
            dim = structural_dim
        else:
            dim = content_dim

        if dim['has_whitelist']:
            # Whitelist mode for this dimension: must be in allowed set
            return element_type in dim['allowed']
        elif element_type not in STRUCTURAL and content_dim['has_whitelist']:
            # Content element but content has a whitelist that doesn't include it
            # (this case is handled by the branch above)
            return False
        elif element_type in STRUCTURAL and content_dim['has_whitelist'] and not structural_dim['has_whitelist']:
            # Structural element, content has a whitelist, structural has no whitelist.
            # The user asked for specific content only (e.g., --only-theorems).
            # Hide structural elements (smart hierarchy will rescue if needed).
            return False
        else:
            # No whitelist for this dimension: pure blacklist mode
            return element_type not in dim['hidden']

    # Legacy fallback (should not be reached with new build_filter_config)
    return True


def has_visible_descendants(structure, parent_idx, filter_config):
    """Check if structural element has visible descendants."""

    parent_level, parent_type, _, _, _, _, parent_file, _, _ = structure[parent_idx]

    if parent_type not in ['section', 'subsection', 'subsubsection']:
        return False

    for i in range(parent_idx + 1, len(structure)):
        child_level, child_type, _, _, _, _, child_file, _, _ = structure[i]

        if child_file != parent_file:
            break

        if child_type in ['section', 'subsection', 'subsubsection'] and child_level <= parent_level:
            break

        if should_display_element(child_type, filter_config):
            return True

    return False


def compute_visibility_map(structure, filter_config):
    """
    Compute visibility for all elements with smart hierarchy handling.

    Returns list of dicts with visibility information for each element.
    """

    visibility_map = []

    for idx, (level, element_type, content, optional_text,
              label, line_num, source_file, char_start, char_end) in enumerate(structure):

        base_visible = should_display_element(element_type, filter_config)

        # Hierarchy preservation: keep parent sections visible if they have visible children
        keep_for_hierarchy = False
        if element_type in ['section', 'subsection'] and not base_visible:
            if filter_config['hierarchy_handling'] == 'smart':
                keep_for_hierarchy = has_visible_descendants(structure, idx, filter_config)

        is_visible = base_visible or keep_for_hierarchy

        visibility_map.append({
            'idx': idx,
            'visible': is_visible,
            'kept_for_hierarchy': keep_for_hierarchy,
            'original_level': level,
            'element_type': element_type
        })

    return visibility_map


def _format_element_body(sorted_structure, target_idx, file_contents, header, truncate=None):
    """
    Extract and format the body text for a structural element.

    Args:
        sorted_structure: structure sorted by (file, char_start)
        target_idx: index of element in sorted_structure
        file_contents: dict mapping files to content
        header: pre-formatted header string
        truncate: max lines to show (None for no truncation)

    Returns:
        Formatted string with header + body text, or None if no body available.
    """
    text, _, _ = get_element_text_range(sorted_structure, target_idx, file_contents)
    if text is None:
        return f"{header}\n(no body text available)"

    # Light cleanup: strip \label{} lines, dedent
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^\\label\{[^}]*\}\s*$', stripped):
            continue
        cleaned.append(line)

    body = textwrap.dedent('\n'.join(cleaned)).strip()
    body_lines = body.split('\n')

    # Truncation
    if truncate is not None and len(body_lines) > truncate:
        remaining = len(body_lines) - truncate
        body = '\n'.join(body_lines[:truncate]) + f"\n... ({remaining} more lines)"
    else:
        body = '\n'.join(body_lines)

    return f"{header}\n{body}"


def format_show(label, structure, file_contents, label_registry, truncate=10):
    """
    Show the body of a labelled environment.

    Args:
        label: the label to look up
        structure: full parsed structure
        file_contents: dict mapping files to content
        label_registry: label -> metadata dict
        truncate: max lines to show (None for no truncation)

    Returns:
        Formatted string with header + body text.
    """
    if label_registry is None:
        label_registry = build_label_registry(structure)

    if label not in label_registry:
        return f"Error: label '{label}' not found."

    info = label_registry[label]
    element_type = info['type']
    content = info['content'] or ''
    source_file = info['file']
    line_num = info['line']

    # Find element index in sorted structure
    sorted_structure = structure  # expects pre-sorted input
    target_idx = None
    for idx, elem in enumerate(sorted_structure):
        if elem[4] == label:
            target_idx = idx
            break

    if target_idx is None:
        return f"Error: label '{label}' found in registry but not in structure."

    # Header
    type_display = element_type.replace('_', ' ').title()
    header = f"[{type_display}] {content} ({source_file}:{line_num})"

    return _format_element_body(sorted_structure, target_idx, file_contents, header, truncate)


def format_proof(label, structure, file_contents, label_registry, truncate=None):
    """
    Show the proof associated with a labelled theorem/proposition/lemma.

    Finds the proof by: (1) explicit \\ref{label} in proof's optional text,
    or (2) the next proof element after the target with no intervening provable element.

    Args:
        label: the label of the theorem to find the proof for
        structure: full parsed structure
        file_contents: dict mapping files to content
        label_registry: label -> metadata dict
        truncate: max lines to show (None for no truncation)

    Returns:
        Formatted string with proof header + body text.
    """
    if label_registry is None:
        label_registry = build_label_registry(structure)

    if label not in label_registry:
        return f"Error: label '{label}' not found."

    info = label_registry[label]
    source_file = info['file']
    char_start = info['char_start']
    element_type = info['type']
    content = info['content'] or ''

    sorted_structure = structure  # expects pre-sorted input

    # Strategy A: explicit \ref{label} in proof's optional text
    for idx, elem in enumerate(sorted_structure):
        if elem[1] == 'proof' and elem[6] == source_file:
            opt_text = elem[3] or ''
            if f'\\ref{{{label}}}' in opt_text:
                type_display = element_type.replace('_', ' ').title()
                header = f"[Proof of {type_display}] {content} ({source_file}:{elem[5]})"
                return _format_element_body(sorted_structure, idx, file_contents, header, truncate)

    # Strategy B: next proof after target in same file, no intervening provable element
    provable = {'theorem', 'proposition', 'lemma', 'corollary', 'conjecture'}
    # Find the target element's index in sorted structure
    target_idx = None
    for i, elem in enumerate(sorted_structure):
        if elem[4] == label:
            target_idx = i
            break
    if target_idx is not None:
        for idx in range(target_idx + 1, len(sorted_structure)):
            elem = sorted_structure[idx]
            if elem[6] != source_file:
                break
            if elem[1] == 'proof':
                # Check elements between target and this proof for intervening provable
                intervening = any(
                    sorted_structure[j][1].rstrip('*') in provable
                    for j in range(target_idx + 1, idx)
                    if sorted_structure[j][6] == source_file
                )
                if not intervening:
                    type_display = element_type.replace('_', ' ').title()
                    header = f"[Proof of {type_display}] {content} ({source_file}:{elem[5]})"
                    return _format_element_body(sorted_structure, idx, file_contents, header, truncate)
                break  # This proof had intervening elements; no further proofs will be closer

    return f"No proof found for '{label}'."


def format_neighbourhood(label, structure, file_contents, label_registry, n=3,
                         compact=False, ref_options=None, filter_config=None,
                         status_map=None, status_filter=None, cite_options=None,
                         known_labels=None, sizes=False, aux_map=None,
                         label_to_papers=None):
    """
    Show N elements before and after a labelled element in document order.

    Args:
        label: the label to centre on
        structure: full parsed structure
        file_contents: dict mapping files to content
        label_registry: label -> metadata dict
        n: number of elements before/after to include (default 3)
        compact: use compact output format
        Other args: passed through to format_output/format_compact_output

    Returns:
        Formatted string showing neighbourhood context.
    """
    if label_registry is None:
        label_registry = build_label_registry(structure)

    if label not in label_registry:
        return f"Error: label '{label}' not found."

    info = label_registry[label]
    source_file = info['file']

    # Sort and filter to same file
    sorted_structure = structure  # expects pre-sorted input
    file_elements = [elem for elem in sorted_structure if elem[6] == source_file]

    # Find target index within file
    target_idx = None
    for j, elem in enumerate(file_elements):
        if elem[4] == label:
            target_idx = j
            break

    if target_idx is None:
        return f"Error: label '{label}' found in registry but not in structure."

    # Slice +-N
    start = max(0, target_idx - n)
    end = min(len(file_elements), target_idx + n + 1)
    neighbourhood = file_elements[start:end]

    # Build a label registry for the slice
    slice_registry = build_label_registry(neighbourhood)

    if compact:
        return format_compact_output(neighbourhood, file_contents, ref_options,
                                     filter_config, status_map, status_filter,
                                     cite_options, slice_registry, known_labels,
                                     sizes, aux_map, label_to_papers)
    else:
        return format_output(neighbourhood, file_contents, ref_options,
                            filter_config, status_map, status_filter,
                            cite_options, slice_registry, known_labels,
                            sizes, aux_map, label_to_papers)


def format_orphan_report(structure, file_contents, label_registry=None):
    """
    Find orphaned labels (never referenced) and missing references (targets that don't exist).

    Returns formatted report string.
    """
    if label_registry is None:
        label_registry = build_label_registry(structure)

    sorted_structure = structure  # expects pre-sorted input


    # Collect all defined labels
    defined_labels = set(label_registry.keys())

    # Single pass: build forward-ref index and reverse-ref index
    all_referenced = set()
    reverse_index = {}  # label -> list of referencing element descriptions
    for idx, elem in enumerate(sorted_structure):
        if elem[1] == 'input':
            continue
        text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
        if not text:
            continue
        refs_in_elem = set(_extract_ref_labels(text))
        all_referenced.update(refs_in_elem)
        # Build reverse index for later "referenced by" lookup
        elem_desc = elem[4] or f"({elem[1]} at {elem[6]}:{elem[5]})"
        for ref in refs_in_elem:
            if ref not in reverse_index:
                reverse_index[ref] = []
            if elem_desc not in reverse_index[ref]:
                reverse_index[ref].append(elem_desc)

    # Orphaned: defined but never referenced
    orphaned = sorted(defined_labels - all_referenced)

    # Missing: referenced but never defined
    missing = sorted(all_referenced - defined_labels)

    lines = []
    if orphaned:
        lines.append(f"Orphaned labels ({len(orphaned)} defined but never referenced):")
        for label in orphaned:
            info = label_registry[label]
            lines.append(f"  {info['type']:12s}  {label:40s}  {info['file']}:{info['line']}")
    else:
        lines.append("No orphaned labels found.")

    lines.append("")

    if missing:
        lines.append(f"Missing references ({len(missing)} referenced but never defined):")
        for label in missing:
            referencing = reverse_index.get(label, [])
            ref_str = ', '.join(referencing[:3])
            if len(referencing) > 3:
                ref_str += f", ... (+{len(referencing) - 3})"
            lines.append(f"  {label:40s}  referenced by: {ref_str}")
    else:
        lines.append("No missing references found.")

    return '\n'.join(lines)


def format_drafting_report(structure, file_contents, label_registry=None, status_map=None):
    """
    Report on all draftingnote environments: location, first line, referenced labels, status.

    Returns formatted report string.
    """
    if label_registry is None:
        label_registry = build_label_registry(structure)

    sorted_structure = structure  # expects pre-sorted input


    notes = []
    for idx, elem in enumerate(sorted_structure):
        if elem[1] not in ('draftingnote', 'reasoning'):
            continue
        text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
        first_line = ''
        refs_in_note = []
        if text:
            # Extract first non-empty, non-label line
            for line in text.split('\n'):
                stripped = line.strip()
                if stripped and not re.match(r'^\\label\{', stripped) and not re.match(r'^\\(begin|end)\{', stripped):
                    first_line = stripped[:120]
                    if len(stripped) > 120:
                        first_line += '...'
                    break
            refs_in_note = _extract_ref_labels(text)

        # Find parent section context
        parent_section = None
        for i in range(idx - 1, -1, -1):
            if sorted_structure[i][1] in ('section', 'subsection') and sorted_structure[i][6] == elem[6]:
                parent_section = sorted_structure[i][4] or sorted_structure[i][2]
                break

        notes.append({
            'type': elem[1],
            'label': elem[4],
            'file': elem[6],
            'line': elem[5],
            'optional_text': elem[3],
            'first_line': first_line,
            'refs': refs_in_note,
            'parent_section': parent_section,
        })

    if not notes:
        return "No drafting notes or reasoning environments found."

    # Group by file
    by_file = OrderedDict()
    for note in notes:
        by_file.setdefault(note['file'], []).append(note)

    lines = [f"Drafting report: {len(notes)} note(s) across {len(by_file)} file(s)", ""]
    for filename, file_notes in by_file.items():
        lines.append(f"  {filename} ({len(file_notes)} notes):")
        for note in file_notes:
            label_str = f"  [{note['label']}]" if note['label'] else ''
            title_str = f"  {note['optional_text']}" if note['optional_text'] else ''
            ref_str = f"  refs: {', '.join(note['refs'])}" if note['refs'] else ''
            lines.append(f"    L{note['line']:4d}  {note['type']}{label_str}{title_str}{ref_str}")
            if note['first_line']:
                lines.append(f"           {note['first_line']}")
        lines.append("")

    return '\n'.join(lines)


def format_cite_usage(cite_key, structure, file_contents, label_registry=None):
    """
    Show where a citation key is used and in what structural context.

    Returns formatted report string.
    """
    if label_registry is None:
        label_registry = build_label_registry(structure)

    sorted_structure = structure  # expects pre-sorted input
    cite_pattern = re.compile(r'(?<!\\no)\\cite(?:\[[^\]]*\])?\{([^}]*)\}')

    # Find all elements that cite this key
    citing_elements = []
    for idx, elem in enumerate(sorted_structure):
        if elem[1] == 'input':
            continue
        text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
        if not text:
            continue
        # Check if cite_key appears in any \cite{} command
        for match in cite_pattern.finditer(text):
            keys = [k.strip() for k in match.group(1).split(',')]
            if cite_key in keys:
                # Find section context
                parent_section = None
                for i in range(idx - 1, -1, -1):
                    if sorted_structure[i][1] in ('section', 'subsection') and sorted_structure[i][6] == elem[6]:
                        parent_section = sorted_structure[i][4] or sorted_structure[i][2]
                        break
                citing_elements.append({
                    'type': elem[1],
                    'label': elem[4],
                    'content': elem[2],
                    'file': elem[6],
                    'line': elem[5],
                    'parent_section': parent_section,
                })
                break  # Only count each element once

    if not citing_elements:
        return f"Citation key '{cite_key}' not found in any element."

    lines = [f"Citation '{cite_key}' used in {len(citing_elements)} element(s):", ""]
    for ce in citing_elements:
        label_str = f"  [{ce['label']}]" if ce['label'] else ''
        section_str = f"  (in {ce['parent_section']})" if ce['parent_section'] else ''
        lines.append(f"  {ce['type']:12s}{label_str}  {ce['file']}:{ce['line']}{section_str}")

    return '\n'.join(lines)


def format_parse_summary(structure, file_contents):
    """
    Print a summary of parse results: environment counts, file counts.

    Returns formatted summary string.
    """
    type_counts = Counter(elem[1] for elem in structure)
    file_set = set(elem[6] for elem in structure)
    labelled = sum(1 for elem in structure if elem[4])
    unlabelled = len(structure) - labelled

    lines = [
        f"Parse summary: {len(structure)} elements across {len(file_set)} file(s)",
        f"  Labelled: {labelled}, Unlabelled: {unlabelled}",
        "",
        "  Element counts by type:",
    ]
    for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"    {etype:20s}  {count:4d}")

    return '\n'.join(lines)


def format_compact_output(structure, file_contents=None, ref_options=None, filter_config=None, status_map=None, status_filter=None, cite_options=None, label_registry=None, known_labels=None, sizes=False, aux_map=None, label_to_papers=None):
    """
    Format output in compact tab-separated format optimised for Claude.

    Format: FILE<tab>TYPE<tab>LABEL<tab>LINE<tab>STATUS<tab>MATH_ISSUES<tab>LAST_REVIEWED<tab>REVIEW_DEPTH<tab>TITLE<tab>DESCRIPTION<tab>AFFECTED_ELEMENTS[<tab>→refs:label1,label2,...]

    Args:
        structure: List of (level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end)
        file_contents: Dict mapping files to their content (for extracting references)
        ref_options: Dict with reference display options
        filter_config: Dict with filtering options
        status_map: Dict mapping (file, label) -> status info (optional)
        status_filter: Set of status values to show (None = show all)
        label_registry: Dict mapping label -> metadata (from build_label_registry)

    Returns:
        String containing compact formatted output
    """
    if ref_options is None:
        ref_options = {'enabled': False}
    if filter_config is None:
        filter_config = _default_filter_config()

    output_lines = []

    if cite_options is None:
        cite_options = {'enabled': False}

    # Build label_map from registry for reference resolution
    label_map = {}
    if ref_options.get('enabled') and file_contents:
        if label_registry is None:
            label_registry = build_label_registry(structure)
        for lbl, info in label_registry.items():
            label_map[lbl] = (info['type'], info['content'], info['file'])

    # Sort structure by file and position
    sorted_structure = structure  # expects pre-sorted input

    # Compute visibility map for display filtering
    visibility_map = compute_visibility_map(sorted_structure, filter_config)

    for idx, (level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end) in enumerate(sorted_structure):

        # Check visibility
        visibility_info = visibility_map[idx]
        if not visibility_info['visible']:
            continue

        # Check status filter if applicable
        if status_map and status_filter and label:
            status_key = (source_file, label)
            if status_key in status_map:
                element_status = status_map[status_key]['STATUS']
                if element_status not in status_filter:
                    continue

        # Skip input commands in compact format
        if element_type == 'input':
            continue

        # Determine title
        title = optional_text if optional_text else content if content else element_type.capitalize()

        # Get status info if available
        status_value = ""
        math_issues_value = ""
        last_reviewed_value = ""
        review_depth_value = ""
        description_value = ""
        affected_value = ""
        if status_map and label:
            status_key = (source_file, label)
            if status_key in status_map:
                status_info = status_map[status_key]
                status_value = status_info['STATUS']
                math_issues_value = status_info['MATH_ISSUES']
                last_reviewed_value = status_info.get('LAST_REVIEWED', '').strip()
                review_depth_value = status_info.get('REVIEW_DEPTH', '').strip()
                description_value = status_info.get('DESCRIPTION', '').strip()
                affected_value = status_info.get('AFFECTED_ELEMENTS', '').strip()

        # Compute size annotation if requested
        line_display = str(line_num)
        if sizes and file_contents:
            el_line_end = compute_line_end(sorted_structure, idx, file_contents)
            if el_line_end:
                el_size = el_line_end - line_num + 1
                line_display = f"{line_num} ({el_size} lines)"

        # Build base line: FILE<tab>TYPE<tab>LABEL<tab>LINE<tab>STATUS<tab>MATH_ISSUES<tab>LAST_REVIEWED<tab>REVIEW_DEPTH<tab>TITLE<tab>DESCRIPTION<tab>AFFECTED_ELEMENTS
        if label:
            base_line = f"{source_file}\t{element_type}\t{label}\t{line_display}\t{status_value}\t{math_issues_value}\t{last_reviewed_value}\t{review_depth_value}\t{title}\t{description_value}\t{affected_value}"
        else:
            base_line = f"{source_file}\t{element_type}\t(no label)\t{line_display}\t{status_value}\t{math_issues_value}\t{last_reviewed_value}\t{review_depth_value}\t{title}\t{description_value}\t{affected_value}"

        # Extract references if enabled and element type matches requested level
        refs = []
        show_refs_here = False
        if ref_options.get('enabled') and file_contents and source_file in file_contents:
            levels = ref_options.get('levels', [])
            _theorem_types = {'theorem', 'lemma', 'proposition', 'corollary', 'definition'}
            if 'section' in levels and element_type == 'section':
                show_refs_here = True
            elif 'subsection' in levels and element_type == 'subsection':
                show_refs_here = True
            elif 'theorem' in levels and element_type in _theorem_types:
                show_refs_here = True
        if show_refs_here:
            # Use get_element_text_range to get the full body text (not just the declaration)
            text_range, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
            content_text = text_range if text_range else ""
            ref_labels = set(_extract_ref_labels(content_text))

            # Apply ref type filtering
            if ref_options.get('types_filter'):
                ref_labels = {lbl for lbl in ref_labels if lbl in label_map and label_map[lbl][0] in ref_options['types_filter']}

            # Apply different-level filtering
            if ref_options.get('different_level') and element_type in ['theorem', 'lemma', 'proposition', 'corollary', 'definition']:
                # Filter out refs from the same section/subsection
                current_section = None
                for i in range(idx - 1, -1, -1):
                    if sorted_structure[i][1] in ['section', 'subsection']:
                        current_section = sorted_structure[i][4]  # label
                        break

                filtered_refs = set()
                for lbl in ref_labels:
                    if lbl in label_map:
                        ref_type, ref_content, ref_file = label_map[lbl]
                        # Find ref's section
                        ref_section = None
                        for level2, elem_type2, content2, opt_text2, label2, line2, file2, start2, end2 in sorted_structure:
                            if label2 == lbl:
                                # Search backwards for this ref's section
                                for i2 in range(len(sorted_structure) - 1, -1, -1):
                                    if sorted_structure[i2][4] == label2:
                                        for i3 in range(i2 - 1, -1, -1):
                                            if sorted_structure[i3][1] in ['section', 'subsection']:
                                                ref_section = sorted_structure[i3][4]
                                                break
                                        break
                                break

                        if ref_section != current_section:
                            filtered_refs.add(lbl)

                ref_labels = filtered_refs

            refs = sorted(ref_labels)

        # Append refs if any, with scope annotations
        if refs:
            annotated = []
            for r in refs:
                if r in label_map:
                    annotated.append(r)
                elif known_labels is not None and r in known_labels:
                    annotated.append(f"{r}(oos)")
                elif known_labels is not None:
                    annotated.append(f"{r}(!)")
                else:
                    annotated.append(r)
            base_line += f"\t→refs:{','.join(annotated)}"

        # Append cites if enabled
        if cite_options.get('enabled') and file_contents and source_file in file_contents:
            show_cites = False
            cite_levels = cite_options.get('levels', [])
            if 'section' in cite_levels and element_type == 'section':
                show_cites = True
            elif 'subsection' in cite_levels and element_type == 'subsection':
                show_cites = True
            elif 'theorem' in cite_levels and element_type in ['theorem', 'lemma', 'proposition', 'corollary', 'definition']:
                show_cites = True

            if show_cites:
                cites = extract_cites_from_element(sorted_structure, idx, file_contents)
                if cites:
                    cite_map = cite_options.get('cite_map', {})
                    if cite_map:
                        cite_strs = [f"{k}={cite_map[k]}" if k in cite_map else k for k in cites]
                    else:
                        cite_strs = cites
                    base_line += f"\t→cites:{','.join(cite_strs)}"

        if label_to_papers and label and label in label_to_papers:
            base_line += f"\t→papers:{','.join(sorted(label_to_papers[label]))}"

        if aux_map and label:
            rendered = format_rendered_ref(label, aux_map)
            if rendered:
                base_line += f"\t→rendered:{rendered}"

        output_lines.append(base_line)

    return '\n'.join(output_lines)


def format_stats(structure, filter_config=None, compact=False):
    """
    Format element type frequency table.

    Returns string with type counts sorted by frequency.
    """
    if filter_config is None:
        filter_config = _default_filter_config()

    sorted_structure = structure  # expects pre-sorted input
    visibility_map = compute_visibility_map(sorted_structure, filter_config)

    counts = {}
    for idx, elem in enumerate(sorted_structure):
        if not visibility_map[idx]['visible']:
            continue
        if elem[1] == 'input':
            continue
        t = elem[1]
        counts[t] = counts.get(t, 0) + 1

    if not counts:
        return "No elements found."

    total = sum(counts.values())

    if compact:
        lines = []
        for t in sorted(counts, key=lambda k: (-counts[k], k)):
            lines.append(f"{t}\t{counts[t]}")
        lines.append(f"TOTAL\t{total}")
        return '\n'.join(lines)

    # Terminal format: aligned columns
    max_type_len = max(len(t) for t in counts)
    max_count_len = max(len(str(c)) for c in counts.values())
    lines = []
    for t in sorted(counts, key=lambda k: (-counts[k], k)):
        lines.append(f"  {t:<{max_type_len}}  {counts[t]:>{max_count_len}}")
    lines.append(f"  {'TOTAL':<{max_type_len}}  {total:>{max_count_len}}")
    return '\n'.join(lines)


def format_stats_per_chapter(structure, filter_config=None, compact=False, status_map=None):
    """
    Format chapter x element type matrix.

    Each row is a chapter (file), each column is an element type.
    Optionally includes status count columns.
    """
    if filter_config is None:
        filter_config = _default_filter_config()

    sorted_structure = structure  # expects pre-sorted input
    visibility_map = compute_visibility_map(sorted_structure, filter_config)

    # Collect counts per chapter per type
    chapter_counts = {}  # chapter -> {type -> count}
    all_types = set()

    for idx, elem in enumerate(sorted_structure):
        if not visibility_map[idx]['visible']:
            continue
        if elem[1] == 'input':
            continue

        chapter = elem[6]  # source_file
        t = elem[1]
        all_types.add(t)

        if chapter not in chapter_counts:
            chapter_counts[chapter] = {}
        chapter_counts[chapter][t] = chapter_counts[chapter].get(t, 0) + 1

    if not chapter_counts:
        return "No elements found."

    # Define column order: structural first, then content types alphabetically
    structural_order = ['section', 'subsection', 'subsubsection']
    content_types = sorted(all_types - set(structural_order))
    type_order = [t for t in structural_order if t in all_types] + content_types

    # Short column headers
    short_names = {
        'section': 'sec', 'subsection': 'sub', 'subsubsection': 'ssub',
        'theorem': 'thm', 'lemma': 'lem', 'proposition': 'prop',
        'corollary': 'cor', 'definition': 'def', 'proof': 'prf',
        'remark': 'rmk', 'example': 'exm', 'note': 'note',
        'claim': 'clm',
    }

    if compact:
        # TSV format
        header = 'Chapter\t' + '\t'.join(short_names.get(t, t[:4]) for t in type_order) + '\ttotal'
        lines = [header]
        totals = {t: 0 for t in type_order}
        grand_total = 0
        for chapter in sorted(chapter_counts.keys()):
            row_counts = chapter_counts[chapter]
            row_total = sum(row_counts.values())
            grand_total += row_total
            cols = []
            for t in type_order:
                c = row_counts.get(t, 0)
                totals[t] += c
                cols.append(str(c))
            lines.append(f"{chapter}\t" + '\t'.join(cols) + f"\t{row_total}")
        # Total row
        lines.append('TOTAL\t' + '\t'.join(str(totals[t]) for t in type_order) + f"\t{grand_total}")
        return '\n'.join(lines)

    # Terminal format: aligned columns
    headers = [short_names.get(t, t[:4]) for t in type_order] + ['total']
    col_width = max(5, max(len(h) for h in headers) + 1)
    chapter_col_width = max(len(ch) for ch in chapter_counts.keys()) + 2

    header_line = f"  {'Chapter':<{chapter_col_width}}" + ''.join(f"{h:>{col_width}}" for h in headers)
    lines = [header_line]

    totals = {t: 0 for t in type_order}
    grand_total = 0
    for chapter in sorted(chapter_counts.keys()):
        row_counts = chapter_counts[chapter]
        row_total = sum(row_counts.values())
        grand_total += row_total
        cols = []
        for t in type_order:
            c = row_counts.get(t, 0)
            totals[t] += c
            cols.append(f"{c:>{col_width}}")
        lines.append(f"  {chapter:<{chapter_col_width}}" + ''.join(cols) + f"{row_total:>{col_width}}")

    # Total row
    total_cols = ''.join(f"{totals[t]:>{col_width}}" for t in type_order)
    lines.append(f"  {'TOTAL':<{chapter_col_width}}" + total_cols + f"{grand_total:>{col_width}}")

    return '\n'.join(lines)


def format_sizes_summary(structure, file_contents, filter_config=None, compact=False):
    """
    Show summary table of total lines per element type.

    Returns formatted string with type, count, and total lines.
    """
    if filter_config is None:
        filter_config = _default_filter_config()

    sorted_structure = structure  # expects pre-sorted input
    visibility_map = compute_visibility_map(sorted_structure, filter_config)

    # Collect counts and total lines per type
    type_data = {}  # type -> {'count': N, 'lines': N}
    for idx, elem in enumerate(sorted_structure):
        if not visibility_map[idx]['visible']:
            continue
        if elem[1] == 'input':
            continue
        t = elem[1]
        line_end = compute_line_end(sorted_structure, idx, file_contents)
        if line_end:
            size = line_end - elem[5] + 1
        else:
            size = 0
        if t not in type_data:
            type_data[t] = {'count': 0, 'lines': 0}
        type_data[t]['count'] += 1
        type_data[t]['lines'] += size

    if not type_data:
        return "No elements found."

    total_count = sum(d['count'] for d in type_data.values())
    total_lines = sum(d['lines'] for d in type_data.values())

    if compact:
        lines = []
        for t in sorted(type_data, key=lambda k: (-type_data[k]['lines'], k)):
            lines.append(f"{t}\t{type_data[t]['count']}\t{type_data[t]['lines']}")
        lines.append(f"TOTAL\t{total_count}\t{total_lines}")
        return '\n'.join(lines)

    # Terminal format
    max_type_len = max(len(t) for t in type_data)
    max_count_len = max(len(str(d['count'])) for d in type_data.values())
    max_lines_len = max(len(f"{d['lines']:,}") for d in type_data.values())
    lines = [f"  {'Type':<{max_type_len}}  {'Count':>{max_count_len}}  {'Total Lines':>{max_lines_len}}"]
    for t in sorted(type_data, key=lambda k: (-type_data[k]['lines'], k)):
        d = type_data[t]
        lines.append(f"  {t:<{max_type_len}}  {d['count']:>{max_count_len}}  {d['lines']:>{max_lines_len},}")
    lines.append(f"  {'TOTAL':<{max_type_len}}  {total_count:>{max_count_len}}  {total_lines:>{max_lines_len},}")
    return '\n'.join(lines)


def format_reverse_refs(labels, combined_structure, file_contents, label_registry, compact=False, resolve_refs=False, transitive=None, min_depth=None, max_depth=None, type_filter=None, aux_map=None):
    """
    Find all elements that reference the given labels.

    Args:
        labels: list of label strings to search for
        combined_structure: full parsed structure
        file_contents: dict mapping files to content
        label_registry: label -> metadata dict
        compact: output in TSV format
        resolve_refs: resolve labels to display names
        transitive: None for direct only, 0 for unlimited depth, N for max depth

    Returns:
        Formatted string of reverse references.
    """
    sorted_structure = combined_structure  # expects pre-sorted input


    # Pre-build reverse ref index for efficiency (needed for transitive)
    elem_forward_refs = {}  # idx -> set of labels referenced
    for idx, elem in enumerate(sorted_structure):
        if elem[1] == 'input':
            continue
        text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
        if text:
            refs = set(_extract_ref_labels(text))
            if refs:
                elem_forward_refs[idx] = refs

    # Build reverse map: target_label -> set of source element indices
    reverse_map = {}
    for idx, refs in elem_forward_refs.items():
        for ref in refs:
            reverse_map.setdefault(ref, set()).add(idx)

    def _find_section_context(idx):
        """Find the nearest parent section for an element."""
        source_file = sorted_structure[idx][6]
        for i in range(idx - 1, -1, -1):
            if sorted_structure[i][1] == 'section' and sorted_structure[i][6] == source_file:
                return sorted_structure[i][4] or sorted_structure[i][2]
        return None

    def _build_match(idx, depth=None):
        """Build a result dict for element at idx."""
        elem = sorted_structure[idx]
        level, element_type, content, optional_text, elem_label, line_num, source_file, char_start, char_end = elem
        result = {
            'type': element_type,
            'content': optional_text or content,
            'label': elem_label,
            'line': line_num,
            'file': source_file,
            'section': _find_section_context(idx),
        }
        if depth is not None:
            result['depth'] = depth
        return result

    results = {}

    for target_label in labels:
        if transitive is not None:
            # Transitive: BFS through reverse refs
            bfs_max_depth = transitive if transitive > 0 else float('inf')
            found = {}  # elem idx -> depth
            queue = [(target_label, 0)]
            visited_labels = {target_label}

            while queue:
                current_label, depth = queue.pop(0)
                if depth >= bfs_max_depth:
                    continue
                for idx in reverse_map.get(current_label, set()):
                    if idx not in found:
                        found[idx] = depth + 1
                        elem_label = sorted_structure[idx][4]
                        if elem_label and elem_label not in visited_labels:
                            visited_labels.add(elem_label)
                            queue.append((elem_label, depth + 1))

            results[target_label] = [_build_match(idx, found[idx]) for idx in sorted(found.keys())]
        else:
            # Direct refs only (original behavior)
            results[target_label] = []
            for idx in sorted(reverse_map.get(target_label, set())):
                results[target_label].append(_build_match(idx))

    # Apply post-BFS display filters (depth range, type filter)
    for target_label in labels:
        if min_depth is not None or max_depth is not None:
            results[target_label] = [
                m for m in results[target_label]
                if (min_depth is None or m.get('depth', 1) >= min_depth)
                and (max_depth is None or m.get('depth', 1) <= max_depth)
            ]
        if type_filter:
            type_set = set(type_filter)
            results[target_label] = [
                m for m in results[target_label] if m['type'] in type_set
            ]

    if compact:
        lines = []
        for target_label in labels:
            matches = results[target_label]
            # Print stats header to stderr for transitive compact output
            if transitive is not None and matches:
                depths = [m['depth'] for m in matches if 'depth' in m]
                files = set(m['file'] for m in matches)
                if depths:
                    max_d = max(depths)
                    depth_counts = {}
                    for d in depths:
                        depth_counts[d] = depth_counts.get(d, 0) + 1
                    depth_dist = ', '.join(f"{depth_counts[d]}@{d}" for d in sorted(depth_counts))
                    print(f"  {target_label}: {len(matches)} results across {len(files)} files, "
                          f"max depth {max_d}: {depth_dist}", file=sys.stderr)
            for match in matches:
                label_display = match['label'] or '(no label)'
                depth_str = f"\tdepth:{match['depth']}" if 'depth' in match else ""
                line = f"{target_label}\t<-ref\t{match['type']}\t{label_display}\t{match['line']}\t{match['file']}{depth_str}"
                if aux_map and match.get('label'):
                    r = format_rendered_ref(match['label'], aux_map)
                    if r:
                        line += f"\t\u2192rendered:{r}"
                lines.append(line)
        return '\n'.join(lines)

    # Terminal format
    lines = []
    for target_label in labels:
        matches = results[target_label]
        if resolve_refs and target_label in label_registry:
            info = label_registry[target_label]
            target_display = f"{info['type'].capitalize()}: {info['content']} [{target_label}]"
        else:
            target_display = target_label

        lines.append(f"{Colors.BOLD}Reverse references for {target_display}:{Colors.RESET}")

        if not matches:
            lines.append(f"  {Colors.TEXT_MUTED}(no references found){Colors.RESET}")
        else:
            # Add stats header for transitive output
            if transitive is not None:
                depths = [m['depth'] for m in matches if 'depth' in m]
                files = set(m['file'] for m in matches)
                if depths:
                    max_d = max(depths)
                    depth_counts = {}
                    for d in depths:
                        depth_counts[d] = depth_counts.get(d, 0) + 1
                    depth_dist = ', '.join(f"{depth_counts[d]}@{d}" for d in sorted(depth_counts))
                    lines.append(f"  {Colors.TEXT_MUTED}({len(matches)} results across {len(files)} files, "
                                 f"max depth {max_d}: {depth_dist}){Colors.RESET}")

            by_file = {}
            for match in matches:
                by_file.setdefault(match['file'], []).append(match)

            for file_name in sorted(by_file.keys()):
                lines.append(f"  {Colors.FILENAME}{file_name}:{Colors.RESET}")
                for match in by_file[file_name]:
                    color = Colors.get_color_for_type(match['type'])
                    label_str = f" [{match['label']}]" if match['label'] else ""
                    rendered_str = ""
                    if aux_map and match.get('label'):
                        r = format_rendered_ref(match['label'], aux_map)
                        if r:
                            rendered_str = f" {Colors.TEXT_MUTED}[{r}]{Colors.RESET}"
                    depth_str = f" (depth {match['depth']})" if 'depth' in match else ""
                    lines.append(f"    {color}{match['type'].capitalize()}: {match['content']}{label_str}{rendered_str}{Colors.RESET} {Colors.LABEL}(line {match['line']}){depth_str}{Colors.RESET}")

        lines.append("")

    return '\n'.join(lines)


def format_deps_matrix(combined_structure, file_contents, label_registry, include_self=False, compact=False):
    """
    Output a chapter x chapter dependency matrix showing cross-reference counts.

    Args:
        combined_structure: full parsed structure
        file_contents: dict mapping files to content
        label_registry: label -> metadata dict
        include_self: if True, show intra-chapter ref counts on diagonal
        compact: output in TSV format

    Returns:
        Formatted dependency matrix string.
    """
    sorted_structure = combined_structure  # expects pre-sorted input

    # Get all chapter files
    chapters = sorted(set(elem[6] for elem in sorted_structure if elem[1] != 'input'))

    # Build matrix: matrix[source_chapter][target_chapter] = count
    matrix = {ch: {ch2: 0 for ch2 in chapters} for ch in chapters}



    for idx, elem in enumerate(sorted_structure):
        if elem[1] == 'input':
            continue

        source_chapter = elem[6]
        text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
        if text is None:
            continue

        for ref_label in _extract_ref_labels(text):
            if ref_label in label_registry:
                target_chapter = label_registry[ref_label]['file']
                if target_chapter in matrix[source_chapter]:
                    matrix[source_chapter][target_chapter] += 1

    if compact:
        # TSV format
        header = 'From \\ To\t' + '\t'.join(chapters)
        lines = [header]
        for src in chapters:
            cols = []
            for tgt in chapters:
                if src == tgt and not include_self:
                    cols.append('-')
                else:
                    cols.append(str(matrix[src][tgt]))
            lines.append(f"{src}\t" + '\t'.join(cols))
        return '\n'.join(lines)

    # Terminal format
    # Abbreviate chapter names for display
    short_chapters = []
    for ch in chapters:
        name = ch.replace('.tex', '')
        if len(name) > 20:
            name = name[:17] + '...'
        short_chapters.append(name)

    col_width = max(6, max(len(s) for s in short_chapters) + 1)
    row_label_width = max(len(s) for s in short_chapters) + 2

    from_to = 'From \\ To'
    header = f"  {from_to:<{row_label_width}}" + ''.join(f"{s:>{col_width}}" for s in short_chapters)
    lines = [header]

    for i, src in enumerate(chapters):
        cols = []
        for j, tgt in enumerate(chapters):
            if i == j and not include_self:
                cols.append(f"{'-':>{col_width}}")
            else:
                cols.append(f"{matrix[src][tgt]:>{col_width}}")
        lines.append(f"  {short_chapters[i]:<{row_label_width}}" + ''.join(cols))

    return '\n'.join(lines)


def format_dot_export(combined_structure, file_contents, label_registry,
                      chapter_level=False, scope_labels=None, transitive_depth=None,
                      aux_map=None, filter_config=None):
    """Export dependency graph as Graphviz DOT string."""
    lines_out = []
    lines_out.append('digraph manuscript_deps {')
    lines_out.append('    rankdir=LR;')
    lines_out.append('    node [fontname="Helvetica"];')
    lines_out.append('    graph [compound=true];')
    lines_out.append('')

    def safe_id(label):
        return re.sub(r'[^A-Za-z0-9_]', '_', label)

    if chapter_level:
        # Chapter-level: aggregate cross-chapter reference counts
        chapter_files = []
        chapter_labels = {}  # file -> list of labels
        chapter_names = {}   # file -> display name
        for elem in combined_structure:
            if elem[1] == 'input':
                continue
            f = elem[6]
            if f not in chapter_labels:
                chapter_labels[f] = []
            lbl = elem[4]
            if lbl:
                chapter_labels[f].append(lbl)
            if f not in chapter_files:
                chapter_files.append(f)
                # Use filename stem as display name
                chapter_names[f] = os.path.splitext(os.path.basename(f))[0]
        # Build cross-chapter edge counts
        edge_counts = {}
        sorted_struct = combined_structure  # expects pre-sorted input
        for idx, elem in enumerate(sorted_struct):
            if elem[1] == 'input':
                continue
            src_file = elem[6]
            src_label = elem[4]
            if not src_label:
                continue
            text, _, _ = get_element_text_range(sorted_struct, idx, file_contents)
            if text:
                targets = _extract_ref_labels(text)
                for t in targets:
                    if t not in label_registry:
                        continue
                    tgt_file = label_registry[t].get('file', '')
                    if tgt_file != src_file:
                        key = (src_file, tgt_file)
                        edge_counts[key] = edge_counts.get(key, 0) + 1
        # Emit nodes
        for f in chapter_files:
            node_id = safe_id(chapter_names[f])
            display = chapter_names[f].replace('_', ' ')
            lines_out.append(f'    "{node_id}" [label="{display}", shape=ellipse, style=filled, fillcolor="#fffde7"];')
        lines_out.append('')
        # Emit edges
        for (src_f, tgt_f), count in sorted(edge_counts.items()):
            src_id = safe_id(chapter_names.get(src_f, src_f))
            tgt_id = safe_id(chapter_names.get(tgt_f, tgt_f))
            lines_out.append(f'    "{src_id}" -> "{tgt_id}" [label="{count}"];')
    else:
        # Theorem-level mode
        forward_graph = build_forward_ref_graph(combined_structure, file_contents, label_registry)

        if scope_labels:
            # BFS in reverse: find all nodes that (transitively) reference scope_labels
            reverse_graph = {}  # to_label -> set(from_labels)
            for src, targets in forward_graph.items():
                for tgt in targets:
                    if tgt not in reverse_graph:
                        reverse_graph[tgt] = set()
                    reverse_graph[tgt].add(src)

            included = set(scope_labels)
            frontier = set(scope_labels)
            depth = 0
            while frontier:
                if transitive_depth is not None and depth >= transitive_depth:
                    break
                next_frontier = set()
                for lbl in frontier:
                    for referrer in reverse_graph.get(lbl, set()):
                        if referrer not in included:
                            included.add(referrer)
                            next_frontier.add(referrer)
                frontier = next_frontier
                depth += 1
            # Also add forward refs from included nodes to scope targets
            for lbl in list(included):
                for tgt in forward_graph.get(lbl, set()):
                    if tgt in scope_labels or tgt in included:
                        included.add(tgt)
        else:
            # All labelled nodes that appear in the graph
            included = set(forward_graph.keys())
            for targets in forward_graph.values():
                included.update(targets)
            included = {l for l in included if l in label_registry}

        # Group by file for clusters
        file_to_labels = {}
        for lbl in included:
            if lbl not in label_registry:
                continue
            f = label_registry[lbl].get('file', 'unknown')
            if f not in file_to_labels:
                file_to_labels[f] = []
            file_to_labels[f].append(lbl)

        # Find display name for each file from first section
        file_display = {}
        for elem in combined_structure:
            f = elem[6]
            if f not in file_display and elem[1] in ('section',):
                content_str = elem[3] or elem[2] or os.path.splitext(os.path.basename(f))[0]
                file_display[f] = content_str
        for f in file_to_labels:
            if f not in file_display:
                file_display[f] = os.path.splitext(os.path.basename(f))[0]

        # Emit subgraph clusters
        for f, labels in sorted(file_to_labels.items()):
            cluster_id = safe_id(os.path.splitext(os.path.basename(f))[0])
            display_name = file_display.get(f, cluster_id).replace('"', '\\"')
            lines_out.append(f'    subgraph cluster_{cluster_id} {{')
            lines_out.append(f'        label="{display_name}";')
            lines_out.append('        style=dashed;')
            for lbl in sorted(labels):
                if lbl not in label_registry:
                    continue
                node_id = safe_id(lbl)
                elem_type = label_registry[lbl].get('type', '')
                fillcolor = Colors.get_dot_fillcolor(elem_type)
                shape = Colors.get_dot_shape(elem_type)
                # Build node label
                if aux_map:
                    rendered = format_rendered_ref(lbl, aux_map)
                    if rendered:
                        display_label = f"{rendered}\\n{lbl}".replace('"', '\\"')
                    else:
                        display_label = f"{elem_type.capitalize()}\\n{lbl}".replace('"', '\\"')
                else:
                    display_label = f"{elem_type.capitalize()}\\n{lbl}".replace('"', '\\"')
                lines_out.append(
                    f'        "{node_id}" [label="{display_label}", '
                    f'shape={shape}, style=filled, fillcolor="{fillcolor}"];'
                )
            lines_out.append('    }')
            lines_out.append('')

        # Emit edges
        for src, targets in sorted(forward_graph.items()):
            if src not in included:
                continue
            src_id = safe_id(src)
            for tgt in sorted(targets):
                if tgt in included:
                    tgt_id = safe_id(tgt)
                    lines_out.append(f'    "{src_id}" -> "{tgt_id}";')

    lines_out.append('}')
    return '\n'.join(lines_out) + '\n'


def format_json_export(combined_structure, file_contents, label_registry, filter_config=None, status_map=None, json_body=False):
    """
    Export the full parsed structure as JSON.

    Args:
        combined_structure: full parsed structure
        file_contents: dict mapping files to content
        label_registry: label -> metadata dict
        filter_config: display filter config (for filtering visible elements)
        status_map: optional status overlay
        json_body: if True, include raw LaTeX body text for each element

    Returns:
        JSON string.
    """

    if filter_config is None:
        filter_config = _default_filter_config()

    sorted_structure = combined_structure  # expects pre-sorted input
    visibility_map = compute_visibility_map(sorted_structure, filter_config)



    # Build forward refs for all elements
    forward_refs = {}  # label -> [ref_labels]
    for idx, elem in enumerate(sorted_structure):
        if elem[1] == 'input' or not elem[4]:
            continue
        text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
        if text:
            refs = list(dict.fromkeys(_extract_ref_labels(text)))  # deduplicate preserving order
            forward_refs[elem[4]] = refs

    # Build reverse refs from forward refs
    reverse_refs = {}  # label -> [source_labels]
    for source_label, targets in forward_refs.items():
        for target in targets:
            reverse_refs.setdefault(target, []).append(source_label)

    # Build elements array with subsection tracking and line ranges
    elements = []
    current_section = None
    current_subsection = None
    current_subsubsection = None

    # First pass: build elements with subsection tracking and line_end
    for idx, elem in enumerate(sorted_structure):
        if not visibility_map[idx]['visible']:
            continue
        if elem[1] == 'input':
            continue

        level, element_type, content, optional_text, label, line_num, source_file, char_start, char_end = elem

        # Track current section/subsection/subsubsection context
        if element_type == 'section':
            current_section = label if label else content
            current_subsection = None
            current_subsubsection = None
        elif element_type == 'subsection':
            current_subsection = label if label else content
            current_subsubsection = None
        elif element_type == 'subsubsection':
            current_subsubsection = label if label else content

        element_data = {
            'type': element_type,
            'content': optional_text or content,
            'file': source_file,
            'line': line_num,
        }

        # Add subsection/subsubsection context
        if current_subsection:
            element_data['subsection'] = current_subsection
        if current_subsubsection:
            element_data['subsubsection'] = current_subsubsection

        # Compute line_end using the module-level function
        line_end = compute_line_end(sorted_structure, idx, file_contents)
        if line_end:
            element_data['line_end'] = line_end

        if label:
            element_data['label'] = label
            element_data['refs_to'] = forward_refs.get(label, [])
            element_data['refs_from'] = reverse_refs.get(label, [])

            # Extract cites
            text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
            if text:
                cites = extract_cites_from_text(text)
                if cites:
                    element_data['cites'] = cites

            # Add section context from registry
            if label in label_registry:
                reg = label_registry[label]
                if reg['section']:
                    element_data['section'] = reg['section']

            # Add status if available
            if status_map:
                status_key = (source_file, label)
                if status_key in status_map:
                    element_data['status'] = status_map[status_key]['STATUS']
                    if status_map[status_key].get('DESCRIPTION'):
                        element_data['status_note'] = status_map[status_key]['DESCRIPTION']
                    if status_map[status_key].get('MATH_ISSUES'):
                        element_data['math_issues'] = status_map[status_key]['MATH_ISSUES']
                    if status_map[status_key].get('LAST_REVIEWED'):
                        element_data['last_reviewed'] = status_map[status_key]['LAST_REVIEWED']
                    if status_map[status_key].get('REVIEW_DEPTH'):
                        element_data['review_depth'] = status_map[status_key]['REVIEW_DEPTH']

        # Add body text if requested (skip sections)
        if json_body and element_type not in ('section', 'subsection', 'subsubsection'):
            text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
            if text:
                element_data['body'] = text

        elements.append(element_data)

    # Second pass: proof-theorem linking
    # Numbered result types that can have proofs
    provable_types = {'theorem', 'proposition', 'lemma', 'corollary', 'conjecture'}

    # Build index of elements by label for quick lookup
    label_to_elem_idx = {}
    for i, elem_data in enumerate(elements):
        if 'label' in elem_data:
            label_to_elem_idx[elem_data['label']] = i

    # Process proofs
    for i, elem_data in enumerate(elements):
        if elem_data['type'] != 'proof':
            continue

        proof_of_label = None

        # Get the proof text to check for explicit patterns
        proof_text = None
        proof_file = elem_data['file']
        proof_line = elem_data['line']

        # Find this proof in sorted_structure to get its text
        for idx, elem in enumerate(sorted_structure):
            if elem[6] == proof_file and elem[5] == proof_line and elem[1] == 'proof':
                proof_text, _, _ = get_element_text_range(sorted_structure, idx, file_contents)
                break

        # Also get the \begin{proof}[...] line itself, which get_element_text_range excludes
        begin_line_text = ""
        if proof_file in file_contents:
            content_lines = file_contents[proof_file].split('\n')
            if 0 < proof_line <= len(content_lines):
                begin_line_text = content_lines[proof_line - 1]

        # Check the \begin{proof} line first for explicit references
        # (handles \begin{proof}[Proof of Theorem~\ref{thm:foo}])
        if begin_line_text:
            begin_patterns = [
                r'\\begin\{proof\}\[.*?\\ref\{([^}]+)\}',
                r'Proof of (?:the )?(?:Theorem|Proposition|Lemma|Corollary)~?\\ref\{([^}]+)\}',
            ]
            for pattern in begin_patterns:
                match = re.search(pattern, begin_line_text)
                if match:
                    proof_of_label = match.group(1)
                    break

        if proof_text and not proof_of_label:
            # Heuristic 1: Explicit pattern "Proof of Theorem~\ref{thm:foo}" in body
            explicit_patterns = [
                r'Proof of (?:Theorem|Proposition|Lemma|Corollary)~?\\ref\{([^}]+)\}',
                r'Proof of (?:the )?(?:Theorem|Proposition|Lemma|Corollary)~?\\ref\{([^}]+)\}',
            ]
            for pattern in explicit_patterns:
                match = re.search(pattern, proof_text, re.IGNORECASE)
                if match:
                    proof_of_label = match.group(1)
                    break

        # Heuristic 3: Proximity fallback - nearest numbered result above in same file
        if not proof_of_label:
            # Look backwards in elements array for nearest provable type in same file
            for j in range(i - 1, -1, -1):
                prev_elem = elements[j]
                if prev_elem['file'] != proof_file:
                    break
                prev_type = prev_elem['type'].rstrip('*')
                if prev_type in provable_types and 'label' in prev_elem:
                    proof_of_label = prev_elem['label']
                    break

        # Validate: the linked theorem must start before the proof
        # (rejects false matches from forward references like "see proof of Theorem~\ref{...}")
        if proof_of_label and proof_of_label in label_to_elem_idx:
            thm_idx = label_to_elem_idx[proof_of_label]
            if elements[thm_idx]['line'] > proof_line:
                proof_of_label = None  # Target is after the proof — reject
                # Fall back to proximity
                for j in range(i - 1, -1, -1):
                    prev_elem = elements[j]
                    if prev_elem['file'] != proof_file:
                        break
                    prev_type = prev_elem['type'].rstrip('*')
                    if prev_type in provable_types and 'label' in prev_elem:
                        proof_of_label = prev_elem['label']
                        break

        # Set proof_of on this proof element
        if proof_of_label:
            elem_data['proof_of'] = proof_of_label

            # Set has_proof on the theorem element
            if proof_of_label in label_to_elem_idx:
                thm_idx = label_to_elem_idx[proof_of_label]
                elements[thm_idx]['has_proof'] = True

                # Set line_end_with_proof on the theorem
                if 'line_end' in elem_data:
                    elements[thm_idx]['line_end_with_proof'] = elem_data['line_end']

    # Build deps matrix
    chapters = sorted(set(elem[6] for elem in sorted_structure if elem[1] != 'input'))
    deps = {ch: {} for ch in chapters}
    for source_label, targets in forward_refs.items():
        if source_label in label_registry:
            src_ch = label_registry[source_label]['file']
            for target in targets:
                if target in label_registry:
                    tgt_ch = label_registry[target]['file']
                    if src_ch != tgt_ch:
                        deps[src_ch][tgt_ch] = deps[src_ch].get(tgt_ch, 0) + 1

    # Build stats
    stats = {}
    for elem in sorted_structure:
        if elem[1] == 'input':
            continue
        ch = elem[6]
        t = elem[1]
        if ch not in stats:
            stats[ch] = {}
        stats[ch][t] = stats[ch].get(t, 0) + 1

    # Find duplicate labels
    duplicates = find_duplicate_labels(sorted_structure)

    output = {
        'elements': elements,
        'deps_matrix': deps,
        'stats': stats,
        'metadata': {
            'files_processed': chapters,
            'total_elements': len(elements),
            'total_labels': len(label_registry),
            'files': [
                {'name': ch, 'lines': file_contents[ch].count('\n') + 1}
                for ch in chapters if ch in file_contents
            ],
            'duplicate_labels': duplicates,
            'schema_version': '2.0',
        }
    }

    return json.dumps(output, indent=2)


def main():
    # Detect invocation: 'latexnav' (pip console script) vs 'python3 latexnav.py'
    prog_name = os.path.basename(sys.argv[0])
    if prog_name.endswith('.py'):
        prog_cmd = f'python {prog_name}'
    else:
        prog_cmd = prog_name

    parser = argparse.ArgumentParser(
        prog=prog_name,
        description='Summarize structure from LaTeX files with colors and cross-reference analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'''Examples:
  # Structural overview
  {prog_cmd} *.tex
  {prog_cmd} --only-sections --only-numbered-results main.tex

  # View theorem statements and proofs
  {prog_cmd} --show thm:foo chapter.tex
  {prog_cmd} --show thm:foo,lem:bar chapter.tex
  {prog_cmd} --show thm:foo --show-limit 20 chapter.tex
  {prog_cmd} --proof thm:foo chapter.tex
  {prog_cmd} --neighbourhood thm:foo chapter.tex

  # Find and filter
  {prog_cmd} --compact --filter "thm:foo" *.tex
  {prog_cmd} --scope sec:intro chapter.tex
  {prog_cmd} --scope "index theory" chapter.tex

  # Dependencies and references
  {prog_cmd} --reverse-refs thm:foo main.tex
  {prog_cmd} --reverse-refs thm:foo --transitive main.tex
  {prog_cmd} --deps-matrix main.tex
  {prog_cmd} --refs-per-theorem --refs-type theorem,lemma *.tex

  # Status and review workflow
  {prog_cmd} --review *.tex
  {prog_cmd} --status --hide-ready --only-numbered-results main.tex

  # Reports
  {prog_cmd} --orphan-report main.tex
  {prog_cmd} --drafting-report *.tex
  {prog_cmd} --cite-usage AuthorYear main.tex
  {prog_cmd} --parse-summary main.tex

  # Export
  {prog_cmd} --json main.tex
  {prog_cmd} --compact --sizes *.tex -o summary.tsv
  {prog_cmd} --dot-export deps.dot --dot-chapter-level main.tex

Parsed environment types:
  Standard:    theorem, definition, lemma, proposition, corollary
  Supporting:  proof, remark, example, note, claim
  Research:    assumption, conjecture, hypothesis, question, problem,
               interpretation, setup, addendum, openproblem, false_conjecture
  Meta:        draftingnote, reasoning
  Custom \\newtheorem declarations are auto-detected. Use --extra-env NAME
  for environments defined in .sty files. Starred variants (e.g. theorem*)
  are parsed but hidden by default; use --show-non-numbered-results.

Reference extraction:
  Covers \\ref{{}}, \\cref{{}}, \\Cref{{}}, \\eqref{{}}, including comma-separated
  labels in \\cref{{a,b}}.

Warning levels (--warnings):
  errors (default)  Duplicate labels, missing files, parse failures
  all               Everything including info/loading messages
  none              Suppress all stderr output (also available as -q)

Argument ordering note:
  Flags that accept an optional value (--status [FILE]) may consume the next
  positional filename if placed before it. Place filenames first or use
  explicit flag values:
    OK:    {prog_cmd} *.tex --status
    OK:    {prog_cmd} --status myfile.tsv *.tex
    BAD:   {prog_cmd} --status *.tex
           (--status consumes the next argument as its optional FILE value)
        '''
    )
    parser.add_argument('input_files', nargs='+', help='Input LaTeX files (one or more)')
    parser.add_argument('-o', '--output', help='Output file (outputs to stdout if not specified)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show cross-references (shorthand for --refs-per-section)')
    parser.add_argument('--refs-per-section', action='store_true', help='Show refs at section level')
    parser.add_argument('--refs-per-subsection', action='store_true', help='Show refs at subsection level')
    parser.add_argument('--refs-per-chapter', action='store_true', help='Show refs at chapter level (per file)')
    parser.add_argument('--refs-per-file', action='store_true', help='Show refs at file level (same as --refs-per-chapter)')
    parser.add_argument('--refs-per-document', action='store_true', help='Show refs for entire document')
    parser.add_argument('--refs-per-theorem', action='store_true', help='Show refs for each theorem/lemma/etc')
    parser.add_argument('--refs-type', help='Filter refs by type (comma-separated: theorem,lemma,definition)')
    parser.add_argument('--refs-group-by-type', action='store_true', help='Group refs by element type')
    parser.add_argument('-d', '--different-level', action='store_true', help='Only show refs from different structural level (for theorem: different section or other specified level)')
    parser.add_argument('--no-color', action='store_true', help='Disable terminal colors')
    parser.add_argument('--compact', '-c', action='store_true', help='Output compact tab-separated format optimised for Claude')
    parser.add_argument('-q', '--quiet', action='store_true', default=False, help='Suppress all stderr warnings (alias for --warnings=none)')
    parser.add_argument('--warnings', nargs='?', const='all', default='errors',
        choices=['errors', 'all', 'none'],
        help='Warning level: errors (default, parse failures/file-not-found), all (everything including info), none (suppress all)')
    parser.add_argument('--filter', '-f', metavar='PATTERN', help='Filter output lines by regex (case-insensitive, matches labels, titles, types)')
    parser.add_argument('--review', action='store_true', help='Review preset: --status --hide-ready --only-numbered-results --compact')
    parser.add_argument('--show', metavar='LABEL', help='Show body of labelled element(s); comma-separated for multiple (truncated to 10 lines)')
    parser.add_argument('--show-full', metavar='LABEL', help='Show full body of labelled element(s); comma-separated for multiple')
    parser.add_argument('--show-limit', type=int, metavar='N',
        help='Override line limit for --show (default 10) or --show-full (default unlimited)')
    parser.add_argument('--proof', metavar='LABEL',
        help='Show the proof associated with a labelled theorem/proposition/lemma')
    parser.add_argument('--neighbourhood', '--neighborhood', metavar='LABEL',
        help='Show N elements before and after LABEL (default N=3)')
    parser.add_argument('--neighbourhood-size', type=int, default=3, metavar='N',
        help='Number of elements before/after for --neighbourhood (default 3)')
    parser.add_argument('--extra-env', metavar='NAME[,NAME,...]',
        help='Add custom environment names (comma-separated) to the parser, for environments not declared via \\newtheorem')
    parser.add_argument('--orphan-report', action='store_true',
        help='Find orphaned labels (never referenced) and missing references')
    parser.add_argument('--drafting-report', action='store_true',
        help='List all draftingnotes grouped by file with first line, refs, and context')
    parser.add_argument('--cite-usage', metavar='KEY',
        help='Show where a citation key is used and in what structural context')
    parser.add_argument('--parse-summary', action='store_true',
        help='Print summary of parse results: element counts by type, labelled vs unlabelled')

    # Status options
    status_group = parser.add_argument_group('status overlay',
        'Overlay publication status information on output')
    status_group.add_argument('--status', nargs='?', const='DEFAULT', metavar='FILE',
        help='Load status from FILE (default: MANUSCRIPT_STATUS_SUMMARY.tsv in same directory as first input file)')
    status_group.add_argument('--status-filter', metavar='STATUS[,STATUS...]',
        help='Show only elements with these statuses (e.g., CRITICAL_REVISION,MAJOR_REVISION)')
    status_group.add_argument('--hide-ready', action='store_true',
        help='Hide elements with READY status')

    # Citation analysis options
    cite_group = parser.add_argument_group('citation analysis',
        'Display citation information from \\cite{} commands')
    cite_group.add_argument('--cites-per-section', action='store_true',
        help='Show citations at section level')
    cite_group.add_argument('--cites-per-subsection', action='store_true',
        help='Show citations at subsection level')
    cite_group.add_argument('--cites-per-theorem', action='store_true',
        help='Show citations for each theorem/lemma/definition')
    cite_group.add_argument('--cites-per-document', action='store_true',
        help='Show citations aggregated for entire document')
    cite_group.add_argument('--resolve-cites', action='store_true',
        help='Resolve cite keys to author/year from bibliography.tex')

    # Scope filtering options
    scope_group = parser.add_argument_group('scope filtering',
        'Restrict output to a specific section or line range')
    scope_group.add_argument('--scope', metavar='LABEL',
        help='Restrict output to within the structural element with this label')
    scope_group.add_argument('--depth', type=int, metavar='N',
        help='Limit structural depth to N levels below scope (requires --scope)')
    scope_group.add_argument('--line-range', metavar='START:END',
        help='Restrict output to elements within line range START:END')
    scope_group.add_argument('--paper', metavar='NAME',
        help='Filter output to elements tagged for paper NAME (reads papers/manifest.yaml)')

    # Display filtering options
    filter_group = parser.add_argument_group('display filtering',
        'Control which structural elements and result types are displayed in main output')

    # Structural filtering - Inclusive
    filter_group.add_argument('--only-sections', action='store_true',
        help='Show only section-level elements')
    filter_group.add_argument('--only-subsections', action='store_true',
        help='Show only subsection-level elements')
    filter_group.add_argument('--only-subsubsections', action='store_true',
        help='Show only subsubsection-level elements')

    # Structural filtering - Exclusive
    filter_group.add_argument('--hide-sections', action='store_true',
        help='Hide section-level elements')
    filter_group.add_argument('--hide-subsections', action='store_true',
        help='Hide subsection-level elements')
    filter_group.add_argument('--hide-subsubsections', action='store_true',
        help='Hide subsubsection-level elements')

    # Individual result types - Inclusive
    filter_group.add_argument('--only-theorems', action='store_true',
        help='Show only theorems')
    filter_group.add_argument('--only-lemmas', action='store_true',
        help='Show only lemmas')
    filter_group.add_argument('--only-propositions', action='store_true',
        help='Show only propositions')
    filter_group.add_argument('--only-corollaries', action='store_true',
        help='Show only corollaries')
    filter_group.add_argument('--only-definitions', action='store_true',
        help='Show only definitions')
    filter_group.add_argument('--only-proofs', action='store_true',
        help='Show only proofs')
    filter_group.add_argument('--only-remarks', action='store_true',
        help='Show only remarks')
    filter_group.add_argument('--only-examples', action='store_true',
        help='Show only examples')
    filter_group.add_argument('--only-notes', action='store_true',
        help='Show only notes')
    filter_group.add_argument('--only-claims', action='store_true',
        help='Show only claims')
    filter_group.add_argument('--only-speculative', action='store_true',
        help='Show only research environments: assumption, conjecture, hypothesis, '
             'question, problem, openproblem, false_conjecture')

    # Individual result types - Exclusive
    filter_group.add_argument('--hide-theorems', action='store_true',
        help='Hide theorems')
    filter_group.add_argument('--hide-lemmas', action='store_true',
        help='Hide lemmas')
    filter_group.add_argument('--hide-propositions', action='store_true',
        help='Hide propositions')
    filter_group.add_argument('--hide-corollaries', action='store_true',
        help='Hide corollaries')
    filter_group.add_argument('--hide-definitions', action='store_true',
        help='Hide definitions')
    filter_group.add_argument('--hide-proofs', action='store_true',
        help='Hide proofs')
    filter_group.add_argument('--hide-remarks', action='store_true',
        help='Hide remarks')
    filter_group.add_argument('--hide-examples', action='store_true',
        help='Hide examples')
    filter_group.add_argument('--hide-notes', action='store_true',
        help='Hide notes')
    filter_group.add_argument('--hide-claims', action='store_true',
        help='Hide claims')

    # Grouped filtering - Inclusive
    filter_group.add_argument('--only-numbered-results', action='store_true',
        help='Show only theorem/lemma/proposition/corollary/definition')
    filter_group.add_argument('--only-non-numbered-results', action='store_true',
        help='Show only theorem*/lemma*/proposition*/corollary*/definition*/example*/remark*/note*/claim*/proof*')
    filter_group.add_argument('--only-supporting', action='store_true',
        help='Show only proof/remark/example/note/claim')
    filter_group.add_argument('--only-structural', action='store_true',
        help='Show only section/subsection/subsubsection')

    # Non-numbered results toggle (additive, not exclusive)
    filter_group.add_argument('--show-non-numbered-results', action='store_true',
        help='Include starred environments (theorem*, lemma*, etc.) which are hidden by default. '
             'These typically represent literature results without theorem numbers')

    # Grouped filtering - Exclusive
    filter_group.add_argument('--hide-numbered-results', action='store_true',
        help='Hide theorem/lemma/proposition/corollary/definition')
    filter_group.add_argument('--hide-supporting', action='store_true',
        help='Hide proof/remark/example/note/claim')
    filter_group.add_argument('--hide-structural', action='store_true',
        help='Hide section/subsection/subsubsection')

    # Dependency analysis options
    dep_group = parser.add_argument_group('dependency analysis',
        'Cross-chapter dependency analysis and statistics')
    dep_group.add_argument('--stats', action='store_true',
        help='Show element type frequency table (combine with --per-chapter for chapter x type matrix)')
    dep_group.add_argument('--per-chapter', action='store_true',
        help='Break statistics down by chapter (requires --stats)')
    dep_group.add_argument('--reverse-refs', metavar='LABEL[,LABEL,...]',
        help='Find all elements that reference the given label(s)')
    dep_group.add_argument('--deps-matrix', action='store_true',
        help='Show chapter x chapter cross-reference dependency matrix')
    dep_group.add_argument('--include-self', action='store_true',
        help='Include intra-chapter refs on the diagonal (with --deps-matrix)')
    dep_group.add_argument('--resolve-refs', action='store_true',
        help='Resolve \\ref{label} to element display names in output')
    dep_group.add_argument('--transitive', action='store_true',
        help='Follow reverse refs transitively (unlimited depth). Use with --reverse-refs')
    dep_group.add_argument('--transitive-depth', type=int, metavar='N', default=None,
        help='Maximum depth for transitive reverse refs (implies --transitive)')
    dep_group.add_argument('--min-depth', type=int, metavar='N', default=None,
        help='Show only transitive results at depth >= N (display filter, requires --transitive)')
    dep_group.add_argument('--max-depth', type=int, metavar='N', default=None,
        help='Show only transitive results at depth <= N (display filter, requires --transitive)')
    dep_group.add_argument('--transitive-types', metavar='TYPE[,TYPE,...]', default=None,
        help='Show only these element types in transitive output (e.g., theorem,proposition)')
    dep_group.add_argument('--head', type=int, metavar='N',
        help='Limit output to first N elements after filtering')
    dep_group.add_argument('--json', action='store_true',
        help='Export full parsed structure as JSON')
    dep_group.add_argument('--body', action='store_true',
        help='Include raw LaTeX body text in JSON export (requires --json)')
    dep_group.add_argument('--sizes', action='store_true',
        help='Show (N lines) size annotations for each element')
    dep_group.add_argument('--sizes-summary', action='store_true',
        help='Show summary table of total lines per element type')
    dep_group.add_argument('--aux-file', metavar='PATH',
        help='Path to .aux file for rendered reference display (auto-detected if omitted)')
    dep_group.add_argument('--rendered-refs', action='store_true',
        help='Augment label display with compiled number and page (e.g., "Theorem I.3.2 (p.14)")')
    dep_group.add_argument('--dot-export', metavar='FILE',
        help='Export dependency graph as Graphviz DOT file')
    dep_group.add_argument('--dot-chapter-level', action='store_true',
        help='Use chapter-level granularity for DOT export (default: theorem-level)')
    dep_group.add_argument('--tags', action='store_true',
        help='List all extraction tags (%%<*tag> / %%</tag>) found in source files')
    dep_group.add_argument('--paper-check', metavar='NAME',
        help='Validate paper manifest: check tags exist, refs resolve, dependencies complete')

    args = parser.parse_args()

    # --review preset: expand to --status --hide-ready --only-numbered-results --compact
    if args.review:
        if not args.status:
            args.status = 'DEFAULT'
        args.hide_ready = True
        args.only_numbered_results = True
        args.compact = True

    # Mutual exclusion: --paper and --scope
    if getattr(args, 'paper', None) and args.scope:
        parser.error('--paper and --scope are mutually exclusive')

    # Disable colors if requested or if outputting to file
    if args.no_color or args.output:
        Colors.disable()

    # Determine reference options
    ref_options = {'enabled': False}

    if args.verbose or any([args.refs_per_section, args.refs_per_subsection, args.refs_per_chapter, args.refs_per_file, args.refs_per_document, args.refs_per_theorem]):
        ref_options['enabled'] = True

        # Collect all requested levels (can specify multiple)
        levels = []
        if args.refs_per_theorem:
            levels.append('theorem')
        if args.refs_per_subsection:
            levels.append('subsection')
        if args.refs_per_section:
            levels.append('section')
        if args.refs_per_chapter:
            levels.append('chapter')
        if args.refs_per_file:
            levels.append('file')
        if args.refs_per_document:
            levels.append('document')

        # -v is a shorthand for --refs-per-section, but only if no explicit flag given
        if args.verbose and not levels:
            levels.append('section')

        ref_options['levels'] = levels  # Now a list instead of single value

        # Type filtering
        if args.refs_type:
            ref_options['types_filter'] = [t.strip() for t in args.refs_type.split(',')]

        # Grouping
        ref_options['group_by_type'] = args.refs_group_by_type

        # Different level filtering
        ref_options['different_level'] = args.different_level

    # Build display filter configuration
    filter_config = build_filter_config(args)
    validate_filter_config(args, filter_config)

    # Warning level helpers
    # --warnings (no value) or --warnings=all: show everything
    # --warnings=errors (default): show errors/file-not-found/parse failures
    # --warnings=none: suppress all
    global _warn_errors, _warn_info
    # -q is an alias for --warnings=none
    if args.quiet:
        args.warnings = 'none'
    warn_level = args.warnings  # 'errors' (default), 'all', or 'none'
    warn_errors = warn_level in ('errors', 'all')
    warn_info = warn_level == 'all'
    _warn_errors = warn_errors
    _warn_info = warn_info

    # Load status information if requested
    status_map = None
    status_filter_set = None

    if args.status:
        # Determine status file path
        if args.status == 'DEFAULT':
            # Use default location: MANUSCRIPT_STATUS_SUMMARY.tsv in same dir as first input file
            first_input_dir = os.path.dirname(os.path.abspath(args.input_files[0]))
            status_file = os.path.join(first_input_dir, 'MANUSCRIPT_STATUS_SUMMARY.tsv')
        else:
            status_file = args.status

        if warn_info:
            print(f"Loading status from '{status_file}'...", file=sys.stderr)
        status_map = load_status_file(status_file)
        if warn_info:
            print(f"Loaded status for {len(status_map)} elements", file=sys.stderr)

        # Build status filter set
        if args.status_filter or args.hide_ready:
            status_filter_set = set()

            if args.status_filter:
                # Add explicitly requested statuses
                for status in args.status_filter.split(','):
                    status_filter_set.add(status.strip())

            if args.hide_ready:
                if not args.status_filter:
                    # Collect all statuses actually present, then exclude READY
                    if status_map:
                        status_filter_set = {entry.get('STATUS', '') for entry in status_map.values()} - {'READY', ''}
                    else:
                        status_filter_set = set()
                else:
                    # If explicit filter exists, remove READY from it
                    status_filter_set.discard('READY')

    # Load manifest if needed
    # Load manifest for paper badges and --paper/--paper-check/--tags features
    manifest = None
    label_to_papers = {}
    tag_to_papers = {}
    first_input_dir = os.path.dirname(os.path.abspath(args.input_files[0]))
    manifest_path = os.path.join(first_input_dir, 'papers', 'manifest.yaml')
    if os.path.exists(manifest_path):
        manifest, label_to_papers, tag_to_papers = load_manifest(manifest_path)
        if manifest and warn_info:
            print(f"Loaded manifest with {len(manifest)} paper(s)", file=sys.stderr)
    elif getattr(args, 'paper', None) or getattr(args, 'paper_check', None):
        # Only warn about missing manifest when paper features are explicitly requested
        if warn_errors:
            print(f"Warning: Manifest not found at '{manifest_path}'", file=sys.stderr)

    # Auto-detect \newtheorem declarations and extend the active environment set
    global _active_environments
    detected_envs = scan_newtheorem_declarations(args.input_files)
    new_envs = detected_envs - _active_environments
    if args.extra_env:
        for name in args.extra_env.split(','):
            name = name.strip()
            if name and name not in _active_environments:
                new_envs.add(name)
    if new_envs:
        _active_environments = _active_environments | new_envs
        if warn_info:
            print(f"Detected custom environments: {', '.join(sorted(new_envs))}", file=sys.stderr)

    # Process all input files
    combined_structure = []
    combined_file_contents = {}
    combined_tag_index = {}
    combined_file_structures = {}
    processed_files = set()

    for input_file in args.input_files:
        if warn_info:
            print(f"Reading '{input_file}'...", file=sys.stderr)
        result = extract_latex_structure(input_file, file_contents=combined_file_contents,
                                         processed_files=processed_files,
                                         tag_index=combined_tag_index,
                                         file_structures=combined_file_structures)

        if result is None:
            print(f"Error processing '{input_file}', skipping...", file=sys.stderr)
            continue

        structure, file_contents = result
        combined_structure.extend(structure)

    # Warn about unlabelled sections and duplicate labels
    if warn_info:
        warn_unlabelled_sections(combined_structure)
    if warn_errors:
        duplicates = find_duplicate_labels(combined_structure)
        for dup in duplicates:
            locs = ', '.join(f"{loc['file']}:{loc['line']}" for loc in dup['locations'])
            print(f"Warning: duplicate label '{dup['label']}' at: {locs}", file=sys.stderr)
        if duplicates:
            cross_chapter = [d for d in duplicates
                            if len(set(loc['file'] for loc in d['locations'])) > 1
                            and not any('backup' in loc['file'].lower() for loc in d['locations'])]
            same_file = [d for d in duplicates
                        if len(set(loc['file'] for loc in d['locations'])) == 1]
            print(f"  ({len(duplicates)} duplicate labels: "
                  f"{len(cross_chapter)} cross-chapter, {len(same_file)} same-file)", file=sys.stderr)

    # Build full label set before scope filtering (for "out of scope" display)
    all_label_set = None
    if args.scope:
        all_label_set = {elem[4] for elem in combined_structure if elem[4]}

    # Apply scope filtering
    if args.scope:
        combined_structure = apply_scope_filter(combined_structure, args.scope, combined_file_contents)
    if args.depth is not None and args.scope:
        combined_structure = apply_depth_filter(combined_structure, args.depth)
    if args.line_range:
        combined_structure = apply_line_range_filter(combined_structure, args.line_range)

    # Apply paper filter (alternative to scope)
    if getattr(args, 'paper', None) and manifest:
        paper_labels = get_paper_labels(manifest, args.paper)
        if paper_labels:
            combined_structure = apply_paper_filter(combined_structure, paper_labels)
        else:
            if warn_errors:
                print(f"Warning: paper '{args.paper}' has no tags or not found in manifest", file=sys.stderr)

    # Sort structure once (all downstream functions expect pre-sorted input)
    combined_structure.sort(key=_SORT_KEY)

    # Build label registry (centralised label-to-element mapping)
    label_registry = build_label_registry(combined_structure)

    # Load aux map for rendered refs and/or DOT export
    aux_map = {}
    if getattr(args, 'rendered_refs', False) or getattr(args, 'dot_export', None):
        aux_path = _resolve_aux_path(getattr(args, 'aux_file', None), args.input_files)
        if aux_path:
            if warn_info:
                print(f"Loading aux data from '{aux_path}'...", file=sys.stderr)
            aux_map = parse_aux_file(aux_path)
        elif getattr(args, 'rendered_refs', False) and warn_errors:
            print("Warning: --rendered-refs: no .aux file found, falling back to raw labels",
                  file=sys.stderr)

    # Report results
    total_elements = len(combined_structure)
    if not combined_structure:
        if warn_errors:
            print(f"No structural elements found", file=sys.stderr)
    elif warn_info:
        print(f"Found {total_elements} structural elements across {len(args.input_files)} file(s)", file=sys.stderr)

    # Build citation options
    cite_options = {'enabled': False}
    if any([args.cites_per_section, args.cites_per_subsection, args.cites_per_theorem, args.cites_per_document]):
        cite_options['enabled'] = True
        cite_levels = []
        if args.cites_per_theorem:
            cite_levels.append('theorem')
        if args.cites_per_subsection:
            cite_levels.append('subsection')
        if args.cites_per_section:
            cite_levels.append('section')
        if args.cites_per_document:
            cite_levels.append('document')
        cite_options['levels'] = cite_levels

        # Load bibliography for resolution
        if args.resolve_cites:
            # Find bibliography.tex in same directory as first input file
            first_input_dir = os.path.dirname(os.path.abspath(args.input_files[0]))
            bib_path = os.path.join(first_input_dir, 'bibliography.tex')
            try:
                with open(bib_path, 'r', encoding='utf-8', errors='ignore') as f:
                    bib_text = f.read()
                cite_options['cite_map'] = parse_bibliography(bib_text)
                if warn_info:
                    print(f"Loaded {len(cite_options['cite_map'])} bibliography entries from '{bib_path}'", file=sys.stderr)
            except FileNotFoundError:
                if warn_errors:
                    print(f"Warning: bibliography file '{bib_path}' not found, using raw keys", file=sys.stderr)
                cite_options['cite_map'] = {}
        else:
            cite_options['cite_map'] = {}

    # DOT export (side-effect: writes file, does not replace stdout dispatch)
    if getattr(args, 'dot_export', None):
        scope_for_dot = None
        if hasattr(args, 'reverse_refs') and args.reverse_refs and not getattr(args, 'dot_chapter_level', False):
            scope_for_dot = [l.strip() for l in args.reverse_refs.split(',')]
        transitive_d = getattr(args, 'transitive_depth', None)
        if transitive_d is None and getattr(args, 'transitive', False):
            transitive_d = 0
        dot_text = format_dot_export(
            combined_structure, combined_file_contents, label_registry,
            chapter_level=getattr(args, 'dot_chapter_level', False),
            scope_labels=scope_for_dot,
            transitive_depth=transitive_d,
            aux_map=aux_map if getattr(args, 'rendered_refs', False) else None,
            filter_config=filter_config,
        )
        try:
            with open(args.dot_export, 'w', encoding='utf-8') as f:
                f.write(dot_text)
            if warn_info:
                print(f"DOT graph written to '{args.dot_export}'", file=sys.stderr)
        except Exception as e:
            print(f"Error writing DOT file: {e}", file=sys.stderr)

    # Dispatch to analysis modes or normal output
    if not combined_structure:
        output_text = "No structural elements found."
    elif args.json:
        output_text = format_json_export(combined_structure, combined_file_contents, label_registry, filter_config, status_map, json_body=args.body)
    elif args.sizes_summary:
        output_text = format_sizes_summary(combined_structure, combined_file_contents, filter_config, args.compact)
    elif args.stats:
        if args.per_chapter:
            output_text = format_stats_per_chapter(combined_structure, filter_config, args.compact, status_map)
        else:
            output_text = format_stats(combined_structure, filter_config, args.compact)
    elif args.reverse_refs:
        labels = [l.strip() for l in args.reverse_refs.split(',')]
        transitive_val = None
        if args.transitive or args.transitive_depth is not None:
            transitive_val = args.transitive_depth if args.transitive_depth is not None else 0
        type_filter = args.transitive_types.split(',') if args.transitive_types else None
        output_text = format_reverse_refs(labels, combined_structure, combined_file_contents, label_registry, args.compact, args.resolve_refs, transitive=transitive_val, min_depth=args.min_depth, max_depth=args.max_depth, type_filter=type_filter, aux_map=aux_map if getattr(args, 'rendered_refs', False) else None)
    elif args.deps_matrix:
        output_text = format_deps_matrix(combined_structure, combined_file_contents, label_registry, args.include_self, args.compact)
    elif args.tags:
        output_text = format_tags(combined_tag_index, args.compact)
    elif args.paper_check:
        if not manifest:
            output_text = f"Error: paper '{args.paper_check}' not found in manifest (manifest not loaded)."
        elif args.paper_check not in manifest:
            output_text = f"Error: paper '{args.paper_check}' not found in manifest. Available: {', '.join(sorted(manifest.keys()))}"
        else:
            output_text = format_paper_check(
                validate_paper(args.paper_check, manifest, combined_tag_index,
                               combined_structure, combined_file_contents, label_registry),
                args.compact)
    elif args.orphan_report:
        output_text = format_orphan_report(combined_structure, combined_file_contents, label_registry)
    elif args.drafting_report:
        output_text = format_drafting_report(combined_structure, combined_file_contents, label_registry, status_map)
    elif args.cite_usage:
        output_text = format_cite_usage(args.cite_usage, combined_structure, combined_file_contents, label_registry)
    elif args.parse_summary:
        output_text = format_parse_summary(combined_structure, combined_file_contents)
    elif args.proof:
        truncate_val = args.show_limit  # reuse --show-limit if provided
        output_text = format_proof(args.proof, combined_structure,
                                   combined_file_contents, label_registry, truncate=truncate_val)
    elif args.neighbourhood:
        output_text = format_neighbourhood(
            args.neighbourhood, combined_structure, combined_file_contents,
            label_registry, n=args.neighbourhood_size, compact=args.compact,
            ref_options=ref_options, filter_config=filter_config,
            status_map=status_map, status_filter=status_filter_set,
            cite_options=cite_options, known_labels=all_label_set,
            sizes=args.sizes,
            aux_map=aux_map if getattr(args, 'rendered_refs', False) else None,
            label_to_papers=label_to_papers)
    elif args.show or args.show_full:
        raw_label = args.show or args.show_full
        if args.show_limit is not None:
            truncate = args.show_limit
        else:
            truncate = 10 if args.show else None
        labels = [l.strip() for l in raw_label.split(',') if l.strip()]
        parts = []
        for lbl in labels:
            parts.append(format_show(lbl, combined_structure, combined_file_contents, label_registry, truncate=truncate))
        output_text = '\n---\n'.join(parts)
    else:
        # Normal structure output
        if args.compact:
            output_text = format_compact_output(combined_structure, combined_file_contents, ref_options, filter_config, status_map, status_filter_set, cite_options, label_registry, known_labels=all_label_set, sizes=args.sizes, aux_map=aux_map if getattr(args, 'rendered_refs', False) else None, label_to_papers=label_to_papers)
        else:
            output_text = format_output(combined_structure, combined_file_contents, ref_options, filter_config, status_map, status_filter_set, cite_options, label_registry, known_labels=all_label_set, sizes=args.sizes, aux_map=aux_map if getattr(args, 'rendered_refs', False) else None, label_to_papers=label_to_papers)

    # Apply --filter regex (post-filter on output lines)
    if args.filter:
        pattern = re.compile(args.filter, re.IGNORECASE)
        lines = output_text.split('\n')
        output_text = '\n'.join(line for line in lines if pattern.search(line))

    # Append out-of-scope summary if --scope active
    if args.scope and output_text:
        if args.compact:
            oos_count = output_text.count('(oos)')
        else:
            oos_count = output_text.count('(out of scope)')
        if oos_count > 0:
            output_text += f"\n[{oos_count} cross-chapter ref(s) hidden by --scope; drop --scope or use main document to see them]"

    # Apply --head limit (post-filter truncation)
    if args.head is not None and args.head > 0:
        lines = output_text.split('\n')
        if len(lines) > args.head:
            output_text = '\n'.join(lines[:args.head])

    # Output to file or stdout
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output_text)
            print(f"Structure saved to '{args.output}'", file=sys.stderr)
        except Exception as e:
            print(f"Error writing to output file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            print(output_text)
            sys.stdout.flush()
        except BrokenPipeError:
            # Suppress BrokenPipeError when piping to commands like head
            pass


if __name__ == '__main__':
    main()
