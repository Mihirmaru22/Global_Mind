# 📊 Full 50-Question Benchmark Evaluation Report

**Generated on:** 2026-08-19 17:30:01  
**Total Questions Tested:** 50  
**Success Rate:** 33/50 (82.0% valid SQL execution)  
- ✅ **Populated Results:** 33
- ⚠️ **Empty Results (Valid SQL, 0 records in DB):** 8
- ❌ **Failed:** 9

---

## 📋 Detailed Question Execution Matrix

| # | Question | Status | Time | Generated SQL | Result Summary |
|---|---|---|---|---|---|
| 1 | **Who bought the most goods from us this year?** | ❌ `failed` | 8.48s | _None_ | No result |
| 2 | **Which buyers haven't placed an order with us in the last three months?** | ✅ `success` | 22.31s | `SELECT
  p.party_name AS buyer_name,
  p.mobile1 AS contact_mobile,
  p.email AS contact_email
FROM party p
LEFT JOIN sales_order so
  ON p.id = so.party_id
  AND so.deleted_at IS NULL
  AND so.sales_order_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
WHERE p.status = 'Y'
  AND p.deleted_at IS NULL
  AND so.id IS NULL` | SQL Query Executed: `SELECT   p.party_name AS buyer_name,   p.mobile1 AS contact_mobile,   p.email AS contact_email FROM |
| 3 | **What was our single biggest order by total value?** | ✅ `success` | 74.58s | `SELECT
  so.id AS sales_order_id,
  so.sales_order_date AS order_date,
  p.party_name AS customer_name,
  SUM(sop.qty * prod.rate) AS total_order_value
FROM sales_order so
JOIN party p ON so.party_id = p.id
JOIN sales_order_products sop ON so.id = sop.sales_order_id
JOIN product prod ON sop.product_id = prod.id
WHERE so.deleted_at IS NULL
  AND sop.deleted_at IS NULL
  AND prod.deleted_at IS NULL
  AND p.deleted_at IS NULL
GROUP BY so.id, so.sales_order_date, p.party_name
ORDER BY total_order_value DESC
LIMIT 1` | SQL Query Executed: `SELECT   so.id AS sales_order_id,   so.sales_order_date AS order_date,   p.party_name AS customer_n |
| 4 | **How many total orders did we receive this month?** | ❌ `failed` | 38.04s | _None_ | No result |
| 5 | **Which customers usually order in the largest bulk quantities?** | ✅ `success` | 39.06s | `SELECT
  p.party_name AS customer_name,
  SUM(sop.qty) AS total_quantity_ordered,
  COUNT(DISTINCT so.id) AS number_of_orders
FROM party p
JOIN sales_order so ON p.id = so.party_id
JOIN sales_order_products sop ON so.id = sop.sales_order_id
WHERE p.deleted_at IS NULL
  AND so.deleted_at IS NULL
  AND sop.deleted_at IS NULL
  AND p.status = 'Y'
