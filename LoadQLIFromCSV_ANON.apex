// B64 will be injected by the python step
String B64 = null;

String EXT_ID_FIELD = 'Old_SF_Id__c';
String COL_OLD_QUOTE = 'Quote__c(OLD)';
String COL_OLD_PRODUCT = 'Product__c';
String COL_QTY = 'Quantity__c';

List<String> splitCsvLine(String line) {
    List<String> out = new List<String>();
    if (line == null) return out;
    Boolean inQuotes = false;
    String cur = '';
    for (Integer i=0;i<line.length();i++) {
        String ch = line.mid(i,1);
        if (ch == '"') {
            if (inQuotes && i+1 < line.length() && line.mid(i+1,1) == '"') {
                cur += '"'; i++;
            } else {
                inQuotes = !inQuotes;
            }
        } else if (ch == ',' && !inQuotes) {
            out.add(cur); cur='';
        } else {
            cur += ch;
        }
    }
    out.add(cur);
    return out;
}

if (String.isBlank(B64)) {
    System.debug('B64 is blank.');
    return;
}

String csvText = EncodingUtil.base64Decode(B64).toString();
List<String> lines = csvText.split('\n');
if (lines.size() < 2) return;

List<String> header = splitCsvLine(lines[0].trim());
Map<String,Integer> idx = new Map<String,Integer>();
for (Integer i=0;i<header.size();i++) idx.put(header[i], i);

for (String required : new List<String>{EXT_ID_FIELD, COL_OLD_QUOTE, COL_OLD_PRODUCT}) {
    if (!idx.containsKey(required)) {
        throw new AuraHandledException('Missing required column: ' + required);
    }
}

List<Map<String,String>> rows = new List<Map<String,String>>();
Set<String> oldQuoteIds = new Set<String>();
Set<String> oldProdIds  = new Set<String>();

for (Integer li=1; li<lines.size(); li++) {
    String line = lines[li];
    if (String.isBlank(line)) continue;
    List<String> cols = splitCsvLine(line);
    Map<String,String> r = new Map<String,String>();
    for (String colName : idx.keySet()) {
        Integer j = idx.get(colName);
        String val = j < cols.size() ? cols[j] : null;
        if (val != null) val = val.trim();
        if (String.isBlank(val) || val == 'null' || val == 'NULL') continue;
        r.put(colName, val);
    }
    if (r.isEmpty()) continue;
    rows.add(r);
    oldQuoteIds.add(r.get(COL_OLD_QUOTE));
    oldProdIds.add(r.get(COL_OLD_PRODUCT));
}

// Resolve products by Old_SF_Id__c
Map<String, Id> oldProdToNew = new Map<String, Id>();
for (Product2 p : [
    SELECT Id, Old_SF_Id__c
    FROM Product2
    WHERE Old_SF_Id__c IN :oldProdIds
]) {
    oldProdToNew.put(p.Old_SF_Id__c, p.Id);
}

// Resolve quotes by Old_SF_Id__c (CPQ quote if present, else standard Quote)
Map<String, Id> oldQuoteToNew = new Map<String, Id>();
Boolean hasCpqQuote = Schema.getGlobalDescribe().containsKey('SBQQ__Quote__c');

if (hasCpqQuote) {
    for (SObject q : Database.query(
        'SELECT Id, Old_SF_Id__c FROM SBQQ__Quote__c WHERE Old_SF_Id__c IN :oldQuoteIds'
    )) {
        oldQuoteToNew.put((String)q.get('Old_SF_Id__c'), (Id)q.get('Id'));
    }
} else {
    for (Quote q : [
        SELECT Id, Old_SF_Id__c
        FROM Quote
        WHERE Old_SF_Id__c IN :oldQuoteIds
    ]) {
        oldQuoteToNew.put(q.Old_SF_Id__c, q.Id);
    }
}

// PricebookEntry resolution: Standard Pricebook + Active entries
Id stdPbId = [SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1].Id;
Map<Id, Id> prodToPbe = new Map<Id, Id>();
if (!oldProdToNew.isEmpty()) {
    for (PricebookEntry pbe : [
        SELECT Id, Product2Id
        FROM PricebookEntry
        WHERE Pricebook2Id = :stdPbId
          AND Product2Id IN :oldProdToNew.values()
          AND IsActive = true
    ]) {
        prodToPbe.put(pbe.Product2Id, pbe.Id);
    }
}

List<QuoteLineItem> upserts = new List<QuoteLineItem>();
List<String> errors = new List<String>();

Integer rowNum = 1;
for (Map<String,String> r : rows) {
    rowNum++;

    String ext = r.get(EXT_ID_FIELD);
    String oldQ = r.get(COL_OLD_QUOTE);
    String oldP = r.get(COL_OLD_PRODUCT);

    Id quoteId = oldQuoteToNew.get(oldQ);
    Id prodId  = oldProdToNew.get(oldP);
    Id pbeId   = (prodId != null) ? prodToPbe.get(prodId) : null;

    if (String.isBlank(ext)) { errors.add('row '+rowNum+' missing ext id'); continue; }
    if (quoteId == null) { errors.add('row '+rowNum+' no quote match old='+oldQ); continue; }
    if (pbeId == null)   { errors.add('row '+rowNum+' no PBE match oldProduct='+oldP); continue; }

    Decimal qty = 1;
    if (r.containsKey(COL_QTY)) {
        try { qty = Decimal.valueOf(r.get(COL_QTY)); } catch (Exception e) {}
    }

    QuoteLineItem qli = new QuoteLineItem();
    qli.put(EXT_ID_FIELD, ext);
    qli.QuoteId = quoteId;
    qli.PricebookEntryId = pbeId;
    qli.Quantity = qty;

    upserts.add(qli);
}

System.debug('INPUT_ROWS=' + rows.size() + ' UPSERTING=' + upserts.size() + ' SKIPPED=' + errors.size());
if (!errors.isEmpty()) {
    System.debug('FIRST_ERRORS=' + String.join(errors.subList(0, Math.min(50, errors.size())), ' | '));
}

if (!upserts.isEmpty()) {
    Database.UpsertResult[] res = Database.upsert(upserts, EXT_ID_FIELD, false);
    Integer ok=0, bad=0;
    for (Integer i=0;i<res.size();i++) {
        if (res[i].isSuccess()) ok++;
        else {
            bad++;
            for (Database.Error e : res[i].getErrors()) {
                System.debug('UPSERT_ERROR idx='+i+' msg='+e.getMessage());
            }
        }
    }
    System.debug('UPSERT_OK=' + ok + ' UPSERT_BAD=' + bad);
}
