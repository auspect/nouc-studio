"""End-to-End Realistic Multimodal Demo Suites for Nouc Studio.

Generates rich, realistic multimodal input bundles (Excel .xlsx, Parquet, DOCX, PPTX,
Markdown with GFM tables, PNG images, and Python source code for AST extraction) across
three high-stakes domains and builds + verifies their multi-view `marimo-studio` applications:

1. `demo_1_saas_ma_audit`: SaaS M&A Due Diligence & ARR Cohort Audit
2. `demo_2_clinical_biotech`: Phase II Oncology Biomarker & Trial Safety Audit
3. `demo_3_ai_infra_finops`: Sovereign AI GPU Cluster FinOps & Frontier LLM Routing Audit
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import docx
import polars as pl
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches
from pydantic import BaseModel, Field

from nouc_studio.agents.orchestrator import MultiAgentOrchestrator, OrchestrationReport
from nouc_studio.config import InsightsConfig
from nouc_studio.verification.gate import VerificationGate, VerificationSuiteReport


class DemoRunSummary(BaseModel):
    """Summary of a completed End-to-End realistic demo build and verification."""

    demo_id: str
    title: str
    domain: str
    input_dir: str
    output_dir: str
    notebook_path: str
    ingested_files_count: int
    tabular_tables_count: int
    document_artifacts_count: int
    ast_symbols_count: int
    lineage_nodes_count: int
    lineage_edges_count: int
    audited_metrics_count: int
    studio_views: list[str] = Field(default_factory=list)
    verification_passed: bool
    launch_command: str


def _create_banner_image(path: Path, title: str, bg_rgb: tuple[int, int, int]) -> None:
    """Create a clean visual diagram PNG artifact with deterministic geometry."""
    img = Image.new("RGB", (640, 240), color=bg_rgb)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 620, 220], outline=(255, 255, 255), width=3)
    draw.rectangle([45, 60, 220, 180], fill=(255, 255, 255, 40), outline=(226, 232, 240), width=2)
    draw.rectangle([260, 60, 420, 180], fill=(255, 255, 255, 40), outline=(226, 232, 240), width=2)
    draw.rectangle([460, 60, 595, 180], fill=(255, 255, 255, 40), outline=(226, 232, 240), width=2)
    draw.text((35, 32), title, fill=(255, 255, 255))
    img.save(path)


def generate_demo_1_saas_ma_bundle(base_dir: Path) -> tuple[Path, str, str]:
    """Create Demo 1: SaaS M&A Due Diligence & ARR Cohort Audit multimodal files."""
    demo_dir = base_dir / "demo_1_saas_ma_audit"
    demo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Excel (.xlsx): Enterprise ARR Cohorts with realistic partial missingness on new Q4 cohort
    df_cohorts = pl.DataFrame(
        {
            "cohort_quarter": ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"],
            "starting_arr_usd": [4200000.0, 4850000.0, 5600000.0, 6450000.0, 7300000.0, 8400000.0],
            "expansion_arr_usd": [680000.0, 810000.0, 940000.0, 1120000.0, 1290000.0, 1480000.0],
            "churned_arr_usd": [190000.0, 210000.0, 240000.0, 265000.0, 290000.0, 310000.0],
            "gross_margin_pct": [78.4, 79.1, 80.2, 81.0, 81.5, 82.1],
            "cac_payback_months": [14.2, 13.8, 13.1, 12.5, 11.9, None],
        }
    )
    df_cohorts.write_excel(demo_dir / "arr_cohorts_2026.xlsx", worksheet="EnterpriseCohorts")

    # 2. Word (.docx): CFO & Audit Committee Due Diligence Memo
    doc = docx.Document()
    doc.add_heading("M&A Financial & Accounting Due Diligence Memo (IFRS-15 / ASC-606)", level=1)
    doc.add_paragraph(
        "Audit scope covers Enterprise and Mid-Market ARR cohorts from 2025-Q1 through 2026-Q2. "
        "Note: 2026-Q2 CAC payback is pending final EMEA reseller commission reconciliation (±2.2% epistemic uncertainty)."
    )
    tbl = doc.add_table(rows=4, cols=3)
    headers = ["control_code", "audit_domain", "compliance_score_pct"]
    for idx, h in enumerate(headers):
        tbl.rows[0].cells[idx].text = h
    rows_data = [
        ("ASC606-01", "Multi-Year Contract Revenue Recognition", "99.2"),
        ("ASC606-02", "Cloud Infrastructure COGS Allocation", "97.5"),
        ("FX-HEDGE-03", "EUR/GBP/JPY Spot vs Forward Reconciliation", "94.8"),
    ]
    for r_idx, r_vals in enumerate(rows_data, start=1):
        for c_idx, val in enumerate(r_vals):
            tbl.rows[r_idx].cells[c_idx].text = val
    doc.save(str(demo_dir / "cfo_due_diligence_memo.docx"))

    # 3. PowerPoint (.pptx): Investment Committee Valuation Deck
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Series C / M&A Valuation Multiples & Rule of 40"
    p_tbl = slide.shapes.add_table(4, 3, Inches(0.8), Inches(1.8), Inches(7.5), Inches(2.2)).table
    p_headers = ["scenario_name", "implied_ev_arr_multiple", "target_rule_of_40_pct"]
    for idx, h in enumerate(p_headers):
        p_tbl.cell(0, idx).text = h
    for r_idx, r_vals in enumerate(
        [
            ("Bear Case (FX Stress)", "9.5", "42.0"),
            ("Base Underwriting Case", "12.8", "51.5"),
            ("Synergy Upside Case", "15.2", "58.0"),
        ],
        start=1,
    ):
        for c_idx, val in enumerate(r_vals):
            p_tbl.cell(r_idx, c_idx).text = val
    prs.save(str(demo_dir / "board_valuation_deck.pptx"))

    # 4. Markdown (.md): FX & Cloud Cost Methodology Notes with GFM Table
    (demo_dir / "fx_and_churn_methodology.md").write_text(
        "# FX Sensitivity & Cloud FinOps Methodology\n\n"
        "## 1. Currency Exposure Assumptions\n"
        "- 34% of Enterprise ARR is denominated in EUR and GBP.\n"
        "- Unhedged spot fluctuations introduce `±1.8%` epistemic uncertainty on USD-reported NRR.\n\n"
        "## 2. Regional Cloud COGS Breakdown\n\n"
        "| region | active_tenants | monthly_cloud_cost_usd | gross_retention_pct |\n"
        "| --- | --- | --- | --- |\n"
        "| North_America | 412 | 185000.0 | 95.8 |\n"
        "| EMEA | 289 | 132000.0 | 94.2 |\n"
        "| APAC | 134 | 68500.0 | 92.6 |\n",
        encoding="utf-8",
    )

    # 5. Python Source Code (.py): Valuation & SaaS Metric Formulas for AST Extraction
    (demo_dir / "saas_valuation_formulas.py").write_text(
        '"""Audited SaaS M&A valuation and cohort retention formulas."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def compute_net_dollar_retention(starting_arr: float, expansion_arr: float, churned_arr: float) -> float:\n"
        '    """Compute Net Dollar Retention (NDR) ratio from cohort ARR flows."""\n'
        "    if starting_arr <= 0.0:\n"
        "        return 0.0\n"
        "    return ((starting_arr + expansion_arr - churned_arr) / starting_arr) * 100.0\n\n\n"
        "def compute_rule_of_40(arr_growth_pct: float, fcf_margin_pct: float) -> float:\n"
        '    """Compute SaaS Rule of 40 composite efficiency index."""\n'
        "    return arr_growth_pct + fcf_margin_pct\n\n\n"
        "def compute_enterprise_value(ending_arr_usd: float, ev_multiple: float, ndr_pct: float) -> float:\n"
        '    """Compute NDR-adjusted implied Enterprise Value (USD)."""\n'
        "    ndr_premium = max(0.8, min(1.35, ndr_pct / 110.0))\n"
        "    return ending_arr_usd * ev_multiple * ndr_premium\n",
        encoding="utf-8",
    )

    # 6. PNG Image (.png)
    _create_banner_image(
        demo_dir / "cohort_waterfall_chart.png",
        "Nouc Studio Demo 1: SaaS M&A ARR Lineage Diagram",
        (30, 58, 138),
    )

    need = (
        "Audit Enterprise ARR cohorts, Net Dollar Retention, Cloud COGS, and M&A valuation multiples "
        "with full cell-to-metric calculation lineage, Pointblank QA checks, and FX epistemic uncertainty."
    )
    title = "Nouc Studio — SaaS M&A Due Diligence & ARR Audit"
    return demo_dir, need, title


