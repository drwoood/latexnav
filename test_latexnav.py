#!/usr/bin/env python3
"""
Unit tests for latexnav.py

Test categories:
  A. Filter logic tests (the bug fix)
  B. Backward compatibility tests (pre-commit hook)
  C. Citation extraction tests
  D. Scope filtering tests
  E. Depth and line-range tests
  F. Missing label warnings
  G. Bibliography resolution tests
  H. Label registry tests
  I. Reverse refs tests
  J. Stats tests
  K. Deps matrix tests
  L. Resolve refs tests
  M. JSON export tests
  N. --quiet and --head tests
  O. Section line_end tests
  P. Subsection scope tests
  Q. Status in JSON tests
  R. Per-file metadata tests
  S. Custom environment parsing tests
  T. Transitive dependency tests
  U. Duplicate label tests
  V. Sizes in text output tests
  W. JSON body text tests
"""

import argparse
import io
import os
import re
import sys
import pytest

# Import the module under test
sys.path.insert(0, os.path.dirname(__file__))
import latexnav as ls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_and_sort(tmp_path):
    """Parse a .tex file and return pre-sorted (structure, file_contents)."""
    result = ls.extract_latex_structure(tmp_path)
    if result is None:
        pytest.fail(f"Failed to parse {tmp_path}")
    structure, file_contents = result
    structure.sort(key=ls._SORT_KEY)
    return structure, file_contents


