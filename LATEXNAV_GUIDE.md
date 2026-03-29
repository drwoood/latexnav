# LaTeX Navigator — Detailed Reference Guide

This is the full feature reference for `latexnav`. For quickstart and installation, see [README.md](README.md).

## Output formats

- **Terminal display** (default): Colour-coded, hierarchical tree view
- **Compact mode** (`--compact`): Tab-separated format for programmatic use and LLM context

## Why use this tool

Manuscript edits cause line numbers to shift — adding a lemma or remark pushes all subsequent content down, making hardcoded line references stale. `latexnav` provides authoritative line numbers by parsing the LaTeX structure directly, rather than relying on potentially outdated references.

## Multi-file projects

For cross-file reference resolution (e.g., `--refs-per-theorem`, `--reverse-refs`), pass the main document file (the one with `\input` commands) — it follows all `\input` chains so the summariser can resolve all labels across files. Use individual chapter files for faster, focused queries within a single file. The `.aux` file is the ground truth for whether labels compile correctly — check it with `grep 'newlabel{thm:foo}' main.aux`.

## Status tracking

If you use a status TSV file (default name: `MANUSCRIPT_STATUS_SUMMARY.tsv`), always include `--status` when exploring sections you plan to modify. Status notes can contain critical information from reviews — known errors, proof gaps, internal inconsistencies. A result that looks correct in the LaTeX source may have known problems recorded only in the status tracking.

## Filtering model (orthogonal two-dimensional)

Filtering operates on two independent dimensions:

- **Structural dimension**: controls which section levels to show (section/subsection/subsubsection)
- **Content dimension**: controls which result types to show (theorem/definition/proof/remark/etc.)

The `--only-*` flags create a whitelist for their dimension; `--hide-*` flags create a blacklist applied subtractively after the whitelist. Cascade rules: `--hide-subsections` also hides subsubsections; `--hide-sections` hides all structural levels.

*Structural filtering:*
- `--only-sections` — Restrict structural display to sections (content elements still shown)
- `--only-subsections` — Restrict to subsections
- `--hide-subsections` — Hide subsections **and** subsubsections (cascade)
- `--hide-subsubsections` — Hide subsubsections only

*Content type filtering:*
- `--only-theorems`, `--only-lemmas`, `--only-propositions`, `--only-corollaries`
- `--only-definitions` — Show only definitions
- `--hide-proofs`, `--hide-remarks`, `--hide-examples` — Hide supporting material
- **Combining**: `--only-numbered-results --hide-definitions` shows theorems/lemmas/propositions/corollaries but NOT definitions

*Grouped filtering:*
- `--only-numbered-results` — Show theorems, lemmas, propositions, corollaries, definitions
- `--hide-supporting` — Hide proofs, remarks, examples, notes
- `--only-structural` — Show sections/subsections/subsubsections only (hides all content)

## Viewing statements and proofs

- `--show LABEL` — Show the body of a labelled environment (truncated to 10 lines). Accepts comma-separated labels for multiple results (separated by `---`). Strips `\label{}` lines and normalises indentation. Header shows type, title, file, and line number
- `--show-full LABEL` — Like `--show` but without truncation. Also accepts comma-separated labels
- `--show-limit N` — Override the line limit for `--show` (default 10) or `--show-full` (default unlimited). Also applies to `--proof`
- `--proof LABEL` — Show the proof associated with a theorem/proposition/lemma. Finds proof by explicit `\ref{label}` in proof title, or by proximity (next proof with no intervening provable element)
- `--neighbourhood LABEL` (`--neighborhood`) — Show ±N elements before and after a labelled element in document order (default N=3). Respects `--compact` and other display options
- `--neighbourhood-size N` — Override the number of elements shown before/after (default 3)

## Finding and filtering

