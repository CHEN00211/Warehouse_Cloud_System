from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json
import os

app = FastAPI(title="JAN Code 在庫管理系統 API (完全體)")
DB_FILE = "database.json"

# 定義一個「資料格式模型」，規定前端傳進貨出貨數量時，必須是整數
class InventoryUpdate(BaseModel):
    count: int

def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# 1. 首頁測試
@app.get("/")
def home():
    return {"status": "success", "message": "歡迎來到在庫管理系統 Web API 伺服器！"}

# 2. 查詢 API (GET)
@app.get("/product/{jan_code}")
def get_product(jan_code: str):
    inventory = load_data()
    if jan_code in inventory:
        return {"jan_code": jan_code, "data": inventory[jan_code]}
    raise HTTPException(status_code=404, detail="查無此商品資訊")

# 3. 網頁進貨 API (POST)
@app.post("/product/{jan_code}/inbound")
def inbound_product(jan_code: str, update: InventoryUpdate):
    inventory = load_data()
    if jan_code not in inventory:
        raise HTTPException(status_code=404, detail="查無此商品，無法進貨")
    
    if update.count <= 0:
        raise HTTPException(status_code=400, detail="進貨數量必須大於 0")
        
    inventory[jan_code]["count"] += update.count
    save_data(inventory)
    return {
        "status": "success",
        "message": f"商品【{inventory[jan_code]['name']}】進貨成功",
        "new_count": inventory[jan_code]["count"]
    }

# 4. 網頁出貨 API (POST)
@app.post("/product/{jan_code}/outbound")
def outbound_product(jan_code: str, update: InventoryUpdate):
    inventory = load_data()
    if jan_code not in inventory:
        raise HTTPException(status_code=404, detail="查無此商品，無法出貨")
        
    if update.count <= 0:
        raise HTTPException(status_code=400, detail="出貨數量必須大於 0")
        
    if inventory[jan_code]["count"] < update.count:
        raise HTTPException(status_code=400, detail=f"庫存不足，目前僅剩 {inventory[jan_code]['count']} 件")
        
    inventory[jan_code]["count"] -= update.count
    save_data(inventory)
    return {
        "status": "success",
        "message": f"商品【{inventory[jan_code]['name']}】出貨成功",
        "new_count": inventory[jan_code]["count"]
    }
