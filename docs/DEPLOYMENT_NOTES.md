# Deployment Notes

## Sandbox to Prod Migration

When promoting this work from sandbox to prod, watch for these:

1. **SalesTransactionType IDs differ** — search for `1ChaZ` in flow XML files,
   replace with prod IDs from this query:
   `sf data query -o PROD -q "SELECT Id, Name FROM SalesTransactionType"`

2. **Standard Pricebook ID differs** — search for `01sao000003VWRhAAO`,
   replace with prod Standard Pricebook ID:
   `sf data query -o PROD -q "SELECT Id FROM Pricebook2 WHERE IsStandard=true"`

3. **Billing_Schedule_Map MDT records** — must exist in prod with same DeveloperNames

4. **Custom fields verified existing in prod** — but if any deploy fails on
   "field doesn't exist", run this diff:
   `sf project retrieve start -o PROD --metadata "CustomObject:QuoteLineItem"`
   then compare to sandbox.

## Rollback Plan

Each flow we deploy is versioned. To rollback:
1. Setup → Flows → Find the flow
2. Activate the previous version
3. Active version always wins; older versions are still available

For new flows we created (no previous version):
- Deactivate them
- Their effect stops immediately

## Flow Activation Order (Important)

Deploy in this order to avoid dependency errors:
1. All SUB_* (subflows) first — they have no triggers
2. Quick Actions
3. RTF_*_BeforeSave_* second
4. RTF_*_AfterSave_* third
5. Custom buttons last (depend on Quick Actions)

## What's NOT in this build

1. Scheduled auto-renewal — needs separate session with full sandbox testing
2. Cancellation flow — placeholder only
3. Upsell flow — punted entirely
4. Email templates — basic PDF only
5. Approval Process integration

## Things that may break

1. EndDate may be overwritten by RLM pricing engine. If you see weird values,
   check Setup → Pricing → Pricebook Entries for product-level defaults.
2. Pricing Waterfall errors are RLM config, not flow-related
3. Quote.Status picklist values must include "Accepted" and "Approved"
4. RLM "Instant Pricing" toggle on QLE affects when our flows fire