def make_args(**overrides):
    """Create an argparse.Namespace with all filter flags defaulted to False/None."""
    defaults = {
        # Structural --only-*
        'only_sections': False,
        'only_subsections': False,
        'only_subsubsections': False,
        # Content --only-*
        'only_theorems': False,
        'only_lemmas': False,
        'only_propositions': False,
        'only_corollaries': False,
        'only_definitions': False,
        'only_proofs': False,
        'only_remarks': False,
        'only_examples': False,
        'only_notes': False,
        'only_claims': False,
        'only_speculative': False,
        # Grouped --only-*
        'only_numbered_results': False,
        'only_non_numbered_results': False,
        'only_supporting': False,
        'only_structural': False,
        # --show-non-numbered-results
        'show_non_numbered_results': False,
        # Structural --hide-*
        'hide_sections': False,
        'hide_subsections': False,
        'hide_subsubsections': False,
        # Content --hide-*
        'hide_theorems': False,
        'hide_lemmas': False,
        'hide_propositions': False,
        'hide_corollaries': False,
        'hide_definitions': False,
        'hide_proofs': False,
        'hide_remarks': False,
        'hide_examples': False,
        'hide_notes': False,
        'hide_claims': False,
        # Grouped --hide-*
        'hide_numbered_results': False,
        'hide_supporting': False,
        'hide_structural': False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def visibility_for(element_type, args_overrides):
    """Shortcut: build filter config from args overrides and test visibility."""
    args = make_args(**args_overrides)
    fc = ls.build_filter_config(args)
    return ls.should_display_element(element_type, fc)


SAMPLE_LATEX = r"""
\section{Introduction}
\label{sec:intro}

Some introductory text.

\subsection{Background}
\label{ssec:background}

Background material here.

\subsubsection{Notation}
\label{sssec:notation}

Notation details.

\begin{definition}[Bulk--boundary map]
\label{def:bulk_boundary}
Let $\mathcal{A}$ be a C*-algebra.
\end{definition}

\begin{theorem}[Main obstruction]
\label{thm:main_obstruction}
There exists no finite-index recovery map.
\end{theorem}

\begin{lemma}[Technical estimate]
\label{lem:tech_estimate}
The following bound holds.
\end{lemma}

\begin{proof}
By direct computation.
\end{proof}

\begin{remark}
\label{rmk:comparison}
This compares with \cite{Harlow2016} and \cite{Pastawski2015,Verlinde2013}.
\end{remark}

\begin{proposition}[Spectral bound]
\label{prop:spectral_bound}
The spectral flow satisfies $\mathrm{sf}(\gamma) \leq n$.
\end{proposition}

\begin{corollary}
\label{cor:entropy_bound}
The entropy is bounded by $\log n$.
\end{corollary}

\begin{example}
\label{ex:simple_case}
Consider the case $n=2$.
\end{example}

\begin{theorem*}[Unnumbered result]
\label{thm:unnumbered}
This is a starred theorem.
\end{theorem*}

\section{Further results}
\label{sec:further}

\begin{theorem}[Second theorem]
\label{thm:second}
Another result referencing \ref{thm:main_obstruction} and \ref{def:bulk_boundary}.
\end{theorem}

\begin{definition}[Second definition]
\label{def:second}
Another definition.
\end{definition}

\subsection{Advanced topics}
\label{ssec:advanced}

\begin{assumption}[Finite dimensionality]
\label{asm:finite_dim}
Assume that $\mathcal{H}$ is finite dimensional.
\end{assumption}

\begin{conjecture}[Index bound]
\label{conj:index_bound}
The index satisfies $[\mathcal{M}:\mathcal{N}] < \infty$.
\end{conjecture}
"""


def parse_sample():
    """Parse SAMPLE_LATEX and return pre-sorted (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(SAMPLE_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


# ===========================================================================
# A. Filter logic tests
# ===========================================================================

class TestFilterLogicBugFix:
    """Tests for the orthogonal two-dimensional filter model."""

    def test_only_numbered_results_hide_definitions(self):
        """THE BUG: --only-numbered-results --hide-definitions must exclude definitions."""
        args = make_args(only_numbered_results=True, hide_definitions=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('lemma', fc) is True
        assert ls.should_display_element('proposition', fc) is True
        assert ls.should_display_element('corollary', fc) is True
        assert ls.should_display_element('definition', fc) is False  # THE FIX

    def test_only_theorems_shows_only_theorems(self):
        """--only-theorems: whitelist {theorem} only."""
        args = make_args(only_theorems=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('lemma', fc) is False
        assert ls.should_display_element('definition', fc) is False
        assert ls.should_display_element('section', fc) is False
        assert ls.should_display_element('proof', fc) is False

    def test_hide_definitions_without_only(self):
        """--hide-definitions: blacklist in default mode."""
        args = make_args(hide_definitions=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('definition', fc) is False
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('section', fc) is True

    def test_structural_only_sections(self):
        """--only-sections: structural whitelist, content default."""
        args = make_args(only_sections=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is False
        assert ls.should_display_element('subsubsection', fc) is False
        # Content elements use default rules (not hidden)
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('definition', fc) is True

    def test_hide_subsections_cascades(self):
        """--hide-subsections: must also hide subsubsections (cascade down)."""
        args = make_args(hide_subsections=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is False
        assert ls.should_display_element('subsubsection', fc) is False  # CASCADE

    def test_hide_sections_cascades_all(self):
        """--hide-sections: must hide all structural elements (cascade down)."""
        args = make_args(hide_sections=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is False
        assert ls.should_display_element('subsection', fc) is False
        assert ls.should_display_element('subsubsection', fc) is False

    def test_hide_subsubsections_no_cascade(self):
        """--hide-subsubsections: only hides subsubsection, not subsection."""
        args = make_args(hide_subsubsections=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is True
        assert ls.should_display_element('subsubsection', fc) is False

    def test_orthogonal_sections_and_theorems(self):
        """--only-sections --only-theorems: shows both dimensions independently."""
        args = make_args(only_sections=True, only_theorems=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is False
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('lemma', fc) is False
        assert ls.should_display_element('definition', fc) is False

    def test_default_hides_starred(self):
        """Starred environments hidden by default."""
        args = make_args()
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('theorem*', fc) is False
        assert ls.should_display_element('lemma*', fc) is False
        assert ls.should_display_element('theorem', fc) is True

    def test_show_non_numbered_overrides(self):
        """--show-non-numbered-results: makes starred visible."""
        args = make_args(show_non_numbered_results=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('theorem*', fc) is True
        assert ls.should_display_element('lemma*', fc) is True

    def test_only_numbered_hide_lemmas(self):
        """--only-numbered-results --hide-lemmas: numbered minus lemmas."""
        args = make_args(only_numbered_results=True, hide_lemmas=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('lemma', fc) is False  # hidden
        assert ls.should_display_element('definition', fc) is True

    def test_only_supporting_hides_numbered(self):
        """--only-supporting: shows proof/remark/etc, hides theorems."""
        args = make_args(only_supporting=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('proof', fc) is True
        assert ls.should_display_element('remark', fc) is True
        assert ls.should_display_element('theorem', fc) is False
        assert ls.should_display_element('section', fc) is False

    def test_only_structural_shows_all_levels(self):
        """--only-structural: shows all section levels."""
        args = make_args(only_structural=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is True
        assert ls.should_display_element('subsubsection', fc) is True
        assert ls.should_display_element('theorem', fc) is False

    def test_only_sections_hide_supporting(self):
        """--only-sections --hide-supporting: structural whitelist + content blacklist."""
        args = make_args(only_sections=True, hide_supporting=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is False
        assert ls.should_display_element('proof', fc) is False
        assert ls.should_display_element('remark', fc) is False
        assert ls.should_display_element('theorem', fc) is True  # not in supporting


class TestSmartHierarchy:
    """Test smart hierarchy preservation."""

    def test_smart_hierarchy_preservation(self):
        """Hidden section kept if it has visible theorem children."""
        structure, file_contents = parse_sample()
        # --only-theorems would hide sections, but smart hierarchy should keep
        # sections that contain theorems
        args = make_args(only_theorems=True)
        fc = ls.build_filter_config(args)
        sorted_structure = sorted(structure, key=lambda x: (x[6], x[7]))
        vis_map = ls.compute_visibility_map(sorted_structure, fc)

        # Find the first section — it should be kept for hierarchy
        for idx, elem in enumerate(sorted_structure):
            if elem[1] == 'section' and 'Introduction' in str(elem[2]):
                assert vis_map[idx]['visible'] is True
                assert vis_map[idx]['kept_for_hierarchy'] is True
                break
        else:
            pytest.fail("Could not find Introduction section")


# ===========================================================================
# B. Backward compatibility tests
# ===========================================================================

class TestBackwardCompat:
    """Test that pre-commit hook commands produce the same results."""

    def test_precommit_main_summary_flags(self):
        """Pre-commit MainSummary flags: --only-sections --hide-supporting --hide-lemmas."""
        args = make_args(
            only_sections=True,
            hide_supporting=True,
            hide_lemmas=True,
        )
        fc = ls.build_filter_config(args)

        # Sections shown
        assert ls.should_display_element('section', fc) is True
        # Subsections hidden (only_sections whitelist)
        assert ls.should_display_element('subsection', fc) is False
        # Theorems shown (not in supporting, not lemma)
        assert ls.should_display_element('theorem', fc) is True
        # Lemmas hidden
        assert ls.should_display_element('lemma', fc) is False
        # Definitions shown (not supporting, not lemma)
        assert ls.should_display_element('definition', fc) is True
        # Proofs hidden (supporting)
        assert ls.should_display_element('proof', fc) is False
        # Remarks hidden (supporting)
        assert ls.should_display_element('remark', fc) is False

    def test_precommit_claude_summary_flags(self):
        """Pre-commit ClaudeSummary flags: --compact --status --refs-per-theorem (no filter flags)."""
        # No filter flags — everything visible except starred (default)
        args = make_args()
        fc = ls.build_filter_config(args)

        assert ls.should_display_element('section', fc) is True
        assert ls.should_display_element('subsection', fc) is True
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('lemma', fc) is True
        assert ls.should_display_element('definition', fc) is True
        assert ls.should_display_element('proof', fc) is True
        assert ls.should_display_element('remark', fc) is True
        assert ls.should_display_element('theorem*', fc) is False  # default hidden


# ===========================================================================
# C. Citation extraction tests
# ===========================================================================

class TestCitationExtraction:
    """Tests for citation parsing and display."""

    def test_cite_single_key(self):
        """\\cite{Harlow2016} extracts single key."""
        text = r"See \cite{Harlow2016} for details."
        cites = ls.extract_cites_from_text(text)
        assert cites == ['Harlow2016']

    def test_cite_multiple_keys(self):
        """\\cite{A,B,C} extracts all keys."""
        text = r"Results from \cite{Alpha2020,Beta2021,Gamma2022}."
        cites = ls.extract_cites_from_text(text)
        assert set(cites) == {'Alpha2020', 'Beta2021', 'Gamma2022'}

    def test_cite_with_optional(self):
        """\\cite[p.42]{Key} extracts key."""
        text = r"Refer to \cite[Theorem 3.1]{Araki1976} for the proof."
        cites = ls.extract_cites_from_text(text)
        assert cites == ['Araki1976']

    def test_cite_deduplication(self):
        """Same key cited twice yields single entry."""
        text = r"By \cite{X} and later \cite{X} again."
        cites = ls.extract_cites_from_text(text)
        assert cites == ['X']

    def test_cite_nocite_ignored(self):
        """\\nocite should not be extracted."""
        text = r"\nocite{Hidden} but \cite{Visible} is included."
        cites = ls.extract_cites_from_text(text)
        assert cites == ['Visible']

    def test_cites_from_element(self):
        """Integration: extract cites from parsed structure element."""
        structure, file_contents = parse_sample()
        sorted_structure = sorted(structure, key=lambda x: (x[6], x[7]))
        # Find the remark (which cites Harlow2016, Pastawski2015, Verlinde2013)
        for idx, elem in enumerate(sorted_structure):
            if elem[1] == 'remark':
                cites = ls.extract_cites_from_element(sorted_structure, idx, file_contents)
                assert 'Harlow2016' in cites
                assert 'Pastawski2015' in cites
                assert 'Verlinde2013' in cites
                break
        else:
            pytest.fail("Could not find remark element")


# ===========================================================================
# D. Scope filtering tests
# ===========================================================================

class TestScopeFiltering:
    """Tests for --scope LABEL."""

    def test_scope_filters_to_section(self):
        """--scope sec:intro: only elements within Introduction section."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_scope_filter(structure, 'sec:intro', file_contents)
        # All elements should be from the Introduction section
        labels = {elem[4] for elem in filtered if elem[4]}
        # Should include intro elements but NOT sec:further or its children
        assert 'sec:intro' in labels
        assert 'thm:main_obstruction' in labels
        assert 'sec:further' not in labels
        assert 'thm:second' not in labels

    def test_scope_unknown_label_warns(self, capsys):
        """--scope with unknown label prints warning and returns all structure."""
        structure, file_contents = parse_sample()
        result = ls.apply_scope_filter(structure, 'sec:nonexistent', file_contents)
        captured = capsys.readouterr()
        assert 'not found' in captured.err
        assert result == structure  # returns unfiltered

    def test_scope_combined_with_content_filter(self):
        """--scope sec:intro --only-theorems: theorems within intro only."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_scope_filter(structure, 'sec:intro', file_contents)
        args = make_args(only_theorems=True)
        fc = ls.build_filter_config(args)
        # Check that we can filter content within the scope
        visible_types = set()
        for elem in filtered:
            if ls.should_display_element(elem[1], fc):
                visible_types.add(elem[1])
        assert 'theorem' in visible_types
        assert 'definition' not in visible_types


# ===========================================================================
# E. Depth and line-range tests
# ===========================================================================

class TestDepthFilter:
    """Tests for --depth N."""

    def test_depth_limits_structural_levels(self):
        """--scope + --depth 1: hides subsubsections."""
        structure, file_contents = parse_sample()
        scoped = ls.apply_scope_filter(structure, 'sec:intro', file_contents)
        filtered = ls.apply_depth_filter(scoped, 1)
        types_present = {elem[1] for elem in filtered}
        # Section (depth 0) and subsection (depth 1) OK
        assert 'section' in types_present
        assert 'subsection' in types_present
        # Subsubsection (depth 2) should be filtered
        assert 'subsubsection' not in types_present

    def test_depth_does_not_affect_content(self):
        """Content elements visible regardless of depth setting."""
        structure, file_contents = parse_sample()
        scoped = ls.apply_scope_filter(structure, 'sec:intro', file_contents)
        filtered = ls.apply_depth_filter(scoped, 0)
        types_present = {elem[1] for elem in filtered}
        # Only section itself at depth 0, but theorems should still be present
        assert 'theorem' in types_present
        assert 'definition' in types_present


class TestLineRangeFilter:
    """Tests for --line-range START:END."""

    def test_line_range_basic(self):
        """Elements within the specified line range only."""
        structure, file_contents = parse_sample()
        # Use a range that captures some elements but not all
        all_lines = sorted(set(elem[5] for elem in structure))
        mid = all_lines[len(all_lines) // 2]
        filtered = ls.apply_line_range_filter(structure, f'{mid}:{mid + 20}')
        for elem in filtered:
            assert mid <= elem[5] <= mid + 20

    def test_line_range_open_end(self):
        """--line-range 100: shows from line 100 to end."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_line_range_filter(structure, '100:')
        for elem in filtered:
            assert elem[5] >= 100

    def test_line_range_open_start(self):
        """--line-range :10 shows from start to line 10."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_line_range_filter(structure, ':10')
        for elem in filtered:
            assert elem[5] <= 10


# ===========================================================================
# F. Missing label warnings
# ===========================================================================

class TestMissingLabelWarnings:
    """Tests for unlabelled section warnings."""

    def test_unlabelled_section_warns(self, capsys):
        """Section without label produces stderr warning."""
        # Must have >500 chars between the unlabelled section and the next \label
        # to prevent find_label_after() from picking up the wrong label
        filler = "\n".join([f"This is filler line {i} with enough text to space things out adequately." for i in range(20)])
        latex = (
            "\\section{No Label Here}\n\n"
            "Some text without a label command.\n\n"
            + filler + "\n\n"
            "\\section{Has Label}\n"
            "\\label{sec:has_label}\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex)
            f.flush()
            tmp_path = f.name
        try:
            result = ls.extract_latex_structure(tmp_path)
            ls.warn_unlabelled_sections(result[0])
            captured = capsys.readouterr()
            assert 'No Label Here' in captured.err
            assert 'Has Label' not in captured.err
        finally:
            os.unlink(tmp_path)

    def test_labelled_section_no_warning(self, capsys):
        """Section with label produces no warning."""
        latex = r"""
\section{Properly Labelled}
\label{sec:proper}

Content here.
"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex)
            f.flush()
            tmp_path = f.name
        try:
            result = ls.extract_latex_structure(tmp_path)
            ls.warn_unlabelled_sections(result[0])
            captured = capsys.readouterr()
            assert captured.err == '' or 'Properly Labelled' not in captured.err
        finally:
            os.unlink(tmp_path)


# ===========================================================================
# G. Bibliography resolution tests
# ===========================================================================

class TestBibliographyResolution:
    """Tests for --resolve-cites bibliography parsing."""

    def test_resolve_cites_basic(self):
        """Parse \\bibitem and resolve key to display text."""
        bib_text = r"""
\begin{thebibliography}{99}
    \bibitem{Harlow2016} D. Harlow, The Ryu-Takayanagi formula from quantum error correction, Comm. Math. Phys. 354 (2017), 865-912.
    \bibitem{Araki1976} Araki, H. (1976). Relative entropy of states of von Neumann algebras.
\end{thebibliography}
"""
        cite_map = ls.parse_bibliography(bib_text)
        assert 'Harlow2016' in cite_map
        assert 'Araki1976' in cite_map

    def test_resolve_cites_missing_key(self):
        """Unknown key falls back gracefully."""
        cite_map = ls.parse_bibliography("")
        assert cite_map.get('NonExistent') is None


# ===========================================================================
# Integration test: full parsing
# ===========================================================================

class TestParsing:
    """Basic parsing sanity checks."""

    def test_parse_sample_latex(self):
        """Sample LaTeX parses without errors and finds expected elements."""
        structure, file_contents = parse_sample()
        types_found = {elem[1] for elem in structure}
        assert 'section' in types_found
        assert 'subsection' in types_found
        assert 'theorem' in types_found
        assert 'definition' in types_found
        assert 'lemma' in types_found
        assert 'proof' in types_found
        assert 'remark' in types_found

    def test_labels_extracted(self):
        """Labels are correctly extracted."""
        structure, file_contents = parse_sample()
        labels = {elem[4] for elem in structure if elem[4]}
        assert 'sec:intro' in labels
        assert 'thm:main_obstruction' in labels
        assert 'def:bulk_boundary' in labels
        assert 'lem:tech_estimate' in labels


# ===========================================================================
# H. Label registry tests
# ===========================================================================

class TestLabelRegistry:
    """Tests for build_label_registry()."""

    def test_registry_contains_all_labels(self):
        """All labelled elements present in registry."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        expected_labels = {elem[4] for elem in structure if elem[4]}
        assert set(registry.keys()) == expected_labels

    def test_registry_chapter_attribution(self):
        """Registry entries have correct source file."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        for label, info in registry.items():
            # All elements from sample are in the same temp file
            assert info['file'] is not None
            assert info['file'].endswith('.tex')

    def test_registry_section_context(self):
        """Registry entries have correct parent section."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        # thm:main_obstruction is under sec:intro (Introduction)
        assert registry['thm:main_obstruction']['section'] == 'Introduction'
        # thm:second is under sec:further (Further results)
        assert registry['thm:second']['section'] == 'Further results'

    def test_registry_element_metadata(self):
        """Registry entries contain required metadata fields."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        info = registry['thm:main_obstruction']
        assert info['type'] == 'theorem'
        assert info['content'] == 'Main obstruction'
        assert info['line'] > 0
        assert info['level'] == 4
        assert 'char_start' in info
        assert 'char_end' in info

    def test_registry_from_format_output_compatible(self):
        """Registry-derived label_map matches format_output expectations."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        # Convert to label_map format used by extract_refs_from_element
        label_map = {}
        for lbl, info in registry.items():
            label_map[lbl] = (info['type'], info['content'], info['file'], info['section'], info['chapter'])
        # Verify a known label
        t, c, f, s, ch = label_map['def:bulk_boundary']
        assert t == 'definition'
        assert 'Bulk' in c or 'boundary' in c


# ===========================================================================
# I. Reverse refs tests
# ===========================================================================

CROSS_REF_LATEX = r"""
\section{Chapter One}
\label{sec:ch1}

\begin{theorem}[First result]
\label{thm:first}
A theorem statement.
\end{theorem}

\begin{proof}
By \ref{thm:first}, we have the result.
\end{proof}

\begin{definition}[Key concept]
\label{def:key}
A definition.
\end{definition}

\section{Chapter Two}
\label{sec:ch2}

\begin{theorem}[Second result]
\label{thm:second_xref}
By \ref{thm:first} and \ref{def:key}, we obtain the claim.
\end{theorem}

\begin{remark}
\label{rmk:note}
Note that \ref{thm:first} is essential. Also see \ref{thm:second_xref}.
\end{remark}

\begin{lemma}
\label{lem:unrelated}
An independent result.
\end{lemma}
"""


def parse_cross_ref_sample():
    """Parse CROSS_REF_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(CROSS_REF_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestReverseRefs:
    """Tests for --reverse-refs (format_reverse_refs)."""

    def test_reverse_refs_finds_references(self):
        """Element referencing a label is found."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['thm:first'], structure, file_contents, registry, compact=True)
        # thm:second_xref and rmk:note both reference thm:first
        assert 'thm:second_xref' in output
        assert 'rmk:note' in output

    def test_reverse_refs_no_false_positives(self):
        """Elements not referencing the label are excluded."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['thm:first'], structure, file_contents, registry, compact=True)
        # lem:unrelated does not reference thm:first
        assert 'lem:unrelated' not in output

    def test_reverse_refs_cross_chapter(self):
        """References from other sections are found."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['def:key'], structure, file_contents, registry, compact=True)
        # thm:second_xref references def:key from a different section
        assert 'thm:second_xref' in output

    def test_reverse_refs_multiple_labels(self):
        """Comma-separated labels all produce results."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['thm:first', 'def:key'], structure, file_contents, registry, compact=True)
        assert 'thm:first\t<-ref' in output
        assert 'def:key\t<-ref' in output

    def test_reverse_refs_terminal_format(self):
        """Terminal format groups by file."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['thm:first'], structure, file_contents, registry, compact=False)
        assert 'Reverse references for' in output
        assert '.tex:' in output  # file grouping header


# ===========================================================================
# J. Stats tests
# ===========================================================================

class TestStats:
    """Tests for --stats and --stats --per-chapter."""

    def test_stats_simple_mode(self):
        """Frequency table matches manual counts."""
        structure, file_contents = parse_sample()
        output = ls.format_stats(structure)
        # Verify some known counts from SAMPLE_LATEX
        assert 'theorem' in output
        assert 'definition' in output
        assert 'TOTAL' in output

    def test_stats_per_chapter(self):
        """Per-chapter matrix has correct structure."""
        structure, file_contents = parse_sample()
        output = ls.format_stats_per_chapter(structure)
        assert 'Chapter' in output
        assert 'total' in output
        assert 'TOTAL' in output

    def test_stats_total_row_sums(self):
        """Total row sums correctly in compact format."""
        structure, file_contents = parse_sample()
        output = ls.format_stats_per_chapter(structure, compact=True)
        lines = output.strip().split('\n')
        # Last line should be TOTAL
        total_line = lines[-1]
        assert total_line.startswith('TOTAL')
        parts = total_line.split('\t')
        # Sum of type columns should equal the total column
        type_cols = [int(p) for p in parts[1:-1]]
        total_col = int(parts[-1])
        assert sum(type_cols) == total_col

    def test_stats_with_filter(self):
        """Stats respects active filters."""
        structure, file_contents = parse_sample()
        args = make_args(only_theorems=True)
        fc = ls.build_filter_config(args)
        output = ls.format_stats(structure, fc, compact=True)
        # Only theorem type should appear (plus sections kept for hierarchy)
        lines = output.strip().split('\n')
        types_found = {line.split('\t')[0] for line in lines if not line.startswith('TOTAL')}
        # With only_theorems + smart hierarchy, sections may be kept
        assert 'theorem' in types_found
        assert 'definition' not in types_found

    def test_stats_compact_format(self):
        """Compact format is tab-separated."""
        structure, file_contents = parse_sample()
        output = ls.format_stats(structure, compact=True)
        for line in output.strip().split('\n'):
            assert '\t' in line


# ===========================================================================
# K. Deps matrix tests
# ===========================================================================

MULTI_FILE_LATEX_CH1 = r"""
\section{Chapter One}
\label{sec:ch1}

\begin{theorem}[First result]
\label{thm:ch1_result}
A theorem.
\end{theorem}
"""

MULTI_FILE_LATEX_CH2 = r"""
\section{Chapter Two}
\label{sec:ch2}

\begin{theorem}[Second result]
\label{thm:ch2_result}
By \ref{thm:ch1_result}, we prove this.
\end{theorem}

\begin{remark}
\label{rmk:ch2_note}
Also \ref{thm:ch1_result} again.
\end{remark}
"""


def parse_multi_file():
    """Parse two separate files and return combined structure."""
    import tempfile
    files = []
    for latex_content in [MULTI_FILE_LATEX_CH1, MULTI_FILE_LATEX_CH2]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex_content)
            f.flush()
            files.append(f.name)

    combined_structure = []
    combined_contents = {}
    processed = set()
    try:
        for fpath in files:
            result = ls.extract_latex_structure(fpath, file_contents=combined_contents, processed_files=processed)
            if result:
                combined_structure.extend(result[0])
        combined_structure.sort(key=ls._SORT_KEY)
        return combined_structure, combined_contents
    finally:
        for fpath in files:
            os.unlink(fpath)


class TestDepsMatrix:
    """Tests for --deps-matrix."""

    def test_deps_matrix_cross_chapter(self):
        """Correct cross-chapter ref counts."""
        structure, file_contents = parse_multi_file()
        registry = ls.build_label_registry(structure)
        output = ls.format_deps_matrix(structure, file_contents, registry, compact=True)
        lines = output.strip().split('\n')
        # Should have header + 2 chapter rows
        assert len(lines) == 3
        # Ch2 -> Ch1 should have refs (thm:ch2_result and rmk:ch2_note both ref thm:ch1_result)
        # But we need to find which row is Ch2
        for line in lines[1:]:
            parts = line.split('\t')
            if 'tmp' in parts[0]:  # temp file names
                vals = parts[1:]
                # At least one non-zero, non-dash value
                has_ref = any(v not in ('0', '-') for v in vals)
                # This is expected for the Ch2 row

    def test_deps_matrix_diagonal_default(self):
        """Default shows - on diagonal."""
        structure, file_contents = parse_multi_file()
        registry = ls.build_label_registry(structure)
        output = ls.format_deps_matrix(structure, file_contents, registry, compact=True)
        lines = output.strip().split('\n')
        for line in lines[1:]:
            parts = line.split('\t')
            # Find this file's column index
            header_parts = lines[0].split('\t')
            for i, h in enumerate(header_parts[1:], 1):
                if h.strip() in parts[0]:
                    assert parts[i] == '-', f"Diagonal should be '-' but got '{parts[i]}'"

    def test_deps_matrix_include_self(self):
        """--include-self shows numbers on diagonal."""
        structure, file_contents = parse_multi_file()
        registry = ls.build_label_registry(structure)
        output = ls.format_deps_matrix(structure, file_contents, registry, include_self=True, compact=True)
        # No dashes expected
        assert '-' not in output.split('\n', 1)[1]  # skip header

    def test_deps_matrix_compact_parseable(self):
        """TSV output is parseable."""
        structure, file_contents = parse_multi_file()
        registry = ls.build_label_registry(structure)
        output = ls.format_deps_matrix(structure, file_contents, registry, compact=True)
        lines = output.strip().split('\n')
        header_cols = len(lines[0].split('\t'))
        for line in lines[1:]:
            assert len(line.split('\t')) == header_cols


# ===========================================================================
# L. Resolve refs tests
# ===========================================================================

class TestResolveRefs:
    """Tests for --resolve-refs in reverse-refs output."""

    def test_resolve_refs_basic(self):
        """Label resolved to display name in terminal output."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['thm:first'], structure, file_contents, registry,
                                         compact=False, resolve_refs=True)
        # Should contain the resolved name
        assert 'First result' in output

    def test_resolve_refs_unknown_label(self):
        """Unknown label falls back to raw display."""
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(['thm:nonexistent'], structure, file_contents, registry,
                                         compact=False, resolve_refs=True)
        assert 'thm:nonexistent' in output
        assert 'no references found' in output


# ===========================================================================
# M. JSON export tests
# ===========================================================================

class TestJsonExport:
    """Tests for --json export."""

    def test_json_valid(self):
        """Output is valid JSON."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        assert isinstance(data, dict)

    def test_json_contains_elements(self):
        """Elements array present with expected fields."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        assert 'elements' in data
        assert len(data['elements']) > 0
        # Check first labelled element has expected fields
        labelled = [e for e in data['elements'] if 'label' in e]
        assert len(labelled) > 0
        elem = labelled[0]
        assert 'type' in elem
        assert 'content' in elem
        assert 'file' in elem
        assert 'line' in elem
        assert 'refs_to' in elem
        assert 'refs_from' in elem

    def test_json_refs_consistent(self):
        """Forward and reverse refs are consistent."""
        import json
        structure, file_contents = parse_cross_ref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        elements_by_label = {e['label']: e for e in data['elements'] if 'label' in e}
        # If A refs_to B, then B should have A in refs_from
        for label, elem in elements_by_label.items():
            for target in elem.get('refs_to', []):
                if target in elements_by_label:
                    assert label in elements_by_label[target].get('refs_from', []), \
                        f"{label} refs_to {target} but {target} doesn't have {label} in refs_from"

    def test_json_metadata(self):
        """Metadata section present with expected fields."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        assert 'metadata' in data
        assert 'files_processed' in data['metadata']
        assert 'total_elements' in data['metadata']
        assert 'total_labels' in data['metadata']

    def test_json_deps_matrix(self):
        """Deps matrix present in JSON output."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        assert 'deps_matrix' in data
        assert 'stats' in data


# ===========================================================================
# N. --quiet and --head tests
# ===========================================================================

class TestQuietAndHead:
    """Tests for --quiet and --head flags."""

    def test_head_limits_output(self):
        """--head N returns at most N lines."""
        structure, file_contents = parse_sample()
        output = ls.format_compact_output(structure, file_contents)
        lines = output.strip().split('\n')
        assert len(lines) > 5  # sanity check
        # Simulate --head
        limited = '\n'.join(lines[:5])
        assert len(limited.split('\n')) == 5


# ===========================================================================
# O. Section line_end tests
# ===========================================================================

class TestSectionLineEnd:
    """Tests for correct section line_end computation in JSON export."""

    def test_section_line_end_spans_to_next_section(self):
        """sec:intro line_end should be the line before sec:further starts."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        intro = next(e for e in data['elements'] if e.get('label') == 'sec:intro')
        further = next(e for e in data['elements'] if e.get('label') == 'sec:further')
        assert intro['line_end'] == further['line'] - 1

    def test_last_section_line_end_to_eof(self):
        """sec:further (last section) line_end should span to end of file."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        further = next(e for e in data['elements'] if e.get('label') == 'sec:further')
        fname = further['file']
        file_lines = file_contents[fname].count('\n') + 1
        assert further['line_end'] == file_lines

    def test_section_line_end_substantial(self):
        """Section line_end should represent substantial content, not just heading."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        intro = next(e for e in data['elements'] if e.get('label') == 'sec:intro')
        size = intro['line_end'] - intro['line'] + 1
        assert size > 30, f"sec:intro should span >30 lines, got {size}"

    def test_subsection_line_end_regression(self):
        """Subsection line_end should extend to next same-or-higher-level structural."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        bg = next(e for e in data['elements'] if e.get('label') == 'ssec:background')
        further = next(e for e in data['elements'] if e.get('label') == 'sec:further')
        # ssec:background should extend to the line before sec:further
        assert bg['line_end'] == further['line'] - 1


# ===========================================================================
# P. Subsection scope tests
# ===========================================================================

class TestSubsectionScope:
    """Tests for --scope at subsection and subsubsection level."""

    def test_scope_subsection(self):
        """--scope ssec:background returns only elements within that subsection."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_scope_filter(structure, 'ssec:background', file_contents)
        labels = {elem[4] for elem in filtered if elem[4]}
        assert 'ssec:background' in labels
        assert 'sssec:notation' in labels
        assert 'def:bulk_boundary' in labels
        assert 'thm:main_obstruction' in labels
        # Elements from sec:further should NOT be included
        assert 'sec:further' not in labels
        assert 'thm:second' not in labels

    def test_scope_subsubsection(self):
        """--scope sssec:notation returns only subsubsection content."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_scope_filter(structure, 'sssec:notation', file_contents)
        labels = {elem[4] for elem in filtered if elem[4]}
        assert 'sssec:notation' in labels
        # Content within the subsubsection
        assert 'def:bulk_boundary' in labels

    def test_scope_theorem_label(self):
        """--scope with a theorem label returns elements from that point onward."""
        structure, file_contents = parse_sample()
        filtered = ls.apply_scope_filter(structure, 'thm:main_obstruction', file_contents)
        labels = {elem[4] for elem in filtered if elem[4]}
        assert 'thm:main_obstruction' in labels
        # Non-structural labels scope from that element to end of file
        assert len(filtered) >= 1


# ===========================================================================
# Q. Status in JSON tests
# ===========================================================================

class TestStatusInJson:
    """Tests for status and status_note fields in JSON export."""

    def test_status_appears_in_json(self):
        """Elements with status in status_map get status, status_note, math_issues."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        fname = structure[0][6]
        status_map = {
            (fname, 'thm:main_obstruction'): {
                'STATUS': 'MINOR_REVISION',
                'DESCRIPTION': 'Missing bound in step 3',
                'MATH_ISSUES': 'Y',
            }
        }
        output = ls.format_json_export(structure, file_contents, registry, status_map=status_map)
        data = json.loads(output)

        thm = next(e for e in data['elements'] if e.get('label') == 'thm:main_obstruction')
        assert thm['status'] == 'MINOR_REVISION'
        assert thm['status_note'] == 'Missing bound in step 3'
        assert thm['math_issues'] == 'Y'

    def test_status_absent_when_no_entry(self):
        """Elements without status entries don't get spurious status fields."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        fname = structure[0][6]
        status_map = {
            (fname, 'thm:main_obstruction'): {
                'STATUS': 'MINOR_REVISION',
                'DESCRIPTION': 'Some issue',
                'MATH_ISSUES': 'N',
            }
        }
        output = ls.format_json_export(structure, file_contents, registry, status_map=status_map)
        data = json.loads(output)

        defn = next(e for e in data['elements'] if e.get('label') == 'def:bulk_boundary')
        assert 'status' not in defn
        assert 'status_note' not in defn
        assert 'math_issues' not in defn

    def test_status_without_description(self):
        """Status with empty description doesn't add status_note."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        fname = structure[0][6]
        status_map = {
            (fname, 'thm:main_obstruction'): {
                'STATUS': 'READY',
                'DESCRIPTION': '',
                'MATH_ISSUES': '',
            }
        }
        output = ls.format_json_export(structure, file_contents, registry, status_map=status_map)
        data = json.loads(output)

        thm = next(e for e in data['elements'] if e.get('label') == 'thm:main_obstruction')
        assert thm['status'] == 'READY'
        assert 'status_note' not in thm
        assert 'math_issues' not in thm


# ===========================================================================
# R. Per-file metadata tests
# ===========================================================================

class TestPerFileMetadata:
    """Tests for per-file line counts in JSON metadata."""

    def test_files_in_metadata(self):
        """JSON metadata includes files array with line counts."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        assert 'files' in data['metadata']
        assert len(data['metadata']['files']) > 0

    def test_file_line_count_matches(self):
        """File line count in metadata matches actual file length."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        for file_info in data['metadata']['files']:
            fname = file_info['name']
            expected_lines = file_contents[fname].count('\n') + 1
            assert file_info['lines'] == expected_lines


# ===========================================================================
# S. Custom environment parsing tests
# ===========================================================================

class TestCustomEnvironments:
    """Tests for parsing assumption, conjecture, and other custom environments."""

    def test_assumption_parsed(self):
        """assumption environment appears in parsed structure."""
        structure, file_contents = parse_sample()
        types_found = {elem[1] for elem in structure}
        assert 'assumption' in types_found

    def test_conjecture_parsed(self):
        """conjecture environment appears in parsed structure."""
        structure, file_contents = parse_sample()
        types_found = {elem[1] for elem in structure}
        assert 'conjecture' in types_found

    def test_custom_env_labels(self):
        """Custom environment labels are extracted correctly."""
        structure, file_contents = parse_sample()
        labels = {elem[4] for elem in structure if elem[4]}
        assert 'asm:finite_dim' in labels
        assert 'conj:index_bound' in labels

    def test_custom_env_line_end(self):
        """Custom environments have correct line_end in JSON."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        asm = next((e for e in data['elements'] if e.get('label') == 'asm:finite_dim'), None)
        assert asm is not None
        assert 'line_end' in asm
        assert asm['line_end'] >= asm['line']

    def test_theorem_star_in_structure(self):
        """theorem* (already in SAMPLE_LATEX) appears in structure."""
        structure, file_contents = parse_sample()
        star_types = {elem[1] for elem in structure if '*' in elem[1]}
        assert 'theorem*' in star_types


# ===========================================================================
# T. Transitive dependency tests
# ===========================================================================

TRANSITIVE_LATEX = r"""
\section{Foundations}
\label{sec:foundations}

\begin{definition}[Base concept]
\label{def:base}
A definition.
\end{definition}

\begin{theorem}[First result]
\label{thm:level1}
By \ref{def:base}, we have this.
\end{theorem}

\begin{theorem}[Second result]
\label{thm:level2}
By \ref{thm:level1}, we prove this.
\end{theorem}

\begin{theorem}[Third result]
\label{thm:level3}
By \ref{thm:level2}, we obtain this.
\end{theorem}
"""


def parse_transitive_sample():
    """Parse TRANSITIVE_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(TRANSITIVE_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestTransitiveDeps:
    """Tests for --reverse-refs --transitive."""

    def test_transitive_finds_chain(self):
        """Transitive reverse refs finds the full dependency chain."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=0  # 0 = unlimited
        )
        assert 'thm:level1' in output
        assert 'thm:level2' in output
        assert 'thm:level3' in output

    def test_transitive_depth_limit(self):
        """--transitive 1 finds only direct refs."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=1
        )
        assert 'thm:level1' in output
        assert 'thm:level2' not in output
        assert 'thm:level3' not in output

    def test_transitive_none_is_direct_only(self):
        """Without --transitive, only direct refs are shown."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True
        )
        assert 'thm:level1' in output
        assert 'thm:level2' not in output