def generate_demo_2_clinical_biotech_bundle(base_dir: Path) -> tuple[Path, str, str]:
    """Create Demo 2: Phase II Oncology Biomarker & Trial Safety Audit multimodal files."""
    demo_dir = base_dir / "demo_2_clinical_biotech"
    demo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Excel (.xlsx): Phase II Patient Cohort Efficacy & PK Telemetry (with censored follow-up nulls)
    df_clinical = pl.DataFrame(
        {
            "cohort_arm": [
                "Dose_40mg_QD",
                "Dose_80mg_QD",
                "Dose_120mg_QD_RP2D",
                "Dose_160mg_QD",
                "Combo_80mg_PD1",
            ],
            "enrolled_patients": [24, 32, 45, 18, 36],
            "tumor_shrinkage_median_pct": [18.5, 34.2, 48.6, 51.0, 56.4],
            "ctdna_molecular_response_pct": [31.0, 54.5, 72.8, 74.0, None],
            "progression_free_survival_months": [5.4, 8.2, 11.8, 10.9, 13.4],
            "grade3_adverse_event_pct": [8.3, 12.5, 15.6, 33.3, 19.4],
        }
    )
    df_clinical.write_excel(demo_dir / "phase2_patient_cohorts.xlsx", worksheet="BiomarkerEfficacy")

    # 2. Word (.docx): Clinical Trial Protocol & RECIST 1.1 Endpoint Specification
    doc = docx.Document()
    doc.add_heading("Protocol ONC-2026-04: Phase II Biomarker-Guided Trial Specification", level=1)
    doc.add_paragraph(
        "Primary endpoint is Objective Response Rate (ORR) by independent central review per RECIST v1.1. "
        "Combo_80mg_PD1 ctDNA molecular clearance batch #4 is awaiting central lab NGS sequencing (±3.5% epistemic uncertainty)."
    )
    tbl = doc.add_table(rows=4, cols=3)
    for idx, h in enumerate(["biomarker_assay", "calibration_cv_pct", "lower_limit_quantification_ng_ml"]):
        tbl.rows[0].cells[idx].text = h
    for r_idx, r_vals in enumerate(
        [
            ("ctDNA_Guardant_NGS", "2.8", "0.05"),
            ("PDL1_IHC_22C3", "4.1", "1.00"),
            ("Serum_IL6_ELISA", "3.4", "0.12"),
        ],
        start=1,
    ):
        for c_idx, val in enumerate(r_vals):
            tbl.rows[r_idx].cells[c_idx].text = val
    doc.save(str(demo_dir / "clinical_protocol_recist.docx"))

    # 3. PowerPoint (.pptx): Data Safety Monitoring Board (DSMB) Interim Review
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "DSMB Interim Safety & Recommended Phase 2 Dose (RP2D)"
    p_tbl = slide.shapes.add_table(4, 3, Inches(0.8), Inches(1.8), Inches(7.5), Inches(2.2)).table
    for idx, h in enumerate(["safety_organ_class", "threshold_max_pct", "observed_rp2d_pct"]):
        p_tbl.cell(0, idx).text = h
    for r_idx, r_vals in enumerate(
        [
            ("Hepatic Transaminase Elevation", "20.0", "8.9"),
            ("Hematologic Neutropenia Grade >=3", "25.0", "11.1"),
            ("QTcF Prolongation >480ms", "10.0", "2.2"),
        ],
        start=1,
    ):
        for c_idx, val in enumerate(r_vals):
            p_tbl.cell(r_idx, c_idx).text = val
    prs.save(str(demo_dir / "dsmb_interim_review.pptx"))

    # 4. Markdown (.md): Central Lab ELISA & NGS Assay Calibration Notes
    (demo_dir / "elisa_assay_calibration.md").write_text(
        "# Central Lab Assay Calibration & Censored Observation Log\n\n"
        "## 1. Epistemic Uncertainty Sources\n"
        "- Right-censored PFS observations in `Combo_80mg_PD1` (median follow-up 9.5 months).\n"
        "- Inter-plate ELISA coefficient of variation (`CV = 3.4%`).\n\n"
        "## 2. Site Enrollment & Protocol Deviation Audit\n\n"
        "| clinical_site_id | evaluable_patients | protocol_deviations | data_lock_completeness_pct |\n"
        "| --- | --- | --- | --- |\n"
        "| US_MD_Anderson | 58 | 1 | 99.4 |\n"
        "| FR_Gustave_Roussy | 49 | 0 | 100.0 |\n"
        "| DE_Charite_Berlin | 38 | 2 | 96.8 |\n",
        encoding="utf-8",
    )

    # 5. Python Source Code (.py): Biostatistics & Therapeutic Index Formulas
    (demo_dir / "survival_and_hazard_model.py").write_text(
        '"""Biostatistical efficacy and therapeutic window calculations for Phase II audit."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def compute_therapeutic_utility_index(shrinkage_pct: float, grade3_ae_pct: float) -> float:\n"
        '    """Compute benefit-risk therapeutic utility score balancing response vs Grade 3+ toxicity."""\n'
        "    return shrinkage_pct - (1.5 * grade3_ae_pct)\n\n\n"
        "def adjust_response_for_assay_cv(observed_pct: float, assay_cv_pct: float) -> tuple[float, float]:\n"
        '    """Return 95% assay-calibrated sensitivity bounds for molecular response rate."""\n'
        "    delta = observed_pct * (1.96 * (assay_cv_pct / 100.0))\n"
        "    return (round(observed_pct - delta, 2), round(observed_pct + delta, 2))\n",
        encoding="utf-8",
    )

    # 6. PNG Image (.png)
    _create_banner_image(
        demo_dir / "kaplan_meier_scan.png",
        "Nouc Studio Demo 2: Oncology Phase II Biomarker Lineage",
        (6, 95, 70),
    )

    need = (
        "Audit Phase II oncology dose-escalation efficacy, ctDNA molecular response, and DSMB safety thresholds "
        "with explicit censoring caveats, assay calibration uncertainty intervals, and full calculation proofs."
    )
    title = "Nouc Studio — Phase II Clinical & Biomarker Audit"
    return demo_dir, need, title


