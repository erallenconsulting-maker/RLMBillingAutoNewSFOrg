public with sharing class QuotePDFController {
    public Quote q { get; private set; }
    public Account acct { get; private set; }
    public Contact billToContact { get; private set; }
    public User owner { get; private set; }
    public List<QuoteLineItem> lineItems { get; private set; }
    public String today { get; private set; }
    public Decimal grandTotal { get; private set; }
    
    public QuotePDFController() {
        Id quoteId = ApexPages.currentPage().getParameters().get('id');
        if (quoteId == null) { return; }
        
        q = [SELECT Id, Name, QuoteNumber, ExpirationDate, Payment_Terms__c, Special_Terms__c,
                    BillingStreet, BillingCity, BillingState, BillingPostalCode, BillingCountry,
                    GrandTotal, Subtotal, Discount, TotalPrice,
                    AccountId, BillToContactId, OwnerId, Account.Name
             FROM Quote WHERE Id = :quoteId LIMIT 1];
        
        if (q.AccountId != null) {
            acct = [SELECT Id, Name, BillingStreet, BillingCity, BillingState, 
                           BillingPostalCode, BillingCountry, Phone
                    FROM Account WHERE Id = :q.AccountId LIMIT 1];
        }
        
        if (q.BillToContactId != null) {
            billToContact = [SELECT Id, Name, Email, Phone, Title
                             FROM Contact WHERE Id = :q.BillToContactId LIMIT 1];
        }
        
        if (q.OwnerId != null) {
            owner = [SELECT Id, Name, Email, Phone FROM User WHERE Id = :q.OwnerId LIMIT 1];
        }
        
        lineItems = [SELECT Id, Product2.Name, Description, Detailed_Line_Description__c,
                            Quantity, ListPrice, UnitPrice, Discount, NetUnitPrice, NetTotalPrice,
                            BillingFrequency__c, SubscriptionTerm, StartDate, Charge_Type__c
                     FROM QuoteLineItem
                     WHERE QuoteId = :quoteId
                     ORDER BY SortOrder ASC NULLS LAST, CreatedDate ASC];
        
        today = Date.today().format();
        
        // Compute grand total ourselves since RLM's NetTotalPrice is wrong
        grandTotal = 0;
        for (QuoteLineItem li : lineItems) {
            Decimal lineTotal = 0;
            if (li.Charge_Type__c == 'One-Time' || li.SubscriptionTerm == null) {
                lineTotal = (li.UnitPrice == null ? 0 : li.UnitPrice) * (li.Quantity == null ? 0 : li.Quantity);
            } else {
                Decimal unit = li.UnitPrice == null ? 0 : li.UnitPrice;
                Decimal term = li.SubscriptionTerm;
                Decimal qty = li.Quantity == null ? 0 : li.Quantity;
                lineTotal = unit * term * qty;
            }
            grandTotal += lineTotal;
        }
    }
    
    public String getFormattedExpirationDate() {
        return q != null && q.ExpirationDate != null ? q.ExpirationDate.format() : '';
    }
    
    public String getQuoteName() {
        return q != null ? (q.QuoteNumber != null ? q.QuoteNumber : q.Name) : '';
    }
}
