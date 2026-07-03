import json
import os

DB_FILE = "database.json"

# 預設資料庫（如果檔案不存在時使用）
default_inventory = {
    "4902750728837": {"name": "UHAグミサプリC 10日", "count": 25, "price": 380, "expiry": "2026-12-31"},
    "4901330502880": {"name": "卡樂比薯條", "count": 45, "price": 150, "expiry": "2026-11-30"},
    "4902102072618": {"name": "可口可樂 500ml", "count": 120, "price": 35, "expiry": "2026-09-15"}
}

def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_inventory

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

inventory = load_data()

print("========================================================================")
print("                  JAN Code 智慧在庫管理系統 (終極版)                     ")
print("========================================================================")

while True:
    print("\n【主選單】")
    print("1. 掃描/輸入 JAN 查詢商品資訊")
    print("2. 商品進貨 (增加庫存)")
    print("3. 商品出貨 (減少庫存)")
    print("4. ✨ 建檔全新商品 (新增 JAN)")
    print("5. 結束並離開系統")
    
    choice = input("請選擇功能 (1-5): ").strip()
    
    if choice == "5":
        print("\n👋 資料已安全儲存，系統成功登出！")
        break
        
    elif choice == "1":
        search_code = input("\n請輸入或掃描 JAN Code: ").strip()
        if search_code in inventory:
            product = inventory[search_code]
            print("\n✅ 查詢成功！")
            header = f"{'JANコード':<15} | {'商品名':<25} | {'現有庫存':<8} | {'賣價':<6} | {'有效期限':<12}"
            print(header)
            print("-" * len(header))
            print(f"{search_code:<15} | {product['name']:<25} | {product['count']:<8} | {product['price']:<6} | {product['expiry']:<12}")
        else:
            print("\n❌ 查無此商品。")
            
    elif choice == "2":
        search_code = input("\n[進貨] 請輸入或掃描 JAN Code: ").strip()
        if search_code in inventory:
            try:
                add_count = int(input(f"目前庫存為 {inventory[search_code]['count']}，請輸入進貨數量: "))
                inventory[search_code]['count'] += add_count
                save_data(inventory)
                print(f"✅ 進貨成功！新庫存為: {inventory[search_code]['count']} 件")
            except ValueError:
                print("❌ 請輸入正確的數字。")
        else:
            print("\n❌ 查無此商品。")
            
    elif choice == "3":
        search_code = input("\n[出貨] 請輸入或掃描 JAN Code: ").strip()
        if search_code in inventory:
            try:
                sub_count = int(input(f"目前庫存為 {inventory[search_code]['count']}，請輸入出貨數量: "))
                if sub_count <= inventory[search_code]['count']:
                    inventory[search_code]['count'] -= sub_count
                    save_data(inventory)
                    print(f"✅ 出貨成功！新庫存為: {inventory[search_code]['count']} 件")
                else:
                    print(f"❌ 庫存不足！目前只剩 {inventory[search_code]['count']} 件")
            except ValueError:
                print("❌ 請輸入正確的數字。")
        else:
            print("\n❌ 查無此商品。")

    elif choice == "4":
        print("\n--- 🆕 全新商品建檔作業 ---")
        new_code = input("1. 請輸入或掃描全新商品 JAN Code: ").strip()
        
        # 後端邏輯：先檢查這個條碼是不是已經存在了，避免重複建檔蓋掉舊資料
        if new_code in inventory:
            print(f"❌ 該商品已存在！品名為: {inventory[new_code]['name']}，請直接使用進貨功能。")
        else:
            name = input("2. 請輸入商品名稱: ").strip()
            try:
                price = int(input("3. 請輸入商品賣價 (元): "))
                count = int(input("4. 請輸入初始庫存量 (件): "))
                expiry = input("5. 請輸入有效期限 (例: 2026-12-31): ").strip()
                
                # 將新資料塞入我們的記憶體庫存中
                inventory[new_code] = {
                    "name": name,
                    "price": price,
                    "count": count,
                    "expiry": expiry
                }
                
                # 永久寫入實體檔案
                save_data(inventory)
                print(f"\n🎉 恭喜！商品【{name}】已成功建檔並安全存檔！")
                
            except ValueError:
                print("❌ 價格或庫存數量輸入錯誤，建檔失敗，請重新操作。")
    else:
        print("❌ 無效的選項，請輸入 1 到 5。")