- `--filter PATTERN` (`-f`) — Post-filter output lines by case-insensitive regex on labels, titles, and types. Replaces `| grep`. Works with all output modes
- `--scope LABEL_OR_TITLE` — Restrict output to within a section. Accepts an exact label (e.g., `--scope sec:intro`) or a title substring for fuzzy matching (e.g., `--scope "spectral theory"`). If the term matches multiple elements, an error lists all matches. Works at all structural levels
- `--depth N` — Limit structural depth to N levels below scope (requires `--scope`)
- `--line-range START:END` — Restrict output to elements within a line range

**`--scope` and reference labels:** When using `--scope`, the summariser restricts label lookup to elements within the scope. References to labels outside the scope display as "(out of scope)" in terminal mode and `(oos)` in compact mode, distinguishing them from truly missing labels which show "(not found)" / `(!)`. To verify cross-file references, either run without `--scope` or check the `.aux` file.

## Reference analysis

- `--refs-per-theorem` — Show cross-references for each theorem/lemma/definition
- `--refs-per-section` — Group refs by section
- `--refs-per-chapter` — Group refs by chapter (file)
- `-d`, `--different-level` — Only show refs from different structural levels (filters out refs within same section)
- `--refs-type theorem,lemma` — Filter to show only references to specific types

Reference extraction covers `\ref{}`, `\cref{}`, `\Cref{}`, and `\eqref{}`, including comma-separated labels in `\cref{a,b}`.

## Citation analysis

- `--cites-per-section` — Show `\cite{}` keys at section level
- `--cites-per-subsection` — Show citations at subsection level
- `--cites-per-theorem` — Show citations for each theorem/lemma/definition
- `--cites-per-document` — Aggregate all citations across the document
- `--resolve-cites` — Resolve cite keys to author/year from bibliography.tex

## Status overlay

- `--status [FILE]` — Overlay publication status from TSV file (default: MANUSCRIPT_STATUS_SUMMARY.tsv)
- `--status-filter STATUS1,STATUS2` — Show only elements with specific statuses (e.g., CRITICAL_REVISION,MAJOR_REVISION)
- `--hide-ready` — Hide elements marked as READY (focus on items needing work)
- `--review` — Preset that expands to `--status --hide-ready --only-numbered-results --compact`

## Report modes

- `--orphan-report` — Find orphaned labels (defined but never referenced) and missing references (referenced but never defined). Reports which elements reference missing labels
- `--drafting-report` — Structured listing of all `draftingnote` and `reasoning` environments, grouped by file. Shows line number, type, label, optional title, `\ref` targets inside the note, and first line of body text
- `--cite-usage KEY` — Show where a citation key is used: lists all elements containing `\cite{...KEY...}` with type, label, file, line, and parent section context
- `--parse-summary` — Element counts by type, file count, labelled vs unlabelled totals

## Dependency analysis

- `--stats` — Element type frequency table for current filtered view
- `--stats --per-chapter` — Chapter x element type matrix
- `--reverse-refs LABEL[,LABEL,...]` — Find all elements that reference the given label(s)
- `--transitive` — Follow reverse refs transitively with unlimited depth (use with `--reverse-refs`). Output includes `depth:N` annotations and a stats header
- `--transitive-depth N` — Follow reverse refs transitively with maximum depth N (implies `--transitive`)
- `--min-depth N` — Show only transitive results at depth >= N (display filter, post-BFS)
- `--max-depth N` — Show only transitive results at depth <= N (display filter, post-BFS)
- `--transitive-types TYPE[,TYPE,...]` — Show only these element types in transitive output (e.g., `theorem,proposition`)
- `--deps-matrix` — Chapter x chapter cross-reference dependency matrix
- `--deps-matrix --include-self` — Include intra-chapter ref counts on the diagonal
- `--resolve-refs` — Resolve `\ref{label}` to element display names in `--reverse-refs` output

## Export and output control

- `--json` — Export full parsed structure as JSON with proof-theorem linking, line ranges, and subsection tracking
- `--body` — Include raw LaTeX body text in JSON export (requires `--json`). Skips sections/subsections
- `--compact` — Tab-separated output format (one line per element)
- `--sizes` — Show `(N lines)` size annotations in text output (compact and terminal modes)
- `--sizes-summary` — Show summary table of total lines per element type (standalone output mode)
- `--head N` — Limit output to first N lines
- `-o FILE` — Write output to file instead of stdout
- `--no-color` — Disable terminal colours

