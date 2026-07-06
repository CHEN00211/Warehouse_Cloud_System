import streamlit as st
import pandas as pd
import gspread

# 雲端資料庫管理員
def load_db_from_sheets():
    try:
        # 從 Google Sheet 讀取，注意 Sheet 名稱要對應您設好的 Inventory, Manifest, Counters
        inv_data = get_google_sheet("Inventory").get_all_records()
        man_data = get_google_sheet("Manifest").get_all_records()
        count_data = get_google_sheet("Counters").get_all_records()
        
        return {
            "inventory": inv_data,
            "manifest_by_order": {row["order_no"]: row for row in man_data} if man_data else {},
            "daily_counters": {row["date"]: row["count"] for row in count_data} if count_data else {}
        }
    except Exception as e:
        return {"inventory": [], "manifest_by_order": {}, "daily_counters": {}}

def save_data(db):
    try:
        # 存入 Inventory
        sheet_inv = get_google_sheet("Inventory")
        sheet_inv.clear()
        if db["inventory"]:
            df_inv = pd.DataFrame(db["inventory"])
            sheet_inv.update([df_inv.columns.values.tolist()] + df_inv.values.tolist())

        # 存入 Manifest
        sheet_man = get_google_sheet("Manifest")
        sheet_man.clear()
        man_rows = [{"order_no": k, **v} for k, v in db["manifest_by_order"].items()]
        if man_rows:
            df_man = pd.DataFrame(man_rows)
            sheet_man.update([df_man.columns.values.tolist()] + df_man.values.tolist())

        # 存入 Counters
        sheet_count = get_google_sheet("Counters")
        sheet_count.clear()
        count_rows = [{"date": k, "count": v} for k, v in db["daily_counters"].items()]
        if count_rows:
            df_count = pd.DataFrame(count_rows)
            sheet_count.update([df_count.columns.values.tolist()] + df_count.values.tolist())
    except Exception as e:
        st.error(f"雲端同步失敗: {e}")
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
