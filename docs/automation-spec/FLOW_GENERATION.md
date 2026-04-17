# RLM Billing Flow Generation

This repo includes generator-based Salesforce Flow metadata for a clean-slate router architecture across:

- Quote
- QuoteLineItem
- Order
- OrderItem
- Contract
- Asset

## Source of truth

CSV behavior/mapping specs under `docs/automation-spec/` are the source of truth and are read during generation.

## Config

`config/flow_objects.yml` defines each object with:

- object API name
- CSV spec path
- object disable toggle field
- hardware-only disable toggle field
- hardware context field
- main subflow API name

## Generate

```bash
scripts/gen_flows.sh
```

## Validate

```bash
scripts/validate_flows.sh
```

Validation performs:

- XML well-formed checks (`xmllint`)
- generated file presence checks (6 routers + 6 main subflows)
- `<start>` ordering sanity checks for record-triggered routers
- guardrail that routers do not use `actionCalls` with `actionType=flow`

## Deploy (dependency-safe)

```bash
scripts/deploy_sb.sh fullsb
```

Deploy order:

1. Subflows first (`SUB_*_Main_Automation_TV`, `SUB_Evaluate_Automation_Context_TV`, `SUB_Log_Automation_Event_TV`)
2. Record-triggered router flows (`RTF_*_AfterSave_TV`)

## Notes

- Generated flows are `Draft` by default so existing automation is not disrupted.
- Router flows invoke subflows via `<subflows>` (required for autolaunched record-triggered flow metadata).
