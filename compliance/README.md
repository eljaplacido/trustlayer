# TrustLayer Compliance Framework

EU AI Act and internal governance compliance layer for TrustLayer.

## Overview

This module provides tools for:

1. **Control Framework Definition** - Machine-readable control catalogs (EU AI Act, Aitomation template)
2. **System Registry** - Register AI systems with risk classification, ownership, and integration details
3. **Evidence Linking** - Link TrustLayer trace events to compliance controls
4. **Readiness Scanning** - Check if AI systems meet production readiness requirements

## Directory Structure

```
compliance/
├── controls/
│   ├── aitomation-template.yaml    # Aitomation governance template
│   └── eu-ai-act-v1.yaml           # EU AI Act control catalog
├── schemas/
│   ├── control.schema.json         # JSON Schema for control frameworks
│   └── system.schema.json          # JSON Schema for system registry
├── src/
│   ├── evidence_linker.py          # Links trace events to controls
│   ├── readiness_scanner.py        # CLI for readiness checks
│   ├── report_generator.py         # Dashboard report generator
│   └── audit_generator.py          # Markdown and JSON audit package generator
└── README.md                       # This file
```

## Quick Start

### 1. Register Your AI System

Create a `system.yaml` file in your project:

```yaml
system:
  id: my-ai-system
  name: "My AI Assistant"
  provider_role: deployer
  risk_class: high-risk
  domain: finance
  owner:
    business: "Jane Doe"
    technical: "John Smith"
    security: "CIO Office"
  data_classes: [personal_data, financial_data]
  approved_use_cases:
    - "Process customer inquiries"
  restricted_use_cases:
    - "Must not make autonomous decisions"
  human_oversight:
    type: human-in-the-loop
    approval_points:
      - "Transactions > 1000 EUR"
      - "New customer onboarding"
  integration:
    agent_id: "my-agent"
    session_id_pattern: "session-*"
    guardian_policy: "finance-high-risk"
    trace_store_url: "http://127.0.0.1:8089"
  controls:
    frameworks:
      - eu-ai-act
      - aitomation-template
  article_50:
    enabled: true
    disclosure_config:
      disclose_ai_interaction: true
    marking_config:
      mark_generated_content: true
```

Article 50 fields are nested under `disclosure_config` and `marking_config`
(see `schemas/system.schema.json` and ADR-016). Runtime evidence uses the
wire events `DISCLOSURE_SHOWN` and `CONTENT_MARKED` across all SDKs.

### 2. Run Readiness Scanner

Check if your system meets basic readiness requirements:

```bash
python -m compliance.src.readiness_scanner --project-dir /path/to/your/project
```

Output:

```
======================================================================
Readiness Report: My AI Assistant (my-ai-system)
======================================================================

✓ PASS !!! system-registry
  System Registry
  System registry found: My AI Assistant

✓ PASS !!! risk-classification
  Risk Classification
  Risk class: high-risk

...

======================================================================
Summary:
  Total checks: 10
  Passed: 7
  Failed: 0
  Gaps: 3
  Skipped: 0
  Readiness score: 70.0%
======================================================================
```

### 3. Generate Compliance Report

Link trace events to controls and generate a compliance report:

```bash
python -m compliance.src.evidence_linker \
  --system /path/to/system.yaml \
  --framework compliance/controls/eu-ai-act-v1.yaml \
  --trace-store-url http://127.0.0.1:8089 \
  --output compliance-report.json
```

## Control Frameworks

### EU AI Act (eu-ai-act-v1.yaml)

Covers key articles for high-risk AI systems:

- **Art. 6** - Risk classification
- **Art. 9** - Risk management system
- **Art. 10** - Data and data governance
- **Art. 11** - Technical documentation
- **Art. 12** - Record-keeping (logging)
- **Art. 13** - Transparency
- **Art. 14** - Human oversight
- **Art. 15** - Accuracy, robustness, cybersecurity

### Aitomation Template (aitomation-template.yaml)

Internal governance framework covering:

- **Section 3.1** - Project governance model
- **Section 3.2** - Architecture and security principles
- **Section 3.3** - Data governance and privacy
- **Section 3.4** - Human oversight and restrictions
- **Section 3.5** - Testing model
- **Section 3.6** - Documentation, logging, monitoring
- **Section 3.7** - Incidents and continuous development
- **Section 4** - AI Risk & Control Register
- **Section 5** - AI Release Readiness Checklist

## Evidence Linking

The evidence linker queries the TrustLayer trace store and matches events to controls based on `evidence_query` definitions in the control framework.

Example control with evidence query:

```yaml
- id: art-12.1
  title: "Automatic recording of events (logs)"
  evidence_types: [logging_configuration, trace_event]
  evidence_query:
    event_types: [AGENT_START, TOOL_CALL, TOOL_RESULT, LLM_CALL, POLICY_CHECK, HUMAN_ESCALATION, AGENT_END]
    min_count: 1
  mandatory: true
  priority: critical
```

This control is satisfied if at least 1 trace event of any type is found in the trace store.

## Integration with TrustLayer

The compliance framework integrates with TrustLayer's existing components:

- **Trace Store** - Evidence linker queries `/v1/events` for trace events
- **Guardian** - System registry references Guardian policies
- **Dashboard** - `CompliancePane` reads a generated readiness report. Generate
  it with `python -m compliance.src.report_generator --project-dirs /path/to/project --output dashboard/public/compliance-readiness.json`.
- **Hermes** - `skills/hermes/compliance_graph.py` generates linked compliance
  notes under `obsidian_vault/07_Compliance/`.

Do not commit a dashboard report generated from real systems. It can contain
system names, owners, classifications, and operational details. The committed
dashboard report is intentionally empty.

## Audit Packages

Generate a reviewable Markdown and JSON package for one or more registered
systems:

```bash
python -m compliance.src.audit_generator \
  --project-dirs /path/to/project-a /path/to/project-b \
  --output-dir ./audit-package
```

The package is an evidence summary, not a legal certification. Treat missing
runtime evidence as a gap and have qualified legal and compliance reviewers
assess applicability of regulatory controls.

## CI/CD Integration

Add readiness checks to your CI pipeline:

```yaml
# .github/workflows/compliance-check.yml
name: Compliance Check
on: [push, pull_request]
jobs:
  readiness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run readiness scanner
        run: |
          python -m compliance.src.readiness_scanner \
            --project-dir . \
            --quiet
        continue-on-error: false
```

Exit codes:
- `0` - All checks passed
- `1` - Critical failures detected
- `2` - Gaps identified (warnings)

## Installation

The tools require Python 3.11+ and can be installed from a repository checkout:

```bash
pip install -e 'compliance[dev]'
```

The CI job runs schema validation and unit tests for the readiness scanner,
evidence linker, dashboard report generator, and audit package generator.

## License

Apache-2.0 (same as TrustLayer core)
