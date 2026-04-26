@isTest
private class QuotePDFControllerTest {
    @isTest
    static void testControllerLoadsQuote() {
        Account a = new Account(Name = 'Test PDF Account', BillingStreet = '123 Main', 
                                 BillingCity = 'Austin', BillingState = 'TX', 
                                 BillingPostalCode = '78701', BillingCountry = 'USA');
        insert a;
        
        Contact c = new Contact(LastName = 'Test', AccountId = a.Id, 
                                 Email = 'test@test.com', Phone = '555-1212');
        insert c;
        
        Opportunity opp = new Opportunity(Name = 'Test Opp', AccountId = a.Id, 
                                           StageName = 'Qualification', CloseDate = Date.today().addDays(30));
        insert opp;
        
        Pricebook2 pb = [SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1];
        
        Quote q = new Quote(Name = 'Test Quote', OpportunityId = opp.Id, 
                             Pricebook2Id = pb.Id, BillToContactId = c.Id);
        insert q;
        
        Test.setCurrentPageReference(new PageReference('Page.QuotePDF'));
        ApexPages.currentPage().getParameters().put('id', q.Id);
        
        Test.startTest();
        QuotePDFController ctrl = new QuotePDFController();
        Test.stopTest();
        
        System.assertNotEquals(null, ctrl.q, 'Quote should load');
        System.assertNotEquals(null, ctrl.acct, 'Account should load');
        System.assertNotEquals(null, ctrl.billToContact, 'Bill-to Contact should load');
        System.assertEquals(0, ctrl.lineItems.size(), 'No line items expected');
    }
    
    @isTest
    static void testControllerHandlesNullId() {
        Test.setCurrentPageReference(new PageReference('Page.QuotePDF'));
        Test.startTest();
        QuotePDFController ctrl = new QuotePDFController();
        Test.stopTest();
        System.assertEquals(null, ctrl.q, 'No quote should load when no id provided');
    }
}
