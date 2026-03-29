# LaTeX Navigator and Structure Summariser

A single-file Python tool for navigating large LaTeX manuscripts. Parses theorems, definitions, sections, labels, cross-references, and dependencies, producing structural summaries with authoritative line numbers.

Designed for mathematical manuscripts with hundreds of labelled environments across multiple files — the kind where grepping for a theorem name returns 30 matches and you need to know which one is the definition vs which ones reference it.

> "Very useful — it's the single most important navigation tool for this manuscript. Before any manuscript task, I use it to orient: find labels, check what's in a section, trace reverse references, see status. Without it, I'd be grepping through 3000+ line LaTeX files blind. For a manuscript of this complexity (6 chapters, hundreds of theorems/labels, cross-chapter dependencies), it's essentially indispensable."
>
> — *Opus 4.6*

> "Based on using it repeatedly on this manuscript, my honest view is that latexnav.py is genuinely useful and above-average for research-manuscript navigation. It is one of the few local tools here that consistently saves time before opening raw .tex."
>
> — *GPT 5.4*

**Built for LLM agent workflows.** When an AI agent (Claude, GPT, Gemini, etc.) works with a large LaTeX manuscript via a CLI tool like Claude Code, Codex, or OpenCode, it faces a fundamental problem: reading raw `.tex` files consumes thousands of context tokens, and the agent has no structural awareness of what theorems exist, what depends on what, or where a proof starts. This tool gives the agent a way to navigate the manuscript structurally — view a theorem statement in 3 lines instead of reading a 200-line file, check reverse dependencies before modifying a result, or get a compact overview of an entire chapter. The `--compact` output mode produces tab-separated summaries optimised for LLM context windows, and the `--show`/`--proof`/`--neighbourhood` commands let agents retrieve exactly the content they need without loading surrounding material.

The tool is equally useful for human navigation from the terminal — colour-coded output, fuzzy scope matching, and `--help` with 25 examples make it practical for direct use.

**Key capabilities:**
- View theorem statements and proofs without opening the file (`--show`, `--proof`)
- Trace what depends on a result before modifying it (`--reverse-refs`)
- Find orphaned labels and missing references (`--orphan-report`)
- Overlay publication status from a TSV file (`--status`)
- Export structure as JSON, DOT dependency graphs, or compact TSV

**Requirements:** Python 3.8+, standard library only. Optional: PyYAML (for manifest features).

## Installation

Copy `latexnav.py` into your project root. No dependencies to install.

```bash
# That's it. Run with:
python3 latexnav.py --help
python3 latexnav.py *.tex
```

