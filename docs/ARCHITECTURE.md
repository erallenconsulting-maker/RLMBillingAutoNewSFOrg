# RLM Billing Automation Architecture

## System Overview

Quote → QLI → Order → OrderItem → Contract → Asset chain, with Partner Subscriptions
as a parallel branch off Order/Contract.

## Trigger Cascade

1. Quote saved → RTF_Quote_BeforeSave_StartDate_TV (sets StartDate=today if blank)
2. Quote saved → RTF_Quote_AfterSave_TV_FIX → SUB_Quote_Main_Automation_TV
   - Address copy, IsPrimary, Pricebook default, Bill-to Contact
   - SUB_Quote_Set_Ordered_TV (NEW) — flips Ordered__c when Status=Accepted/Approved
   - SUB_Quote_Rollup_To_Opportunity_TV (NEW) — fires when Quote becomes Primary+Accepted
3. QuoteLineItem saved → RTF_QuoteLineItem_BeforeSave_TV (sets StartDate=today)
4. QuoteLineItem saved → RTF_QuoteLineItem_AfterSave_TV
   - SUB_QuoteLineItem_Main_Automation_TV: descriptions, hardware flags
   - SUB_QuoteLineItem_Calculate_Revenue_TV: MRR/ARR, Billing Schedule MDT, EndDate, PricingTermCount
   - SUB_Quote_Rollup_Revenue_TV: rolls up to parent Quote
5. Quote.Ordered__c flips true → RTF_Quote_Order_Creation_TV (NEW) — auto-creates Order from Quote
6. Order saved → RTF_Order_AfterSave_TV → SUB_Order_Main_Automation_TV
   - Address copy, Currency, custom fields
   - Auto-Contract creation (existing)
7. OrderItem creation gates on QLI.Partner_Subscription__c:
   - If TRUE: SUB_Order_Create_Partner_Subscription_TV (NEW) creates Partner_Subscription__c record
   - If FALSE: standard OrderItem creation
8. All OrderItems present → SUB_Order_Activate_TV (NEW) auto-activates Order
9. Order activated → SUB_Contract_Create_Assets_TV (NEW) creates Assets from non-Partner-Sub OrderItems
10. Contract activates → SUB_Contract_Rollup_To_Account_TV (NEW)

## Renewal Path

- Manual: Quick action button on Contract → SUB_Contract_Create_Renewal_TV
- Creates new Opportunity (Stage=Qualification, Close=+30d, Name pattern)
- Creates new Quote (SalesTransactionTypeId=Renewal STT)
- Copies QLIs from Active Assets + original Quote (dedupe by Product2Id, exclude One-Time)

## Amendment Path

- Manual: Quick action button on Contract → SUB_Contract_Create_Amendment_TV
- Creates new Opportunity (Stage=Qualification, Close=+14d, AmendedContract__c=original)
- Creates new Quote (SalesTransactionTypeId=Amendment STT, Master_Contract__c=original)
- Copies all active QLIs from original Quote

## Partner Subscription Routing

QLI.Partner_Subscription__c = TRUE flows to Partner_Subscription__c records,
not OrderItems. This prevents NetSuite double-billing.

Records created with:
- Account__c, Order__c, Quote__c, Contract__c populated from chain
- Quote_Line_Item__c → original QLI
- Active__c = TRUE on creation
- Source_Transaction_Type__c = SalesTransactionType.Name from Quote

## Rollup Logic

### Quote → Opportunity (Primary Quote, Accepted/Approved):
- Opportunity.ARR__c = Quote.Total_ARR__c
- Opportunity.Renewal_Amount_ARR__c = Quote.Total_Renewal_ARR__c
- Opportunity.Up_for_Renewal_Amount_ARR__c = Quote.Total_Up_For_Renewal_ARR__c
- Opportunity.Renewal_Date__c = Quote.Renewal_Date__c
- Opportunity.Next_Renewal_Date__c = Quote.Next_Renewal_Date__c

### Active Contract → Account:
- Account.Contracted_ARR__c = SUM(active Contract.ARR__c)
- Account.Contracted_MRR__c = Contracted_ARR__c / 12
- Account.Total_Account_ARR__c = Contracted_ARR__c
- Account.Renewal_Date__c = MIN(active Contract.EndDate)
- Account.Next_Renewal_Date_1__c = MIN(active Contract.EndDate)

## PricingTermCount Logic (CPQ MultiplierProrator equivalent)

- For Recurring + StartDate aligned to billing period: PricingTermCount = SubscriptionTerm
- For Recurring + StartDate mid-period: PricingTermCount = SubscriptionTerm + (partial period factor)
- For One-Time: PricingTermCount = 1

Currently implemented as: PricingTermCount = SubscriptionTerm (no partial proration).
TODO: Add proration if reps need partial-period billing.

## Known Limitations

1. EndDate may be overwritten by RLM pricing engine — investigate if values seem wrong
2. Pricing Waterfall errors are RLM org settings, not flow-related
3. Scheduled auto-renewal NOT included in this build — manual renewal button only
4. PDF Quote button is text-based, not pixel-matching the Techera DOCX template
