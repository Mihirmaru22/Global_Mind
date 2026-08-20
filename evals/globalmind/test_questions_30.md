# 📊 30 Benchmark & Test Questions for GlobleMind / LocalMind

A curated dataset of 30 questions designed to test the RAG and Text-to-SQL pipeline across three distinct difficulty and phrasing tiers:

---

## 🧑‍💼 Category 1: 10 Layman / Casual Business Questions
*(Informal language, zero database jargon, everyday business phrasing)*

1. **"How many active customers do we currently have?"**
   * *Intent:* Count active parties (`party.status = 'Y' AND party.deleted_at IS NULL`).
   * *Target Tables:* `party`

2. **"Who are our top 5 clients by total spending this year?"**
   * *Intent:* Sum product revenue grouped by party for the current fiscal year (`LIMIT 5`).
   * *Target Tables:* `party`, `sales_order`, `sales_order_products`, `product`, `financial_year`

3. **"Which sales inquiries/leads are still open and waiting for follow-up?"**
   * *Intent:* Filter leads with active pipeline statuses (`lead.status IN ('Pending', 'In-Progress')`).
   * *Target Tables:* `lead`

4. **"What is our single best-selling product by quantity sold?"**
   * *Intent:* Sum ordered quantity per product, rank descending, pick the top 1 (`LIMIT 1`).
   * *Target Tables:* `sales_order_products`, `product`

5. **"Which customers haven't bought anything from us in the last 6 months?"**
   * *Intent:* Anti-join active parties against sales orders placed within the last 180 days.
   * *Target Tables:* `party`, `sales_order`

6. **"Do we have any inventory cartons in the warehouse that haven't been verified yet?"**
   * *Intent:* Filter stock records where verification status is pending (`carton_verify_status = 'P'`).
   * *Target Tables:* `stock`, `product`

7. **"Which manufacturing batches produced less output than what was originally planned?"**
   * *Intent:* Compare target quantity (`production.qty`) with actual completed output (`actual_production.apq`).
   * *Target Tables:* `production`, `actual_production`, `product`

8. **"How much money have we spent on raw materials from each supplier?"**
   * *Intent:* Calculate purchase expenditure per supplier party (`SUM(pp.qty * pr.rate)`).
   * *Target Tables:* `party`, `purchase`, `purchase_products`, `product`

9. **"How many new leads came in through our website versus sales reps?"**
   * *Intent:* Group leads by lead generation source (`lead.lead_generate_from`).
   * *Target Tables:* `lead`

10. **"How much total available stock do we have on hand across all categories?"**
    * *Intent:* Sum in-stock warehouse inventory (`stock.status = 'B'` with `CAST(stock.qty AS DECIMAL)`).
    * *Target Tables:* `stock`, `product`, `category`

---

## 🎯 Category 2: 10 Schema-Aligned Business Questions
*(Closer to database entity concepts like orders, proformas, dispatch challans, and product types)*

11. **"List all sales orders with customer name, order number, and due date for the current financial year."**
    * *Intent:* Join sales orders with party and financial year table (`financial_year.current_year = 'Y'`).
    * *Target Tables:* `sales_order`, `party`, `financial_year`

12. **"Show all proforma invoices with customer name, grand total, and GST tax amount."**
    * *Intent:* Retrieve billed proforma invoice totals and tax amounts with customer names.
    * *Target Tables:* `proforma`, `party`

13. **"List recent delivery challans with party name, sales order number, transporter name, and vehicle number."**
    * *Intent:* Join delivery challan to party and sales order to trace dispatch and shipping details.
    * *Target Tables:* `delivery_challan`, `party`, `sales_order`

14. **"Show total stock quantity grouped by category for finished goods products (product type 2)."**
    * *Intent:* Aggregate stock on hand filtered by `product_type_id = 2` grouped by category name.
    * *Target Tables:* `stock`, `product`, `category`

15. **"Show the breakdown of sales leads by status (Pending, Success, In-Progress, Reject)."**
    * *Intent:* Count total leads grouped by `lead.status`.
    * *Target Tables:* `lead`

16. **"List active products with category name, unit of measurement, GST percentage, and rate."**
    * *Intent:* Master data catalog lookup with category and unit table joins (`product.status = 'Y'`).
    * *Target Tables:* `product`, `category`, `unit`

17. **"Show total purchase order quantity and value grouped by vendor party name."**
    * *Intent:* Aggregate purchase products joined to purchase and party headers.
    * *Target Tables:* `purchase`, `purchase_products`, `party`, `product`

18. **"List quotations sent to clients with quotation number, party name, and payment mode terms."**
    * *Intent:* Retrieve quotation records with linked party names and terms.
    * *Target Tables:* `quotation`, `party`

19. **"Show actual production entries with production number, machine name, product name, and completed quantity."**
    * *Intent:* Join actual production log with production order, machine, and product catalogs.
    * *Target Tables:* `actual_production`, `production`, `product`, `machine`

20. **"Show monthly sales order counts and revenue for the active financial year."**
    * *Intent:* Group sales orders by month format (`DATE_FORMAT(sales_order_date, '%Y-%m')`) with rate calculation.
    * *Target Tables:* `sales_order`, `sales_order_products`, `product`, `financial_year`

---

## 🎲 Category 3: 10 Random, Comparative & Multi-Filter Edge Cases
*(Cross-table analytics, historical comparisons, geographical filters, and boundary conditions)*

21. **"Compare our total sales revenue between this year and last year."**
    * *Intent:* Partition sales calculations across distinct financial year IDs (`financial_id`).
    * *Target Tables:* `sales_order`, `sales_order_products`, `product`, `financial_year`

22. **"Which sales executive or agent generated the highest number of converted (Success) leads?"**
    * *Intent:* Join leads with users table, filter by `status = 'Success'`, and group by user name.
    * *Target Tables:* `lead`, `users`

23. **"List all customers located in Maharashtra or Gujarat with their city and contact mobile."**
    * *Intent:* Join party table with states table (`states.name IN ('Maharashtra', 'Gujarat')`).
    * *Target Tables:* `party`, `states`

24. **"Which top 3 manufacturing machines produced the highest total volume of goods?"**
    * *Intent:* Group actual production by `machine_id`, sum `apq`, order descending (`LIMIT 3`).
    * *Target Tables:* `actual_production`, `production`, `machine`

25. **"Show all stock adjustment entries where materials were marked as StockOut."**
    * *Intent:* Filter stock adjustment records with `transaction_type = 'StockOut'`.
    * *Target Tables:* `stock_adjustment`, `product`

26. **"Which products have a minimum order quantity (MOQ) greater than 500 units?"**
    * *Intent:* Filter product catalog with `product.moq > 500`.
    * *Target Tables:* `product`, `category`

27. **"Show the latest 10 dispatched delivery challans with driver name and transport details."**
    * *Intent:* Order delivery challan records by `dc_date DESC` (`LIMIT 10`).
    * *Target Tables:* `delivery_challan`, `party`

28. **"How many leads were rejected, and what were the main initial contact sources for them?"**
    * *Intent:* Filter `lead.status = 'Reject'` and count grouped by `lead_generate_from`.
    * *Target Tables:* `lead`

29. **"What is the total GST collected from all billed proforma invoices to date?"**
    * *Intent:* Sum `proforma.gst_amount` across all non-deleted proforma records.
    * *Target Tables:* `proforma`

30. **"Show customers who have an opening balance greater than zero along with their balance type."**
    * *Intent:* Join party with party opening balance table (`party_opening_balance.opening_balance > 0`).
    * *Target Tables:* `party`, `party_opening_balance`
