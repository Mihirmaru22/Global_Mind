# 🗣️ 50 Pure Layman Business Benchmark Questions

A benchmark suite of **50 distinct, zero-jargon business questions**. These represent natural language queries asked by business owners, sales heads, plant managers, warehouse supervisors, and accountants without any knowledge of database schemas or technical terminology.

---

### 💼 Sales Performance & Customer Trends
1. **"Who bought the most goods from us this year?"**
   * *Business Goal:* Identify top revenue-generating customers in the active financial year.

2. **"Which buyers haven't placed an order with us in the last three months?"**
   * *Business Goal:* Spot churned or inactive clients needing sales re-engagement.

3. **"What was our single biggest order by total value?"**
   * *Business Goal:* Find the highest revenue sales order on record.

4. **"How many total orders did we receive this month?"**
   * *Business Goal:* Monitor short-term sales volume velocity.

5. **"Which customers usually order in the largest bulk quantities?"**
   * *Business Goal:* Identify high-volume buyers for volume-discount negotiations.

6. **"Can you show a monthly breakdown of our sales revenue for this year?"**
   * *Business Goal:* Track month-over-month revenue growth trends.

---

### 🎯 Sales Inquiries & Lead Pipeline
7. **"How many potential clients are currently waiting for our follow-up?"**
   * *Business Goal:* Measure active pipeline leads (`Pending` / `In-Progress`).

8. **"Where do most of our successful deals come from?"**
   * *Business Goal:* Evaluate ROI across lead sources (Website, Social Media, Referrals, Sales Reps).

9. **"Which sales executive converted the most leads into actual customers?"**
   * *Business Goal:* Rank sales team performance by successful conversions.

10. **"How many customer inquiries got rejected or lost recently?"**
    * *Business Goal:* Review lost deal volume and failure reasons.

11. **"Are there any open prospects that came in through social media?"**
    * *Business Goal:* Filter digital marketing inbound leads.

12. **"What percentage of our total inquiries end up closing successfully?"**
    * *Business Goal:* Calculate the overall lead-to-win conversion rate.

---

### 📦 Warehouse & Inventory Management
13. **"What products are currently running dangerously low on stock?"**
    * *Business Goal:* Identify items nearing stockout or below safety thresholds.

14. **"How much total inventory is sitting in the warehouse right now?"**
    * *Business Goal:* Calculate aggregate on-hand stock valuation and units.

15. **"Are there any packed cartons in the warehouse waiting for manager verification?"**
    * *Business Goal:* Flag pending QA/verification bottleneck cartons (`carton_verify_status = 'P'`).

16. **"Which items have been lying in storage for the longest time without moving?"**
    * *Business Goal:* Detect dead stock or slow-moving finished goods.

17. **"How many cartons were shipped out of the warehouse this week?"**
    * *Business Goal:* Measure outbound warehouse dispatch throughput.

18. **"Do we have any recorded stock adjustment write-offs this month?"**
    * *Business Goal:* Audit physical stock reconciliation adjustments.

---

### 🏭 Plant Floor & Production Output
19. **"Which factory machines produced the highest output this month?"**
    * *Business Goal:* Evaluate machinery productivity and utilization.

20. **"Did any manufacturing batch fail to hit its original planned target?"**
    * *Business Goal:* Identify production shortfalls (`actual_production < planned_production`).

21. **"How much finished product did the factory complete over the past week?"**
    * *Business Goal:* Track short-term factory manufacturing yield.

22. **"Which machine had the lowest production or highest downtime?"**
    * *Business Goal:* Pinpoint underperforming or maintenance-heavy equipment.

23. **"What is the total quantity produced across all job orders this year?"**
    * *Business Goal:* Annual manufacturing output milestone tracking.

24. **"What is the average output volume per manufacturing batch?"**
    * *Business Goal:* Benchmark standard batch production size.

---

### 🛒 Purchasing & Supplier Expenditure
25. **"Which suppliers did we pay the most money to this year?"**
    * *Business Goal:* Analyze top vendor spend and supplier concentration risk.

26. **"How much raw material did we buy from vendors last month?"**
    * *Business Goal:* Track monthly raw material procurement expense.

27. **"Who is our primary supplier for packaging materials?"**
    * *Business Goal:* Identify vendor dependency for packaging items.

28. **"What is our average monthly spending on supplier purchases?"**
    * *Business Goal:* Establish procurement budget baseline.

29. **"Which raw material items account for the biggest chunk of our purchase expenses?"**
    * *Business Goal:* Pareto analysis (80/20 rule) of purchase spend by material.

30. **"How many purchase shipments did we receive from vendors this quarter?"**
    * *Business Goal:* Track inbound logistics and supplier delivery frequency.

---

### 🚚 Shipping, Logistics & Dispatch
31. **"Which transport agency handles the bulk of our product deliveries?"**
    * *Business Goal:* Logistics partner performance and freight volume share.

32. **"Which clients received the most deliveries over the last 30 days?"**
    * *Business Goal:* Identify most active distribution destinations.

33. **"What delivery vehicles are most commonly used for our shipments?"**
    * *Business Goal:* Vehicle fleet utilization and freight capacity planning.

34. **"How many delivery notes/challans were created today?"**
    * *Business Goal:* Daily dispatch activity snapshot.

35. **"How much finished product did the factory complete over the past week?."**
    * *Business Goal:* Outbound delivery tracking for customer service inquiries.

36. **"Which drivers handled the highest number of delivery runs recently?"**
    * *Business Goal:* Driver trip allocation and workload balancing.

---

### 💰 Billing, Invoicing & Taxes
37. **"How much total GST tax did we collect on proforma bills this year?"**
    * *Business Goal:* Tax liability estimation from generated proforma invoices.

38. **"Which clients have the highest billed amounts on proforma invoices?"**
    * *Business Goal:* Top billed clients summary.

39. **"Can you show our total revenue before taxes versus after taxes for this year?"**
    * *Business Goal:* Gross revenue vs. net billing comparison.

40. **"Which customers currently have an active opening balance on their accounts?"**
    * *Business Goal:* Accounts receivable legacy balance review.

41. **"What was our highest value proforma bill generated this month?"**
    * *Business Goal:* Flag major monthly billing milestones.

42. **"How many formal quotations did we send to clients this quarter?"**
    * *Business Goal:* Quotation pipeline volume before conversion into orders.

---

### 🏷️ Product Catalog, Pricing & Master Data
43. **"What are our top 5 most expensive finished goods per unit?"**
    * *Business Goal:* Premium product line pricing visibility.

44. **"Which product category has the largest variety of items?"**
    * *Business Goal:* Master catalog depth and category diversification.

45. **"Which products require a high minimum purchase quantity (MOQ)?"**
    * *Business Goal:* Identify bulk-only commercial items (`moq > threshold`).

46. **"How many items are finished goods versus raw materials in our catalog?"**
    * *Business Goal:* Master product catalog segmentation breakdown.

47. **"Are there any products marked as inactive or disabled in our system?"**
    * *Business Goal:* Catalog hygiene check (`product.status = 'N'`).

---

### 🗺️ Geographic & Regional Distribution
48. **"Which states or regions generate the highest sales revenue for us?"**
    * *Business Goal:* Regional market penetration analysis.

49. **"How many active buyers do we have in Maharashtra versus Gujarat?"**
    * *Business Goal:* Comparative customer base sizing across primary territories.

50. **"What is the breakdown of our customer base by city?"**
    * *Business Goal:* Urban distribution footprint and sales territory planning.