**Using with an LLM agent?** See [LLM agent integration](#llm-agent-integration) for setup. The quickest path: tell the agent to read this README and set up its memory/instructions files as suggested in that section.

## Quickstart

```bash
# Structural overview of your manuscript
python3 latexnav.py --only-sections --only-numbered-results main.tex

# View a theorem's statement (10 lines) or full body
python3 latexnav.py --show thm:main_result chapter1.tex
python3 latexnav.py --show-full thm:main_result chapter1.tex

# View multiple statements at once
python3 latexnav.py --show thm:main_result,lem:helper chapter1.tex

# View the proof of a theorem
python3 latexnav.py --proof thm:main_result chapter1.tex

# What's near a result? (±3 elements by default)
python3 latexnav.py --neighbourhood thm:main_result chapter1.tex

# Find a label (built-in regex filter, replaces | grep)
python3 latexnav.py --compact --filter "thm:main" *.tex

# Focus on a section (by label or title substring)
python3 latexnav.py --scope sec:introduction chapter1.tex
python3 latexnav.py --scope "spectral theory" chapter2.tex

# Who references this result?
python3 latexnav.py --reverse-refs thm:main_result main.tex

# Full transitive dependency chain
python3 latexnav.py --reverse-refs thm:main_result --transitive main.tex

# Cross-file dependency matrix
python3 latexnav.py --deps-matrix main.tex
```

Use the main document file (the one with `\input` commands) for cross-file reference resolution. Individual chapter files cannot resolve labels from other files.

## Feature overview

| Category | Key flags | Purpose |
|----------|-----------|---------|
| Viewing | `--show`, `--show-full`, `--proof`, `--neighbourhood` | View statements, proofs, and context without opening files |
| Finding | `--filter`, `--scope`, `--line-range` | Locate results by label, title, or line range |
| References | `--reverse-refs`, `--deps-matrix`, `--refs-per-theorem` | Trace dependencies and cross-references |
| Reports | `--orphan-report`, `--drafting-report`, `--cite-usage`, `--parse-summary` | Structural analysis and cleanup |
| Status | `--status`, `--hide-ready`, `--review` | Publication status overlay from TSV |
| Export | `--json`, `--compact`, `--dot-export`, `--sizes` | Machine-readable output |
| Display | `--only-theorems`, `--hide-proofs`, `--only-sections` | Filter by structural level and element type |

Reference extraction covers `\ref{}`, `\cref{}`, `\Cref{}`, and `\eqref{}`, including comma-separated labels in `\cref{a,b}`.

Run `python3 latexnav.py --help` for the complete flag reference with examples.

## Common workflows

**Before modifying a theorem:** check what depends on it, then view the statement.
```bash
python3 latexnav.py --reverse-refs thm:main_result main.tex
python3 latexnav.py --show thm:main_result chapter1.tex
```

**Pre-submission cleanup:** find orphaned labels, unused definitions, and missing references.
```bash
python3 latexnav.py --orphan-report main.tex
```

**Review workflow:** see all results that need work (hides READY items).
```bash
python3 latexnav.py --review *.tex
# Equivalent to: --status --hide-ready --only-numbered-results --compact
```

**Citation audit:** check where a specific reference is used.
```bash
python3 latexnav.py --cite-usage AuthorYear main.tex
```

**Export for scripting:** compact TSV output, one line per element.
```bash
python3 latexnav.py --compact --refs-per-theorem main.tex > structure.tsv
```

## Parsed environments

The summariser automatically detects `\newtheorem` declarations in your files. Standard environments are recognised out of the box:

- **Numbered:** theorem, definition, lemma, proposition, corollary
- **Supporting:** proof, remark, example, note, claim
- **Research:** assumption, conjecture, hypothesis, question, problem, openproblem

Starred variants (e.g. `theorem*`) are parsed but hidden by default; use `--show-non-numbered-results` to include them.

For environments defined in `.sty` files that aren't scanned, use `--extra-env NAME[,NAME,...]`.

### Draftingnote and reasoning environments (optional)

The summariser also recognises two meta-environments for mathematical development workflow:

- **`draftingnote`** — marks uncertainties, gaps, or points requiring verification in a proof or derivation. Useful during drafting to flag steps that need checking without interrupting the mathematical flow.
- **`reasoning`** — marks intermediate reasoning or scratch work that may not appear in the final version. Useful for helping the model to think and recording why a particular approach was taken.

These are **entirely optional** — the summariser works without them. If you use them, they appear as structural elements in the output, enabling `--drafting-report` (structured listing with first line, refs, and context) and `--filter draftingnote` (quick listing).

**Defining the environments.** Add to your preamble (requires the `mdframed` package):

```latex
\usepackage{mdframed}

\newenvironment{draftingnote}
  {\begin{mdframed}[linecolor=red,linewidth=1.5pt]
    \textbf{Drafting note:}\par\small}
  {\end{mdframed}}

\newenvironment{reasoning}
  {\begin{mdframed}[linecolor=black!50!magenta!50,linewidth=1.5pt]
    \emph{Reasoning:}\par\small}
  {\end{mdframed}}
```

You can use any visual styling — the summariser matches on the environment name, not the formatting.

**Using with an LLM agent.** If you use an AI assistant (Claude Code, Codex, OpenCode, etc.) to help with mathematical writing, add something like this to your agent's instructions file:

```markdown
## Special environments

Your LaTeX context includes two environments for mathematical development:

- `\begin{draftingnote} ... \end{draftingnote}`: Use this for uncertainties,
  gaps, or points requiring verification. If you produce a proof and cannot
  ensure it is complete and correct, you MUST include a draftingnote explaining
  what is uncertain.
- `\begin{reasoning} ... \end{reasoning}`: Use this when you need to reason
  through part of a proof or derivation within the LaTeX output.
```

This prompts the agent to use draftingnotes for honest uncertainty tracking rather than silently producing questionable proofs.

## Status tracking (optional)

Create a TSV file (default name: `MANUSCRIPT_STATUS_SUMMARY.tsv`) with columns:

```
FILE	LABEL	STATUS	DESCRIPTION	MATH_ISSUES
```

Valid statuses: `READY`, `MINOR_REVISION`, `MAJOR_REVISION`, `CRITICAL_REVISION`, `PLACEHOLDER`, `DEPRECATED`

Then use `--status` to overlay status on output, `--hide-ready` to focus on items needing work, or `--review` as a shortcut for the full review workflow.

## Warning levels

Stderr output is controlled by `--warnings`:

| Level | Flag | Shows |
|-------|------|-------|
| errors (default) | (no flag needed) | Duplicate labels, missing files, parse failures |
| all | `--warnings` | Everything including loading messages |
| none | `--warnings=none` or `-q` | Suppress all stderr |

## LLM agent integration

The summariser's compact output mode (`--compact`) produces tab-separated output optimised for LLM context windows. This makes it a structural navigation tool that AI agents can invoke instead of reading raw `.tex` files — saving tokens and giving the agent awareness of the manuscript's logical structure.

### Documentation strategy

For LLM agents, we recommend a **two-tier documentation approach** to manage context window cost:

1. **Concise snippet** (~15 lines) in your always-loaded instructions file (e.g., `.claude/CLAUDE.md`, `AGENTS.md`). Covers: what the tool is, when to use it, 10-row command table, key caveats.
2. **Detailed reference** in a separate file the agent reads on demand (e.g., `DOCUMENT_GUIDE.md`). Covers: full feature reference, all flags, edge cases, filtering model, paper workflow.

This keeps the base context small while making the full reference accessible when needed.

### Concise snippet (for always-loaded context)

Paste this into your agent's main instructions file. Adapt the file paths to your project.

````markdown
## LaTeX structure navigation

Use `latexnav.py` before reading raw .tex files. It parses LaTeX
directly, so line numbers are always current. Stderr shows errors by default;
use `--warnings` for all diagnostics or `-q` to suppress.

| Task | Command |
|------|---------|
| Show theorem statement | `python3 latexnav.py --show thm:foo *.tex` |
| Show multiple statements | `python3 latexnav.py --show thm:foo,lem:bar *.tex` |
| Show a theorem's proof | `python3 latexnav.py --proof thm:foo *.tex` |
| Context around a result | `python3 latexnav.py --neighbourhood thm:foo *.tex` |
| Find a label | `python3 latexnav.py --compact --filter "thm:foo" *.tex` |
| Who references X? | `python3 latexnav.py --reverse-refs LABEL main.tex` |
| Review workflow | `python3 latexnav.py --review *.tex` |
| Cross-file dependencies | `python3 latexnav.py --deps-matrix main.tex` |
| Orphaned/missing labels | `python3 latexnav.py --orphan-report main.tex` |
| Drafting note report | `python3 latexnav.py --drafting-report *.tex` |

**Key caveats:**
- Use the main document file (with `\input` commands) for cross-file ref resolution
- `--scope LABEL` restricts the label lookup table; refs outside scope show as `(oos)` in compact / `(out of scope)` in terminal — drop `--scope` to verify
- `--compact` produces tab-separated output optimised for LLM parsing
````

### Detailed reference (for on-demand context)

For the full feature reference, create a separate file (e.g., `DOCUMENT_GUIDE.md`) that the agent reads when it needs detailed information about a specific feature. This should cover:

- Complete flag reference with descriptions
- The orthogonal filtering model (structural × content dimensions, `--only-*` / `--hide-*`)
- Reference analysis options (`--refs-per-*`, `--refs-type`, `--different-level`)
- Citation analysis (`--cites-per-*`, `--resolve-cites`)
- Scope filtering details (exact label, fuzzy title matching, `(oos)` vs `(!)` annotations)
- Status overlay (TSV format, `--status-filter`, `--hide-ready`)
- Dependency analysis (`--reverse-refs`, `--transitive`, depth controls, type filters)
- JSON export fields and proof-theorem linking
- DOT graph export (chapter-level and theorem-level)
- Compiled reference display (`--rendered-refs`, `.aux` file integration)
- Paper extraction workflow (`--tags`, `--paper`, `--paper-check`)

Instruct the agent to read this file when it needs details beyond the concise command table.

### Target CLI tools

| CLI tool | Always-loaded file | On-demand file |
|----------|-------------------|----------------|
| Claude Code | `.claude/CLAUDE.md` | `.claude/docs/DOCUMENT_GUIDE.md` |
| Codex (GPT) | `AGENTS.md` | `DOCUMENT_GUIDE.md` |
| OpenCode | `PROJECT_SETUP.md` | `DOCUMENT_GUIDE.md` |
| Gemini CLI | `GEMINI.md` | `DOCUMENT_GUIDE.md` |

## Licence

MIT. See [LICENSE](LICENSE).