## DOT dependency graphs

- `--dot-export FILE` — Export dependency graph as Graphviz DOT file. At theorem level, nodes are theorem/lemma/definition environments grouped in per-file subgraph clusters; edges follow `\ref{}` citations. When combined with `--reverse-refs LABEL`, the graph is scoped to nodes that (transitively) reference LABEL. At chapter level, nodes are files with cross-reference counts on edges
- `--dot-chapter-level` — Use chapter-level granularity for DOT export (default: theorem-level). Best for overview graphs; theorem-level works best when scoped with `--reverse-refs --transitive-depth N`

Render DOT files with: `dot -Tsvg deps.dot > deps.svg`

## Compiled reference display (aux file integration)

- `--rendered-refs` — Augment every label with its compiled PDF number and page from the `.aux` file (e.g., `→ Theorem 3.2 (p.14)` in terminal; `→rendered:Theorem 3.2 (p.14)` in compact TSV). The `.aux` file is auto-detected by same-stem matching (e.g., `main.tex` → `main.aux`). Requires a recent LaTeX compile
- `--aux-file PATH` — Specify the `.aux` file path explicitly (overrides auto-detection)

## Parsed environments

Custom `\newtheorem` declarations in scanned files are auto-detected. Use `--extra-env NAME[,NAME,...]` to add environments defined in `.sty` files or other non-scanned locations.

- `--only-speculative` — Show only research environments: assumption, conjecture, hypothesis, question, problem, openproblem, false_conjecture
- `--show-non-numbered-results` — Include starred variants (e.g., `theorem*`) which are hidden by default

## Warning levels

- `--warnings [LEVEL]` — Warning level: `errors` (default), `all`, `none`. `--warnings` without a value = `all`
- `-q`, `--quiet` — Alias for `--warnings=none`

## Example queries

