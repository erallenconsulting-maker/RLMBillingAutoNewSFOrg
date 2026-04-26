# Testing Checklist

Run scenarios in order. Each builds on the last.

## Setup
1. In sandbox, create or use a test Account with billing/shipping addresses
2. Create a Contact linked to that Account
3. Create an Opportunity with that Account, set OwnerId
4. Add Contact as Primary Contact Role on Opportunity

## Scenario A — Quote Creation
1. From Opportunity → New Quote
2. Save with empty StartDate
3. Verify in SOQL:
   `SELECT Id, IsPrimary__c, OpportunityId, AccountId, BillToContactId, StartDate, Pricebook2Id FROM Quote WHERE Id = 'NEW_ID'`
4. Expected: IsPrimary=true, parent links populated, StartDate=today, Pricebook2Id=Standard

## Scenario B — Add Recurring QLI
1. On Quote, Lines → Add product
2. Charge Type=Recurring, Billing Frequency=Monthly, Subscription Term=12, Quantity=10
3. Save
4. SOQL:
   `SELECT StartDate, EndDate, MRR__c, ARR__c, Billing_Schedule__c, Billing_Schedule_Status__c, PricingTermCount FROM QuoteLineItem WHERE Id='NEW_ID'`
5. Expected: StartDate=today, EndDate=today+365, MRR/ARR populated, Billing_Schedule="Monthly - 12 months", Status=Derived, PricingTermCount=12

## Scenario C — Add Partner Subscription QLI
1. Add product with Partner_Subscription__c = TRUE
2. Save
3. Note the QLI Id

## Scenario D — Quote → Accepted (auto-Order)
1. Update Quote.Status to "Accepted"
2. Save
3. SOQL: `SELECT Id, Ordered__c, Total_ARR__c FROM Quote WHERE Id='QUOTE_ID'`
4. Expected: Ordered__c=true
5. SOQL: `SELECT Id, Status, QuoteId FROM Order WHERE QuoteId='QUOTE_ID'`
6. Expected: Order created in Draft status
7. SOQL: `SELECT Id FROM OrderItem WHERE OrderId='ORDER_ID'`
8. Expected: One OrderItem per non-Partner-Sub QLI
9. SOQL: `SELECT Id, Quote_Line_Item__c FROM Partner_Subscription__c WHERE Quote__c='QUOTE_ID'`
10. Expected: One Partner_Subscription record per Partner-Sub QLI

## Scenario E — Opportunity Rollup
1. SOQL: `SELECT ARR__c, Renewal_Amount_ARR__c FROM Opportunity WHERE Id='OPP_ID'`
2. Expected: ARR matches Quote.Total_ARR__c

## Scenario F — Order Activation + Contract
1. Verify all OrderItems present
2. Order auto-activates → Contract gets created and activated
3. SOQL: `SELECT Id, Status, ContractId, Contracted__c FROM Order WHERE Id='ORDER_ID'`
4. SOQL: `SELECT Id, Status, AccountId, Master_Contract__c FROM Contract WHERE Order__c='ORDER_ID'`
5. SOQL: `SELECT Id, Contract__c, Product2Id FROM Asset WHERE Contract__c='CONTRACT_ID'`
6. Expected: Asset count = non-Partner-Sub OrderItem count

## Scenario G — Account Rollup
1. SOQL: `SELECT Contracted_ARR__c, Total_Account_ARR__c, Renewal_Date__c FROM Account WHERE Id='ACCT_ID'`
2. Expected: Sum of active Contract.ARR__c for this account

## Scenario H — Manual Renewal
1. On the active Contract, click "Create Renewal Quote" button
2. Should land on a new Quote
3. SOQL: `SELECT Id, Master_Contract__c, SalesTransactionTypeId, OpportunityId FROM Quote WHERE Id='NEW_RENEWAL_QUOTE'`
4. Expected: Master_Contract__c=original Contract, SalesTransactionTypeId=Renewal STT, new Opp linked

## Scenario I — Manual Amendment
1. On active Contract, click "Create Amendment Quote"
2. SOQL: same as Scenario H but SalesTransactionTypeId=Amendment STT

## Scenario J — PDF Quote Generation
1. On Quote, click "Generate Quote PDF" button
2. PDF should download
3. Verify: account name, contact, line items, totals all populate

## Diagnostic Queries
```sql
-- Recent QLI flow trace
SELECT Id, CreatedDate, Charge_Type__c, SubscriptionTerm, StartDate, EndDate,
       Billing_Schedule__c, Billing_Schedule_Status__c, MRR__c, ARR__c,
       PricingTermCount, Partner_Subscription__c
FROM QuoteLineItem
WHERE CreatedDate = TODAY
ORDER BY CreatedDate DESC

-- Recent Quote flow trace
SELECT Id, Name, Status, IsPrimary__c, Ordered__c, Total_ARR__c, Total_MRR__c,
       AccountId, OpportunityId, BillToContactId, StartDate, Pricebook2Id
FROM Quote
WHERE LastModifiedDate = TODAY
ORDER BY LastModifiedDate DESC

-- Partner Subscriptions
SELECT Id, Account__c, Order__c, Contract__c, Quote_Line_Item__c, Active__c,
       Source_Transaction_Type__c, Quantity__c, Customer_Price__c
FROM Partner_Subscription__c
WHERE CreatedDate = TODAY
```