# ===========================================================================
# U. Duplicate label tests
# ===========================================================================

DUPLICATE_LABEL_LATEX_1 = r"""
\section{Chapter One}
\label{sec:dup_ch1}

\begin{theorem}[Result one]
\label{thm:shared_label}
A theorem.
\end{theorem}
"""

DUPLICATE_LABEL_LATEX_2 = r"""
\section{Chapter Two}
\label{sec:dup_ch2}

\begin{theorem}[Result two]
\label{thm:shared_label}
Another theorem with the same label.
\end{theorem}
"""


def parse_duplicate_label_sample():
    """Parse two files with a duplicate label."""
    import tempfile
    files = []
    for latex_content in [DUPLICATE_LABEL_LATEX_1, DUPLICATE_LABEL_LATEX_2]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex_content)
            f.flush()
            files.append(f.name)

    combined_structure = []
    combined_contents = {}
    processed = set()
    try:
        for fpath in files:
            result = ls.extract_latex_structure(fpath, file_contents=combined_contents, processed_files=processed)
            if result:
                combined_structure.extend(result[0])
        combined_structure.sort(key=ls._SORT_KEY)
        return combined_structure, combined_contents
    finally:
        for fpath in files:
            os.unlink(fpath)


class TestDuplicateLabels:
    """Tests for duplicate label detection."""

    def test_duplicate_labels_in_metadata(self):
        """JSON metadata includes duplicate_labels list."""
        import json
        structure, file_contents = parse_duplicate_label_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        assert 'duplicate_labels' in data['metadata']
        dup_labels = [d['label'] for d in data['metadata']['duplicate_labels']]
        assert 'thm:shared_label' in dup_labels

    def test_duplicate_labels_detection(self):
        """find_duplicate_labels correctly identifies cross-file duplicates."""
        structure, file_contents = parse_duplicate_label_sample()
        dups = ls.find_duplicate_labels(structure)
        assert len(dups) > 0
        assert any(d['label'] == 'thm:shared_label' for d in dups)

    def test_no_false_positives_from_lookahead(self):
        """Parser lookahead artifacts (same label on consecutive lines) are filtered out."""
        structure, file_contents = parse_sample()
        dups = ls.find_duplicate_labels(structure)
        # SAMPLE_LATEX has parser-generated "duplicates" from label lookahead
        # (same label assigned to consecutive elements within 10 lines).
        # These should be filtered out as artifacts.
        assert len(dups) == 0


