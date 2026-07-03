from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import uvicorn
import datetime
from typing import List

app = FastAPI(title="中日雙語在庫管理系統-後端大腦 (iData T1 Pro Optimized)")

# ==========================================
# 1. CORS 跨域全放行（確保實體 PDA / 手機與電腦皆能順暢跨網段連線）
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. 模擬實體資料庫內部存儲（實際環境可無縫替換為 SQL Server / SQLite）
# ==========================================
# 商品主表
DB_PRODUCTS = [
    {"jan_code": "4901234567890", "sku": "SKU-A01", "name": "日系保濕化妝水", "name_ja": "高保湿化粧水", "stock": 150, "cost": 300, "price": 600},
    {"jan_code": "4902345678901", "sku": "SKU-B02", "name": "極細毛抗敏牙刷", "name_ja": "極細毛ハブラシ", "stock": 80, "cost": 50, "price": 120}
]

# 預計到貨單明細表（實務跨境物流核心）
DB_EXPECTED_DELIVERIES = []

# 在庫履歷表
DB_INVENTORY_LOGS = []

# ==========================================
# 3. Pydantic 資料傳輸模型定義
# ==========================================
class ExpectedDeliveryItem(BaseModel):
    order_no: str
    jan_code: str
    name_ja: str
    expected_count: int

class VerifyPayload(BaseModel):
    order_no: str
    jan_code: str
    received_count: int
    lot_no: str
    expiry_date: str

# ==========================================
# 4. 實體同步 API 接口實作
# ==========================================

@app.post("/api/expected_deliveries/bulk")
def bulk_insert_expected_deliveries(items: List[ExpectedDeliveryItem]):
    """
    1️⃣ 接收前端（電腦/手機）上傳的精簡版到貨單明細，並同步寫入資料庫
    """
    if not items:
        raise HTTPException(status_code=400, detail="上傳資料不可為空")
    
    # 清理舊的同名單據，避免重複導入造成對帳混亂
    target_order = items[0].order_no
    global DB_EXPECTED_DELIVERIES
    DB_EXPECTED_DELIVERIES = [item for item in DB_EXPECTED_DELIVERIES if item["order_no"] != target_order]
    
    # 批次寫入實體資料庫
    for item in items:
        DB_EXPECTED_DELIVERIES.append({
            "order_no": item.order_no,
            "jan_code": item.jan_code,
            "name_ja": item.name_ja,
            "expected_count": item.expected_count,
            "received_count": 0,
            "lot_no": "",
            "expiry_date": "",
            "status": "未驗收"
        })
    return {"status": "success", "message": f"成功載入單據 {target_order}，共 {len(items)} 筆品項。"}


@app.get("/api/expected_deliveries/orders")
def get_all_order_numbers():
    """
    2️⃣ 供全系統所有終端（電腦、各持 PDA）拉取目前存在的所有到貨單號清單
    """
    orders = list(set([item["order_no"] for item in DB_EXPECTED_DELIVERIES]))
    return sorted(orders, reverse=True)


@app.get("/api/expected_deliveries/detail/{order_no}")
def get_order_details(order_no: str):
    """
    3️⃣ 依據所選單號，即時回傳該到貨單的最新點收與漏報追查狀態明細
    """
    details = [item for item in DB_EXPECTED_DELIVERIES if item["order_no"] == order_no]
    return details


@app.post("/api/expected_deliveries/verify")
def verify_received_item(payload: VerifyPayload):
    """
    4️⃣ 核心：現場 PDA 驗收回寫 API
    執行邏輯：更新到貨明細進度 -> 自動連動同步更新主商品在庫表 -> 寫入歷史履歷
    """
    global DB_PRODUCTS
    # A. 更新預計到貨明細表狀態
    matched_item = None
    for item in DB_EXPECTED_DELIVERIES:
        if item["order_no"] == payload.order_no and item["jan_code"] == payload.jan_code:
            item["received_count"] = payload.received_count
            item["lot_no"] = payload.lot_no
            item["expiry_date"] = payload.expiry_date
            
            # 計算驗收狀態
            if payload.received_count >= item["expected_count"]:
                item["status"] = "完全驗收"
            elif payload.received_count > 0:
                item["status"] = "到貨短少"
            else:
                item["status"] = "未到貨"
            matched_item = item
            break
            
    if not matched_item:
        raise HTTPException(status_code=404, detail="找不到該單據與對應的 JAN 條碼品項")
        
    # B. 同步連動更新商品主在庫表 (若主表無此跨境新品，自動以日文名新增基底，防呆防漏)
    prod_exists = False
    for prod in DB_PRODUCTS:
        if prod["jan_code"] == payload.jan_code:
            prod["stock"] += payload.received_count
            prod_exists = True
            break
            
    if not prod_exists:
        # 主表自動初始化新列（跨境防呆，讓庫存點收不卡關）
        DB_PRODUCTS.append({
            "jan_code": payload.jan_code,
            "sku": f"AUTO-{payload.jan_code[-4:]}",
            "name": matched_item["name_ja"],
            "name_ja": matched_item["name_ja"],
            "stock": payload.received_count,
            "cost": 0,
            "price": 0
        })
        
    # C. 寫入全域在庫變更履歷表
    DB_INVENTORY_LOGS.append({
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "order_no": payload.order_no,
        "jan_code": payload.jan_code,
        "name_ja": matched_item["name_ja"],
        "lot_no": payload.lot_no,
        "expiry_date": payload.expiry_date,
        "change_qty": payload.received_count,
        "action": "PO_RECEIVING"
    })
    
    return {"status": "success", "message": f"JAN {payload.jan_code} 驗收回寫成功，主在庫與履歷已同步更新。"}


@app.get("/api/products")
def get_all_products():
    """
    加碼提供：供頁籤 1（現在庫一覽）即時向後端撈取全公司最新在庫狀況
    """
    return DB_PRODUCTS

# ==========================================
# 5. 後端大腦啟動服務設定
# ==========================================
if __name__ == "__main__":
    # 服務開在 8000 端口，允許局域網內所有終端（PDA、其他電腦）透過 IP 進行連線存取
    uvicorn.run(app, host="0.0.0.0", port=8000)
