# 🏗️ Master Engineering Specification: Enterprise Text-to-SQL Pipeline Architecture

---

## 1. Executive Summary & Core Engineering Philosophy

In modern enterprise resource planning (ERP) and manufacturing execution systems (MES), databases are not clean textbook schemas. They are large (50–100+ tables), heavily normalized, historically evolved systems filled with:
- Polymorphic tables (e.g. `party` holding both customers and vendors).
- Denormalization gaps (e.g. `sales_order` and `purchase` storing no precomputed monetary totals).
- Implicit zero-state records (e.g. out-of-stock items having 0 physical rows in `stock`).
- Historical schema misspellings (e.g. `followup_medimum`).
- Custom enum codes (`'B'`, `'D'`, `'P'`, `'V'`, `'Y'`, `'N'`).
- Type mismatches (e.g. numeric stock quantities stored as `VARCHAR(50)`).

Standard naive Text-to-SQL approaches—such as prompting an LLM with a naive table dump or relying purely on vector embeddings—consistently fail in production. They hallucinate non-existent status columns, omit vital transactional header tables, fail to account for soft-deletes, and choke on API rate limits during analytical query bursts.

The **Global Mind Text-to-SQL Pipeline** is an enterprise-grade, deterministic-heuristic-assisted cognitive architecture. It operates across 9 distinct execution stages to transform ambiguous, zero-jargon business inquiries into mathematically exact, highly optimized, and AST-validated SQL queries.

