"""
build_db.py — 构建示例业务 SQLite 数据库
"""
import sqlite3
import pandas as pd
import numpy as np

np.random.seed(42)
conn = sqlite3.connect("business.db")

# 订单表
n = 1000
categories = ["电子产品", "服装", "食品", "家居", "图书"]
cities = ["北京", "上海", "广州", "深圳", "杭州"]
df = pd.DataFrame({
    "order_id": range(1, n + 1),
    "category": np.random.choice(categories, n),
    "city": np.random.choice(cities, n),
    "amount": np.random.randint(50, 2000, n),
    "quantity": np.random.randint(1, 5, n),
    "order_date": pd.date_range("2026-01-01", periods=n).astype(str),
})
df.to_sql("orders", conn, index=False, if_exists="replace")

# 用户表
users = pd.DataFrame({
    "user_id": range(1, 201),
    "city": np.random.choice(cities, 200),
    "age": np.random.randint(20, 60, 200),
    "membership": np.random.choice(["普通", "银卡", "金卡"], 200, p=[0.6, 0.3, 0.1]),
})
users.to_sql("users", conn, index=False, if_exists="replace")

conn.close()
print("business.db 构建完成：orders 表 1000 行，users 表 200 行")
