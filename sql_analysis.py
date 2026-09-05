import pandas as pd
import numpy as np
import os

# ── LOAD DATA ──────────────────────────────────────────
data_path = r'C:\Users\kusha\Downloads\archive (2)'

orders      = pd.read_csv(os.path.join(data_path, 'olist_orders_dataset.csv'))
customers   = pd.read_csv(os.path.join(data_path, 'olist_customers_dataset.csv'))
items       = pd.read_csv(os.path.join(data_path, 'olist_order_items_dataset.csv'))
payments    = pd.read_csv(os.path.join(data_path, 'olist_order_payments_dataset.csv'))
products    = pd.read_csv(os.path.join(data_path, 'olist_products_dataset.csv'))
sellers     = pd.read_csv(os.path.join(data_path, 'olist_sellers_dataset.csv'))
translation = pd.read_csv(os.path.join(data_path, 'product_category_name_translation.csv'))

# ── CLEAN DATA ─────────────────────────────────────────
date_cols = ['order_purchase_timestamp','order_approved_at',
             'order_delivered_carrier_date','order_delivered_customer_date',
             'order_estimated_delivery_date']
for col in date_cols:
    orders[col] = pd.to_datetime(orders[col])

orders = orders.dropna(subset=['order_delivered_customer_date'])
orders['order_approved_at'] = orders['order_approved_at'].fillna(orders['order_purchase_timestamp'])
products = products.dropna(subset=['product_category_name'])

# ── MERGE ──────────────────────────────────────────────
products = products.merge(translation, on='product_category_name', how='left')
products['category'] = products['product_category_name_english'].fillna(products['product_category_name'])

df = orders.merge(customers, on='customer_id', how='left')
df = df.merge(items, on='order_id', how='left')

payments_agg = payments.groupby('order_id').agg(
    payment_value=('payment_value', 'sum'),
    payment_type=('payment_type', 'first')
).reset_index()
df = df.merge(payments_agg, on='order_id', how='left')
df = df.merge(products[['product_id','category']], on='product_id', how='left')
df = df.merge(sellers[['seller_id','seller_state']], on='seller_id', how='left')

# ── FEATURE ENGINEERING ────────────────────────────────
df['delivery_days'] = (df['order_delivered_customer_date'] - df['order_purchase_timestamp']).dt.days
df['is_late'] = (df['order_delivered_customer_date'] > df['order_estimated_delivery_date']).astype(int)
df['delivery_status'] = df['is_late'].map({0: 'On-Time', 1: 'Late'})
df['order_month'] = df['order_purchase_timestamp'].dt.to_period('M')
df = df[df['delivery_days'].between(0, 120)]
df = df[df['payment_value'] > 0]

# ── RFM SEGMENTATION ───────────────────────────────────
snapshot_date = df['order_purchase_timestamp'].max() + pd.Timedelta(days=1)
rfm = df.groupby('customer_unique_id').agg(
    Recency=('order_purchase_timestamp', lambda x: (snapshot_date - x.max()).days),
    Frequency=('order_id', 'nunique'),
    Monetary=('payment_value', 'sum')
).reset_index()

rfm['R_Score'] = pd.qcut(rfm['Recency'], 5, labels=[5,4,3,2,1])
rfm['F_Score'] = pd.qcut(rfm['Frequency'].rank(method='first'), 5, labels=[1,2,3,4,5])
rfm['M_Score'] = pd.qcut(rfm['Monetary'], 5, labels=[1,2,3,4,5])

def segment(row):
    r, f = int(row['R_Score']), int(row['F_Score'])
    if r >= 4 and f >= 4: return 'Champion'
    elif r >= 3 and f >= 3: return 'Loyal'
    elif r >= 3: return 'Potential'
    elif r == 2: return 'At Risk'
    else: return 'Lost'

rfm['Segment'] = rfm.apply(segment, axis=1)

# ── SAVE OUTPUTS ───────────────────────────────────────
rfm.to_csv(os.path.join(data_path, 'rfm_segments.csv'), index=False)