GROUP BY p.id, p.party_name
ORDER BY total_quantity_ordered DESC
LIMIT 20` | SQL Query Executed: `SELECT   p.party_name AS customer_name,   SUM(sop.qty) AS total_quantity_ordered,   COUNT(DISTINCT  |
| 6 | **Can you show a monthly breakdown of our sales revenue for this year?** | ✅ `success` | 99.97s | `SELECT 
  DATE_FORMAT(so.sales_order_date, '%Y-%m') AS sales_month,
  SUM(p.rate * sop.qty) AS sales_revenue
FROM 
  sales_order so
  JOIN sales_order_products sop ON so.id = sop.sales_order_id
  JOIN product p ON sop.product_id = p.id
  JOIN financial_year fy ON so.financial_id = fy.id
WHERE 
  fy.current_year = 'Y' AND so.deleted_at IS NULL AND sop.deleted_at IS NULL
GROUP BY 
  sales_month
ORDER BY 
  sales_month` | SQL Query Executed: `SELECT    DATE_FORMAT(so.sales_order_date, '%Y-%m') AS sales_month,   SUM(p.rate * sop.qty) AS sale |
| 7 | **How many potential clients are currently waiting for our follow-up?** | ✅ `success` | 30.92s | `SELECT COUNT(p.id) AS potential_clients_waiting_for_followup
FROM party p
JOIN lead l ON p.id = l.party_id
WHERE l.status IN ('Pending', 'In-Progress')
AND l.deleted_at IS NULL
AND p.deleted_at IS NULL` | SQL Query Executed: `SELECT COUNT(p.id) AS potential_clients_waiting_for_followup FROM party p JOIN lead l ON p.id = l.p |
| 8 | **Where do most of our successful deals come from?** | ❌ `failed` | 26.34s | _None_ | No result |
| 9 | **Which sales executive converted the most leads into actual customers?** | ✅ `success` | 116.9s | `SELECT u.name AS top_sales_executive, COUNT(DISTINCT l.id) AS total_leads_converted
FROM lead l
JOIN users u ON l.lead_assign_to = u.id
WHERE l.status = 'Success'
GROUP BY u.name
ORDER BY total_leads_converted DESC
LIMIT 1` | SQL Query Executed: `SELECT u.name AS top_sales_executive, COUNT(DISTINCT l.id) AS total_leads_converted FROM lead l JOI |
| 10 | **How many customer inquiries got rejected or lost recently?** | ✅ `success` | 32.88s | `SELECT COUNT(l.id) AS rejected_leads_count
FROM lead l
WHERE l.status IN ('Reject', 'Lost') AND l.deleted_at IS NULL
AND l.lead_date_time >= DATE_FORMAT(CURDATE() - INTERVAL 1 MONTH, '%Y-%m-%d')` | SQL Query Executed: `SELECT COUNT(l.id) AS rejected_leads_count FROM lead l WHERE l.status IN ('Reject', 'Lost') AND l.d |
| 11 | **Are there any open prospects that came in through social media?** | ✅ `success` | 51.86s | `SELECT 
    T1.company_name AS company_name, 
    T1.contact_name AS contact_name, 
    T1.email AS email, 
    T1.mobile AS mobile, 
    T1.lead_generate_from AS lead_source, 
    T1.status AS lead_status
FROM 
    lead AS T1
WHERE 
    T1.deleted_at IS NULL 
    AND T1.status IN ('Pending', 'In-Progress') 
    AND T1.lead_generate_from = 'SocialMedia'` | SQL Query Executed: `SELECT      T1.company_name AS company_name,      T1.contact_name AS contact_name,      T1.email AS |
| 12 | **What percentage of our total inquiries end up closing successfully?** | ✅ `success` | 12.82s | `SELECT 
  SUM(CASE WHEN l.status = 'Success' THEN 1 ELSE 0 END) / COUNT(l.id) * 100 AS success_rate
FROM 
  lead l
WHERE 
  l.deleted_at IS NULL` | SQL Query Executed: `SELECT    SUM(CASE WHEN l.status = 'Success' THEN 1 ELSE 0 END) / COUNT(l.id) * 100 AS success_rate |
| 13 | **What products are currently running dangerously low on stock?** | ✅ `success` | 18.04s | `SELECT 
  p.id AS product_id,
  p.product_name AS product_name,
  pc.color AS product_color,
  COALESCE(SUM(CAST(s.qty AS DECIMAL(10,2))), 0) AS current_stock,
  pc.minimum_stock AS minimum_stock
FROM 
  product p
  JOIN product_color pc ON p.id = pc.product_id
  LEFT JOIN stock s ON s.product_id = p.id AND s.product_color_id = pc.id AND s.status = 'B' AND s.deleted_at IS NULL
WHERE 
  pc.minimum_stock > 0
GROUP BY 
  p.id, p.product_name, pc.color, pc.minimum_stock
HAVING 
  current_stock < pc.minimum_stock
ORDER BY 
  current_stock ASC, pc.minimum_stock DESC
LIMIT 20` | SQL Query Executed: `SELECT    p.id AS product_id,   p.product_name AS product_name,   pc.color AS product_color,   COAL |
| 14 | **How much total inventory is sitting in the warehouse right now?** | ✅ `success` | 27.49s | `SELECT 
  SUM(CAST(s.qty AS DECIMAL(10,2))) AS total_inventory
FROM 
  stock s
WHERE 
  s.status = 'B' AND s.deleted_at IS NULL` | SQL Query Executed: `SELECT    SUM(CAST(s.qty AS DECIMAL(10,2))) AS total_inventory FROM    stock s WHERE    s.status =  |
| 15 | **Are there any packed cartons in the warehouse waiting for manager verification?** | ✅ `success` | 83.19s | `SELECT COUNT(*) AS pending_packed_cartons
FROM packagings
WHERE carton_verify_status = 'P' AND status = 'B' AND deleted_at IS NULL` | SQL Query Executed: `SELECT COUNT(*) AS pending_packed_cartons FROM packagings WHERE carton_verify_status = 'P' AND stat |
| 16 | **Which items have been lying in storage for the longest time without moving?** | ⚠️ `empty_result` | 50.13s | `SELECT 
  p.product_name AS product_name,
  s.batch_no AS batch_number,
  s.invoice_date AS storage_date,
  DATEDIFF(CURDATE(), s.invoice_date) AS days_in_storage
FROM 
  stock s
  JOIN product p ON s.product_id = p.id
WHERE 
  s.deleted_at IS NULL
  AND s.status = 'B'
  AND s.carton_verify_status = 'V'
ORDER BY 
  days_in_storage DESC
LIMIT 1;` | SQL Query Executed: `SELECT    p.product_name AS product_name,   s.batch_no AS batch_number,   s.invoice_date AS storage |
| 17 | **How many cartons were shipped out of the warehouse this week?** | ✅ `success` | 52.44s | `SELECT COUNT(DISTINCT dc.id) AS cartons_shipped
FROM delivery_challan dc
JOIN delivery_challan_products dcp ON dc.id = dcp.dc_id
WHERE dc.dc_date BETWEEN CURDATE() - INTERVAL 7 DAY AND CURDATE()
AND dc.deleted_at IS NULL
AND dcp.deleted_at IS NULL` | SQL Query Executed: `SELECT COUNT(DISTINCT dc.id) AS cartons_shipped FROM delivery_challan dc JOIN delivery_challan_prod |
| 18 | **Do we have any recorded stock adjustment write-offs this month?** | ✅ `success` | 105.01s | `SELECT 
  COUNT(id) AS stock_adjustment_write_offs
FROM 
  stock_adjustment
WHERE 
  transaction_type = 'WriteOff' 
  AND stock_adjustment_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01') 
  AND deleted_at IS NULL` | SQL Query Executed: `SELECT    COUNT(id) AS stock_adjustment_write_offs FROM    stock_adjustment WHERE    transaction_ty |
| 19 | **Which factory machines produced the highest output this month?** | ⚠️ `empty_result` | 186.08s | `SELECT 
  m.machine_name AS top_machine, 
  SUM(p.qty) AS highest_output
FROM 
  production p
  JOIN machine m ON p.machine_id = m.id
WHERE 
  p.deleted_at IS NULL 
  AND m.deleted_at IS NULL 
  AND p.production_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
GROUP BY 
  m.machine_name
ORDER BY 
  highest_output DESC
LIMIT 1` | SQL Query Executed: `SELECT    m.machine_name AS top_machine,    SUM(p.qty) AS highest_output FROM    production p   JOI |
| 20 | **Did any manufacturing batch fail to hit its original planned target?** | ✅ `success` | 40.76s | `SELECT 
  p.id AS production_id,
  p.qty AS planned_quantity,
  COALESCE(ap.apq, 0) AS actual_produced_quantity,
  (p.qty - COALESCE(ap.apq, 0)) AS production_shortfall
FROM 
  production p
  LEFT JOIN actual_production ap ON p.id = ap.production_id
WHERE 
  p.qty > COALESCE(ap.apq, 0)
  AND p.deleted_at IS NULL
  AND ap.deleted_at IS NULL
ORDER BY 
  production_shortfall DESC
LIMIT 1` | SQL Query Executed: `SELECT    p.id AS production_id,   p.qty AS planned_quantity,   COALESCE(ap.apq, 0) AS actual_produ |
| 21 | **How much finished product did the factory complete over the past week?** | ⚠️ `empty_result` | 52.42s | `SELECT 
  SUM(apq) AS total_actual_product_quantity
FROM 
  actual_production
WHERE 
  production_date BETWEEN CURDATE() - INTERVAL 1 WEEK AND CURDATE()
  AND product_type_id = 2
  AND deleted_at IS NULL` | SQL Query Executed: `SELECT    SUM(apq) AS total_actual_product_quantity FROM    actual_production WHERE    production_d |
| 22 | **Which machine had the lowest production or highest downtime?** | ✅ `success` | 199.59s | `SELECT 
  m.machine_name AS machine_name,
  SUM(p.qty) AS total_planned_production,
  SUM(ap.apq) AS actual_production,
  SUM(p.qty - ap.apq) AS production_shortfall
FROM 
  machine m
  JOIN production p ON m.id = p.machine_id
  JOIN actual_production ap ON p.id = ap.production_id
WHERE 
  m.deleted_at IS NULL AND p.deleted_at IS NULL AND ap.deleted_at IS NULL
GROUP BY 
  m.machine_name
ORDER BY 
  production_shortfall DESC
LIMIT 1` | SQL Query Executed: `SELECT    m.machine_name AS machine_name,   SUM(p.qty) AS total_planned_production,   SUM(ap.apq) A |
| 23 | **What is the total quantity produced across all job orders this year?** | ⚠️ `empty_result` | 108.21s | `SELECT SUM(apq) AS total_apq 
FROM actual_production 
WHERE production_date BETWEEN MAKEDATE(YEAR(CURDATE()), 1) AND CURDATE() 
AND deleted_at IS NULL` | SQL Query Executed: `SELECT SUM(apq) AS total_apq  FROM actual_production  WHERE production_date BETWEEN MAKEDATE(YEAR(C |
| 24 | **What is the average output volume per manufacturing batch?** | ✅ `success` | 18.31s | `SELECT AVG(apq) AS average_apq 
FROM actual_production 
WHERE deleted_at IS NULL;` | SQL Query Executed: `SELECT AVG(apq) AS average_apq  FROM actual_production  WHERE deleted_at IS NULL;` |
| 25 | **Which suppliers did we pay the most money to this year?** | ❌ `failed` | 71.8s | _None_ | No result |
| 26 | **How much raw material did we buy from vendors last month?** | ❌ `failed` | 256.5s | _None_ | No result |
| 27 | **Who is our primary supplier for packaging materials?** | ❌ `failed` | 184.06s | _None_ | No result |
| 28 | **What is our average monthly spending on supplier purchases?** | ❌ `not_applicable` | 5.48s | _None_ | No result |
| 29 | **Which raw material items account for the biggest chunk of our purchase expenses?** | ✅ `success` | 177.87s | `SELECT p.product_name AS raw_material_item, 
       SUM(pp.qty * p.rate) AS purchase_expenditure
FROM purchase_products pp
JOIN product p ON pp.product_id = p.id
JOIN category c ON p.category_id = c.id
WHERE c.product_type = 'RM'
GROUP BY p.product_name
ORDER BY purchase_expenditure DESC
LIMIT 1` | SQL Query Executed: `SELECT p.product_name AS raw_material_item,         SUM(pp.qty * p.rate) AS purchase_expenditure FR |
| 30 | **How many purchase shipments did we receive from vendors this quarter?** | ✅ `success` | 27.18s | `SELECT COUNT(DISTINCT dc.id) AS purchase_shipments_received
FROM delivery_challan dc
JOIN party p ON dc.party_id = p.id
JOIN financial_year fy ON dc.financial_id = fy.id
WHERE p.profile_type = 'Company'
AND fy.current_year = 'Y'
AND QUARTER(dc.dc_date) = QUARTER(CURDATE())
AND dc.deleted_at IS NULL
AND p.deleted_at IS NULL
AND fy.deleted_at IS NULL` | SQL Query Executed: `SELECT COUNT(DISTINCT dc.id) AS purchase_shipments_received FROM delivery_challan dc JOIN party p O |
| 31 | **Which transport agency handles the bulk of our product deliveries?** | ✅ `success` | 76.67s | `SELECT dc.transport_name AS top_transport_agency
FROM delivery_challan dc
JOIN delivery_challan_products dcp ON dc.id = dcp.dc_id
WHERE dc.deleted_at IS NULL AND dcp.deleted_at IS NULL
GROUP BY dc.transport_name
ORDER BY SUM(dcp.qty) DESC
LIMIT 1` | SQL Query Executed: `SELECT dc.transport_name AS top_transport_agency FROM delivery_challan dc JOIN delivery_challan_pro |
| 32 | **Which clients received the most deliveries over the last 30 days?** | ⚠️ `empty_result` | 37.45s | `SELECT 
  p.party_name AS client_name, 
  COUNT(dc.id) AS total_deliveries
FROM 
  delivery_challan dc
  JOIN party p ON dc.party_id = p.id
WHERE 
  dc.deleted_at IS NULL 
  AND p.deleted_at IS NULL 
  AND dc.transport_updated_at >= CURDATE() - INTERVAL 30 DAY
GROUP BY 
  p.party_name
ORDER BY 
  total_deliveries DESC
LIMIT 1` | SQL Query Executed: `SELECT    p.party_name AS client_name,    COUNT(dc.id) AS total_deliveries FROM    delivery_challan |
| 33 | **What delivery vehicles are most commonly used for our shipments?** | ✅ `success` | 127.04s | `SELECT dc.transport_name AS transport_name, COUNT(dc.id) AS frequency
FROM delivery_challan dc
WHERE dc.deleted_at IS NULL
GROUP BY dc.transport_name
ORDER BY frequency DESC
LIMIT 1` | SQL Query Executed: `SELECT dc.transport_name AS transport_name, COUNT(dc.id) AS frequency FROM delivery_challan dc WHER |
| 34 | **How many delivery notes/challans were created today?** | ✅ `success` | 21.37s | `SELECT COUNT(id) AS delivery_challans_created_today
FROM delivery_challan
WHERE created_at >= CURDATE()
AND deleted_at IS NULL` | SQL Query Executed: `SELECT COUNT(id) AS delivery_challans_created_today FROM delivery_challan WHERE created_at >= CURDA |
| 35 | **Show all shipments sent out to clients during the past week.** | ⚠️ `empty_result` | 88.08s | `SELECT 
    dc.dc_no AS delivery_challan_no,
    dc.dc_date AS delivery_date,
    p.party_name AS client_name,
    dc.transport_name AS transport_agency,
    dc.lr_number AS lr_number,
    dc.lr_date AS lr_date
FROM 
    delivery_challan dc
JOIN 
    party p ON dc.party_id = p.id
WHERE 
    dc.deleted_at IS NULL 
    AND p.deleted_at IS NULL 
    AND dc.dc_date BETWEEN CURDATE() - INTERVAL 7 DAY AND CURDATE()
ORDER BY 
    dc.dc_date DESC` | SQL Query Executed: `SELECT      dc.dc_no AS delivery_challan_no,     dc.dc_date AS delivery_date,     p.party_name AS c |
| 36 | **Which drivers handled the highest number of delivery runs recently?** | ✅ `success` | 89.51s | `SELECT T1.transport_name AS driver_name, COUNT(T1.id) AS total_delivery_runs
FROM delivery_challan T1
WHERE T1.deleted_at IS NULL
GROUP BY T1.transport_name
ORDER BY COUNT(T1.id) DESC
LIMIT 1` | SQL Query Executed: `SELECT T1.transport_name AS driver_name, COUNT(T1.id) AS total_delivery_runs FROM delivery_challan  |
| 37 | **How much total GST tax did we collect on proforma bills this year?** | ⚠️ `empty_result` | 36.67s | `SELECT SUM(p.gst_amount) AS total_gst_tax_collected
FROM proforma p
WHERE YEAR(p.pi_date) = YEAR(CURDATE())
AND p.deleted_at IS NULL` | SQL Query Executed: `SELECT SUM(p.gst_amount) AS total_gst_tax_collected FROM proforma p WHERE YEAR(p.pi_date) = YEAR(CU |
| 38 | **Which clients have the highest billed amounts on proforma invoices?** | ✅ `success` | 24.35s | `SELECT p.party_name AS client, SUM(pf.grand_total) AS billed_amount
FROM party p
JOIN proforma pf ON p.id = pf.party_id
WHERE pf.deleted_at IS NULL
GROUP BY p.party_name
ORDER BY billed_amount DESC
LIMIT 1` | SQL Query Executed: `SELECT p.party_name AS client, SUM(pf.grand_total) AS billed_amount FROM party p JOIN proforma pf O |
| 39 | **Can you show our total revenue before taxes versus after taxes for this year?** | ✅ `success` | 102.86s | `SELECT 
  SUM(p.rate * sop.qty) AS total_revenue_before_tax,
  SUM(pf.grand_total) AS total_revenue_after_tax
FROM 
  sales_order_products sop
  JOIN product p ON sop.product_id = p.id
  JOIN proforma pf ON pf.id = sop.sales_order_id
  JOIN financial_year fy ON fy.id = pf.financial_id
WHERE 
  fy.current_year = 'Y' AND pf.deleted_at IS NULL AND sop.deleted_at IS NULL` | SQL Query Executed: `SELECT    SUM(p.rate * sop.qty) AS total_revenue_before_tax,   SUM(pf.grand_total) AS total_revenue |
| 40 | **Which customers currently have an active opening balance on their accounts?** | ⚠️ `empty_result` | 30.12s | `SELECT 
  p.party_name AS customer_name,
  pob.opening_balance AS active_opening_balance
FROM 
  party p
  JOIN party_opening_balance pob ON p.id = pob.party_id
WHERE 
  pob.balance_type = 'Active' AND 
  p.status = 'Y' AND 
  pob.deleted_at IS NULL AND 
  p.deleted_at IS NULL` | SQL Query Executed: `SELECT    p.party_name AS customer_name,   pob.opening_balance AS active_opening_balance FROM    pa |
| 41 | **What was our highest value proforma bill generated this month?** | ❌ `failed` | 183.51s | _None_ | No result |
| 42 | **How many formal quotations did we send to clients this quarter?** | ✅ `success` | 173.29s | `SELECT COUNT(q.id) AS formal_quotations_sent
FROM quotation q
JOIN quotation_products qp ON q.id = qp.quotation_id
WHERE q.quotation_date >= MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL QUARTER(CURDATE()) QUARTER - INTERVAL 1 QUARTER
AND q.quotation_date < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL QUARTER(CURDATE()) QUARTER
AND q.deleted_at IS NULL` | SQL Query Executed: `SELECT COUNT(q.id) AS formal_quotations_sent FROM quotation q JOIN quotation_products qp ON q.id =  |
| 43 | **What are our top 5 most expensive finished goods per unit?** | ✅ `success` | 44.58s | `SELECT p.product_name AS product_name, p.rate AS unit_price
FROM product p
WHERE p.product_type_id = 2 AND p.deleted_at IS NULL
ORDER BY p.rate DESC
LIMIT 5` | SQL Query Executed: `SELECT p.product_name AS product_name, p.rate AS unit_price FROM product p WHERE p.product_type_id  |
| 44 | **Which product category has the largest variety of items?** | ✅ `success` | 20.79s | `SELECT c.category_name AS product_category, COUNT(DISTINCT pc.color) AS variety_of_items
FROM category c
JOIN color pc ON c.id = pc.category_id
WHERE c.deleted_at IS NULL AND pc.deleted_at IS NULL
GROUP BY c.category_name
ORDER BY variety_of_items DESC
LIMIT 1` | SQL Query Executed: `SELECT c.category_name AS product_category, COUNT(DISTINCT pc.color) AS variety_of_items FROM categ |
| 45 | **Which products require a high minimum purchase quantity (MOQ)?** | ✅ `success` | 59.34s | `SELECT p.product_name AS product_name, p.moq AS minimum_order_quantity
FROM product p
WHERE p.deleted_at IS NULL
ORDER BY p.moq DESC
LIMIT 20` | SQL Query Executed: `SELECT p.product_name AS product_name, p.moq AS minimum_order_quantity FROM product p WHERE p.delet |
| 46 | **How many items are finished goods versus raw materials in our catalog?** | ✅ `success` | 131.8s | `SELECT 
  SUM(CASE WHEN p.product_type_id = 2 THEN 1 ELSE 0 END) AS finished_goods_count,
  SUM(CASE WHEN p.product_type_id = 1 THEN 1 ELSE 0 END) AS raw_materials_count
FROM 
  product p
WHERE 
  p.deleted_at IS NULL` | SQL Query Executed: `SELECT    SUM(CASE WHEN p.product_type_id = 2 THEN 1 ELSE 0 END) AS finished_goods_count,   SUM(CAS |
| 47 | **Are there any products marked as inactive or disabled in our system?** | ✅ `success` | 162.51s | `SELECT p.product_name AS inactive_product_name, pt.product_type AS product_type
FROM product p
JOIN product_type pt ON p.product_type_id = pt.id
WHERE p.status = 'N' AND p.deleted_at IS NULL` | SQL Query Executed: `SELECT p.product_name AS inactive_product_name, pt.product_type AS product_type FROM product p JOIN |
| 48 | **Which states or regions generate the highest sales revenue for us?** | ❌ `failed` | 172.22s | _None_ | No result |
| 49 | **How many active buyers do we have in Maharashtra versus Gujarat?** | ✅ `success` | 17.96s | `SELECT 
  s.name AS state_name, 
  COUNT(DISTINCT p.id) AS active_buyers
FROM 
  party p
  JOIN states s ON p.state_id = s.id
WHERE 
  p.status = 'Y' AND p.deleted_at IS NULL AND p.profile_type = 'Party'
GROUP BY 
  s.name
HAVING 
  s.name IN ('Maharashtra', 'Gujarat')` | SQL Query Executed: `SELECT    s.name AS state_name,    COUNT(DISTINCT p.id) AS active_buyers FROM    party p   JOIN sta |
| 50 | **What is the breakdown of our customer base by city?** | ✅ `success` | 71.39s | `SELECT 
  p.city AS customer_city,
  COUNT(p.id) AS number_of_customers
FROM 
  party p
WHERE 
  p.profile_type = 'Party' AND
  p.deleted_at IS NULL
GROUP BY 
  p.city
ORDER BY 
  number_of_customers DESC
LIMIT 20` | SQL Query Executed: `SELECT    p.city AS customer_city,   COUNT(p.id) AS number_of_customers FROM    party p WHERE    p. |

---

## 📝 Full Per-Question Outputs

### Q1: Who bought the most goods from us this year?
- **Business Goal:** Identify top revenue-generating customers in the active financial year.
- **Status:** `failed` (8.48s)
**Output:**

No result

---

### Q2: Which buyers haven't placed an order with us in the last three months?
- **Business Goal:** Spot churned or inactive clients needing sales re-engagement.
- **Status:** `success` (22.31s)
```sql
SELECT
  p.party_name AS buyer_name,
  p.mobile1 AS contact_mobile,
  p.email AS contact_email
FROM party p
LEFT JOIN sales_order so
  ON p.id = so.party_id
  AND so.deleted_at IS NULL
  AND so.sales_order_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
WHERE p.status = 'Y'
  AND p.deleted_at IS NULL
  AND so.id IS NULL
```

**Output:**

SQL Query Executed: `SELECT
  p.party_name AS buyer_name,
  p.mobile1 AS contact_mobile,
  p.email AS contact_email
FROM party p
LEFT JOIN sales_order so
  ON p.id = so.party_id
  AND so.deleted_at IS NULL
  AND so.sales_order_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
WHERE p.status = 'Y'
  AND p.deleted_at IS NULL
  AND so.id IS NULL`

| buyer_name | contact_mobile | contact_email |
| --- | --- | --- |
| OM MANUFACTURERS | 9106310985 | info@ommanufacturers.com |
| OM MANUFACTURERS-INTERNAL |  |  |
| 5-Point Profile Tools LLP | 9762217205 | 5pointprofiletools@gmail.com |
| 7 STAR DIAMOND DRESSERS | 9879265430 |  |
| AADIRAJ CORPORATION | 9825670474 |  |
| ZAWAR GAUGES & TOOLS PVT LTD | 9422307006 | ZAWARGAUGES@GMAIL.COM |
| ZABBER MASONARY DRILL | 9327664940 |  |
| YUKTI INDUSTRIES | 9638215232 |  |
| Y H TOOLS MANUFACTURERS PVT LTD | 9815524499 | info@niconvises.com |
| YG CUTTING TOOLS CORPORATION PVT. LTD. |  | santhosha@yg1india.com |

_Showing 10 of 500 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

### Q3: What was our single biggest order by total value?
- **Business Goal:** Find the highest revenue sales order on record.
- **Status:** `success` (74.58s)
```sql
SELECT
  so.id AS sales_order_id,
  so.sales_order_date AS order_date,
  p.party_name AS customer_name,
  SUM(sop.qty * prod.rate) AS total_order_value
FROM sales_order so
JOIN party p ON so.party_id = p.id
JOIN sales_order_products sop ON so.id = sop.sales_order_id
JOIN product prod ON sop.product_id = prod.id
WHERE so.deleted_at IS NULL
  AND sop.deleted_at IS NULL
  AND prod.deleted_at IS NULL
  AND p.deleted_at IS NULL
GROUP BY so.id, so.sales_order_date, p.party_name
ORDER BY total_order_value DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT
  so.id AS sales_order_id,
  so.sales_order_date AS order_date,
  p.party_name AS customer_name,
  SUM(sop.qty * prod.rate) AS total_order_value
FROM sales_order so
JOIN party p ON so.party_id = p.id
JOIN sales_order_products sop ON so.id = sop.sales_order_id
JOIN product prod ON sop.product_id = prod.id
WHERE so.deleted_at IS NULL
  AND sop.deleted_at IS NULL
  AND prod.deleted_at IS NULL
  AND p.deleted_at IS NULL
GROUP BY so.id, so.sales_order_date, p.party_name
ORDER BY total_order_value DESC
LIMIT 1`

| sales_order_id | order_date | customer_name | total_order_value |
| --- | --- | --- | --- |
| 5537 | 2024-11-26 | IQDENT SPOKLA Z OGRANICZONA ODPOWIEDZIALNOSCIA | 1778400.0 |

---

### Q4: How many total orders did we receive this month?
- **Business Goal:** Monitor short-term sales volume velocity.
- **Status:** `failed` (38.04s)
**Output:**

No result

---

### Q5: Which customers usually order in the largest bulk quantities?
- **Business Goal:** Identify high-volume buyers for volume-discount negotiations.
- **Status:** `success` (39.06s)
```sql
SELECT
  p.party_name AS customer_name,
  SUM(sop.qty) AS total_quantity_ordered,
  COUNT(DISTINCT so.id) AS number_of_orders
FROM party p
JOIN sales_order so ON p.id = so.party_id
JOIN sales_order_products sop ON so.id = sop.sales_order_id
WHERE p.deleted_at IS NULL
  AND so.deleted_at IS NULL
  AND sop.deleted_at IS NULL
  AND p.status = 'Y'
GROUP BY p.id, p.party_name
ORDER BY total_quantity_ordered DESC
LIMIT 20
```

**Output:**

SQL Query Executed: `SELECT
  p.party_name AS customer_name,
  SUM(sop.qty) AS total_quantity_ordered,
  COUNT(DISTINCT so.id) AS number_of_orders
FROM party p
JOIN sales_order so ON p.id = so.party_id
JOIN sales_order_products sop ON so.id = sop.sales_order_id
WHERE p.deleted_at IS NULL
  AND so.deleted_at IS NULL
  AND sop.deleted_at IS NULL
  AND p.status = 'Y'
GROUP BY p.id, p.party_name
ORDER BY total_quantity_ordered DESC
LIMIT 20`

| customer_name | total_quantity_ordered | number_of_orders |
| --- | --- | --- |
| DORMER TOOLS INDIA PVT LTD-903 & 904 | 5380400.0 | 124 |
| OM MANUFACTURERS-INTERNAL | 2939694.0 | 1496 |
| IQDENT SPOKLA Z OGRANICZONA ODPOWIEDZIALNOSCIA | 1728000.0 | 12 |
| YG-1 INDIA PRIVATE LIMITED | 1203256.0 | 8 |
| XCEED TOOLINGS PVT LTD | 1202471.0 | 63 |
| FORBES PRECISION TOOLS AND MACHINE PARTS LIMITED | 1181480.0 | 100 |
| FORBES & CO. LTD-WALUJ | 1170778.0 | 120 |
| YG CUTTING TOOLS CORPORATION PVT. LTD. | 1052000.0 | 36 |
| EMKAY TOOLS LTD | 980372.0 | 40 |
| CRAFT TECH CUTTING TOOLS PVT LTD | 960212.0 | 31 |

_Showing 10 of 20 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

### Q6: Can you show a monthly breakdown of our sales revenue for this year?
- **Business Goal:** Track month-over-month revenue growth trends.
- **Status:** `success` (99.97s)
```sql
SELECT 
  DATE_FORMAT(so.sales_order_date, '%Y-%m') AS sales_month,
  SUM(p.rate * sop.qty) AS sales_revenue
FROM 
  sales_order so
  JOIN sales_order_products sop ON so.id = sop.sales_order_id
  JOIN product p ON sop.product_id = p.id
  JOIN financial_year fy ON so.financial_id = fy.id
WHERE 
  fy.current_year = 'Y' AND so.deleted_at IS NULL AND sop.deleted_at IS NULL
GROUP BY 
  sales_month
ORDER BY 
  sales_month
```

**Output:**

SQL Query Executed: `SELECT 
  DATE_FORMAT(so.sales_order_date, '%Y-%m') AS sales_month,
  SUM(p.rate * sop.qty) AS sales_revenue
FROM 
  sales_order so
  JOIN sales_order_products sop ON so.id = sop.sales_order_id
  JOIN product p ON sop.product_id = p.id
  JOIN financial_year fy ON so.financial_id = fy.id
WHERE 
  fy.current_year = 'Y' AND so.deleted_at IS NULL AND sop.deleted_at IS NULL
GROUP BY 
  sales_month
ORDER BY 
  sales_month`

| sales_month | sales_revenue |
| --- | --- |
| 2025-04 | 6417595.699999995 |
| 2025-05 | 6744544.119999998 |
| 2025-06 | 600164.8499999999 |

---

### Q7: How many potential clients are currently waiting for our follow-up?
- **Business Goal:** Measure active pipeline leads (`Pending` / `In-Progress`).
- **Status:** `success` (30.92s)
```sql
SELECT COUNT(p.id) AS potential_clients_waiting_for_followup
FROM party p
JOIN lead l ON p.id = l.party_id
WHERE l.status IN ('Pending', 'In-Progress')
AND l.deleted_at IS NULL
AND p.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT COUNT(p.id) AS potential_clients_waiting_for_followup
FROM party p
JOIN lead l ON p.id = l.party_id
WHERE l.status IN ('Pending', 'In-Progress')
AND l.deleted_at IS NULL
AND p.deleted_at IS NULL`

| potential_clients_waiting_for_followup |
| --- |
| 0 |

---

### Q8: Where do most of our successful deals come from?
- **Business Goal:** Evaluate ROI across lead sources (Website, Social Media, Referrals, Sales Reps).
- **Status:** `failed` (26.34s)
**Output:**

No result

---

### Q9: Which sales executive converted the most leads into actual customers?
- **Business Goal:** Rank sales team performance by successful conversions.
- **Status:** `success` (116.9s)
```sql
SELECT u.name AS top_sales_executive, COUNT(DISTINCT l.id) AS total_leads_converted
FROM lead l
JOIN users u ON l.lead_assign_to = u.id
WHERE l.status = 'Success'
GROUP BY u.name
ORDER BY total_leads_converted DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT u.name AS top_sales_executive, COUNT(DISTINCT l.id) AS total_leads_converted
FROM lead l
JOIN users u ON l.lead_assign_to = u.id
WHERE l.status = 'Success'
GROUP BY u.name
ORDER BY total_leads_converted DESC
LIMIT 1`

| top_sales_executive | total_leads_converted |
| --- | --- |
| PRATIK  PIPALIYA | 90 |

---

### Q10: How many customer inquiries got rejected or lost recently?
- **Business Goal:** Review lost deal volume and failure reasons.
- **Status:** `success` (32.88s)
```sql
SELECT COUNT(l.id) AS rejected_leads_count
FROM lead l
WHERE l.status IN ('Reject', 'Lost') AND l.deleted_at IS NULL
AND l.lead_date_time >= DATE_FORMAT(CURDATE() - INTERVAL 1 MONTH, '%Y-%m-%d')
```

**Output:**

SQL Query Executed: `SELECT COUNT(l.id) AS rejected_leads_count
FROM lead l
WHERE l.status IN ('Reject', 'Lost') AND l.deleted_at IS NULL
AND l.lead_date_time >= DATE_FORMAT(CURDATE() - INTERVAL 1 MONTH, '%Y-%m-%d')`

| rejected_leads_count |
| --- |
| 6 |

---

### Q11: Are there any open prospects that came in through social media?
- **Business Goal:** Filter digital marketing inbound leads.
- **Status:** `success` (51.86s)
```sql
SELECT 
    T1.company_name AS company_name, 
    T1.contact_name AS contact_name, 
    T1.email AS email, 
    T1.mobile AS mobile, 
    T1.lead_generate_from AS lead_source, 
    T1.status AS lead_status
FROM 
    lead AS T1
WHERE 
    T1.deleted_at IS NULL 
    AND T1.status IN ('Pending', 'In-Progress') 
    AND T1.lead_generate_from = 'SocialMedia'
```

**Output:**

SQL Query Executed: `SELECT 
    T1.company_name AS company_name, 
    T1.contact_name AS contact_name, 
    T1.email AS email, 
    T1.mobile AS mobile, 
    T1.lead_generate_from AS lead_source, 
    T1.status AS lead_status
FROM 
    lead AS T1
WHERE 
    T1.deleted_at IS NULL 
    AND T1.status IN ('Pending', 'In-Progress') 
    AND T1.lead_generate_from = 'SocialMedia'`

| company_name | contact_name | email | mobile | lead_source | lead_status |
| --- | --- | --- | --- | --- | --- |
| Shiv Shakti Metal | Virendra Tripathi | viren@shivshaktimetal.com | 6359576799 / 9054125645 | SocialMedia | Pending |
| RUDRA ENGINEERING | MR. SIDRAM CHOOGULE | rudraenginerring018@gmail.com | 98815 64573 | SocialMedia | Pending |
| SIVA SAKTHI TRADERS | MR. NAGAMUTHU | kishore.muthu2006@gmail.com | 7401354926 / 8608264778 | SocialMedia | Pending |
| PRIMCOAT PVD TECHNOLOGY INDIA PRIVATE LIMITED | Mr.Shaneshwar | shaneshwar.supnar@primcoat.com | 97629 23534 | SocialMedia | Pending |
| RAVI INTERNATIONAL | MR. RAVI JAIN | info@garvintools.com | 9891970145 | SocialMedia | Pending |
| HARSHVARDHAN TRADERS | MR. ARUNKUMAR NATAJAN | htatools@gmail.com | 9626666993 | SocialMedia | Pending |
| JYOTI TOOLS (INDIA) | MR. ABHAY MITTAL | info@jyotitoolsindia.com | 9914532404 | SocialMedia | Pending |
| AHASAAS MULTI FUNCTIONAL PROJECTS | MR. AVDHESH KUMAR | ahasaas@gmail.com | 9839812812 | SocialMedia | Pending |
| SRI VENKATESWARA ENGINEERING - WORKS | MR. LOKESHWARAN | informsvew@yahoo.com | 99407 45534 | SocialMedia | Pending |
| SIVARAM PRESS TOOLS | MR. SHIVA | shivaram.141@gmail.com | 81218 50695 | SocialMedia | Pending |

_Showing 10 of 18 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

### Q12: What percentage of our total inquiries end up closing successfully?
- **Business Goal:** Calculate the overall lead-to-win conversion rate.
- **Status:** `success` (12.82s)
```sql
SELECT 
  SUM(CASE WHEN l.status = 'Success' THEN 1 ELSE 0 END) / COUNT(l.id) * 100 AS success_rate
FROM 
  lead l
WHERE 
  l.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  SUM(CASE WHEN l.status = 'Success' THEN 1 ELSE 0 END) / COUNT(l.id) * 100 AS success_rate
FROM 
  lead l
WHERE 
  l.deleted_at IS NULL`

| success_rate |
| --- |
| 50.0000 |

---

### Q13: What products are currently running dangerously low on stock?
- **Business Goal:** Identify items nearing stockout or below safety thresholds.
- **Status:** `success` (18.04s)
```sql
SELECT 
  p.id AS product_id,
  p.product_name AS product_name,
  pc.color AS product_color,
  COALESCE(SUM(CAST(s.qty AS DECIMAL(10,2))), 0) AS current_stock,
  pc.minimum_stock AS minimum_stock
FROM 
  product p
  JOIN product_color pc ON p.id = pc.product_id
  LEFT JOIN stock s ON s.product_id = p.id AND s.product_color_id = pc.id AND s.status = 'B' AND s.deleted_at IS NULL
WHERE 
  pc.minimum_stock > 0
GROUP BY 
  p.id, p.product_name, pc.color, pc.minimum_stock
HAVING 
  current_stock < pc.minimum_stock
ORDER BY 
  current_stock ASC, pc.minimum_stock DESC
LIMIT 20
```

**Output:**

SQL Query Executed: `SELECT 
  p.id AS product_id,
  p.product_name AS product_name,
  pc.color AS product_color,
  COALESCE(SUM(CAST(s.qty AS DECIMAL(10,2))), 0) AS current_stock,
  pc.minimum_stock AS minimum_stock
FROM 
  product p
  JOIN product_color pc ON p.id = pc.product_id
  LEFT JOIN stock s ON s.product_id = p.id AND s.product_color_id = pc.id AND s.status = 'B' AND s.deleted_at IS NULL
WHERE 
  pc.minimum_stock > 0
GROUP BY 
  p.id, p.product_name, pc.color, pc.minimum_stock
HAVING 
  current_stock < pc.minimum_stock
ORDER BY 
  current_stock ASC, pc.minimum_stock DESC
LIMIT 20`

| product_id | product_name | product_color | current_stock | minimum_stock |
| --- | --- | --- | --- | --- |
| 26 | PGB 0.5-7.0 | TRANS+BLACK | 0.00 | 60000.0 |
| 175 | CHP14065105-INNER | TRANS | 0.00 | 50000.0 |
| 176 | CHP14065105-OUTER | TRANS | 0.00 | 50000.0 |
| 546 | CHP20120200-D-OUTER | TRANS | 0.00 | 40000.0 |
| 545 | CHP20120200-D-INNER | TRANS | 0.00 | 40000.0 |
| 116 | SHP08-TUBE52 | TRANS | 0.00 | 35000.0 |
| 147 | CHP06070110-OUTER | TRANS | 0.00 | 30000.0 |
| 179 | CHP14080120-INNER | TRANS | 0.00 | 30000.0 |
| 146 | CHP06070110-INNER | TRANS | 0.00 | 30000.0 |
| 180 | CHP14080120-OUTER | TRANS | 0.00 | 30000.0 |

_Showing 10 of 20 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

### Q14: How much total inventory is sitting in the warehouse right now?
- **Business Goal:** Calculate aggregate on-hand stock valuation and units.
- **Status:** `success` (27.49s)
```sql
SELECT 
  SUM(CAST(s.qty AS DECIMAL(10,2))) AS total_inventory
FROM 
  stock s
WHERE 
  s.status = 'B' AND s.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  SUM(CAST(s.qty AS DECIMAL(10,2))) AS total_inventory
FROM 
  stock s
WHERE 
  s.status = 'B' AND s.deleted_at IS NULL`

| total_inventory |
| --- |
| 85964.00 |

---

### Q15: Are there any packed cartons in the warehouse waiting for manager verification?
- **Business Goal:** Flag pending QA/verification bottleneck cartons (`carton_verify_status = 'P'`).
- **Status:** `success` (83.19s)
```sql
SELECT COUNT(*) AS pending_packed_cartons
FROM packagings
WHERE carton_verify_status = 'P' AND status = 'B' AND deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT COUNT(*) AS pending_packed_cartons
FROM packagings
WHERE carton_verify_status = 'P' AND status = 'B' AND deleted_at IS NULL`

| pending_packed_cartons |
| --- |
| 333 |

---

### Q16: Which items have been lying in storage for the longest time without moving?
- **Business Goal:** Detect dead stock or slow-moving finished goods.
- **Status:** `empty_result` (50.13s)
```sql
SELECT 
  p.product_name AS product_name,
  s.batch_no AS batch_number,
  s.invoice_date AS storage_date,
  DATEDIFF(CURDATE(), s.invoice_date) AS days_in_storage
FROM 
  stock s
  JOIN product p ON s.product_id = p.id
WHERE 
  s.deleted_at IS NULL
  AND s.status = 'B'
  AND s.carton_verify_status = 'V'
ORDER BY 
  days_in_storage DESC
LIMIT 1;
```

**Output:**

SQL Query Executed: `SELECT 
  p.product_name AS product_name,
  s.batch_no AS batch_number,
  s.invoice_date AS storage_date,
  DATEDIFF(CURDATE(), s.invoice_date) AS days_in_storage
FROM 
  stock s
  JOIN product p ON s.product_id = p.id
WHERE 
  s.deleted_at IS NULL
  AND s.status = 'B'
  AND s.carton_verify_status = 'V'
ORDER BY 
  days_in_storage DESC
LIMIT 1;`

No matching records found in the database.

---

### Q17: How many cartons were shipped out of the warehouse this week?
- **Business Goal:** Measure outbound warehouse dispatch throughput.
- **Status:** `success` (52.44s)
```sql
SELECT COUNT(DISTINCT dc.id) AS cartons_shipped
FROM delivery_challan dc
JOIN delivery_challan_products dcp ON dc.id = dcp.dc_id
WHERE dc.dc_date BETWEEN CURDATE() - INTERVAL 7 DAY AND CURDATE()
AND dc.deleted_at IS NULL
AND dcp.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT COUNT(DISTINCT dc.id) AS cartons_shipped
FROM delivery_challan dc
JOIN delivery_challan_products dcp ON dc.id = dcp.dc_id
WHERE dc.dc_date BETWEEN CURDATE() - INTERVAL 7 DAY AND CURDATE()
AND dc.deleted_at IS NULL
AND dcp.deleted_at IS NULL`

| cartons_shipped |
| --- |
| 0 |

---

### Q18: Do we have any recorded stock adjustment write-offs this month?
- **Business Goal:** Audit physical stock reconciliation adjustments.
- **Status:** `success` (105.01s)
```sql
SELECT 
  COUNT(id) AS stock_adjustment_write_offs
FROM 
  stock_adjustment
WHERE 
  transaction_type = 'WriteOff' 
  AND stock_adjustment_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01') 
  AND deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  COUNT(id) AS stock_adjustment_write_offs
FROM 
  stock_adjustment
WHERE 
  transaction_type = 'WriteOff' 
  AND stock_adjustment_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01') 
  AND deleted_at IS NULL`

| stock_adjustment_write_offs |
| --- |
| 0 |

---

### Q19: Which factory machines produced the highest output this month?
- **Business Goal:** Evaluate machinery productivity and utilization.
- **Status:** `empty_result` (186.08s)
```sql
SELECT 
  m.machine_name AS top_machine, 
  SUM(p.qty) AS highest_output
FROM 
  production p
  JOIN machine m ON p.machine_id = m.id
WHERE 
  p.deleted_at IS NULL 
  AND m.deleted_at IS NULL 
  AND p.production_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
GROUP BY 
  m.machine_name
ORDER BY 
  highest_output DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT 
  m.machine_name AS top_machine, 
  SUM(p.qty) AS highest_output
FROM 
  production p
  JOIN machine m ON p.machine_id = m.id
WHERE 
  p.deleted_at IS NULL 
  AND m.deleted_at IS NULL 
  AND p.production_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
GROUP BY 
  m.machine_name
ORDER BY 
  highest_output DESC
LIMIT 1`

No matching records found in the database.

---

### Q20: Did any manufacturing batch fail to hit its original planned target?
- **Business Goal:** Identify production shortfalls (`actual_production < planned_production`).
- **Status:** `success` (40.76s)
```sql
SELECT 
  p.id AS production_id,
  p.qty AS planned_quantity,
  COALESCE(ap.apq, 0) AS actual_produced_quantity,
  (p.qty - COALESCE(ap.apq, 0)) AS production_shortfall
FROM 
  production p
  LEFT JOIN actual_production ap ON p.id = ap.production_id
WHERE 
  p.qty > COALESCE(ap.apq, 0)
  AND p.deleted_at IS NULL
  AND ap.deleted_at IS NULL
ORDER BY 
  production_shortfall DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT 
  p.id AS production_id,
  p.qty AS planned_quantity,
  COALESCE(ap.apq, 0) AS actual_produced_quantity,
  (p.qty - COALESCE(ap.apq, 0)) AS production_shortfall
FROM 
  production p
  LEFT JOIN actual_production ap ON p.id = ap.production_id
WHERE 
  p.qty > COALESCE(ap.apq, 0)
  AND p.deleted_at IS NULL
  AND ap.deleted_at IS NULL
ORDER BY 
  production_shortfall DESC
LIMIT 1`

| production_id | planned_quantity | actual_produced_quantity | production_shortfall |
| --- | --- | --- | --- |
| 5516 | 60606.0 | 0.0 | 60606.0 |

---

### Q21: How much finished product did the factory complete over the past week?
- **Business Goal:** Track short-term factory manufacturing yield.
- **Status:** `empty_result` (52.42s)
```sql
SELECT 
  SUM(apq) AS total_actual_product_quantity
FROM 
  actual_production
WHERE 
  production_date BETWEEN CURDATE() - INTERVAL 1 WEEK AND CURDATE()
  AND product_type_id = 2
  AND deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  SUM(apq) AS total_actual_product_quantity
FROM 
  actual_production
WHERE 
  production_date BETWEEN CURDATE() - INTERVAL 1 WEEK AND CURDATE()
  AND product_type_id = 2
  AND deleted_at IS NULL`

| total_actual_product_quantity |
| --- |
| NULL |

_Note: The query matched 0 records for aggregation, returning NULL._

---

### Q22: Which machine had the lowest production or highest downtime?
- **Business Goal:** Pinpoint underperforming or maintenance-heavy equipment.
- **Status:** `success` (199.59s)
```sql
SELECT 
  m.machine_name AS machine_name,
  SUM(p.qty) AS total_planned_production,
  SUM(ap.apq) AS actual_production,
  SUM(p.qty - ap.apq) AS production_shortfall
FROM 
  machine m
  JOIN production p ON m.id = p.machine_id
  JOIN actual_production ap ON p.id = ap.production_id
WHERE 
  m.deleted_at IS NULL AND p.deleted_at IS NULL AND ap.deleted_at IS NULL
GROUP BY 
  m.machine_name
ORDER BY 
  production_shortfall DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT 
  m.machine_name AS machine_name,
  SUM(p.qty) AS total_planned_production,
  SUM(ap.apq) AS actual_production,
  SUM(p.qty - ap.apq) AS production_shortfall
FROM 
  machine m
  JOIN production p ON m.id = p.machine_id
  JOIN actual_production ap ON p.id = ap.production_id
WHERE 
  m.deleted_at IS NULL AND p.deleted_at IS NULL AND ap.deleted_at IS NULL
GROUP BY 
  m.machine_name
ORDER BY 
  production_shortfall DESC
LIMIT 1`

| machine_name | total_planned_production | actual_production | production_shortfall |
| --- | --- | --- | --- |
| OMB 012 | 1883867.0 | 1654528.0 | 229339.0 |

---

### Q23: What is the total quantity produced across all job orders this year?
- **Business Goal:** Annual manufacturing output milestone tracking.
- **Status:** `empty_result` (108.21s)
```sql
SELECT SUM(apq) AS total_apq 
FROM actual_production 
WHERE production_date BETWEEN MAKEDATE(YEAR(CURDATE()), 1) AND CURDATE() 
AND deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT SUM(apq) AS total_apq 
FROM actual_production 
WHERE production_date BETWEEN MAKEDATE(YEAR(CURDATE()), 1) AND CURDATE() 
AND deleted_at IS NULL`

| total_apq |
| --- |
| NULL |

_Note: The query matched 0 records for aggregation, returning NULL._

---

### Q24: What is the average output volume per manufacturing batch?
- **Business Goal:** Benchmark standard batch production size.
- **Status:** `success` (18.31s)
```sql
SELECT AVG(apq) AS average_apq 
FROM actual_production 
WHERE deleted_at IS NULL;
```

**Output:**

SQL Query Executed: `SELECT AVG(apq) AS average_apq 
FROM actual_production 
WHERE deleted_at IS NULL;`

| average_apq |
| --- |
| 4627.045230180316 |

---

### Q25: Which suppliers did we pay the most money to this year?
- **Business Goal:** Analyze top vendor spend and supplier concentration risk.
- **Status:** `failed` (71.8s)
**Output:**

No result

---

### Q26: How much raw material did we buy from vendors last month?
- **Business Goal:** Track monthly raw material procurement expense.
- **Status:** `failed` (256.5s)
**Output:**

No result

---

### Q27: Who is our primary supplier for packaging materials?
- **Business Goal:** Identify vendor dependency for packaging items.
- **Status:** `failed` (184.06s)
**Output:**

No result

---

### Q28: What is our average monthly spending on supplier purchases?
- **Business Goal:** Establish procurement budget baseline.
- **Status:** `not_applicable` (5.48s)
**Output:**

No result

---

### Q29: Which raw material items account for the biggest chunk of our purchase expenses?
- **Business Goal:** Pareto analysis (80/20 rule) of purchase spend by material.
- **Status:** `success` (177.87s)
```sql
SELECT p.product_name AS raw_material_item, 
       SUM(pp.qty * p.rate) AS purchase_expenditure
FROM purchase_products pp
JOIN product p ON pp.product_id = p.id
JOIN category c ON p.category_id = c.id
WHERE c.product_type = 'RM'
GROUP BY p.product_name
ORDER BY purchase_expenditure DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT p.product_name AS raw_material_item, 
       SUM(pp.qty * p.rate) AS purchase_expenditure
FROM purchase_products pp
JOIN product p ON pp.product_id = p.id
JOIN category c ON p.category_id = c.id
WHERE c.product_type = 'RM'
GROUP BY p.product_name
ORDER BY purchase_expenditure DESC
LIMIT 1`

| raw_material_item | purchase_expenditure |
| --- | --- |
| BHIDA PATTI | 0.0 |

---

### Q30: How many purchase shipments did we receive from vendors this quarter?
- **Business Goal:** Track inbound logistics and supplier delivery frequency.
- **Status:** `success` (27.18s)
```sql
SELECT COUNT(DISTINCT dc.id) AS purchase_shipments_received
FROM delivery_challan dc
JOIN party p ON dc.party_id = p.id
JOIN financial_year fy ON dc.financial_id = fy.id
WHERE p.profile_type = 'Company'
AND fy.current_year = 'Y'
AND QUARTER(dc.dc_date) = QUARTER(CURDATE())
AND dc.deleted_at IS NULL
AND p.deleted_at IS NULL
AND fy.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT COUNT(DISTINCT dc.id) AS purchase_shipments_received
FROM delivery_challan dc
JOIN party p ON dc.party_id = p.id
JOIN financial_year fy ON dc.financial_id = fy.id
WHERE p.profile_type = 'Company'
AND fy.current_year = 'Y'
AND QUARTER(dc.dc_date) = QUARTER(CURDATE())
AND dc.deleted_at IS NULL
AND p.deleted_at IS NULL
AND fy.deleted_at IS NULL`

| purchase_shipments_received |
| --- |
| 0 |

---

### Q31: Which transport agency handles the bulk of our product deliveries?
- **Business Goal:** Logistics partner performance and freight volume share.
- **Status:** `success` (76.67s)
```sql
SELECT dc.transport_name AS top_transport_agency
FROM delivery_challan dc
JOIN delivery_challan_products dcp ON dc.id = dcp.dc_id
WHERE dc.deleted_at IS NULL AND dcp.deleted_at IS NULL
GROUP BY dc.transport_name
ORDER BY SUM(dcp.qty) DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT dc.transport_name AS top_transport_agency
FROM delivery_challan dc
JOIN delivery_challan_products dcp ON dc.id = dcp.dc_id
WHERE dc.deleted_at IS NULL AND dcp.deleted_at IS NULL
GROUP BY dc.transport_name
ORDER BY SUM(dcp.qty) DESC
LIMIT 1`

| top_transport_agency |
| --- |
| NULL |

---

### Q32: Which clients received the most deliveries over the last 30 days?
- **Business Goal:** Identify most active distribution destinations.
- **Status:** `empty_result` (37.45s)
```sql
SELECT 
  p.party_name AS client_name, 
  COUNT(dc.id) AS total_deliveries
FROM 
  delivery_challan dc
  JOIN party p ON dc.party_id = p.id
WHERE 
  dc.deleted_at IS NULL 
  AND p.deleted_at IS NULL 
  AND dc.transport_updated_at >= CURDATE() - INTERVAL 30 DAY
GROUP BY 
  p.party_name
ORDER BY 
  total_deliveries DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT 
  p.party_name AS client_name, 
  COUNT(dc.id) AS total_deliveries
FROM 
  delivery_challan dc
  JOIN party p ON dc.party_id = p.id
WHERE 
  dc.deleted_at IS NULL 
  AND p.deleted_at IS NULL 
  AND dc.transport_updated_at >= CURDATE() - INTERVAL 30 DAY
GROUP BY 
  p.party_name
ORDER BY 
  total_deliveries DESC
LIMIT 1`

No matching records found in the database.

---

### Q33: What delivery vehicles are most commonly used for our shipments?
- **Business Goal:** Vehicle fleet utilization and freight capacity planning.
- **Status:** `success` (127.04s)
```sql
SELECT dc.transport_name AS transport_name, COUNT(dc.id) AS frequency
FROM delivery_challan dc
WHERE dc.deleted_at IS NULL
GROUP BY dc.transport_name
ORDER BY frequency DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT dc.transport_name AS transport_name, COUNT(dc.id) AS frequency
FROM delivery_challan dc
WHERE dc.deleted_at IS NULL
GROUP BY dc.transport_name
ORDER BY frequency DESC
LIMIT 1`

| transport_name | frequency |
| --- | --- |
| NULL | 7482 |

---

### Q34: How many delivery notes/challans were created today?
- **Business Goal:** Daily dispatch activity snapshot.
- **Status:** `success` (21.37s)
```sql
SELECT COUNT(id) AS delivery_challans_created_today
FROM delivery_challan
WHERE created_at >= CURDATE()
AND deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT COUNT(id) AS delivery_challans_created_today
FROM delivery_challan
WHERE created_at >= CURDATE()
AND deleted_at IS NULL`

| delivery_challans_created_today |
| --- |
| 0 |

---

### Q35: Show all shipments sent out to clients during the past week.
- **Business Goal:** Outbound delivery tracking for customer service inquiries.
- **Status:** `empty_result` (88.08s)
```sql
SELECT 
    dc.dc_no AS delivery_challan_no,
    dc.dc_date AS delivery_date,
    p.party_name AS client_name,
    dc.transport_name AS transport_agency,
    dc.lr_number AS lr_number,
    dc.lr_date AS lr_date
FROM 
    delivery_challan dc
JOIN 
    party p ON dc.party_id = p.id
WHERE 
    dc.deleted_at IS NULL 
    AND p.deleted_at IS NULL 
    AND dc.dc_date BETWEEN CURDATE() - INTERVAL 7 DAY AND CURDATE()
ORDER BY 
    dc.dc_date DESC
```

**Output:**

SQL Query Executed: `SELECT 
    dc.dc_no AS delivery_challan_no,
    dc.dc_date AS delivery_date,
    p.party_name AS client_name,
    dc.transport_name AS transport_agency,
    dc.lr_number AS lr_number,
    dc.lr_date AS lr_date
FROM 
    delivery_challan dc
JOIN 
    party p ON dc.party_id = p.id
WHERE 
    dc.deleted_at IS NULL 
    AND p.deleted_at IS NULL 
    AND dc.dc_date BETWEEN CURDATE() - INTERVAL 7 DAY AND CURDATE()
ORDER BY 
    dc.dc_date DESC`

No matching records found in the database.

---

### Q36: Which drivers handled the highest number of delivery runs recently?
- **Business Goal:** Driver trip allocation and workload balancing.
- **Status:** `success` (89.51s)
```sql
SELECT T1.transport_name AS driver_name, COUNT(T1.id) AS total_delivery_runs
FROM delivery_challan T1
WHERE T1.deleted_at IS NULL
GROUP BY T1.transport_name
ORDER BY COUNT(T1.id) DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT T1.transport_name AS driver_name, COUNT(T1.id) AS total_delivery_runs
FROM delivery_challan T1
WHERE T1.deleted_at IS NULL
GROUP BY T1.transport_name
ORDER BY COUNT(T1.id) DESC
LIMIT 1`

| driver_name | total_delivery_runs |
| --- | --- |
| NULL | 7482 |

---

### Q37: How much total GST tax did we collect on proforma bills this year?
- **Business Goal:** Tax liability estimation from generated proforma invoices.
- **Status:** `empty_result` (36.67s)
```sql
SELECT SUM(p.gst_amount) AS total_gst_tax_collected
FROM proforma p
WHERE YEAR(p.pi_date) = YEAR(CURDATE())
AND p.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT SUM(p.gst_amount) AS total_gst_tax_collected
FROM proforma p
WHERE YEAR(p.pi_date) = YEAR(CURDATE())
AND p.deleted_at IS NULL`

| total_gst_tax_collected |
| --- |
| NULL |

_Note: The query matched 0 records for aggregation, returning NULL._

---

### Q38: Which clients have the highest billed amounts on proforma invoices?
- **Business Goal:** Top billed clients summary.
- **Status:** `success` (24.35s)
```sql
SELECT p.party_name AS client, SUM(pf.grand_total) AS billed_amount
FROM party p
JOIN proforma pf ON p.id = pf.party_id
WHERE pf.deleted_at IS NULL
GROUP BY p.party_name
ORDER BY billed_amount DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT p.party_name AS client, SUM(pf.grand_total) AS billed_amount
FROM party p
JOIN proforma pf ON p.id = pf.party_id
WHERE pf.deleted_at IS NULL
GROUP BY p.party_name
ORDER BY billed_amount DESC
LIMIT 1`

| client | billed_amount |
| --- | --- |
| HM TOOLS | 15488.09 |

---

### Q39: Can you show our total revenue before taxes versus after taxes for this year?
- **Business Goal:** Gross revenue vs. net billing comparison.
- **Status:** `success` (102.86s)
```sql
SELECT 
  SUM(p.rate * sop.qty) AS total_revenue_before_tax,
  SUM(pf.grand_total) AS total_revenue_after_tax
FROM 
  sales_order_products sop
  JOIN product p ON sop.product_id = p.id
  JOIN proforma pf ON pf.id = sop.sales_order_id
  JOIN financial_year fy ON fy.id = pf.financial_id
WHERE 
  fy.current_year = 'Y' AND pf.deleted_at IS NULL AND sop.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  SUM(p.rate * sop.qty) AS total_revenue_before_tax,
  SUM(pf.grand_total) AS total_revenue_after_tax
FROM 
  sales_order_products sop
  JOIN product p ON sop.product_id = p.id
  JOIN proforma pf ON pf.id = sop.sales_order_id
  JOIN financial_year fy ON fy.id = pf.financial_id
WHERE 
  fy.current_year = 'Y' AND pf.deleted_at IS NULL AND sop.deleted_at IS NULL`

| total_revenue_before_tax | total_revenue_after_tax |
| --- | --- |
| 15609.0 | 74512.04 |

---

### Q40: Which customers currently have an active opening balance on their accounts?
- **Business Goal:** Accounts receivable legacy balance review.
- **Status:** `empty_result` (30.12s)
```sql
SELECT 
  p.party_name AS customer_name,
  pob.opening_balance AS active_opening_balance
FROM 
  party p
  JOIN party_opening_balance pob ON p.id = pob.party_id
WHERE 
  pob.balance_type = 'Active' AND 
  p.status = 'Y' AND 
  pob.deleted_at IS NULL AND 
  p.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  p.party_name AS customer_name,
  pob.opening_balance AS active_opening_balance
FROM 
  party p
  JOIN party_opening_balance pob ON p.id = pob.party_id
WHERE 
  pob.balance_type = 'Active' AND 
  p.status = 'Y' AND 
  pob.deleted_at IS NULL AND 
  p.deleted_at IS NULL`

No matching records found in the database.

---

### Q41: What was our highest value proforma bill generated this month?
- **Business Goal:** Flag major monthly billing milestones.
- **Status:** `failed` (183.51s)
**Output:**

No result

---

### Q42: How many formal quotations did we send to clients this quarter?
- **Business Goal:** Quotation pipeline volume before conversion into orders.
- **Status:** `success` (173.29s)
```sql
SELECT COUNT(q.id) AS formal_quotations_sent
FROM quotation q
JOIN quotation_products qp ON q.id = qp.quotation_id
WHERE q.quotation_date >= MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL QUARTER(CURDATE()) QUARTER - INTERVAL 1 QUARTER
AND q.quotation_date < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL QUARTER(CURDATE()) QUARTER
AND q.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT COUNT(q.id) AS formal_quotations_sent
FROM quotation q
JOIN quotation_products qp ON q.id = qp.quotation_id
WHERE q.quotation_date >= MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL QUARTER(CURDATE()) QUARTER - INTERVAL 1 QUARTER
AND q.quotation_date < MAKEDATE(YEAR(CURDATE()), 1) + INTERVAL QUARTER(CURDATE()) QUARTER
AND q.deleted_at IS NULL`

| formal_quotations_sent |
| --- |
| 0 |

---

### Q43: What are our top 5 most expensive finished goods per unit?
- **Business Goal:** Premium product line pricing visibility.
- **Status:** `success` (44.58s)
```sql
SELECT p.product_name AS product_name, p.rate AS unit_price
FROM product p
WHERE p.product_type_id = 2 AND p.deleted_at IS NULL
ORDER BY p.rate DESC
LIMIT 5
```

**Output:**

SQL Query Executed: `SELECT p.product_name AS product_name, p.rate AS unit_price
FROM product p
WHERE p.product_type_id = 2 AND p.deleted_at IS NULL
ORDER BY p.rate DESC
LIMIT 5`

| product_name | unit_price |
| --- | --- |
| CHP110160230-SET | 85.0 |
| THP50045100 | 80.0 |
| CHP76300600-SET | 69.0 |
| CHP65300450-SET | 59.8 |
| CHP50350650-SET | 54.05 |

---

### Q44: Which product category has the largest variety of items?
- **Business Goal:** Master catalog depth and category diversification.
- **Status:** `success` (20.79s)
```sql
SELECT c.category_name AS product_category, COUNT(DISTINCT pc.color) AS variety_of_items
FROM category c
JOIN color pc ON c.id = pc.category_id
WHERE c.deleted_at IS NULL AND pc.deleted_at IS NULL
GROUP BY c.category_name
ORDER BY variety_of_items DESC
LIMIT 1
```

**Output:**

SQL Query Executed: `SELECT c.category_name AS product_category, COUNT(DISTINCT pc.color) AS variety_of_items
FROM category c
JOIN color pc ON c.id = pc.category_id
WHERE c.deleted_at IS NULL AND pc.deleted_at IS NULL
GROUP BY c.category_name
ORDER BY variety_of_items DESC
LIMIT 1`

| product_category | variety_of_items |
| --- | --- |
| CHANGEABLE PACK | 35 |

---

### Q45: Which products require a high minimum purchase quantity (MOQ)?
- **Business Goal:** Identify bulk-only commercial items (`moq > threshold`).
- **Status:** `success` (59.34s)
```sql
SELECT p.product_name AS product_name, p.moq AS minimum_order_quantity
FROM product p
WHERE p.deleted_at IS NULL
ORDER BY p.moq DESC
LIMIT 20
```

**Output:**

SQL Query Executed: `SELECT p.product_name AS product_name, p.moq AS minimum_order_quantity
FROM product p
WHERE p.deleted_at IS NULL
ORDER BY p.moq DESC
LIMIT 20`

| product_name | minimum_order_quantity |
| --- | --- |
| SLP12080120-OUTER | NULL |
| PB3508 | NULL |
| PB3512 | NULL |
| PB402115 | NULL |
| PB623409 | NULL |
| PB94377.5 | NULL |
| PB17.817.86.3 | NULL |
| PB3508 WITH FOAM | NULL |
| PB3512 WITH FOAM | NULL |
| PB222208 | NULL |

_Showing 10 of 20 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

### Q46: How many items are finished goods versus raw materials in our catalog?
- **Business Goal:** Master product catalog segmentation breakdown.
- **Status:** `success` (131.8s)
```sql
SELECT 
  SUM(CASE WHEN p.product_type_id = 2 THEN 1 ELSE 0 END) AS finished_goods_count,
  SUM(CASE WHEN p.product_type_id = 1 THEN 1 ELSE 0 END) AS raw_materials_count
FROM 
  product p
WHERE 
  p.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT 
  SUM(CASE WHEN p.product_type_id = 2 THEN 1 ELSE 0 END) AS finished_goods_count,
  SUM(CASE WHEN p.product_type_id = 1 THEN 1 ELSE 0 END) AS raw_materials_count
FROM 
  product p
WHERE 
  p.deleted_at IS NULL`

| finished_goods_count | raw_materials_count |
| --- | --- |
| 615 | 86 |

---

### Q47: Are there any products marked as inactive or disabled in our system?
- **Business Goal:** Catalog hygiene check (`product.status = 'N'`).
- **Status:** `success` (162.51s)
```sql
SELECT p.product_name AS inactive_product_name, pt.product_type AS product_type
FROM product p
JOIN product_type pt ON p.product_type_id = pt.id
WHERE p.status = 'N' AND p.deleted_at IS NULL
```

**Output:**

SQL Query Executed: `SELECT p.product_name AS inactive_product_name, pt.product_type AS product_type
FROM product p
JOIN product_type pt ON p.product_type_id = pt.id
WHERE p.status = 'N' AND p.deleted_at IS NULL`

| inactive_product_name | product_type |
| --- | --- |
| PB623409 | Finished Goods |
| PB623409 WITH FOAM | Finished Goods |
| CHP38070100-SET | Finished Goods |
| CHP18200350-R-INNER | Finished Goods |
| CHP18200350-R-OUTER | Finished Goods |
| CHP50100180 | Finished Goods |
| CHP38070100-INNER | Finished Goods |
| CAP02 | Finished Goods |
| CAP03 | Finished Goods |
| CAP04 | Finished Goods |

_Showing 10 of 48 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

### Q48: Which states or regions generate the highest sales revenue for us?
- **Business Goal:** Regional market penetration analysis.
- **Status:** `failed` (172.22s)
**Output:**

No result

---

### Q49: How many active buyers do we have in Maharashtra versus Gujarat?
- **Business Goal:** Comparative customer base sizing across primary territories.
- **Status:** `success` (17.96s)
```sql
SELECT 
  s.name AS state_name, 
  COUNT(DISTINCT p.id) AS active_buyers
FROM 
  party p
  JOIN states s ON p.state_id = s.id
WHERE 
  p.status = 'Y' AND p.deleted_at IS NULL AND p.profile_type = 'Party'
GROUP BY 
  s.name
HAVING 
  s.name IN ('Maharashtra', 'Gujarat')
```

**Output:**

SQL Query Executed: `SELECT 
  s.name AS state_name, 
  COUNT(DISTINCT p.id) AS active_buyers
FROM 
  party p
  JOIN states s ON p.state_id = s.id
WHERE 
  p.status = 'Y' AND p.deleted_at IS NULL AND p.profile_type = 'Party'
GROUP BY 
  s.name
HAVING 
  s.name IN ('Maharashtra', 'Gujarat')`

| state_name | active_buyers |
| --- | --- |
| Gujarat | 38 |
| Maharashtra | 56 |

---

### Q50: What is the breakdown of our customer base by city?
- **Business Goal:** Urban distribution footprint and sales territory planning.
- **Status:** `success` (71.39s)
```sql
SELECT 
  p.city AS customer_city,
  COUNT(p.id) AS number_of_customers
FROM 
  party p
WHERE 
  p.profile_type = 'Party' AND
  p.deleted_at IS NULL
GROUP BY 
  p.city
ORDER BY 
  number_of_customers DESC
LIMIT 20
```

**Output:**

SQL Query Executed: `SELECT 
  p.city AS customer_city,
  COUNT(p.id) AS number_of_customers
FROM 
  party p
WHERE 
  p.profile_type = 'Party' AND
  p.deleted_at IS NULL
GROUP BY 
  p.city
ORDER BY 
  number_of_customers DESC
LIMIT 20`

| customer_city | number_of_customers |
| --- | --- |
| Pune | 308 |
| Rajkot | 182 |
| AHMEDABAD | 85 |
| Bangalore | 63 |
|  | 55 |
| MUMBAI | 53 |
| AURANGABAD | 38 |
| Surat | 34 |
| FARIDABAD | 33 |
| DELHI | 27 |

_Showing 10 of 20 rows (result too large to display in full). Narrow your question (add a filter, date range, or LIMIT) to see a different slice._

---