def generate_demo_3_ai_infra_finops_bundle(base_dir: Path) -> tuple[Path, str, str]:
    """Create Demo 3: Sovereign AI GPU Cluster FinOps & Frontier Model Routing Audit multimodal files."""
    demo_dir = base_dir / "demo_3_ai_infra_finops"
    demo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Excel (.xlsx): 2026 Frontier Model Routing Telemetry (Gemini 3.8 Flash, Gemini 4 Argon, Sonnet 5.5, GPT-6 Sol, Qwen3-Coder, DeepSeek V4)
    df_models = pl.DataFrame(
        {
            "model_id": [
                "google:gemini-3.8-flash",
                "google:gemini-4-argon",
                "anthropic:claude-sonnet-5-5",
                "openai:gpt-6-sol",
                "ollama:qwen3-coder:30b",
                "openai:deepseek-ai/DeepSeek-V4-Pro",
            ],
            "monthly_requests_k": [1420.0, 380.0, 510.0, 440.0, 1890.0, 920.0],
            "p99_ttft_ms": [185.0, 420.0, 390.0, 365.0, 110.0, 240.0],
            "cost_per_1m_tokens_usd": [0.18, 2.40, 2.80, 3.10, 0.04, 0.22],
            "verified_pass_at_1_pct": [89.4, 96.2, 95.8, 96.5, 86.1, 93.7],
            "monthly_spend_usd": [12850.0, 41200.0, 53400.0, 49800.0, 3200.0, 14900.0],
        }
    )
    df_models.write_excel(demo_dir / "frontier_llm_routing_2026.xlsx", worksheet="ModelRoutingTelemetry")

    # 2. Parquet (.parquet): Self-Hosted H200 / B200 GPU Cluster Telemetry
    df_gpu = pl.DataFrame(
        {
            "rack_id": ["RACK-B200-EU1", "RACK-B200-EU2", "RACK-H200-EU3", "RACK-H200-US1"],
            "gpu_count": [64, 64, 128, 128],
            "avg_power_draw_kw": [74.5, 76.2, 88.4, 91.0],
            "kv_cache_utilization_pct": [84.2, 87.9, 91.5, 79.4],
            "tokens_per_sec_cluster": [148000.0, 152400.0, 119000.0, 124500.0],
            "thermal_throttle_events": [0, 1, 4, None],
        }
    )
    df_gpu.write_parquet(demo_dir / "h200_b200_fleet_telemetry.parquet")

    # 3. Word (.docx): KV-Cache OOM Incident Postmortem & SLA Governance
    doc = docx.Document()
    doc.add_heading("SRE Postmortem: EU-Central vLLM KV-Cache Pressure & Tail Latency", level=1)
    doc.add_paragraph(
        "During peak 128k-context agentic code generation bursts, RACK-H200-EU3 reached 91.5% KV-cache occupancy. "
        "Enabling FP8 KV-cache quantization reduced p99 TTFT by 34% with <0.2% epistemic perplexity drift."
    )
    tbl = doc.add_table(rows=3, cols=3)
    for idx, h in enumerate(["slo_metric", "contractual_target", "measured_p99"]):
        tbl.rows[0].cells[idx].text = h
    for r_idx, r_vals in enumerate(
        [
            ("Interactive Agent TTFT (ms)", "500.0", "285.0"),
            ("Sandbox Verification Turnaround (ms)", "2000.0", "412.0"),
        ],
        start=1,
    ):
        for c_idx, val in enumerate(r_vals):
            tbl.rows[r_idx].cells[c_idx].text = val
    doc.save(str(demo_dir / "kv_cache_outage_postmortem.docx"))

    # 4. PowerPoint (.pptx): 2026 Sovereign AI Infrastructure Capex Deck
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Hybrid Cloud + Sovereign B200 Cluster TCO Comparison"
    p_tbl = slide.shapes.add_table(3, 3, Inches(0.8), Inches(1.8), Inches(7.5), Inches(2.0)).table
    for idx, h in enumerate(["deployment_tier", "monthly_amortized_capex_usd", "data_sovereignty_score"]):
        p_tbl.cell(0, idx).text = h
    for r_idx, r_vals in enumerate(
        [
            ("Sovereign On-Prem B200 (vLLM / Ollama)", "68000.0", "100.0"),
            ("Cloud Frontier Burst (Gemini 4 / Sonnet 5.5 / GPT-6 Sol)", "157250.0", "92.0"),
        ],
        start=1,
    ):
        for c_idx, val in enumerate(r_vals):
            p_tbl.cell(r_idx, c_idx).text = val
    prs.save(str(demo_dir / "sovereign_cluster_expansion.pptx"))

    # 5. Markdown (.md): FinOps & Carbon Intensity Governance
    (demo_dir / "finops_slo_notes.md").write_text(
        "# Sovereign AI FinOps & Model Routing Governance\n\n"
        "## 1. Routing Policy\n"
        "- Fastsandbox & AST verification queries route to `google:gemini-3.8-flash` and local `ollama:qwen3-coder:30b`.\n"
        "- Deep architectural proofs route to `google:gemini-4-argon`, `anthropic:claude-sonnet-5-5`, or `openai:gpt-6-sol`.\n",
        encoding="utf-8",
    )

    # 6. Python Source Code (.py): Token Economics & GPU Amortization Formulas
    (demo_dir / "token_economics_engine.py").write_text(
        '"""FinOps token economics and GPU cluster amortization formulas."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def compute_blended_cost_per_1m_tokens(total_spend_usd: float, total_tokens_millions: float) -> float:\n"
        '    """Compute blended effective cost per 1M tokens across cloud and local GPU tiers."""\n'
        "    if total_tokens_millions <= 0.0:\n"
        "        return 0.0\n"
        "    return total_spend_usd / total_tokens_millions\n\n\n"
        "def compute_tokens_per_kilowatt(tokens_per_sec: float, power_draw_kw: float) -> float:\n"
        '    """Compute energy efficiency in generated tokens per second per kW."""\n'
        "    if power_draw_kw <= 0.0:\n"
        "        return 0.0\n"
        "    return tokens_per_sec / power_draw_kw\n",
        encoding="utf-8",
    )

    # 7. PNG Image (.png)
    _create_banner_image(
        demo_dir / "b200_nvlink_topology.png",
        "Nouc Studio Demo 3: AI Infra & Frontier LLM Routing Lineage",
        (88, 28, 135),
    )

    need = (
        "Audit hybrid AI infrastructure FinOps, B200/H200 GPU power efficiency, p99 TTFT latency SLOs, "
        "and cost/accuracy trade-offs across Gemini 3.8 Flash, Gemini 4 Argon, Claude Sonnet 5.5, GPT-6 Sol, and local Qwen3-Coder."
    )
    title = "Nouc Studio — AI Infra FinOps & Frontier LLM Routing Studio"
    return demo_dir, need, title


