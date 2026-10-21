# Financial & Operational Audit Methodology

## 1. Scope & Assumptions
- Revenue figures are reported in USD net of regional VAT/GST.
- Regional currency conversions use monthly volume-weighted spot rates (`±1.5%` FX epistemic uncertainty).
- Operational latency measurements (`latency_ms`) represent p95 gateway telemetry over a 30-day window.

## 2. Verification Requirements
- All tabular columns must pass Posit `pointblank` non-null and schema checks prior to KPI aggregation.
- Every executive figure must expose its complete topological calculation trace in the `audit` Studio view.
