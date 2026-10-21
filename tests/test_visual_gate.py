"""Rendering regressions for serialized Marimo callout HTML, not browser geometry."""

import marimo as mo
import pytest

from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.verification.gate import GateCheckResult, VerificationGate


@pytest.fixture(scope="module")
def gate(tmp_path_factory: pytest.TempPathFactory) -> VerificationGate:
    tmp_path = tmp_path_factory.mktemp("visual-gate")
    return VerificationGate(
        AdaptiveMemoryStore(tmp_path / "local-memory", tmp_path / "global-memory"),
        cwd=tmp_path,
    )


def inspect_output(gate: VerificationGate, output: mo.Html) -> GateCheckResult:
    return gate.run_visual_layout_check(
        gate.cwd / "app.py",
        _precomputed_run=([output], {"output": output}, []),
    )


@pytest.mark.parametrize("indentation", [4, 16, 24])
def test_nested_callout_detects_markdown_rendered_as_indented_code(
    gate: VerificationGate, indentation: int,
) -> None:
    # A multiline interpolated source list with a flush-left second line prevents
    # mo.md from dedenting the preceding heading. This is the real card regression.
    sources = "- First source\n- Second source"
    padding = " " * indentation
    broken = mo.md(f"\n{padding}#### Source provenance\n{padding}SHA-256 source records:\n\n{padding}{sources}\n")
    output = mo.callout(mo.callout(broken, kind="info"), kind="neutral")
    assert "<pre>" in broken.text
    assert "<pre>" not in output.text  # Serialized behind two data-html attributes.

    result = inspect_output(gate, output)

    assert not result.passed
    assert any("VisualMarkdownCodeBlock[cell #0]" in message for message in result.diagnostics)


def test_normal_multiline_markdown_callout_passes(gate: VerificationGate) -> None:
    output = mo.callout(mo.md("#### Source provenance\n\n**Value:** EUR 1,900\n\n- First source\n- Second source"))

    assert inspect_output(gate, output).passed


@pytest.mark.parametrize("language", ["markdown", "python", ""])
def test_intentional_fenced_source_inside_callout_is_not_a_rendering_error(
    gate: VerificationGate, language: str,
) -> None:
    source = "### Literal source heading\n**literal bold**\n" + r"\text{some_value}" + "\n<marimo-error></marimo-error>"
    output = mo.callout(mo.md(f"```{language}\n{source}\n```"))

    result = inspect_output(gate, output)

    assert result.passed, result.diagnostics


def test_python_comments_in_indented_source_are_not_a_markdown_card_error(gate: VerificationGate) -> None:
    output = mo.callout(mo.Html('<pre><code class="language-python">### Python comment\nrevenue = 100</code></pre>'))

    assert inspect_output(gate, output).passed


@pytest.mark.parametrize("indentation", [0, 12])
def test_unlabelled_python_source_with_a_heading_comment_passes(
    gate: VerificationGate, indentation: int,
) -> None:
    padding = " " * indentation
    output = mo.callout(mo.Html(f"<pre><code>{padding}### Python comment\n{padding}revenue = 100</code></pre>"))

    assert inspect_output(gate, output).passed


@pytest.mark.parametrize(
    ("html", "diagnostic"),
    [
        ("<marimo-error>Cell failed</marimo-error>", "VisualErrorTraceback"),
        ('<span class="katex-error" title="ParseError">bad formula</span>', "VisualKaTeXSyntaxError"),
        ("<span>Traceback (most recent call last):</span>", "VisualErrorTraceback"),
    ],
)
def test_errors_hidden_inside_nested_callout_json_are_detected(
    gate: VerificationGate, html: str, diagnostic: str,
) -> None:
    output = mo.callout(mo.callout(mo.Html(html)))

    result = inspect_output(gate, output)

    assert not result.passed
    assert any(diagnostic in message for message in result.diagnostics)


def test_katex_formula_inside_nested_callout_is_decoded_and_checked(gate: VerificationGate) -> None:
    output = mo.callout(mo.callout(mo.md(r"$$\text{some_value}$$")))

    result = inspect_output(gate, output)

    assert not result.passed
    assert any("VisualKaTeXSyntaxError" in message for message in result.diagnostics)


def test_escaped_katex_underscore_inside_callout_passes(gate: VerificationGate) -> None:
    output = mo.callout(mo.md(r"$$\text{some\_value}$$"))

    assert inspect_output(gate, output).passed


def test_literal_escaped_error_html_is_not_parsed_as_an_error_element(gate: VerificationGate) -> None:
    output = mo.callout(mo.Html("<pre><code>&lt;marimo-error&gt;Example&lt;/marimo-error&gt;</code></pre>"))

    assert inspect_output(gate, output).passed


@pytest.mark.parametrize("in_callout", [False, True])
def test_ordinary_html_data_attribute_has_no_json_contract(
    gate: VerificationGate, in_callout: bool,
) -> None:
    output = mo.Html('<div data-html="&lt;p&gt;Preview&lt;/p&gt;">Visible content</div>')
    if in_callout:
        output = mo.callout(output)

    result = inspect_output(gate, output)

    assert result.passed, result.diagnostics