```bash
# Show a theorem's statement directly
latexnav --show thm:main_result main.tex

# Show multiple statements at once
latexnav --show thm:main_result,def:widget main.tex

# Show with custom line limit
latexnav --show thm:main_result --show-limit 20 main.tex

# Show the proof of a theorem
latexnav --proof thm:main_result chapter1.tex

# Show neighbourhood context (±3 elements around a result)
latexnav --neighbourhood thm:main_result chapter1.tex

# Neighbourhood with custom size and compact output
latexnav --neighbourhood thm:main_result --neighbourhood-size 5 --compact chapter1.tex

# Find a label with built-in filter (replaces | grep)
latexnav --compact --filter "thm:main" *.tex

# Review workflow preset
latexnav --review *.tex

# List all drafting notes
latexnav --compact --filter draftingnote *.tex

# Structured drafting note report
latexnav --drafting-report *.tex

# Find orphaned labels and missing references
latexnav --orphan-report main.tex

# Where is a citation key used?
latexnav --cite-usage AuthorYear main.tex

# Parse summary (element counts)
latexnav --parse-summary main.tex

# Quick overview: all theorems and their dependencies
latexnav --only-theorems --refs-per-theorem main.tex

# Compact format for LLM context
latexnav --compact --only-numbered-results main.tex

# Find all definitions in a specific file
latexnav --only-definitions chapter2.tex

# Show structure without proofs and remarks
latexnav --hide-proofs --hide-remarks main.tex

# Find what theorems reference a specific definition
latexnav --only-theorems --refs-per-theorem main.tex | grep "def:widget"

# Section-level overview with cross-file references
latexnav --only-sections --refs-per-chapter -d main.tex

# Show publication status with structure overview
latexnav --status --only-sections main.tex

# Find all critical issues
latexnav --status --status-filter CRITICAL_REVISION main.tex

# Focus on items needing work
latexnav --status --hide-ready --only-numbered-results main.tex

# Compact format with all status information
latexnav --compact --status main.tex

# Show citations with author/year resolution
latexnav --cites-per-section --resolve-cites chapter1.tex

# Focus on a specific section
latexnav --scope sec:intro --only-theorems --refs-per-theorem chapter1.tex

# Show elements in a line range
latexnav --line-range 100:200 chapter1.tex

# Numbered results minus definitions
latexnav --only-numbered-results --hide-definitions main.tex

# Reverse reference lookup
latexnav --reverse-refs thm:main_result main.tex

# Cross-file dependency matrix
latexnav --deps-matrix main.tex

# Element type statistics per file
latexnav --stats --per-chapter main.tex

# Export full structure as JSON
latexnav --json main.tex > structure.json

# JSON with body text
latexnav --json --body chapter1.tex > ch1_body.json

# Scope a specific subsection
latexnav --scope subsec:background chapter1.tex

# Transitive reverse references (full dependency chain)
latexnav --reverse-refs def:widget --transitive main.tex

# Size annotations in compact output
latexnav --compact --sizes chapter1.tex

# Find all conjectures, hypotheses, and open questions
latexnav --only-speculative *.tex

# Transitive refs filtered to depth 2-4, theorems only
latexnav --reverse-refs thm:main_result --transitive --min-depth 2 --max-depth 4 --transitive-types theorem main.tex

# Size summary: lines per element type
latexnav --sizes-summary chapter1.tex

# Show compiled PDF numbers/pages alongside labels (requires .aux file)
latexnav --rendered-refs --compact main.tex | grep "thm:main_result"

# Rendered refs in terminal output for a section
latexnav --rendered-refs --only-theorems --scope sec:intro main.tex

# Chapter-level dependency graph (render with: dot -Tsvg chapter.dot > chapter.svg)
latexnav --dot-export chapter.dot --dot-chapter-level main.tex

# Focused theorem-level dependency graph: 2-hop reverse references
latexnav --reverse-refs thm:main_result --transitive-depth 2 --dot-export deps.dot main.tex

# Combined: rendered labels in both stdout and DOT node labels
latexnav --rendered-refs --reverse-refs thm:main_result --transitive-depth 2 --dot-export deps.dot main.tex
```

## Common workflows

| Task | Command |
|------|---------|
| Before modifying a theorem | `latexnav --reverse-refs LABEL main.tex` then `latexnav --show LABEL *.tex` |
| Explore a section (with issues) | `latexnav --status --scope sec:foo chapter.tex` |
| Finding all definitions | `latexnav --only-definitions --compact main.tex` |
| Understanding file dependencies | `latexnav --deps-matrix main.tex` |
| Locating a specific result | `latexnav --compact --filter "thm:foo" main.tex` |
| Quick structural overview | `latexnav --only-sections --only-numbered-results main.tex` |
| Check publication status | `latexnav --status --only-sections main.tex` |
| Find critical issues | `latexnav --status --status-filter CRITICAL_REVISION,MAJOR_REVISION main.tex` |
| Review what needs work | `latexnav --review *.tex` |
| What does a section cite? | `latexnav --scope sec:intro --cites-per-theorem chapter1.tex` |
| Section-scoped structure | `latexnav --scope sec:intro --depth 1 chapter1.tex` |
| Cross-file refs (full manuscript) | `latexnav --refs-per-theorem main.tex \| grep "thm:foo"` |
| Verify a label compiles | `grep 'newlabel{thm:foo}' main.aux` |
| Results not yet ready | `latexnav --status --hide-ready chapter.tex` |
| Transitive dependency chain | `latexnav --reverse-refs LABEL --transitive main.tex` |
| Element type statistics | `latexnav --stats --per-chapter main.tex` |
| Export for programmatic analysis | `latexnav --json main.tex` |
| Pre-submission orphan check | `latexnav --orphan-report main.tex` |
| Drafting note inventory | `latexnav --drafting-report *.tex` |
| Citation audit | `latexnav --cite-usage AuthorYear main.tex` |
