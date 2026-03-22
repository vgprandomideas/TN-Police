# Sources and notes

This package keeps a strict boundary between:
1. public-source statewide metrics, and
2. synthetic operational workflow data used only to make the MVP interactive.

## Public-source seeded metrics
The seed file includes:
- 2023 Tamil Nadu statewide baseline metrics
- partial 2024 public-reported statewide figures
- partial 2025 public-reported or policy-note capability figures

These are stored in `data/public_metrics_seed.csv`.

## Synthetic data
The following are synthetic demo records:
- station-level incident flow
- case collaboration objects
- assignments/comments
- ingest queue jobs
- entity graph examples

## Why this boundary exists
Open public websites do not expose privileged law-enforcement APIs for live FIR, full case records, CCTV internals, or unrestricted district-wise crime cubes. The MVP is architected so sanctioned connectors can replace the synthetic adapters later without changing the overall product shape.