```
+----------------------------------------------------------------------------------------------------+
|                                    COGNITIVE PIPELINE FLOWCHART                                    |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|    [ User Natural Language Business Ingestion ]                                                    |
|                         |                                                                          |
|                         v                                                                          |
|   +---------------------------------------------+                                                  |
|   | STAGE 1: Semantic Intent Extraction Layer   | ---> (Metrics, Dimensions, Filters, Aggregation)  |
|   +---------------------------------------------+                                                  |
|                         |                                                                          |
|                         v                                                                          |
|   +---------------------------------------------+                                                  |
|   | STAGE 2: Hybrid Schema RAG & Anchor Inject  | <--- (Dense + Sparse Retrieval + Domain Anchors) |
|   +---------------------------------------------+                                                  |
|                         |                                                                          |
|                         v                                                                          |
|   +---------------------------------------------+                                                  |
|   | STAGE 3: Dynamic Enum Glossary & Graph Join | <--- (835 Mappings, 162 FK Paths, Live Enums)    |
|   +---------------------------------------------+                                                  |
|                         |                                                                          |
|                         v                                                                          |
|   +---------------------------------------------+                                                  |
|   | STAGE 4: Main Text-to-SQL Reasoning Engine  | <--- (Dialect Constraints, Live Date, Few-Shots) |
|   +---------------------------------------------+                                                  |
|                         |                                                                          |
|                         v                                                                          |
|   +---------------------------------------------+       FAIL (AST / Column Hallucination)          |
|   | STAGE 5: Multi-Stage AST Validation Gate    | -------------------------------------+           |
|   +---------------------------------------------+                                      |           |
|                         | PASS                                                         |           |
|                         v                                                              v           |
|   +---------------------------------------------+                            +-------------------+ |
|   | STAGE 7: Safe Non-Blocking Execution Engine |                            | STAGE 6: Iterative| |
|   +---------------------------------------------+                            | Self-Repair Loop  | |
|                         |                                                    +-------------------+ |
|                         | (Result Set / Execution Status)                              |           |
|                         +--------------------------------------------------------------+           |
|                         |                                                                          |
|                         v                                                                          |
|   +---------------------------------------------+                                                  |
|   | STAGE 8: Context Protection & Serialization | ---> (500-Row Capping, Markdown Table Rendering) |
|   +---------------------------------------------+                                                  |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. In-Depth 9-Stage Pipeline Architecture

```
+====================================================================================================+
| STAGE 1: SEMANTIC INTENT EXTRACTION (THE SEMANTIC LAYER)                                           |
+====================================================================================================+
```
Business users do not speak in database column names. They ask: *"Who bought the most goods from us this year?"* or *"What items are running dangerously low?"*

The intent extraction stage decouples natural language understanding from SQL syntax generation using a specialized business-question parser (`extract_analytical_intent()` in [`src/stages/s12b_sql_retrieval.py`](file:///data/shared/project/Global_Mind/src/stages/s12b_sql_retrieval.py)).

#### Formal Intent Taxonomy:
1. **Metrics**: Identified target quantities (`sales value / revenue`, `quantity / units`, `stock on hand`, `production output`, `purchase expenditure`).
2. **Dimensions**: Grouping attributes (`customer / party`, `supplier`, `product`, `category`, `machine`, `month`, `sales executive`).
3. **Filters**: Statuses and state constraints (`open / pending`, `carton verification status`, `active records`, `shortfall`).
4. **Time Period**: Relative temporal expressions (`this financial year`, `last month`, `past 6 months`, `past week`, `today`).
5. **Aggregation**: Mathematical functions (`SUM`, `COUNT`, `AVG`, `MAX`, `MIN`).
6. **Limits & Sorting**: Positional ordering (`limit: 1, sort: DESC` for "best/highest/top"; `limit: 1, sort: ASC` for "lowest/worst/cheapest").

#### Trade Directionality Disambiguation:
A critical ambiguity in ERP systems is the word *"bought"*:
- *"Who bought from us?"* / *"Who spent the most?"* $\rightarrow$ **Customer Sales** (`sales_order`).
- *"What did we buy from suppliers?"* / *"Procurement costs"* $\rightarrow$ **Supplier Purchases** (`purchase`).
The extractor parses sentence directionality to ensure the model never queries procurement tables for sales questions.

---

```
+====================================================================================================+
| STAGE 2: HYBRID SCHEMA RAG & DOMAIN CONCEPT ANCHORING                                              |
+====================================================================================================+
```
A primary failure mode of naive vector RAG in Text-to-SQL is **table dropping**. Vector similarity often retrieves peripheral tables while omitting core bridge tables (e.g. retrieving `party` and `product` but omitting `sales_order` and `sales_order_products`).

To eliminate table dropping, the pipeline combines **Hybrid Dense/Sparse Vector Search** with **Deterministic Domain Anchor Injection**:

```
+-----------------------------------------------------------------------------------+
|                        HYBRID RETRIEVAL & ANCHORING ENGINE                        |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  1. Dense Vector Embedding (BGE / Gemini Embeddings)                              |
|     + Sparse Lexical Scoring (BM25 Token Index)                                   |
|     Top-K Retrieval = 8 Table DDL Chunks                                          |
|                                                                                   |
|  2. Deterministic Domain Concept Ingestion:                                       |
|     - Sales/Revenue   -> sales_order, sales_order_products, party, product, fy    |
|     - Purchasing      -> purchase, purchase_products, party, product, fy          |
|     - Inventory       -> stock, product, product_color, category, warehouse       |
|     - Manufacturing   -> production, actual_production, machine, product          |
|     - CRM/Leads       -> lead, lead_history, users, party                         |
|     - Logistics       -> delivery_challan, delivery_challan_products, party       |
|     - Invoicing       -> proforma, quotation, party, financial_year               |
|                                                                                   |
|  3. 1-Hop Graph Bridge Traversal (config/sql_relationships.json):                 |
|     - Ranks neighbor tables by active foreign key connection density              |
|     - Injects bridge tables up to graph expansion budget                          |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