monthly_revenue = df.groupby('order_month').agg(
    total_revenue=('payment_value', 'sum'),
    total_orders=('order_id', 'nunique'),
    avg_order_value=('payment_value', 'mean')
).reset_index()
monthly_revenue['order_month'] = monthly_revenue['order_month'].astype(str)
monthly_revenue.to_csv(os.path.join(data_path, 'monthly_revenue.csv'), index=False)

delivery = df.groupby('customer_state').agg(
    avg_delivery_days=('delivery_days', 'mean'),
    late_rate=('is_late', 'mean'),
    total_orders=('order_id', 'nunique')
).reset_index()
delivery.to_csv(os.path.join(data_path, 'delivery_performance.csv'), index=False)

print("All outputs saved successfully!")

import sqlite3

# Load clean data into SQLite database
df = pd.read_csv(os.path.join(data_path, 'master_clean.csv'))
conn = sqlite3.connect(os.path.join(data_path, 'ecommerce.db'))
df.to_sql('orders', conn, if_exists='replace', index=False)
print("Data loaded into SQLite successfully")

# ── QUERY 1: Top 10 categories by revenue ────────────────────────
query1 = pd.read_sql("""
    SELECT 
        category,
        ROUND(SUM(payment_value), 2) AS total_revenue,
        COUNT(DISTINCT order_id) AS total_orders,
        ROUND(AVG(payment_value), 2) AS avg_order_value
    FROM orders
    GROUP BY category
    ORDER BY total_revenue DESC
    LIMIT 10
""", conn)

print("\n=== TOP 10 CATEGORIES BY REVENUE ===")
print(query1)

# ── QUERY 2: Delivery performance by state ───────────────────────
query2 = pd.read_sql("""
    SELECT 
        customer_state,
        ROUND(AVG(delivery_days), 2) AS avg_delivery_days,
        ROUND(AVG(is_late) * 100, 2) AS late_rate_pct,
        COUNT(DISTINCT order_id) AS total_orders
    FROM orders
    GROUP BY customer_state
    ORDER BY avg_delivery_days DESC
""", conn)

print("\n=== DELIVERY PERFORMANCE BY STATE ===")
print(query2)

# ── QUERY 3: Monthly revenue trend ───────────────────────────────
query3 = pd.read_sql("""
    SELECT 
        order_month,
        ROUND(SUM(payment_value), 2) AS monthly_revenue,
        COUNT(DISTINCT order_id) AS total_orders,
        ROUND(AVG(payment_value), 2) AS avg_order_value
    FROM orders
    GROUP BY order_month
    ORDER BY order_month
""", conn)

print("\n=== MONTHLY REVENUE TREND ===")
print(query3)

# ── QUERY 4: Late delivery rate by month (window function) ───────
query4 = pd.read_sql("""
    SELECT 
        order_month,
        COUNT(DISTINCT order_id) AS total_orders,
        SUM(is_late) AS late_orders,
        ROUND(SUM(is_late) * 100.0 / COUNT(DISTINCT order_id), 2) AS late_rate_pct,
        ROUND(AVG(SUM(is_late) * 100.0 / COUNT(DISTINCT order_id)) 
              OVER (ORDER BY order_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) 
              AS rolling_3m_late_rate
    FROM orders
    GROUP BY order_month
    ORDER BY order_month
""", conn)

print("\n=== LATE DELIVERY TREND WITH 3-MONTH ROLLING AVERAGE ===")
print(query4)

# ── QUERY 5: Customer segmentation summary ───────────────────────
query5 = pd.read_sql("""
    SELECT 
        customer_state,
        COUNT(DISTINCT customer_unique_id) AS unique_customers,
        ROUND(SUM(payment_value), 2) AS total_revenue,
        ROUND(AVG(payment_value), 2) AS avg_order_value,
        ROUND(SUM(payment_value) * 100.0 / SUM(SUM(payment_value)) OVER (), 2) AS revenue_share_pct
    FROM orders
    GROUP BY customer_state
    ORDER BY total_revenue DESC
    LIMIT 10
""", conn)

print("\n=== TOP 10 STATES BY REVENUE WITH SHARE ===")
print(query5)

conn.close()
print("\nAll SQL queries executed successfully!")