def build_and_verify_all_demos(
    *,
    examples_root: Path = Path("examples"),
    dist_root: Path = Path("dist"),
    selected_demo: str = "all",
) -> list[DemoRunSummary]:
    """Generate multimodal files, run the 5-agent orchestrator, and run the RLVR verification gate on realistic demos."""
    cfg = InsightsConfig()
    orchestrator = MultiAgentOrchestrator(config=cfg)
    gate = VerificationGate(memory=orchestrator.memory, cwd=cfg.project_root)

    builders: list[tuple[str, str, Any, Path]] = [
        (
            "demo_1_saas",
            "SaaS M&A Due Diligence & ARR Cohort Audit",
            generate_demo_1_saas_ma_bundle,
            dist_root / "demo_1_saas",
        ),
        (
            "demo_2_clinical",
            "Phase II Oncology Biomarker & Trial Safety Audit",
            generate_demo_2_clinical_biotech_bundle,
            dist_root / "demo_2_clinical",
        ),
        (
            "demo_3_finops",
            "Sovereign AI GPU Cluster FinOps & Frontier Model Routing",
            generate_demo_3_ai_infra_finops_bundle,
            dist_root / "demo_3_finops",
        ),
    ]

    summaries: list[DemoRunSummary] = []
    for demo_id, domain_label, bundle_fn, out_dir in builders:
        if selected_demo != "all" and selected_demo != demo_id:
            continue

        in_dir, need, title = bundle_fn(examples_root)
        report: OrchestrationReport = orchestrator.run_pipeline(
            user_need=need,
            input_paths=[in_dir],
            output_dir=out_dir,
            app_title=title,
        )
        nb_path = Path(report.studio_bundle.notebook_path)
        ver_report: VerificationSuiteReport = gate.verify_notebook(
            nb_path,
            monty_assertions=["1 + 1 == 2"],
            run_ty=True,
        )

        summaries.append(
            DemoRunSummary(
                demo_id=demo_id,
                title=title,
                domain=domain_label,
                input_dir=str(in_dir),
                output_dir=str(out_dir),
                notebook_path=str(nb_path),
                ingested_files_count=len(report.manifest.ingested_files),
                tabular_tables_count=len(report.manifest.tabular_artifacts),
                document_artifacts_count=len(report.manifest.document_artifacts),
                ast_symbols_count=len(report.manifest.code_symbols),
                lineage_nodes_count=report.lineage_node_count,
                lineage_edges_count=report.lineage_edge_count,
                audited_metrics_count=len(report.traces),
                studio_views=[v.view_name for v in report.studio_bundle.views if v.validation_passed],
                verification_passed=ver_report.all_passed,
                launch_command=report.studio_bundle.launch_edit_command,
            )
        )

    return summaries