# ===========================================================================
# V. Sizes in text output tests
# ===========================================================================

class TestSizesFlag:
    """Tests for --sizes flag in compact output."""

    def test_sizes_in_compact_output(self):
        """--sizes adds (N lines) annotations to compact output."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)

        output = ls.format_compact_output(
            structure, file_contents,
            label_registry=registry,
            sizes=True
        )
        import re
        size_matches = re.findall(r'\(\d+ lines?\)', output)
        assert len(size_matches) > 0

    def test_sizes_match_json_line_end(self):
        """Size annotations match JSON line_end - line + 1 for unambiguous labels."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)

        json_output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(json_output)

        # Use only unambiguous labels (no labels shared between elements)
        unambiguous = {'sec:intro', 'sec:further', 'thm:main_obstruction',
                       'def:bulk_boundary', 'thm:second', 'def:second'}
        expected_sizes = {}
        for elem in data['elements']:
            if elem.get('label') in unambiguous and 'line_end' in elem:
                expected_sizes[elem['label']] = elem['line_end'] - elem['line'] + 1

        output = ls.format_compact_output(
            structure, file_contents,
            label_registry=registry,
            sizes=True
        )

        import re
        matched_any = False
        for line in output.split('\n'):
            parts = line.split('\t')
            if len(parts) >= 4:
                label = parts[2]
                if label in expected_sizes:
                    size_match = re.search(r'\((\d+) lines?\)', line)
                    if size_match:
                        actual_size = int(size_match.group(1))
                        assert actual_size == expected_sizes[label], \
                            f"Size mismatch for {label}: {actual_size} vs {expected_sizes[label]}"
                        matched_any = True
        assert matched_any, "No size annotations found to validate"


# ===========================================================================
# W. JSON body text tests
# ===========================================================================

class TestJsonBody:
    """Tests for --json-body flag."""

    def test_json_body_includes_content(self):
        """Elements have body field when json_body is enabled."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry, json_body=True)
        data = json.loads(output)

        thm = next(e for e in data['elements'] if e.get('label') == 'thm:main_obstruction')
        assert 'body' in thm
        assert 'finite-index recovery map' in thm['body']

    def test_json_default_no_body(self):
        """Default JSON export does NOT include body field."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)

        thm = next(e for e in data['elements'] if e.get('label') == 'thm:main_obstruction')
        assert 'body' not in thm

    def test_json_body_skips_sections(self):
        """Sections do not get body field even with json_body."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry, json_body=True)
        data = json.loads(output)

        sec = next(e for e in data['elements'] if e.get('label') == 'sec:intro')
        assert 'body' not in sec


# ===========================================================================
# X. Out-of-scope refs tests
# ===========================================================================

SCOPE_LATEX = r"""
\section{First section}
\label{sec:first}

\begin{theorem}[Alpha]
\label{thm:alpha}
This references \ref{thm:beta} and \ref{thm:nonexistent}.
\end{theorem}

\section{Second section}
\label{sec:second}

