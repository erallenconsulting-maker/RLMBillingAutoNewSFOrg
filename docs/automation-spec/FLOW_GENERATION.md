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

- `object_api` — Salesforce object API name
- `csv_spec` — path to the CSV spec for this object
- `object_disable_toggle_field` — toggle field name for the object-level disable
- `hardware_disable_toggle_field` — toggle field name for hardware-only disable
- `hardware_context_field` — field on the triggering record that indicates hardware context
- `main_subflow_api` — API name of the generated main subflow
- `parent_lookups` — comma-separated `Object:LookupField` pairs mapping parent objects to the lookup field on the triggering record (e.g. `Account:AccountId,Opportunity:OpportunityId`). These drive automatic parent lookups in the main subflow.

## Generated main subflow structure

Each main subflow emits real field-update nodes derived from the CSV rows:

```
Start
  → Get_Triggering_Record       (recordLookups by inRecordId)
  → Get_<Parent1>               (recordLookups via parent_lookups config)
  → ...
  → Update_Record_Always        (recordUpdates — "Record Creation or Record Update" fields)
  → Decide_Create_Or_Update     (decisions — gates create-only vs update-only paths)
      → Yes_Create: Update_Record_Create → Log
      → No (Update): Update_Record_Update → Log
  → Log_Main_Subflow_Execution
```

Fields with no resolvable source reference (child rollups, complex lookups, constants) are
listed in the flow description for manual admin review.

## Generate

```bash
scripts/gen_flows.sh
```

Run this whenever CSVs or `config/flow_objects.yml` change. Output shows how many fields
were mapped per object:

```
Generated: RTF_Order_AfterSave_TV.flow-meta.xml + SUB_Order_Main_Automation_TV.flow-meta.xml (20/31 fields mapped)
```

## Validate

```bash
scripts/validate_flows.sh
```

Validation performs:

- XML well-formed checks (Python `ET.parse`; `xmllint` if available)
- Generated file count checks (6 routers + 6 main subflows)
- `<start>` element ordering sanity checks for record-triggered routers
- Guard that routers do not use `actionCalls` with `actionType=flow`
- Presence of `frmIsNewRecord` formula in each RTF
- Presence of `inIsNewRecord` variable in each main subflow

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
- The `frmIsNewRecord` formula in each RTF uses `ISBLANK({!$Record__Prior.Id})` to detect creates. It is passed to the main subflow as `inIsNewRecord`.
- Fields skipped during generation (child rollups, unmapped sources) appear in the flow description and require manual admin review.
- `parent_lookups` in the YAML config must list every parent object whose fields are referenced in the CSV. Update and regenerate whenever new source objects appear.

## Known CSV data quality issues

The following source field references in the CSV specs lack the correct `__c` suffix and will generate element references that may need manual correction after deployment:

| Object | Target Field | Generated source ref | Should be |
|--------|-------------|----------------------|-----------|
| Asset | `DoesAutomaticallyRenew` | `Get_QuoteLineItem.DoesAutomaticallyRenew` | `Get_QuoteLineItem.DoesAutomaticallyRenew__c` |
| Asset | `SubscriptionTerm` | `Get_QuoteLineItem.SubscriptionTerm` | `Get_QuoteLineItem.Subscription_Term__c` |

These entries in the Asset CSV spec have `QuoteLineItem.DoesAutomaticallyRenew` / `QuoteLineItem.SubscriptionTerm` in the source API column but the QuoteLineItem CSV defines them as `DoesAutomaticallyRenew__c` and `Subscription_Term__c`. Update the Asset CSV source column to fix these, then regenerate.