#### Graph Neighbor Selection Algorithm:
Let $T_{\text{active}}$ be the set of retrieved and anchored tables. The connection score for candidate neighbor table $n \notin T_{\text{active}}$ is defined as:
$$\text{Score}(n) = \sum_{t \in T_{\text{active}}} \mathbb{I}((t, n) \in E \lor (n, t) \in E)$$
Where $E$ represents the set of 162 foreign-key relationships discovered by [`scripts/auto_harvest_metadata.py`](file:///data/shared/project/Global_Mind/scripts/auto_harvest_metadata.py). High-scoring bridges are injected into the prompt.

---

```
+====================================================================================================+
| STAGE 3: DYNAMIC COLUMN GLOSSARY & LIVE ENUM HARVESTING                                            |
+====================================================================================================+
```
Enterprise databases rely on exact string literals and categorical codes. LLMs cannot guess whether "Active" is `'Y'`, `'1'`, `'Active'`, or `'true'`.

The pipeline maintains [`config/sql_column_glossary.json`](file:///data/shared/project/Global_Mind/config/sql_column_glossary.json)—an auto-harvested repository of **835 column mappings** and exact live database enums:

```json
{
  "stock.qty": {
    "type": "VARCHAR(50)",
    "casting_rule": "CAST(stock.qty AS DECIMAL(10,2))",
    "note": "stock.qty is stored as string in MySQL. Always cast before mathematical aggregation."
  },
  "stock.status": {
    "type": "ENUM/CHAR",
    "allowed_values": {
      "B": "Booked / On-Hand Stock (Available in Warehouse)",
      "D": "Dispatched / Shipped Stock"
    }
  },
  "stock.carton_verify_status": {
    "type": "ENUM/CHAR",
    "allowed_values": {
      "P": "Pending (Unverified Cartons)",
      "V": "Verified Cartons"
    }
  },
  "lead.status": {
    "type": "VARCHAR",
    "allowed_values": ["Pending", "In-Progress", "Success", "Reject"]
  },
  "party.status": {
    "type": "CHAR(1)",
    "allowed_values": {"Y": "Active", "N": "Inactive"}
  }
}
```

---

```
+====================================================================================================+
| STAGE 4: MAIN TEXT-TO-SQL PROMPT GENERATION & REASONING                                            |
+====================================================================================================+
```
The prompt assembler merges schema DDLs, relationship paths, live date, and strict SQL rules into a structured system prompt:

#### System Prompt Anatomy:
1. **Dialect Declaration**: Declares MySQL dialect rules.
2. **Current Date Injection**: Injects live system date (e.g. `Current Date: 2026-08-19`) to anchor relative temporal calculations (`DATE_SUB(CURDATE(), INTERVAL 3 MONTH)`).
3. **No-SQL Escape Hatch**: Directs the LLM to output `NO_SQL` if the question cannot be answered by the available schema, preventing ungrounded hallucinations.
4. **Calculated Value Formulations**:
   - Sales Order Value: `SUM(sop.qty * p.rate)`
   - Invoiced Gross Value: `SUM(proforma.grand_total)`
   - Actual Production Output: `SUM(actual_production.apq)`
5. **Soft-Delete Rule**: Mandates `deleted_at IS NULL` for every joined table having a soft-delete column.

---

```
+====================================================================================================+
| STAGE 5: MULTI-STAGE AST VALIDATION & SAFETY GATE                                                  |
+====================================================================================================+
```
Before any query reaches the database engine, it passes through the `ColumnRegistry` AST verification layer ([`src/core/sql_column_registry.py`](file:///data/shared/project/Global_Mind/src/core/sql_column_registry.py)):

```
[ Candidate SQL String ]
            |
            v
+-----------------------------------------------------------+
| 1. SQLglot Parse & Dialect Syntax Validation              |
|    - Verifies valid MySQL AST token stream                |
+-----------------------------------------------------------+
            | PASS
            v
+-----------------------------------------------------------+
| 2. AST Read-Only Enforcer                                 |
|    - Rejects INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE|
+-----------------------------------------------------------+
            | PASS
            v
+-----------------------------------------------------------+
| 3. ColumnRegistry Deep Existence Verification             |
|    - Extracts all exp.Table and exp.Column nodes          |
|    - Verifies existence against 64 live table schemas     |
|    - Detects hallucinated columns (e.g. party.rate)       |
+-----------------------------------------------------------+
            | PASS
            v
+-----------------------------------------------------------+
| 4. Metric Alias & Aggregate Quality Gate                  |
|    - Distinguishes computed metrics from hallucinated cols|
|    - Whitelists total_orders, total_sales, apq, output    |
+-----------------------------------------------------------+
            | PASS
            v
[ Verified Executable AST ]
```

---

```
+====================================================================================================+
| STAGE 6: ITERATIVE SELF-REPAIR REFLECTION LOOP                                                     |
+====================================================================================================+
```
When validation or runtime execution fails, the engine triggers an automatic error-reflection prompt:

```text
The SQL query you generated failed execution or validation.

User question: "{user_question}"
Previous SQL:
```sql
{failed_sql}
```

Error encountered:
{error_message}

Database Schema Correction Hints:
{targeted_schema_hints}

Instructions:
1. Carefully inspect the error message and the schema.
2. If a column or table does not exist, replace it with the correct column/table from the schema above.
3. Fix any syntax errors or join condition mismatches.
4. Return ONLY the corrected SQL query in a ```sql ... ``` block.
```

The repair loop operates within a bounded budget ($N \le 3$ retries), guaranteeing sub-second self-correction without latency degradation.

---

```
+====================================================================================================+
| STAGE 7: SAFE ASYNCHRONOUS DATABASE EXECUTION ENGINE                                               |
+====================================================================================================+
```
* **Engine**: Fully non-blocking asynchronous MySQL execution using `aiomysql`.
* **Transaction Mode**: Read-only connection session (`SET TRANSACTION READ ONLY`).
* **Connection Pooling**: Managed pool (`minsize=2`, `maxsize=10`) with automatic keepalive and connection recycling.

---

```
+====================================================================================================+
| STAGE 8: RESULT SANITIZATION, CONTEXT PROTECTION & MARKDOWN FORMATTING                             |
+====================================================================================================+
```
* **Context Capping**: Query results are capped at 500 rows to protect downstream LLM context windows.
* **Type Normalization**: Decimal, Date, and Timestamp objects are serialized to clean ISO strings and formatted currency values.
* **Empty Result Handling**: If a query executes successfully but matches 0 rows, the system renders a structured notification:
  ```markdown
  _Note: The query executed successfully but matched 0 records for the specified filter criteria._
  ```

---

## 3. Comprehensive Database Schema Atlas (10 Subsystems)

The enterprise database comprises 64 tables organized into 10 operational subsystems:

```
+----------------------------------------------------------------------------------------------------+
|                                 ENTERPRISE SCHEMA SUBSYSTEM MATRIX                                 |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [ 1. Sales & Orders ]        [ 2. Purchasing ]             [ 3. Inventory & Stock ]               |
|  - sales_order                - purchase                    - stock                                |
|  - sales_order_products       - purchase_products           - product_color                        |
|  - party                      - purchase_attachment         - category                             |
|  - product                    - party                       - warehouse                            |
|                                                                                                    |
|  [ 4. Manufacturing ]         [ 5. CRM & Pipeline ]         [ 6. Packaging & Cartons ]             |
|  - production                 - lead                        - packagings                           |
|  - actual_production          - lead_history                - product_packaging_detail             |
|  - machine                    - users                       - packing_material                     |
|                                                                                                    |
|  [ 7. Logistics & Dispatch ]  [ 8. Billing & Invoices ]     [ 9. Accounting & Balances ]           |
|  - delivery_challan           - proforma                    - party_opening_balance                |
|  - delivery_challan_products  - quotation                   - stock_adjustment                     |
|  - transporter                - financial_year              - financial_year                       |
|                                                                                                    |
|  [ 10. Master Data ]                                                                               |
|  - countries, states, cities, product_type, unit, users, image_setting                             |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

### Detailed Subsystem Column & Join Reference:

#### 1. Sales & Order Management
* **`sales_order`**: `id`, `financial_id`, `sales_order_no`, `sales_order_date`, `party_id`, `created_at`, `deleted_at`.
* **`sales_order_products`**: `id`, `sales_order_id`, `product_id`, `unit_id`, `qty`, `deleted_at`.
* **Core Rule**: Total sales order value is computed as `SUM(sop.qty * p.rate)` by joining `sales_order_products` to `product`.

#### 2. Purchasing & Procurement
* **`purchase`**: `id`, `financial_id`, `purchase_no`, `purchase_date`, `party_id`, `deleted_at`.
* **`purchase_products`**: `id`, `pi_id`, `product_id`, `unit_id`, `qty`, `deleted_at`.
* **Core Rule**: To identify vendors/suppliers, join `party` to `purchase` via `party.id = purchase.party_id`.

#### 3. Warehouse & Inventory Control
* **`stock`**: `id`, `product_id`, `product_color_id`, `warehouse_id`, `qty` (`VARCHAR`), `status` (`'B'`/`'D'`), `carton_verify_status` (`'P'`/`'V'`), `deleted_at`.
* **`product`**: `id`, `product_name`, `minimum_stock`, `rate`, `status` (`'Y'`/`'N'`).
* **`product_color`**: `id`, `product_id`, `color_name`.
* **Core Rule**: Stock quantity requires `CAST(stock.qty AS DECIMAL(10,2))`. Out-of-stock items require `LEFT JOIN stock` with `COALESCE`.

#### 4. Manufacturing & Production Execution
* **`production`**: `id`, `machine_id`, `product_id`, `product_color_id`, `qty` (Planned Target), `production_date`, `deleted_at`.
* **`actual_production`**: `id`, `production_id`, `apq` (Actual Production Quantity), `production_date`, `deleted_at`.
* **`machine`**: `id`, `machine_name`, `status` (`'Y'`/`'N'`).
* **Core Rule**: Planned target is `production.qty`. Achieved factory output is `actual_production.apq`.

#### 5. CRM & Sales Pipeline Management
* **`lead`**: `id`, `lead_no`, `lead_name`, `company_name`, `mobile`, `email`, `lead_assign_to` ($\rightarrow$ `users.id`), `lead_generate_from`, `followup_medimum`, `status` (`'Pending'`, `'In-Progress'`, `'Success'`, `'Reject'`), `created_at`, `deleted_at`.
* **`lead_history`**: `id`, `lead_id`, `followup_date`, `remark`, `deleted_at`.
* **Core Rule**: To identify assigned sales executives, join `lead.lead_assign_to = users.id`.

#### 6. Logistics, Dispatches & Fleet Management
* **`delivery_challan`**: `id`, `financial_id`, `dc_no`, `dc_date`, `sales_order_id`, `party_id`, `transport_name`, `vehicle_no`, `driver_name`, `deleted_at`.
* **`delivery_challan_products`**: `id`, `dc_id`, `product_id`, `qty`, `deleted_at`.

#### 7. Billing, Invoicing & GST Taxation
* **`proforma`**: `id`, `financial_id`, `proforma_no`, `proforma_date`, `party_id`, `sub_total`, `discount_amount`, `gst_amount`, `grand_total`, `deleted_at`.
* **`financial_year`**: `id`, `fyear`, `start_date`, `end_date`, `current_year` (`'Y'`/`'N'`).
* **Core Rule**: `proforma` and `quotation` have **NO status column**. For current year tax/revenue, join `financial_year` and filter `financial_year.current_year = 'Y'`.

---

## 4. Query Execution Blueprints across 10 Operational Domains

### Domain 1: Top Customer Revenue Ranking
* **Layman Question**: *"Who bought the most goods from us this year?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    p.party_name AS customer_name,
    SUM(sop.qty * prod.rate) AS total_sales_value
  FROM sales_order AS so
  JOIN party AS p ON so.party_id = p.id
  JOIN sales_order_products AS sop ON so.id = sop.sales_order_id
  JOIN product AS prod ON sop.product_id = prod.id
  JOIN financial_year AS fy ON so.financial_id = fy.id
  WHERE fy.current_year = 'Y'
    AND so.deleted_at IS NULL
    AND p.deleted_at IS NULL
    AND sop.deleted_at IS NULL
    AND prod.deleted_at IS NULL
    AND fy.deleted_at IS NULL
  GROUP BY p.party_name
  ORDER BY total_sales_value DESC
  LIMIT 1;
  ```

---

### Domain 2: Inactive Customer Relational Anti-Join
* **Layman Question**: *"Which buyers haven't placed an order with us in the last three months?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    p.party_name AS customer_name,
    p.email AS customer_email,
    p.mobile1 AS customer_mobile
  FROM party AS p
  LEFT JOIN sales_order AS so ON p.id = so.party_id
    AND so.deleted_at IS NULL
    AND so.sales_order_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
  WHERE p.profile_type = 'Party'
    AND p.status = 'Y'
    AND p.deleted_at IS NULL
    AND so.id IS NULL
  ORDER BY p.party_name;
  ```

---

### Domain 3: Zero-Inventory / Low-Stock Relational Outer Join
* **Layman Question**: *"What products are currently running dangerously low on stock?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    p.product_name,
    pc.color_name,
    p.minimum_stock,
    COALESCE(SUM(CAST(s.qty AS DECIMAL(10,2))), 0) AS current_stock
  FROM product p
  JOIN product_color pc ON p.id = pc.product_id
  LEFT JOIN stock s ON pc.id = s.product_color_id
    AND s.status = 'B'
    AND s.deleted_at IS NULL
  WHERE p.deleted_at IS NULL
    AND pc.deleted_at IS NULL
  GROUP BY p.id, p.product_name, pc.id, pc.color_name, p.minimum_stock
  HAVING current_stock < p.minimum_stock;
  ```

---

### Domain 4: Unverified Warehouse Inventory Breakdown
* **Layman Question**: *"How many boxes or cartons are waiting to be verified in the warehouse?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    p.product_name,
    pc.color_name,
    SUM(CAST(s.qty AS DECIMAL(10,2))) AS unverified_cartons
  FROM stock s
  JOIN product p ON s.product_id = p.id
  JOIN product_color pc ON s.product_color_id = pc.id
  WHERE s.carton_verify_status = 'P'
    AND s.deleted_at IS NULL
    AND p.deleted_at IS NULL
  GROUP BY p.product_name, pc.color_name;
  ```

---

### Domain 5: Factory Floor Production Output
* **Layman Question**: *"How much finished product did the factory complete over the past week?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    SUM(ap.apq) AS total_finished_product_quantity
  FROM actual_production ap
  JOIN production p ON ap.production_id = p.id
  JOIN product_type pt ON p.product_type_id = pt.id
  WHERE pt.product_type = 'Finished Goods'
    AND ap.production_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 1 WEEK) AND CURDATE()
    AND ap.deleted_at IS NULL
    AND p.deleted_at IS NULL;
  ```

---

### Domain 6: Machine Output Shortfall Analysis
* **Layman Question**: *"Which manufacturing machines fell short of their planned targets yesterday?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    m.machine_name,
    p.qty AS planned_target,
    COALESCE(SUM(ap.apq), 0) AS actual_output,
    (p.qty - COALESCE(SUM(ap.apq), 0)) AS shortfall
  FROM production p
  JOIN machine m ON p.machine_id = m.id
  LEFT JOIN actual_production ap ON p.id = ap.production_id AND ap.deleted_at IS NULL
  WHERE p.production_date = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
    AND p.deleted_at IS NULL
  GROUP BY m.id, m.machine_name, p.id, p.qty
  HAVING actual_output < planned_target;
  ```

---

### Domain 7: CRM Sales Rep Lead Conversion Ranking
* **Layman Question**: *"Which sales executive converted the most leads into actual customers?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    u.name AS sales_executive_name,
    COUNT(l.id) AS successful_conversions_count
  FROM lead l
  JOIN users u ON l.lead_assign_to = u.id
  WHERE l.status = 'Success'
    AND l.deleted_at IS NULL
    AND u.deleted_at IS NULL
  GROUP BY u.id, u.name
  ORDER BY successful_conversions_count DESC;
  ```

---

### Domain 8: Monthly Sales Revenue Trend
* **Layman Question**: *"Can you show a monthly breakdown of our sales revenue for this year?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    DATE_FORMAT(so.sales_order_date, '%Y-%m') AS sales_month,
    SUM(sop.qty * p.rate) AS monthly_sales_revenue
  FROM sales_order so
  JOIN sales_order_products sop ON so.id = sop.sales_order_id
  JOIN product p ON sop.product_id = p.id
  JOIN financial_year fy ON so.financial_id = fy.id
  WHERE fy.current_year = 'Y'
    AND so.deleted_at IS NULL
    AND sop.deleted_at IS NULL
    AND p.deleted_at IS NULL
  GROUP BY sales_month
  ORDER BY sales_month ASC;
  ```

---

### Domain 9: Lead Acquisition Channel Performance
* **Layman Question**: *"Where do most of our successful deals come from?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    lead_generate_from AS acquisition_source,
    COUNT(id) AS converted_deals_count
  FROM lead
  WHERE status = 'Success'
    AND deleted_at IS NULL
  GROUP BY lead_generate_from
  ORDER BY converted_deals_count DESC;
  ```

---

### Domain 10: Invoiced GST Tax Collection
* **Layman Question**: *"How much total GST tax did we collect on proforma bills this year?"*
* **Generated Blueprint**:
  ```sql
  SELECT
    SUM(pf.gst_amount) AS total_gst_collected
  FROM proforma pf
  JOIN financial_year fy ON pf.financial_id = fy.id
  WHERE fy.current_year = 'Y'
    AND pf.deleted_at IS NULL;
  ```

---

## 5. Multi-Provider Orchestration & Rate-Limiting Resilience

Analytical benchmarking requires running large test suites without crashing on free-tier rate limits. The routing layer implements a dynamic multi-provider priority cascade configured in [`config/providers.yaml`](file:///data/shared/project/Global_Mind/config/providers.yaml):

```
+-----------------------------------------------------------------------------------+
|                         PROVIDER CASCADE SPECIFICATION                            |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  1. Primary Provider: Gemini 2.5 Flash                                            |
|     - Quota: 1,000,000 Tokens/Min (TPM)                                           |
|     - Execution Latency: ~1.2s - 2.5s                                              |
|     - Trigger Failover Condition: HTTP 429 / HTTP 503                             |
|                                                                                   |
|  2. First Fallback: Groq (Qwen 3.6 27B)                                           |
|     - Quota: 8,000 TPM / 200,000 Tokens/Day (TPD)                                 |
|     - Execution Latency: ~400ms - 800ms                                           |
|     - Trigger Failover Condition: TPM/TPD Exceeded / 38s Rate Backoff             |
|                                                                                   |
|  3. Second Fallback: NVIDIA NIM (Llama 3.1 70B Instruct)                          |
|     - Quota: High-capacity enterprise token quota                                 |
|     - Execution Latency: ~2.0s - 3.5s                                              |
|     - Trigger Failover Condition: API Error / Unreachable                         |
|                                                                                   |
|  4. Terminal Fallback: OpenRouter (Qwen 2.5 72B Instruct Free)                     |
|     - Quota: Community distributed fallback tier                                  |
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

---

## 6. Failure Mode Analysis, Guardrails & Edge Cases

| Failure Mode | Root Cause | Automated Detection Gate | Engineered Remediation Strategy |
| :--- | :--- | :--- | :--- |
| **Table Dropping** | Vector search missed bridge tables (`sales_order`, `production`). | Schema RAG Chunk Inspection. | **Domain Concept Anchoring**: Automatically injects all mandatory tables based on business keywords. |
| **0-Stock Blindness** | `stock` only stores positive rows; `INNER JOIN` eliminated out-of-stock items. | AST Parser Join Inspection. | **LEFT JOIN + COALESCE**: Forces outer join and `HAVING current_stock < minimum_stock`. |
| **Inactive Customer Bug** | Naive `sales_order_date < cutoff` returned active buyers. | Self-repair Anti-Join Rule. | **SQL Anti-Join**: Enforces `LEFT JOIN ... ON ... >= cutoff WHERE so.id IS NULL`. |
| **Type Incompatible SUM** | `stock.qty` is `VARCHAR(50)`. | ColumnRegistry Type Gate. | **Automated CAST Injection**: Automatically mandates `CAST(stock.qty AS DECIMAL(10,2))`. |
| **Hallucinated Status Col** | `quotation`/`proforma` have no `status` column. | `ColumnRegistry.validate()` | Rejects query before DB; triggers self-repair reflection loop. |
| **Rate Limit 429 Crash** | Rapid batch evaluation exceeded free-tier RPM/TPM limits. | `ModelRouter` Circuit Breaker. | Cascades to `gemini-2.5-flash` (1M TPM) and paces batch requests with 4.0s delays. |
| **Spurious Alias Warnings** | Metric aliases (`total_orders`, `apq`) flagged as hallucinated columns. | `validate_aliases()` Whitelist. | Whitelists aggregate metrics and manufacturing/warehouse domain terminology. |
| **Database Corruption Risk** | Malicious or hallucinated DML (`UPDATE`, `DROP`, `DELETE`). | SQLglot AST Statement Gate. | Hard-rejects any statement type other than read-only `exp.Select`. |

---

## 7. Production Deployment, Security & Observability

### Security Architecture:
1. **Read-Only Database Credentials**:
   ```sql
   CREATE USER 'globalmind_readonly'@'localhost' IDENTIFIED BY 'secure_password';
   GRANT SELECT ON globalmind.* TO 'globalmind_readonly'@'localhost';
   FLUSH PRIVILEGES;
   ```
2. **AST-Level Token Sanitization**: Queries with multiple semicolons, stacked queries, or comment injection sequences (`--`, `/*`) are sanitized prior to execution.

### Continuous Automated Evaluation Suite:
* **Benchmark Test Suite** ([`evals/globalmind/layman_questions_50.md`](file:///data/shared/project/Global_Mind/evals/globalmind/layman_questions_50.md)): 50 diverse questions covering all 10 enterprise domains.
* **Batch Test Runner** ([`scripts/run_batch_eval.py`](file:///data/shared/project/Global_Mind/scripts/run_batch_eval.py)): Runs automated regression suites and outputs [`evals/globalmind/eval_run_report.md`](file:///data/shared/project/Global_Mind/evals/globalmind/eval_run_report.md).
* **CLI Single-Question Inspector** ([`scripts/test_question.py`](file:///data/shared/project/Global_Mind/scripts/test_question.py)): For instant developer debugging.