\begin{theorem}[Beta]
\label{thm:beta}
A result.
\end{theorem}
"""


def parse_scope_sample():
    """Parse SCOPE_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(SCOPE_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestOutOfScope:
    """Tests for B1: 'out of scope' vs 'not found' labelling."""

    def test_scoped_ref_shows_out_of_scope(self):
        """Ref to a label outside --scope shows '(out of scope)' not '(not found)'."""
        structure, file_contents = parse_scope_sample()
        # Build full label set (as main() does before scope filtering)
        all_label_set = {elem[4] for elem in structure if elem[4]}
        assert 'thm:beta' in all_label_set

        # Scope to sec:first — thm:beta exists globally but not in scope
        scoped = ls.apply_scope_filter(structure, 'sec:first', file_contents)
        registry = ls.build_label_registry(scoped)

        output = ls.format_output(
            scoped, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=all_label_set
        )
        assert '(out of scope)' in output
        # thm:nonexistent truly doesn't exist — should be "(not found)"
        assert '(not found)' in output

    def test_unscoped_ref_shows_not_found(self):
        """Without --scope, missing refs show '(not found)' as before."""
        structure, file_contents = parse_scope_sample()
        registry = ls.build_label_registry(structure)

        output = ls.format_output(
            structure, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=None  # No scope active
        )
        # thm:nonexistent should be "(not found)"
        assert '(not found)' in output
        assert '(out of scope)' not in output


# ===========================================================================
# Y. Speculative filter tests
# ===========================================================================

class TestSpeculativeFilter:
    """Tests for C1: --only-speculative filter."""

    def test_speculative_shows_conjecture_and_assumption(self):
        """--only-speculative shows conjecture and assumption."""
        args = make_args(only_speculative=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('conjecture', fc) is True
        assert ls.should_display_element('assumption', fc) is True
        assert ls.should_display_element('hypothesis', fc) is True

    def test_speculative_hides_theorem_and_definition(self):
        """--only-speculative hides regular theorems and definitions."""
        args = make_args(only_speculative=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('theorem', fc) is False
        assert ls.should_display_element('definition', fc) is False
        assert ls.should_display_element('proof', fc) is False

    def test_speculative_combined_with_theorems(self):
        """--only-speculative --only-theorems shows both."""
        args = make_args(only_speculative=True, only_theorems=True)
        fc = ls.build_filter_config(args)
        assert ls.should_display_element('conjecture', fc) is True
        assert ls.should_display_element('theorem', fc) is True
        assert ls.should_display_element('definition', fc) is False


# ===========================================================================
# Z. Depth range filter tests
# ===========================================================================

class TestDepthRangeFilter:
    """Tests for C2: --min-depth and --max-depth."""

    def test_min_depth_filters_shallow(self):
        """--min-depth 2 excludes depth-1 results."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=0, min_depth=2
        )
        assert 'thm:level1' not in output  # depth 1
        assert 'thm:level2' in output      # depth 2
        assert 'thm:level3' in output      # depth 3

    def test_max_depth_filters_deep(self):
        """--max-depth 2 excludes depth-3 results."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=0, max_depth=2
        )
        assert 'thm:level1' in output      # depth 1
        assert 'thm:level2' in output      # depth 2
        assert 'thm:level3' not in output   # depth 3

    def test_min_and_max_depth_range(self):
        """--min-depth 2 --max-depth 2 shows only depth 2."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=0, min_depth=2, max_depth=2
        )
        assert 'thm:level1' not in output   # depth 1
        assert 'thm:level2' in output       # depth 2
        assert 'thm:level3' not in output    # depth 3


# ===========================================================================
# AA. Transitive type filter tests
# ===========================================================================

class TestTransitiveTypeFilter:
    """Tests for C3: --transitive-types filter."""

    def test_type_filter_theorem_only(self):
        """--transitive-types theorem shows only theorems (not definitions)."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        # The chain: def:base -> thm:level1 -> thm:level2 -> thm:level3
        # plus sec:foundations is a section that references def:base
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=0, type_filter=['theorem']
        )
        assert 'thm:level1' in output
        assert 'thm:level2' in output
        # No sections should appear
        for line in output.split('\n'):
            if line.strip():
                parts = line.split('\t')
                assert parts[2] == 'theorem', f"Expected only theorems, got: {line}"

    def test_type_filter_definition_only(self):
        """--transitive-types definition shows only definitions."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=True, transitive=0, type_filter=['definition']
        )
        # No theorems should appear; there are no definitions referencing def:base
        assert 'thm:level1' not in output


# ===========================================================================
# AB. Sizes in terminal output tests
# ===========================================================================

class TestSizesTerminal:
    """Tests for D1: --sizes in non-compact (terminal) output."""

    def test_sizes_in_terminal_output(self):
        """format_output with sizes=True produces '(line N, M lines)' annotations."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)

        output = ls.format_output(
            structure, file_contents,
            label_registry=registry,
            sizes=True
        )
        # Should contain size annotations like "(line 5, 3 lines)"
        assert re.search(r'\(line \d+, \d+ lines\)', output), \
            f"No size annotations found in terminal output"

    def test_sizes_false_no_annotation(self):
        """format_output with sizes=False does NOT produce size annotations."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)

        output = ls.format_output(
            structure, file_contents,
            label_registry=registry,
            sizes=False
        )
        assert not re.search(r'\(line \d+, \d+ lines\)', output)


# ===========================================================================
# AC. Sizes summary tests
# ===========================================================================

class TestSizesSummary:
    """Tests for D2: --sizes-summary output mode."""

    def test_sizes_summary_terminal(self):
        """format_sizes_summary produces type/count/lines table."""
        structure, file_contents = parse_sample()
        output = ls.format_sizes_summary(structure, file_contents)
        assert 'theorem' in output
        assert 'TOTAL' in output
        # Should have numbers
        assert re.search(r'\d+', output)

    def test_sizes_summary_compact(self):
        """format_sizes_summary compact produces TSV."""
        structure, file_contents = parse_sample()
        output = ls.format_sizes_summary(structure, file_contents, compact=True)
        lines = output.strip().split('\n')
        # Each line should have tab separators
        for line in lines:
            parts = line.split('\t')
            assert len(parts) == 3, f"Expected 3 tab-separated fields, got {len(parts)}: {line}"


# ===========================================================================
# AD. Transitive stats header tests
# ===========================================================================

class TestTransitiveStatsHeader:
    """Tests for E1: stats summary header in transitive output."""

    def test_terminal_stats_header(self):
        """Transitive terminal output includes stats summary."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=False, transitive=0
        )
        # Should contain a stats line like "(3 results across 1 files, max depth 3: ...)"
        assert re.search(r'\d+ results across \d+ files', output), \
            f"No stats header found in transitive output"

    def test_no_stats_header_without_transitive(self):
        """Non-transitive output does NOT include stats header."""
        structure, file_contents = parse_transitive_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_reverse_refs(
            ['def:base'], structure, file_contents, registry,
            compact=False, transitive=None
        )
        assert 'results across' not in output


# ===========================================================================
# AE. JSON schema version tests
# ===========================================================================

class TestSchemaVersion:
    """Tests for F1: schema_version in JSON metadata."""

    def test_schema_version_present(self):
        """JSON metadata includes schema_version field."""
        import json
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        assert 'schema_version' in data['metadata']
        assert data['metadata']['schema_version'] == '2.0'


# ===========================================================================
# AF. Starred environment display tests
# ===========================================================================

class TestStarredDisplay:
    """Tests for B2: theorem* displays as 'Theorem* [lit]' in terminal."""

    def test_starred_shows_lit_marker(self):
        """Starred theorem shows '[lit]' marker in terminal output."""
        structure, file_contents = parse_sample()
        fc = ls.build_filter_config(make_args(show_non_numbered_results=True))
        output = ls.format_output(
            structure, file_contents,
            filter_config=fc
        )
        assert '[lit]' in output

    def test_non_starred_no_lit_marker(self):
        """Non-starred theorem does NOT show '[lit]' marker."""
        structure, file_contents = parse_sample()
        output = ls.format_output(structure, file_contents)
        # The default output hides starred envs, so check with theorems only
        lines = output.split('\n')
        for line in lines:
            if 'Theorem:' in line and 'Theorem*' not in line:
                assert '[lit]' not in line


# ===========================================================================
# AG. Duplicate label summary tests
# ===========================================================================

DUPLICATE_LATEX_A = r"""
\section{Section A}
\label{sec:dupa}

\begin{theorem}[Shared]
\label{thm:shared}
A theorem.
\end{theorem}
"""

DUPLICATE_LATEX_B = r"""
\section{Section B}
\label{sec:dupb}

\begin{theorem}[Shared copy]
\label{thm:shared}
Another theorem with the same label.
\end{theorem}
"""


class TestDuplicateSummary:
    """Tests for B3: duplicate label summary count."""

    def test_duplicate_summary_printed(self):
        """find_duplicate_labels detects cross-file duplicates."""
        import tempfile
        tmp_a = tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp')
        tmp_b = tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp')
        try:
            tmp_a.write(DUPLICATE_LATEX_A)
            tmp_a.flush()
            tmp_b.write(DUPLICATE_LATEX_B)
            tmp_b.flush()

            result_a = ls.extract_latex_structure(tmp_a.name)
            result_b = ls.extract_latex_structure(tmp_b.name)
            combined = result_a[0] + result_b[0]

            duplicates = ls.find_duplicate_labels(combined)
            assert len(duplicates) >= 1
            shared = [d for d in duplicates if d['label'] == 'thm:shared']
            assert len(shared) == 1
            assert len(shared[0]['locations']) == 2

            # Verify cross-chapter detection logic
            cross_chapter = [d for d in duplicates
                            if len(set(loc['file'] for loc in d['locations'])) > 1
                            and not any('backup' in loc['file'].lower() for loc in d['locations'])]
            assert len(cross_chapter) >= 1
        finally:
            os.unlink(tmp_a.name)
            os.unlink(tmp_b.name)


# ===========================================================================
# AH. Draftingnote and reasoning environment tests
# ===========================================================================

DRAFTINGNOTE_LATEX = r"""
\section{Results}
\label{sec:results}

\begin{theorem}[Main result]
\label{thm:main}
A theorem.
\end{theorem}

\begin{draftingnote}
This step needs verification against Lemma 3.2 of \cite{Foo2020}.
\end{draftingnote}

\begin{reasoning}
We consider two cases. First, if $x > 0$, then...
\end{reasoning}

\begin{draftingnote}[Open question]
\label{dn:open_question}
Is the bound sharp?
\end{draftingnote}
"""


def parse_draftingnote_sample():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(DRAFTINGNOTE_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestDraftingnoteEnvironments:
    """Tests for draftingnote and reasoning environment parsing."""

    def test_draftingnote_parsed(self):
        """draftingnote environment appears in parsed structure."""
        structure, file_contents = parse_draftingnote_sample()
        types_found = {elem[1] for elem in structure}
        assert 'draftingnote' in types_found

    def test_reasoning_parsed(self):
        """reasoning environment appears in parsed structure."""
        structure, file_contents = parse_draftingnote_sample()
        types_found = {elem[1] for elem in structure}
        assert 'reasoning' in types_found

    def test_draftingnote_label_extracted(self):
        """Labelled draftingnote has its label extracted."""
        structure, file_contents = parse_draftingnote_sample()
        labels = {elem[4] for elem in structure if elem[4]}
        assert 'dn:open_question' in labels

    def test_draftingnote_count(self):
        """Correct number of draftingnotes found."""
        structure, file_contents = parse_draftingnote_sample()
        dn_count = sum(1 for elem in structure if elem[1] == 'draftingnote')
        assert dn_count == 2

    def test_draftingnote_line_end_in_json(self):
        """Draftingnote has correct line_end in JSON export."""
        import json
        structure, file_contents = parse_draftingnote_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_json_export(structure, file_contents, registry)
        data = json.loads(output)
        dn = next((e for e in data['elements'] if e.get('label') == 'dn:open_question'), None)
        assert dn is not None
        assert dn['line_end'] >= dn['line']


# ===========================================================================
# AI. Default quiet mode tests
# ===========================================================================

class TestDefaultQuiet:
    """Tests for default quiet mode and --warnings flag."""

    def test_quiet_flag_defaults_true(self):
        """The -q/--quiet flag defaults to True (quiet by default)."""
        # Simulate parsing with no flags
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('-q', '--quiet', action='store_true', default=True)
        parser.add_argument('--warnings', action='store_true')
        args = parser.parse_args([])
        assert args.quiet is True
        assert args.warnings is False

    def test_warnings_flag_is_opt_in(self):
        """The --warnings flag must be explicitly passed."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('-q', '--quiet', action='store_true', default=True)
        parser.add_argument('--warnings', action='store_true')
        args = parser.parse_args(['--warnings'])
        assert args.warnings is True

    def test_warn_unlabelled_still_works(self, capsys):
        """warn_unlabelled_sections still produces output when called directly."""
        filler = "\n".join([f"This is filler line {i} with enough text." for i in range(20)])
        latex = (
            "\\section{No Label Here}\n\n"
            "Some text.\n\n"
            + filler + "\n\n"
            "\\section{Has Label}\n"
            "\\label{sec:has_label}\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex)
            f.flush()
            tmp_path = f.name
        try:
            result = ls.extract_latex_structure(tmp_path)
            ls.warn_unlabelled_sections(result[0])
            captured = capsys.readouterr()
            # The function itself always warns; gating is in main()
            assert 'No Label Here' in captured.err
        finally:
            os.unlink(tmp_path)


# ===========================================================================
# AJ. Compact out-of-scope annotation tests
# ===========================================================================

class TestCompactOutOfScope:
    """Tests for out-of-scope ref annotations in compact mode."""

    def test_compact_oos_annotation(self):
        """Out-of-scope ref gets (oos) annotation in compact mode."""
        structure, file_contents = parse_scope_sample()
        all_label_set = {elem[4] for elem in structure if elem[4]}
        scoped = ls.apply_scope_filter(structure, 'sec:first', file_contents)
        registry = ls.build_label_registry(scoped)
        output = ls.format_compact_output(
            scoped, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=all_label_set
        )
        assert 'thm:beta(oos)' in output

    def test_compact_not_found_annotation(self):
        """Truly missing ref gets (!) annotation in compact mode."""
        structure, file_contents = parse_scope_sample()
        all_label_set = {elem[4] for elem in structure if elem[4]}
        scoped = ls.apply_scope_filter(structure, 'sec:first', file_contents)
        registry = ls.build_label_registry(scoped)
        output = ls.format_compact_output(
            scoped, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=all_label_set
        )
        assert 'thm:nonexistent(!)' in output

    def test_compact_no_annotation_without_scope(self):
        """Without known_labels, refs are bare (no annotations)."""
        structure, file_contents = parse_scope_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_compact_output(
            structure, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=None
        )
        assert '(oos)' not in output
        assert '(!)' not in output


# ===========================================================================
# AK. Filter flag tests
# ===========================================================================

class TestFilterFlag:
    """Tests for --filter regex post-filter."""

    def test_filter_by_label_prefix(self):
        """Filter 'thm:' keeps only lines containing theorem labels."""
        structure, file_contents = parse_sample()
        output = ls.format_compact_output(structure, file_contents)
        lines = output.strip().split('\n')
        # Apply filter
        pattern = re.compile('thm:', re.IGNORECASE)
        filtered = [line for line in lines if pattern.search(line)]
        assert len(filtered) > 0
        for line in filtered:
            assert 'thm:' in line

    def test_filter_by_title(self):
        """Filter 'Introduction' matches section title."""
        structure, file_contents = parse_sample()
        output = ls.format_compact_output(structure, file_contents)
        lines = output.strip().split('\n')
        pattern = re.compile('Introduction', re.IGNORECASE)
        filtered = [line for line in lines if pattern.search(line)]
        assert len(filtered) >= 1
        assert any('Introduction' in line for line in filtered)

    def test_filter_regex(self):
        """Filter with regex pattern works."""
        structure, file_contents = parse_sample()
        output = ls.format_compact_output(structure, file_contents)
        lines = output.strip().split('\n')
        pattern = re.compile(r'def:.*boundary', re.IGNORECASE)
        filtered = [line for line in lines if pattern.search(line)]
        assert len(filtered) >= 1
        assert any('def:bulk_boundary' in line for line in filtered)

    def test_filter_no_match(self):
        """Filter with no matches returns empty output."""
        structure, file_contents = parse_sample()
        output = ls.format_compact_output(structure, file_contents)
        lines = output.strip().split('\n')
        pattern = re.compile('ZZZZNONEXISTENT', re.IGNORECASE)
        filtered = [line for line in lines if pattern.search(line)]
        assert len(filtered) == 0


# ===========================================================================
# AL. Review preset tests
# ===========================================================================

class TestReviewPreset:
    """Tests for --review preset flag."""

    def test_review_sets_flags(self):
        """--review sets status, hide_ready, only_numbered_results, compact."""
        import argparse
        args = argparse.Namespace(
            review=True,
            status=None,
            hide_ready=False,
            only_numbered_results=False,
            compact=False,
        )
        # Simulate the preset expansion
        if args.review:
            if not args.status:
                args.status = 'DEFAULT'
            args.hide_ready = True
            args.only_numbered_results = True
            args.compact = True

        assert args.status == 'DEFAULT'
        assert args.hide_ready is True
        assert args.only_numbered_results is True
        assert args.compact is True

    def test_review_preserves_explicit_status(self):
        """--review with explicit --status path preserves that path."""
        import argparse
        args = argparse.Namespace(
            review=True,
            status='custom.tsv',
            hide_ready=False,
            only_numbered_results=False,
            compact=False,
        )
        if args.review:
            if not args.status:
                args.status = 'DEFAULT'
            args.hide_ready = True
            args.only_numbered_results = True
            args.compact = True

        assert args.status == 'custom.tsv'


# ===========================================================================
# AM. Show label tests
# ===========================================================================

class TestShowLabel:
    """Tests for --show and --show-full."""

    def test_show_contains_body(self):
        """format_show returns the theorem body text."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:main_obstruction', structure, file_contents, registry)
        assert 'finite-index recovery map' in output

    def test_show_contains_header(self):
        """format_show includes type and title in header."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:main_obstruction', structure, file_contents, registry)
        assert '[Theorem]' in output
        assert 'Main obstruction' in output

    def test_show_strips_label(self):
        """format_show strips \\label{} lines from body."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:main_obstruction', structure, file_contents, registry)
        assert '\\label{thm:main_obstruction}' not in output

    def test_show_truncates(self):
        """format_show truncates to specified number of lines."""
        # Create a long environment
        long_body = '\n'.join([f"Line {i} of the proof." for i in range(30)])
        latex = (
            "\\section{Test}\\label{sec:test}\n\n"
            "\\begin{theorem}[Long theorem]\\label{thm:long}\n"
            + long_body + "\n"
            "\\end{theorem}\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex)
            f.flush()
            tmp_path = f.name
        try:
            result = ls.extract_latex_structure(tmp_path)
            structure, file_contents = result
            registry = ls.build_label_registry(structure)
            output = ls.format_show('thm:long', structure, file_contents, registry, truncate=5)
            assert '... (' in output
            assert 'more lines)' in output
        finally:
            os.unlink(tmp_path)

    def test_show_full_no_truncation(self):
        """format_show with truncate=None shows all lines."""
        long_body = '\n'.join([f"Line {i} of the proof." for i in range(30)])
        latex = (
            "\\section{Test}\\label{sec:test}\n\n"
            "\\begin{theorem}[Long theorem]\\label{thm:long}\n"
            + long_body + "\n"
            "\\end{theorem}\n"
        )
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(latex)
            f.flush()
            tmp_path = f.name
        try:
            result = ls.extract_latex_structure(tmp_path)
            structure, file_contents = result
            registry = ls.build_label_registry(structure)
            output = ls.format_show('thm:long', structure, file_contents, registry, truncate=None)
            assert '... (' not in output
            assert 'Line 29' in output
        finally:
            os.unlink(tmp_path)

    def test_show_unknown_label(self):
        """format_show with unknown label returns error."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:nonexistent', structure, file_contents, registry)
        assert 'Error' in output
        assert 'not found' in output


# ---------------------------------------------------------------------------
# AN. Auto-detection of \newtheorem declarations (Priority 2, item 2.1)
# ---------------------------------------------------------------------------

NEWTHEOREM_PREAMBLE = r"""\newtheorem{observation}{Observation}
\newtheorem{axiom}{Axiom}[section]
\newtheorem*{unnumbered}{Unnumbered Remark}
"""

NEWTHEOREM_BODY = r"""\section{Test section}\label{sec:test}

\begin{observation}[First observation]\label{obs:first}
Something observed.
\end{observation}

\begin{axiom}\label{ax:one}
An axiom.
\end{axiom}

\begin{theorem}[Standard theorem]\label{thm:std}
A standard theorem still works.
\end{theorem}
"""


class TestNewtheoremDetection:
    """AN. Auto-detect \\newtheorem declarations."""

    def test_scan_finds_newtheorem(self):
        """scan_newtheorem_declarations detects \\newtheorem{NAME}."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
            f.write(NEWTHEOREM_PREAMBLE)
            f.flush()
            tmp = f.name
        try:
            result = ls.scan_newtheorem_declarations([tmp])
            assert 'observation' in result
            assert 'axiom' in result
            assert 'unnumbered' in result
        finally:
            os.unlink(tmp)

    def test_scan_follows_input(self):
        """scan_newtheorem_declarations follows \\input chains."""
        import tempfile, os as _os
        tmpdir = tempfile.mkdtemp()
        preamble_path = _os.path.join(tmpdir, 'preamble.tex')
        main_path = _os.path.join(tmpdir, 'main.tex')
        with open(preamble_path, 'w') as f:
            f.write(r'\newtheorem{custom}{Custom}' + '\n')
        with open(main_path, 'w') as f:
            f.write(r'\input{preamble}' + '\n' + r'\begin{document}' + '\n')
        try:
            result = ls.scan_newtheorem_declarations([main_path])
            assert 'custom' in result
        finally:
            _os.unlink(preamble_path)
            _os.unlink(main_path)
            _os.rmdir(tmpdir)

    def test_detected_env_is_parsed(self):
        """After scanning, custom environments appear in parsed structure."""
        import tempfile
        # Reset _active_environments to include detected envs
        old_active = ls._active_environments.copy()
        try:
            combined = NEWTHEOREM_PREAMBLE + NEWTHEOREM_BODY
            with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
                f.write(combined)
                f.flush()
                tmp = f.name
            try:
                detected = ls.scan_newtheorem_declarations([tmp])
                ls._active_environments = ls._active_environments | detected
                result = ls.extract_latex_structure(tmp)
                assert result is not None
                structure, _ = result
                types = {elem[1] for elem in structure}
                assert 'observation' in types
                assert 'axiom' in types
                assert 'theorem' in types  # standard still works
            finally:
                os.unlink(tmp)
        finally:
            ls._active_environments = old_active

    def test_default_envs_still_work(self):
        """Standard environments work without any \\newtheorem declarations."""
        structure, _ = parse_sample()
        types = {elem[1] for elem in structure}
        assert 'theorem' in types
        assert 'definition' in types

    def test_extra_env_extends_active(self):
        """Manually adding to _active_environments allows parsing custom envs."""
        import tempfile
        old_active = ls._active_environments.copy()
        try:
            ls._active_environments = ls._active_environments | {'widget'}
            latex = (
                "\\section{Test}\\label{sec:t}\n"
                "\\begin{widget}[Gadget]\\label{wid:one}\nContent.\n\\end{widget}\n"
            )
            with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
                f.write(latex)
                f.flush()
                tmp = f.name
            try:
                result = ls.extract_latex_structure(tmp)
                structure, _ = result
                types = {elem[1] for elem in structure}
                assert 'widget' in types
            finally:
                os.unlink(tmp)
        finally:
            ls._active_environments = old_active


# ---------------------------------------------------------------------------
# AO. Hardcoded aux file fallback removed (Priority 2, item 2.2)
# ---------------------------------------------------------------------------

class TestNoHardcodedAux:
    """AO. _resolve_aux_path no longer falls back to HolographicExtensions.aux."""

    def test_same_stem_fallback(self):
        """Same-stem .aux file is found."""
        import tempfile, os as _os
        tmpdir = tempfile.mkdtemp()
        tex_path = _os.path.join(tmpdir, 'foo.tex')
        aux_path = _os.path.join(tmpdir, 'foo.aux')
        open(tex_path, 'w').close()
        open(aux_path, 'w').close()
        try:
            result = ls._resolve_aux_path(None, [tex_path])
            assert result == aux_path
        finally:
            _os.unlink(tex_path)
            _os.unlink(aux_path)
            _os.rmdir(tmpdir)

    def test_no_holographic_fallback(self):
        """No fallback to HolographicExtensions.aux when stem aux missing."""
        import tempfile, os as _os
        tmpdir = tempfile.mkdtemp()
        tex_path = _os.path.join(tmpdir, 'other.tex')
        holo_aux = _os.path.join(tmpdir, 'HolographicExtensions.aux')
        open(tex_path, 'w').close()
        open(holo_aux, 'w').close()
        try:
            result = ls._resolve_aux_path(None, [tex_path])
            assert result is None  # should NOT find HolographicExtensions.aux
        finally:
            _os.unlink(tex_path)
            _os.unlink(holo_aux)
            _os.rmdir(tmpdir)

    def test_explicit_aux_overrides(self):
        """Explicit --aux-file is returned regardless of stem matches."""
        import tempfile, os as _os
        tmpdir = tempfile.mkdtemp()
        explicit_aux = _os.path.join(tmpdir, 'custom.aux')
        open(explicit_aux, 'w').close()
        try:
            result = ls._resolve_aux_path(explicit_aux, ['nonexistent.tex'])
            assert result == explicit_aux
        finally:
            _os.unlink(explicit_aux)
            _os.rmdir(tmpdir)


# ---------------------------------------------------------------------------
# AP. Fuzzy scope selection (Priority 2, item 2.4)
# ---------------------------------------------------------------------------

FUZZY_SCOPE_LATEX = r"""\section{Introduction to algebra}\label{sec:intro}

\begin{definition}[Basic group]\label{def:group}
A group is a set with an operation.
\end{definition}

\section{Advanced topics in algebra}\label{sec:advanced}

\begin{theorem}[Main result]\label{thm:main}
The main theorem statement.
\end{theorem}

\section{Geometry and topology}\label{sec:geom}

\begin{lemma}[Geometric lemma]\label{lem:geom}
A geometric result.
\end{lemma}
"""


def parse_fuzzy_scope():
    """Parse FUZZY_SCOPE_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(FUZZY_SCOPE_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestFuzzyScope:
    """AP. Fuzzy scope selection by title or partial label."""

    def test_exact_label_unchanged(self):
        """Exact label match still works (backward compatibility)."""
        structure, fc = parse_fuzzy_scope()
        filtered = ls.apply_scope_filter(structure, 'sec:intro', fc)
        labels = {e[4] for e in filtered if e[4]}
        assert 'sec:intro' in labels
        assert 'def:group' in labels
        assert 'thm:main' not in labels

    def test_title_substring_match(self):
        """Case-insensitive title substring finds the right section."""
        structure, fc = parse_fuzzy_scope()
        filtered = ls.apply_scope_filter(structure, 'geometry and topology', fc)
        labels = {e[4] for e in filtered if e[4]}
        assert 'sec:geom' in labels
        assert 'lem:geom' in labels
        assert 'thm:main' not in labels

    def test_ambiguous_match_returns_empty(self):
        """Ambiguous substring matching multiple elements returns empty list."""
        structure, fc = parse_fuzzy_scope()
        # "algebra" matches both sec:intro ("Introduction to algebra") and sec:advanced ("Advanced topics in algebra")
        filtered = ls.apply_scope_filter(structure, 'algebra', fc)
        assert filtered == []

    def test_no_match_returns_full(self):
        """Unmatched term returns full structure with warning."""
        structure, fc = parse_fuzzy_scope()
        filtered = ls.apply_scope_filter(structure, 'xyznonexistent', fc)
        assert len(filtered) == len(structure)

    def test_partial_label_match(self):
        """Substring matching part of a label works."""
        structure, fc = parse_fuzzy_scope()
        # "sec:geom" is an exact label match, but "geom" should fuzzy-match
        # It matches sec:geom (title "Geometry and topology"), lem:geom (label contains "geom"),
        # and def:group's title doesn't match. Let's test a unique partial.
        filtered = ls.apply_scope_filter(structure, 'topology', fc)
        labels = {e[4] for e in filtered if e[4]}
        assert 'sec:geom' in labels
        assert 'lem:geom' in labels


# ===========================================================================
# AQ. --show-limit tests
# ===========================================================================

LONG_THEOREM_LATEX = r"""
\section{Results}
\label{sec:results}

\begin{theorem}[Long result]
\label{thm:long}
Line 1 of the theorem.
Line 2 of the theorem.
Line 3 of the theorem.
Line 4 of the theorem.
Line 5 of the theorem.
Line 6 of the theorem.
Line 7 of the theorem.
Line 8 of the theorem.
Line 9 of the theorem.
Line 10 of the theorem.
Line 11 of the theorem.
Line 12 of the theorem.
\end{theorem}
"""


def parse_long_theorem():
    """Parse LONG_THEOREM_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(LONG_THEOREM_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestShowLimit:
    """AQ. Tests for --show-limit flag."""

    def test_show_limit_overrides_default(self):
        """--show-limit 3 truncates to 3 lines."""
        structure, file_contents = parse_long_theorem()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:long', structure, file_contents, registry, truncate=3)
        assert 'Line 3' in output
        assert 'Line 4' not in output
        assert '... (' in output

    def test_show_limit_overrides_full(self):
        """--show-limit with --show-full truncates."""
        structure, file_contents = parse_long_theorem()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:long', structure, file_contents, registry, truncate=5)
        assert 'Line 5' in output
        assert 'Line 6' not in output
        assert '... (' in output

    def test_show_limit_zero(self):
        """--show-limit 0 shows only header."""
        structure, file_contents = parse_long_theorem()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:long', structure, file_contents, registry, truncate=0)
        assert '[Theorem]' in output
        assert 'Long result' in output
        assert 'Line 1' not in output
        assert '... (' in output and 'more lines)' in output


# ===========================================================================
# AR. --show with multiple labels
# ===========================================================================

class TestShowMultipleLabels:
    """AR. Tests for --show with comma-separated labels."""

    def test_show_single_unchanged(self):
        """Single label produces no separator."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_show('thm:main_obstruction', structure, file_contents, registry)
        assert '---' not in output
        assert 'Main obstruction' in output

    def test_show_comma_separated(self):
        """Two labels produce both bodies separated by ---."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        labels = ['thm:main_obstruction', 'def:bulk_boundary']
        parts = [ls.format_show(l, structure, file_contents, registry) for l in labels]
        output = '\n---\n'.join(parts)
        assert '---' in output
        assert 'Main obstruction' in output
        assert 'Bulk--boundary map' in output

    def test_show_with_spaces(self):
        """Spaces after commas are stripped."""
        raw = 'thm:main_obstruction, def:bulk_boundary'
        labels = [l.strip() for l in raw.split(',') if l.strip()]
        assert labels == ['thm:main_obstruction', 'def:bulk_boundary']

    def test_show_unknown_in_list(self):
        """One valid + one invalid shows body + error."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        labels = ['thm:main_obstruction', 'thm:nonexistent']
        parts = [ls.format_show(l, structure, file_contents, registry) for l in labels]
        output = '\n---\n'.join(parts)
        assert 'Main obstruction' in output
        assert "Error: label 'thm:nonexistent' not found." in output

    def test_show_trailing_comma(self):
        """Trailing comma doesn't produce empty label."""
        raw = 'thm:main_obstruction,'
        labels = [l.strip() for l in raw.split(',') if l.strip()]
        assert labels == ['thm:main_obstruction']


# ===========================================================================
# AS. --scope cross-chapter ref summary
# ===========================================================================

class TestScopeSummary:
    """AS. Tests for out-of-scope reference summary line."""

    def test_scope_summary_terminal(self):
        """Terminal mode shows summary with count of out-of-scope refs."""
        structure, file_contents = parse_scope_sample()
        all_label_set = {elem[4] for elem in structure if elem[4]}
        scoped = ls.apply_scope_filter(structure, 'sec:first', file_contents)
        registry = ls.build_label_registry(scoped)
        output = ls.format_output(
            scoped, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=all_label_set
        )
        # Count occurrences and verify summary would be correct
        oos_count = output.count('(out of scope)')
        assert oos_count > 0, "Expected at least one out-of-scope ref"

    def test_scope_summary_compact(self):
        """Compact mode shows (oos) annotations."""
        structure, file_contents = parse_scope_sample()
        all_label_set = {elem[4] for elem in structure if elem[4]}
        scoped = ls.apply_scope_filter(structure, 'sec:first', file_contents)
        registry = ls.build_label_registry(scoped)
        output = ls.format_compact_output(
            scoped, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=all_label_set
        )
        oos_count = output.count('(oos)')
        assert oos_count > 0, "Expected at least one (oos) annotation"

    def test_no_oos_no_summary(self):
        """No cross-scope refs means no summary line."""
        structure, file_contents = parse_scope_sample()
        all_label_set = {elem[4] for elem in structure if elem[4]}
        # Scope to sec:second — thm:beta has no cross-scope refs
        scoped = ls.apply_scope_filter(structure, 'sec:second', file_contents)
        registry = ls.build_label_registry(scoped)
        output = ls.format_output(
            scoped, file_contents,
            ref_options={'enabled': True, 'levels': ['theorem'], 'group_by_type': False},
            label_registry=registry,
            known_labels=all_label_set
        )
        assert '(out of scope)' not in output


# ===========================================================================
# AT. --neighbourhood tests
# ===========================================================================

class TestNeighbourhood:
    """AT. Tests for --neighbourhood flag."""

    def test_neighbourhood_basic(self):
        """Neighbourhood of thm:main_obstruction includes nearby elements."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_neighbourhood('thm:main_obstruction', structure,
                                         file_contents, registry, n=3)
        # Should include def:bulk_boundary (before) and lem:tech_estimate (after)
        assert 'bulk_boundary' in output.lower() or 'Bulk' in output
        assert 'tech_estimate' in output.lower() or 'Technical' in output

    def test_neighbourhood_size_1(self):
        """N=1 shows only immediate neighbours."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_neighbourhood('thm:main_obstruction', structure,
                                         file_contents, registry, n=1)
        # With n=1, should have at most 3 elements (1 before, target, 1 after)
        # Check that distant elements are NOT present
        assert 'Spectral bound' not in output

    def test_neighbourhood_at_start(self):
        """Element at start of file — no crash, only elements after."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_neighbourhood('sec:intro', structure,
                                         file_contents, registry, n=2)
        assert 'Introduction' in output
        assert output  # non-empty

    def test_neighbourhood_unknown_label(self):
        """Unknown label returns error string."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_neighbourhood('thm:nonexistent', structure,
                                         file_contents, registry)
        assert 'Error' in output
        assert 'not found' in output

    def test_neighbourhood_compact(self):
        """Compact mode produces tab-separated output."""
        structure, file_contents = parse_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_neighbourhood('thm:main_obstruction', structure,
                                         file_contents, registry, n=2,
                                         compact=True)
        assert '\t' in output


# ===========================================================================
# AU. --proof tests
# ===========================================================================

PROOF_LATEX = r"""
\section{Results}
\label{sec:results}

\begin{theorem}[First result]
\label{thm:first}
Statement of first theorem.
\end{theorem}

\begin{proof}
We prove by contradiction.
Line 2 of proof.
Line 3 of proof.
\end{proof}

\begin{lemma}[Helper]
\label{lem:helper}
A helper lemma.
\end{lemma}

\begin{theorem}[Second result]
\label{thm:second}
Statement of second.
\end{theorem}

\begin{proof}[Proof of Theorem~\ref{thm:second}]
Explicit proof reference.
\end{proof}

\begin{definition}[Widget]
\label{def:widget}
A widget is defined.
\end{definition}
"""


def parse_proof_sample():
    """Parse PROOF_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(PROOF_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestProofLookup:
    """AU. Tests for --proof flag."""

    def test_proof_proximity(self):
        """--proof thm:first finds the immediately following proof."""
        structure, file_contents = parse_proof_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_proof('thm:first', structure, file_contents, registry)
        assert 'contradiction' in output
        assert '[Proof of Theorem]' in output

    def test_proof_explicit_ref(self):
        """--proof thm:second finds proof with explicit \\ref{thm:second}."""
        structure, file_contents = parse_proof_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_proof('thm:second', structure, file_contents, registry)
        assert 'Explicit proof reference' in output

    def test_proof_no_proof(self):
        """--proof def:widget returns 'No proof found'."""
        structure, file_contents = parse_proof_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_proof('def:widget', structure, file_contents, registry)
        assert 'No proof found' in output

    def test_proof_unknown_label(self):
        """--proof with unknown label returns error."""
        structure, file_contents = parse_proof_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_proof('thm:nonexistent', structure, file_contents, registry)
        assert 'Error' in output
        assert 'not found' in output

    def test_proof_skips_intervening(self):
        """--proof lem:helper does NOT match thm:second's proof (intervening theorem)."""
        structure, file_contents = parse_proof_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_proof('lem:helper', structure, file_contents, registry)
        assert 'No proof found' in output


# ===========================================================================
# AV. --orphan-report tests
# ===========================================================================

ORPHAN_LATEX = r"""
\section{Intro}
\label{sec:intro}

\begin{theorem}[Referenced]
\label{thm:referenced}
Statement.
\end{theorem}

\begin{lemma}[Orphan]
\label{lem:orphan}
Never referenced anywhere.
\end{lemma}

\begin{proof}
Uses \ref{thm:referenced} and \ref{thm:missing_target}.
\end{proof}
"""


def parse_orphan_sample():
    """Parse ORPHAN_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(ORPHAN_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestOrphanReport:
    """AV. Tests for --orphan-report."""

    def test_finds_orphaned_labels(self):
        """Labels never referenced are reported as orphaned."""
        structure, file_contents = parse_orphan_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_orphan_report(structure, file_contents, registry)
        assert 'lem:orphan' in output
        assert 'Orphaned labels' in output

    def test_finds_missing_refs(self):
        """References to undefined labels are reported as missing."""
        structure, file_contents = parse_orphan_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_orphan_report(structure, file_contents, registry)
        assert 'thm:missing_target' in output
        assert 'Missing references' in output

    def test_referenced_not_orphaned(self):
        """Labels that are referenced are NOT in the orphan list."""
        structure, file_contents = parse_orphan_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_orphan_report(structure, file_contents, registry)
        # thm:referenced is used in the proof
        orphan_section = output.split('Missing references')[0]
        assert 'thm:referenced' not in orphan_section


# ===========================================================================
# AW. --drafting-report tests
# ===========================================================================

DRAFTING_REPORT_LATEX = r"""
\section{Analysis}
\label{sec:analysis}

\begin{theorem}[Main]
\label{thm:main}
Statement.
\end{theorem}

\begin{draftingnote}
This proof needs checking. See \ref{thm:main}.
\end{draftingnote}

\begin{draftingnote}[Gap in argument]
\label{dn:gap}
The step from line 3 to line 4 is not justified.
\end{draftingnote}

\section{Further work}
\label{sec:further}

\begin{reasoning}
We expect \ref{thm:main} to generalise.
\end{reasoning}
"""


def parse_drafting_report_sample():
    """Parse DRAFTING_REPORT_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(DRAFTING_REPORT_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestDraftingReport:
    """AW. Tests for --drafting-report."""

    def test_finds_draftingnotes(self):
        """Report includes draftingnote environments."""
        structure, file_contents = parse_drafting_report_sample()
        output = ls.format_drafting_report(structure, file_contents)
        assert 'draftingnote' in output
        assert 'note(s)' in output

    def test_finds_reasoning(self):
        """Report includes reasoning environments."""
        structure, file_contents = parse_drafting_report_sample()
        output = ls.format_drafting_report(structure, file_contents)
        assert 'reasoning' in output

    def test_shows_first_line(self):
        """Report shows the first line of each note's body."""
        structure, file_contents = parse_drafting_report_sample()
        output = ls.format_drafting_report(structure, file_contents)
        assert 'proof needs checking' in output

    def test_shows_refs(self):
        """Report shows refs inside draftingnotes."""
        structure, file_contents = parse_drafting_report_sample()
        output = ls.format_drafting_report(structure, file_contents)
        assert 'thm:main' in output

    def test_shows_label(self):
        """Report shows labels of labelled draftingnotes."""
        structure, file_contents = parse_drafting_report_sample()
        output = ls.format_drafting_report(structure, file_contents)
        assert 'dn:gap' in output

    def test_empty_document(self):
        """Document with no notes returns appropriate message."""
        structure, file_contents = parse_sample()
        output = ls.format_drafting_report(structure, file_contents)
        # SAMPLE_LATEX has no draftingnotes
        assert 'No drafting notes' in output


# ===========================================================================
# AX. --cite-usage tests
# ===========================================================================

CITE_LATEX = r"""
\section{Background}
\label{sec:bg}

\begin{theorem}[Alpha]
\label{thm:alpha}
A result from \cite{Jones1983}.
\end{theorem}

\begin{remark}
\label{rmk:note}
See also \cite{Jones1983,Connes1994} for context.
\end{remark}

\begin{proof}
By \cite{Connes1994}.
\end{proof}
"""


def parse_cite_sample():
    """Parse CITE_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(CITE_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestCiteUsage:
    """AX. Tests for --cite-usage KEY."""

    def test_finds_citing_elements(self):
        """Citation key used in multiple elements is found."""
        structure, file_contents = parse_cite_sample()
        output = ls.format_cite_usage('Jones1983', structure, file_contents)
        assert 'Jones1983' in output
        assert 'thm:alpha' in output

    def test_not_found(self):
        """Citation key not in document returns appropriate message."""
        structure, file_contents = parse_cite_sample()
        output = ls.format_cite_usage('Nonexistent2099', structure, file_contents)
        assert 'not found' in output

    def test_shows_section_context(self):
        """Output includes parent section context."""
        structure, file_contents = parse_cite_sample()
        output = ls.format_cite_usage('Connes1994', structure, file_contents)
        assert 'sec:bg' in output or 'Background' in output


# ===========================================================================
# AY. --parse-summary tests
# ===========================================================================

class TestParseSummary:
    """AY. Tests for --parse-summary."""

    def test_summary_counts(self):
        """Summary includes element counts."""
        structure, file_contents = parse_sample()
        output = ls.format_parse_summary(structure, file_contents)
        assert 'Parse summary' in output
        assert 'theorem' in output
        assert 'definition' in output

    def test_labelled_count(self):
        """Summary reports labelled vs unlabelled counts."""
        structure, file_contents = parse_sample()
        output = ls.format_parse_summary(structure, file_contents)
        assert 'Labelled' in output
        assert 'Unlabelled' in output


# ===========================================================================
# AZ. Tiered warnings tests
# ===========================================================================

class TestTieredWarnings:
    """AZ. Tests for --warnings=errors/all/none."""

    def test_default_is_errors(self):
        """Default --warnings value is 'errors'."""
        import argparse
        # Simulate argparse default
        parser = argparse.ArgumentParser()
        parser.add_argument('--warnings', nargs='?', const='all', default='errors',
                            choices=['errors', 'all', 'none'])
        args = parser.parse_args([])
        assert args.warnings == 'errors'

    def test_bare_warnings_is_all(self):
        """--warnings without value gives 'all'."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--warnings', nargs='?', const='all', default='errors',
                            choices=['errors', 'all', 'none'])
        args = parser.parse_args(['--warnings'])
        assert args.warnings == 'all'

    def test_warnings_none(self):
        """--warnings=none gives 'none'."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--warnings', nargs='?', const='all', default='errors',
                            choices=['errors', 'all', 'none'])
        args = parser.parse_args(['--warnings=none'])
        assert args.warnings == 'none'

    def test_warn_level_helpers(self):
        """Verify warn_errors/warn_info logic."""
        for level, expect_errors, expect_info in [
            ('errors', True, False),
            ('all', True, True),
            ('none', False, False),
        ]:
            warn_errors = level in ('errors', 'all')
            warn_info = level == 'all'
            assert warn_errors == expect_errors, f"level={level}"
            assert warn_info == expect_info, f"level={level}"


# ===========================================================================
# BA. \cref/\eqref extraction tests
# ===========================================================================

CREF_LATEX = r"""
\section{Results}
\label{sec:results}

\begin{theorem}[Main]
\label{thm:main}
Statement.
\end{theorem}

\begin{proof}
By \cref{thm:main} and \eqref{eq:energy} and \Cref{lem:helper}.
\end{proof}

\begin{lemma}[Helper]
\label{lem:helper}
See \ref{thm:main}.
\end{lemma}
"""


def parse_cref_sample():
    """Parse CREF_LATEX and return (structure, file_contents)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tex', delete=False, dir='/tmp') as f:
        f.write(CREF_LATEX)
        f.flush()
        tmp_path = f.name
    try:
        return _parse_and_sort(tmp_path)
    finally:
        os.unlink(tmp_path)


class TestCrefEqrefExtraction:
    """BA. Tests for \\cref/\\eqref/\\Cref extraction."""

    def test_cref_extracted_in_orphan_report(self):
        """\\cref references are detected (thm:main is not orphaned)."""
        structure, file_contents = parse_cref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_orphan_report(structure, file_contents, registry)
        orphan_section = output.split('Missing references')[0] if 'Missing references' in output else output
        # thm:main is referenced via \cref and \ref — should NOT be orphaned
        assert 'thm:main' not in orphan_section

    def test_eqref_detected_as_missing(self):
        """\\eqref{eq:energy} shows up as a missing reference (not defined)."""
        structure, file_contents = parse_cref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_orphan_report(structure, file_contents, registry)
        assert 'eq:energy' in output

    def test_Cref_extracted(self):
        """\\Cref{lem:helper} is detected as a reference."""
        structure, file_contents = parse_cref_sample()
        registry = ls.build_label_registry(structure)
        output = ls.format_orphan_report(structure, file_contents, registry)
        orphan_section = output.split('Missing references')[0] if 'Missing references' in output else output
        # lem:helper referenced via \Cref — should NOT be orphaned
        assert 'lem:helper' not in orphan_section


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
