import streamlit as st
import pandas as pd
import gspread
import io          
import re          
import datetime

# 1. 頁面設定 (必須是第一行，不可更動)
st.set_page_config(page_title="到貨驗收系統", layout="wide")
st.title("到貨驗收系統")

# 2. 定義連線函式
def get_google_sheet(sheet_name):
    # 確保 Secrets 設定在 Streamlit Cloud 中
    creds = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(creds)
    return gc.open("Inventory_DB").worksheet(sheet_name)
# ========================================================
# 插入段落：ITF 轉 JAN 條碼轉換器 (加在這裡)
# ========================================================
def itf_to_jan13(barcode: str) -> str:
    """如果輸入是 14 位 ITF 碼，自動轉換為 13 位 JAN 碼；其餘原樣返回"""
    if not barcode:
        return ""
        
    # 清除前後空白與特殊字元
    barcode = str(barcode).strip()
    
    # 檢查是否為 14 位純數字的 ITF 碼
    if len(barcode) == 14 and barcode.isdigit():
        # 1. 取出中間的第 2 到 13 碼 (共 12 位數)
        jan_core = barcode[1:13]
        
        # 2. 計算標準的 Modulus 10 檢查碼 (權重 3-1-3-1)
        # 從最後一位往前算，奇數位置權重 3，偶數位置權重 1
        odd_sum = sum(int(jan_core[i]) for i in range(0, 12, 2))
        even_sum = sum(int(jan_core[i]) for i in range(1, 12, 2))
        
        total = odd_sum + (even_sum * 3)
        check_digit = (10 - (total % 10)) % 10
        
        # 3. 拼回 13 位的 JAN 碼
        return jan_core + str(check_digit)
        
    return barcode # 如果是 13 位 JAN 碼或其他格式，就直接回傳不變
# ========================================================    
# 4. 初始化 Session State
if "db" not in st.session_state:
    with st.spinner("正在從 Google Sheets 同步雲端數據..."):
        try:
            # 先建立一個乾淨的基礎結構
            st.session_state["db"] = {"inventory": [], "manifest_by_order": {}, "daily_counters": {}}
            
            # --- 💡 讀取 Manifest 工作表 ---
            manifest_sheet = get_google_sheet("Manifest")  
            raw_records = manifest_sheet.get_all_records()
            
            temp_manifest = {}
            for row in raw_records:
                o_no = str(row.get("order_no", "")).strip()
                if not o_no:
                    continue
                
                # 如果這個單號還沒建立，先初始化它的結構
                if o_no not in temp_manifest:
                    temp_manifest[o_no] = {
                        "info": {
                            "vendor": str(row.get("vendor", "-")),
                            "expected_delivery": str(row.get("expected_delive", "-")), 
                            "operator": str(row.get("operator", "-"))
                        },
                        "items": {},
                        "archived_order": row.get("archived_order") in [True, "TRUE", "True"]
                    }
                
                # 💡 核心修正：將讀取到的 jan_code 轉為字串
                jan_raw = str(row.get("jan_code", "")).strip()
                
                # 處理 Google Sheets 科學記號 (例如 4.98721E+12)
                if "E+" in jan_raw or "e+" in jan_raw:
                    try:
                        # 轉成浮點數後再轉成整數字串，強行還原條碼
                        jan_code = str(int(float(jan_raw)))
                    except:
                        jan_code = jan_raw
                else:
                    jan_code = jan_raw
                
                if jan_code:
                    # 補足可能因為轉型丟失的前導 0 (JAN 碼通常為 13 位)
                    if len(jan_code) == 12 and jan_raw.startswith("4"):
                        pass # 有些狀況是正常的，但通常補到13位比較安全
                        
                    temp_manifest[o_no]["items"][jan_code] = {
                        "name_ja": row.get("name_ja", "-"),
                        "expected_count": int(row.get("expected_count", 0) or 0),
                        "actual_count": int(row.get("actual_count", 0) or 0), # 新增對應 J 欄
                        "status": row.get("status", "未點收") # 對應 M 欄
                    }
            
            # 將整理好的雲端資料同步回 session_state
            st.session_state["db"]["manifest_by_order"] = temp_manifest
            st.success("雲端 Manifest 數據同步成功！")
            
        except Exception as e:
            st.error(f" 雲端同步失敗。錯誤訊息: {e}")
            st.session_state["db"] = {"inventory": [], "manifest_by_order": {}, "daily_counters": {}}



# 5. UI 設定
tab1, tab2, tab3, tab4 = st.tabs(["到貨導入", "PDA驗收", "歷史單據", "實體盤點"])


# ==========================================
# 🛑【全域物理消滅】用 CSS 隱藏並自動關閉 Clear Cache 彈窗
# ==========================================
import streamlit.components.v1 as components

components.html(
    """
    <script>
    const doc = window.parent.document;

    // 🛠️ 策略 1：注入 CSS，只要網頁敢渲染 Clear cache 視窗，直接透明化、隱藏化、縮小到 0 像素
    // 讓它完全沒有機會出現在人類的眼睛裡
    const style = doc.createElement('style');
    style.innerHTML = `
        div[role="dialog"]:has(h1), 
        div[role="dialog"]:contains("Clear caches"),
        .stModal, 
        [data-testid="stModal"] {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            width: 0px !important;
            height: 0px !important;
            pointer-events: none !important;
        }
    `;
    doc.head.appendChild(style);

    // 🛠️ 策略 2：啟動網頁雷達（MutationObserver），24小時監控網頁結構
    // 只要發現 Streamlit 把彈窗塞進網頁，程式在百萬分之一秒內自動去點擊 "Cancel" 或右上角的 "X"
    const observer = new MutationObserver((mutations) => {
        // 尋找畫面上任何包含 "Clear caches" 的標題或彈窗
        const modalHeaders = doc.querySelectorAll('h1, h2, h3, div');
        modalHeaders.forEach(el => {
            if (el.textContent && el.textContent.includes('Clear caches')) {
                // 找到了！往上尋找整個彈窗大外層
                const modal = el.closest('div[role="dialog"]');
                if (modal) {
                    // 1. 先用物理隱藏確保使用者絕對看不到
                    modal.style.display = 'none';
                    modal.style.visibility = 'hidden';
                    
                    // 2. 自動尋找彈窗內的 "Cancel" 按鈕或右上角的關閉叉叉進行模擬點擊
                    const buttons = modal.querySelectorAll('button');
                    buttons.forEach(btn => {
                        if (btn.textContent && (btn.textContent.includes('Cancel') || btn.textContent.includes('cancel'))) {
                            btn.click();
                        }
                    });
                    
                    // 如果沒找到按鈕，直接點擊右上角的叉叉 (通常是第一個按鈕)
                    if (buttons.length > 0) {
                        buttons[0].click();
                    }
                }
            }
        });
    });

    // 將雷達綁定至網頁主體根節點
    observer.observe(doc.body, { childList: true, subtree: true });
    </script>
    """,
    height=0,
)


# ==========================================
# ☁️ Google Sheets 全雲端持久化閘門
# ==========================================
def load_db_from_sheets():
    try:
        inv_rows = get_google_sheet("Inventory").get_all_records()
        man_rows = get_google_sheet("Manifest").get_all_records()
        count_rows = get_google_sheet("Counters").get_all_records()
        
        manifest_dict = {}
        for row in man_rows:
            o_no = str(row.get("order_no", "")).strip()
            if not o_no: 
                continue
                
            # 💡 核心解碼修正：如果這張入庫單第一次出現在迴圈中，立刻從該行儲存格抽取 info
            if o_no not in manifest_dict:
                manifest_dict[o_no] = {
                    "info": {
                        "upload_date": str(row.get("upload_date", "-")),
                        "expected_delivery": str(row.get("expected_delivery", "-")),
                        "operator": str(row.get("operator", "-")),
                        "vendor": str(row.get("vendor", "-"))
                    },
                    # 確保 archived_order 布林值型態解析正確
                    "archived_order": str(row.get("archived_order", "False")).lower() in ['true', '1', 'yes'],
                    "items": {}
                }
                
            jan = str(row.get("jan_code", "")).strip()
            if jan:
                manifest_dict[o_no]["items"][jan] = {
                    "name_ja": row.get("name_ja", ""),
                    "expected_count": int(row.get("expected_count", 0)),
                    "actual_count": int(row.get("actual_count", 0)),
                    "lot_no": str(row.get("lot_no", "")),
                    "expiry": str(row.get("expiry", "")),
                    "status": str(row.get("status", "未點收")),
                    "is_sub_row": str(row.get("is_sub_row", "False")).lower() in ['true', '1', 'yes'],
                    "parent_jan": str(row.get("parent_jan", ""))
                }
                
            # 💡 核心防禦：萬一這張單據前面的行數 info 漏掉了，後面任何一行只要有資料就自動反向補齊！
            if row.get("operator") and manifest_dict[o_no]["info"]["operator"] == "-":
                manifest_dict[o_no]["info"]["operator"] = str(row.get("operator"))
            if row.get("vendor") and manifest_dict[o_no]["info"]["vendor"] == "-":
                manifest_dict[o_no]["info"]["vendor"] = str(row.get("vendor"))
            if row.get("expected_delivery") and manifest_dict[o_no]["info"]["expected_delivery"] == "-":
                manifest_dict[o_no]["info"]["expected_delivery"] = str(row.get("expected_delivery"))
            if row.get("upload_date") and manifest_dict[o_no]["info"]["upload_date"] == "-":
                manifest_dict[o_no]["info"]["upload_date"] = str(row.get("upload_date"))
        
        return {
            "inventory": inv_rows,
            "manifest_by_order": manifest_dict,
            "daily_counters": {str(row["date"]): int(row["count"]) for row in count_rows if "date" in row}
        }
    except Exception as e:
        st.error(f"雲端資料重組失敗: {e}")
        return {"inventory": [], "manifest_by_order": {}, "daily_counters": {}}


def save_data(db):
    try:
        # 1. 儲存 Inventory
        sheet_inv = get_google_sheet("Inventory")
        sheet_inv.clear()
        if db["inventory"]:
            df_inv = pd.DataFrame(db["inventory"])
            # 💡 強制將所有欄位轉為標準字串，防止型態衝突
            df_inv = df_inv.fillna("").astype(str)
            sheet_inv.update([df_inv.columns.values.tolist()] + df_inv.values.tolist())

        # 2. 儲存 Manifest (平坦化寫入 Google Sheets)
        sheet_man = get_google_sheet("Manifest")
        sheet_man.clear()
        flat_manifest = []
        for o_no, doc in db["manifest_by_order"].items():
            info = doc.get("info", {})
            archived = doc.get("archived_order", False)
            for jan, item in doc.get("items", {}).items():
                flat_manifest.append({
                    "order_no": str(o_no),
                    "upload_date": str(info.get("upload_date", "")),
                    "expected_delivery": str(info.get("expected_delivery", "")),
                    "operator": str(info.get("operator", "")),
                    "vendor": str(info.get("vendor", "")),
                    "archived_order": str(archived),
                    "jan_code": str(jan),
                    "name_ja": str(item.get("name_ja", "")),
                    "expected_count": int(item.get("expected_count", 0)),
                    "actual_count": int(item.get("actual_count", 0)),
                    "lot_no": str(item.get("lot_no", "")),
                    "expiry": str(item.get("expiry", "")),
                    "status": str(item.get("status", "未點收")),
                    "is_sub_row": str(item.get("is_sub_row", False)),
                    "parent_jan": str(item.get("parent_jan", ""))
                })
        if flat_manifest:
            df_man = pd.DataFrame(flat_manifest)
            # 💡 核心防禦：強制將整張 Manifest 表格欄位全數鎖定為標準字串，徹底消滅 struct_value 錯誤
            df_man = df_man.fillna("").astype(str)
            sheet_man.update([df_man.columns.values.tolist()] + df_man.values.tolist())

        # 3. 儲存 Counters
        sheet_count = get_google_sheet("Counters")
        sheet_count.clear()
        count_list = [{"date": str(k), "count": int(v)} for k, v in db["daily_counters"].items()]
        if count_list:
            df_count = pd.DataFrame(count_list)
            df_count = df_count.fillna("").astype(str)
            sheet_count.update([df_count.columns.values.tolist()] + df_count.values.tolist())
            
        st.toast("雲端同步成功")
    except Exception as e:
        st.error(f"雲端存檔失敗: {e}")


# 核心防禦：每次重整，都強制從雲端同步最新狀態
if "db" not in st.session_state:
    st.session_state["db"] = load_db_from_sheets()

db = st.session_state["db"]

# ==========================================
# 語系與字典設定 (純淨無符號分流版)
# ==========================================
if "lang" not in st.session_state:
    st.session_state.lang = "zh"

lang_choice = st.sidebar.selectbox("Language / 語言切換", ["繁體中文", "日本語"])
st.session_state.lang = "zh" if lang_choice == "繁體中文" else "ja"

i18n = {
    "zh": {
        "title": "到貨驗收系統",
        "tab1": "入庫單CSV 導入",
        "tab2": "驗收點貨",
        "tab3": "歷史單據",
        "tab4": "庫存盤點管理", 
        "order_no": "入庫單號",
        "scan_jan": "JAN Code",
        "jan_not_found": "警告：此 JAN 碼不在本入貨清單中",
        "dup_warning": "警告：此條碼已點收過，狀態為 [已點收驗收]，是否進行覆蓋回寫",
        "expected": "預計應到數量",
        "actual": "驗收數量",
        "expiry": "有效期限",
        "submit": "確認提交",
        "date_err": "錯誤：效期格式必須為 YYYY/MM/DD",
        "success": "驗收成功回寫",
        "csv_upload": "請完整填寫單據表頭資訊，並附上預計到貨單 CSV 檔案（格式: jan_code, name_ja, expected_count）",
        "export_report": "匯出",
        "filter_mode": "篩選模式",
        "filter_all": "顯示全部",
        "filter_short": "顯示未到貨品項",
        "op_name_label": "操作人員 (必填)",
        "vendor_name_label": "供應商 (必填)",
        "eta_date_label": "預計入庫日 ( 2026/1/1 必填)",
        "btn_upload_label": "確認提交",
        "warning_missing": "錯誤：請填寫操作人員、供應商、預計入庫日並附加 CSV 檔案",
        "warning_past_date": "錯誤：預計入庫日不能是今天之前的日期",
        "warning_date_invalid": "錯誤：輸入的預計入庫日日期數字不合法",
        "err_csv_header": "錯誤：CSV 標頭必須包含 jan_code, name_ja, expected_count",
        "history_title": "未入庫單據一覽",
        "del_select_label": "刪除入貨單",
        "del_btn_label": "確認刪除",
        "no_manifest_msg": "目前尚無入庫單資料",
        "history_main_title": "歷史單據總覽",
        "history_detail_title": "差異追查清單",
        "export_excel_btn": "匯出 Excel (.xlsx)",
        "success_msg_prefix": "上傳成功",
        "lot_no_label": "Lot 批次",
        "lot_no_err": "錯誤：請輸入 Lot 批次",
        "finish_verify_btn": "完成驗貨",
        "force_archive_btn": "強制結案上傳",
        "cancel_archive_btn": "取消並返回點貨",
        "gate_warning_msg": "【防呆警示】目前此單據內還有 {} 筆商品尚未完成驗貨！請問是否仍要強制完工結案並上傳報表？",
        "status_done": "驗貨完畢",
        "status_pending": "未點收", 
        "tab4": "庫存盤點管理", 
        "inv_upload_title": "1. 導入新實體盤點名冊", 
        "inv_select_sheet_title": "2. 選擇欲執行的盤點表單", 
        "inv_title": "3. 該單據當前實體庫存名冊", 
        "inv_edit_title": "4. 庫存盤點數量修正", 
        "inv_select_item": "選擇欲修正的庫存項目 (序號 - 條碼 - 批次)", 
        "inv_new_stock": "盤點後實際新庫存量", 
        "inv_update_btn": "更新庫存數量", 
        "inv_update_success": "庫存修正成功！已同步更新至盤點單資料庫", 
        "inv_sheet_no": "盤點單號 / 名稱 (必填)", 
        "inv_op": "盤點人員 (必填)",
        "tab4_title_import": "1. 導入新實體盤點名冊",
        "tab4_input_sheet_id": "盤點單號 / 名稱 (必填)",
        "tab4_err_duplicated": "提示：此貨位與效期組合之前已完成盤點！",
        "tab4_confirm_override": "確認覆蓋原盤點數據",
        "t4_import_title": "1. 導入新實體盤點名冊",
        "t4_sheet_id": "盤點單號 / 名稱 (必填)",
        "t4_operator": "盤點人員 (必填)",
        "t4_upload_csv": "上傳盤點庫存名冊 CSV",
        "t4_btn_register": "確認導入盤點單",
        "t4_err_fields": "錯誤：請填寫盤點單號、人員並上傳 CSV 檔案",
        "t4_err_csv": "錯誤：CSV 格式不符。必須包含: jan_code, name_ja, location, expiry, stock",
        "t4_select_sheet": "2. 選擇欲執行的盤點表單",
        "t4_pda_scan": "PDA 條碼掃描盤點",
        "t4_scan_hint": "請將游標停在此處並使用 PDA 刷條碼",
        "t4_counted_warning": "提示：此貨位與效期組合之前已完成盤點！",
        "t4_override_check": "確認覆蓋原盤點數據",
        "t4_input_qty": "請輸入實際盤點數量",
        "t4_btn_confirm": "同時確認提交",
        "t4_status_list": "盤點進度動態清單",
        "t4_uncounted": "未盤點品項",
        "t4_counted": "已盤點品項"  
    },
    "ja": {
        "title": "入荷検収システム",
        "tab1": "納品データ(CSV)登録",
        "tab2": "検品",
        "tab3": "履歴一覧",
        "order_no": "伝票番号",
        "scan_jan": "JANコード",
        "jan_not_found": "警告：このJANコードは入荷予定リストに登録されていません",
        "dup_warning": "警告：既に検収登録済みの商品です。上書き保存しますか",
        "expected": "納品予定数",
        "actual": "納品数",
        "expiry": "賞味期限/消費期限 (2026-01-01)",
        "submit": "確定",
        "date_err": "賞味期限は「YYYY/MM/DD」の形式で入力してください。",
        "success": "検収データの登録が完了しました",
        "csv_upload": "伝票情報を入力し、CSVファイルを添付の上、「確定」ボタンを押してください（形式: jan_code, name_ja, expected_count）",
        "export_report": "出力",
        "filter_mode": "フィルターモード",
        "filter_all": "すべて表示",
        "filter_short": "未納入品のみ表示",
        "op_name_label": "担当者 (必須)",
        "vendor_name_label": "仕入先(必須)",
        "eta_date_label": "納品予定日 (2026/1/1 必須)",
        "btn_upload_label": "確定",
        "warning_missing": "エラー：担当者、仕入先、正しい入荷予定日、およびCSVファイルを添付してください",
        "warning_past_date": "エラー：入荷予定日は今日以降の日付を入力してください",
        "warning_date_invalid": "エラー：輸入された入荷予定日の日付が正しくありません",
        "err_csv_header": "エラー：CSVヘッダーに jan_code, name_ja, expected_count が必要です",
        "history_title": "未納品履歴一覧",
        "del_select_label": "削除する入荷伝票番号を選択",
        "del_btn_label": "確認削除",
        "no_manifest_msg": "入荷予定伝票データがありません。上のフォームからインポートしてください。",
        "history_main_title": "履歴一覧",
        "history_detail_title": "差異追跡リスト",
        "export_excel_btn": "Excel出力 (.xlsx)",
        "success_msg_prefix": "アップロード完了",
        "lot_no_label": "ロット番号",
        "lot_no_err": "エラー：ロット番号を入力してください",
        "finish_verify_btn": "検収完了",
        "force_archive_btn": "強制的に終了してアップロード",
        "cancel_archive_btn": "キャンセルして戻る",
        "gate_warning_msg": "【警告】まだ検収が完了していない商品が {} 件あります！このまま強制終了してデータをアップロードしますか？",
        "status_done": "検収完了",
        "status_pending": "未検収",
        "tab4": "在庫・棚卸管理", 
        "inv_upload_title": "1. 棚卸マスターデータのインポート", 
        "inv_select_sheet_title": "2. 実行する棚卸伝票の選択", 
        "inv_title": "3. 選択された棚卸在庫データ一覧", 
        "inv_edit_title": "4. 棚卸在庫数修正", 
        "inv_select_item": "修正対象を選択 (項番 - JAN - ロット)", 
        "inv_new_stock": "実棚数量（修正後）", 
        "inv_update_btn": "在庫数を更新", 
        "inv_update_success": "在庫数が修正され、データベースに同期されました", 
        "inv_sheet_no": "棚卸番号 / 名称 (必須)", 
        "inv_op": "棚卸担当者 (必須)",
        "tab4_title_import": "1. 棚卸マスターデータのインポート",
        "tab4_input_sheet_id": "棚卸番号 / 名称 (必須)",
        "tab4_err_duplicated": "注意：この組み合わせは既に棚卸完了しています！",
        "tab4_confirm_override": "既存データを上書きする",
        "t4_import_title": "1. 棚卸マスターデータのインポート",
        "t4_sheet_id": "棚卸番号 / 名称 (必須)",
        "t4_operator": "棚卸担当者 (必須)",
        "t4_upload_csv": "棚卸CSVファイルをアップロードしてください",
        "t4_btn_register": "棚卸伝票を登録",
        "t4_err_fields": "エラー：棚卸番号、担当者、CSVファイルを入力・添付してください",
        "t4_err_csv": "エラー：CSV形式が正しくありません。jan_code, name_ja, location, expiry, stock を含めてください",
        "t4_select_sheet": "2. 実行する棚卸伝票の選択",
        "t4_pda_scan": "PDA バーコードスキャン棚卸",
        "t4_scan_hint": "JANコードをスキャンしてください",
        "t4_counted_warning": "注意：この組み合わせは既に棚卸完了しています！",
        "t4_override_check": "既存データを上書きする",
        "t4_input_qty": "実棚数を入力してください",
        "t4_btn_confirm": "一括確定する",
        "t4_status_list": "棚卸進捗状況リスト",
        "t4_uncounted": "未棚卸品目",
        "t4_counted": "棚卸完了品目"
    }
}

t = i18n[st.session_state.lang]


if "f_op_name" not in st.session_state:
    st.session_state.f_op_name = ""
if "f_vendor_name" not in st.session_state:
    st.session_state.f_vendor_name = ""
if "f_eta_date" not in st.session_state:
    st.session_state.f_eta_date = ""
if "f_f_eta" not in st.session_state:
    st.session_state.f_f_eta = ""
if "t1_form_key" not in st.session_state:
    st.session_state.t1_form_key = 0
if "pda_key" not in st.session_state:
    st.session_state.pda_key = 0


# ==========================================
# PART 2: Tab1 CSV 上傳與核心資料處理
# ==========================================
with tab1:
    if "last_success_msg" in st.session_state and st.session_state["last_success_msg"]:
        st.success(st.session_state["last_success_msg"])
        st.session_state["last_success_msg"] = "" 

    col_imp1, col_imp2, col_imp3 = st.columns(3)
    with col_imp1:
        operator_name = st.text_input(t["op_name_label"], value=st.session_state.f_op_name, key=f"op_input_slot_{st.session_state.t1_form_key}")
    with col_imp2:
        vendor_name = st.text_input(t["vendor_name_label"], value=st.session_state.f_vendor_name, key=f"vn_input_slot_{st.session_state.t1_form_key}")
    with col_imp3:
        current_eta_val = st.session_state.f_f_eta if st.session_state.f_f_eta else st.session_state.f_eta_date
        eta_date_input = st.text_input(t["eta_date_label"], value=current_eta_val, key=f"eta_input_slot_{st.session_state.t1_form_key}")
        
    uploaded_file = st.file_uploader("Upload CSV File", type=["csv"], label_visibility="collapsed", key=f"csv_uploader_slot_{st.session_state.t1_form_key}")
    submit_upload_btn = st.button(t["btn_upload_label"], type="primary", key=f"btn_submit_slot_{st.session_state.t1_form_key}")
    
    if submit_upload_btn:
        st.session_state.f_op_name = operator_name
        st.session_state.f_vendor_name = vendor_name
        st.session_state.f_f_eta = eta_date_input
        st.session_state.f_eta_date = eta_date_input
        
        cleaned_eta = eta_date_input.strip().replace("/", "-")
        eta_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", cleaned_eta)
        
        if not operator_name.strip() or not vendor_name.strip() or not eta_match or uploaded_file is None:
            st.error(t["warning_missing"])
        else:
            year, month, day = eta_match.groups()
            try:
                v_date = datetime.date(int(year), int(month), int(day))
                
                if v_date < datetime.date.today():
                    st.error(t["warning_past_date"])
                else:
                    final_eta_str = v_date.strftime("%Y/%m/%d")
                    df_upload = pd.read_csv(uploaded_file, dtype={"jan_code": str})
                    required_cols = ["jan_code", "name_ja", "expected_count"]
                    
                    if all(col in df_upload.columns for col in required_cols):
                        today_mmdd = datetime.date.today().strftime("%m%d")
                        if today_mmdd not in db["daily_counters"]:
                            db["daily_counters"][today_mmdd] = 0
                        db["daily_counters"][today_mmdd] += 1
                        
                        auto_order_no = f"{today_mmdd}{db['daily_counters'][today_mmdd]:03d}"
                        current_time_str = datetime.datetime.now().strftime("%Y/%m/%d")
                        
                        db["manifest_by_order"][auto_order_no] = {
                            "info": {
                                "upload_date": current_time_str,
                                "expected_delivery": final_eta_str,
                                "operator": operator_name.strip(),
                                "vendor": vendor_name.strip()
                            },
                            "items": {}
                        }
                        
                        for _, row in df_upload.iterrows():
                            jan_key = str(row["jan_code"]).strip()
                            db["manifest_by_order"][auto_order_no]["items"][jan_key] = {
                                "name_ja": row["name_ja"],
                                "expected_count": int(row["expected_count"]),
                                "actual_count": 0,
                                "lot_no": "",
                                "expiry": "",
                                "status": "未點收" 
                            }
                        
                        prefix = t.get("success_msg_prefix", "上傳成功")
                        st.session_state["last_success_msg"] = f"{prefix}: {auto_order_no}"
                        
                        st.session_state.f_op_name = ""
                        st.session_state.f_vendor_name = ""
                        st.session_state.f_eta_date = ""
                        st.session_state.f_f_eta = ""
                        st.session_state.t1_form_key += 1
                        
                        save_data(db)
                        st.rerun()
                    else:
                        st.error(t["err_csv_header"])
            except ValueError:
                st.error(t["warning_date_invalid"])

# ==========================================
# PART 3: Tab1 底部未入庫單據一覽與刪除功能
# ==========================================
    st.markdown("---")
    st.text(t["history_title"])
    
    if db and "manifest_by_order" in db and db["manifest_by_order"]:
        history_data = []
        active_orders = []
        sorted_orders = sorted(list(db["manifest_by_order"].keys()), reverse=True)
        
        display_idx = 1
        for o_no in sorted_orders:
            doc = db["manifest_by_order"][o_no]
            pool = doc.get("items", {})
            total_items = len(pool)
            verified_items = sum(1 for item in pool.values() if item.get("status") == "決收點貨")
            
            # 💡 只有手動完成了「完成驗貨」結案的單據，才會從這裡隱藏
            if doc.get("archived_order") is True:
                continue
                
            active_orders.append(o_no)
            info = doc.get("info", {})
            
            # 💡 計算狀態三分法標籤（用於未入庫一覽表）
            if verified_items == total_items:
                grid_status = "全數驗收" if st.session_state.lang == "zh" else "全数検収"
            elif verified_items > 0:
                grid_status = "部分驗收" if st.session_state.lang == "zh" else "一部検収"
            else:
                grid_status = "未驗收" if st.session_state.lang == "zh" else "未検収"
            
            # 💡【核心修正】Tab1 未入庫大表標頭純進化分流，完全拆分中日文
            if st.session_state.lang == "zh":
                history_data.append({
                    "序號": display_idx,
                    "入庫單號": o_no,
                    "供應商": info.get("vendor", "-"),
                    "預計入庫日": info.get("expected_delivery", "-"),
                    "操作人員": info.get("operator", "-"),
                    "上傳日": info.get("upload_date", "-"),
                    "商品總品項數": total_items,
                    "已完成驗貨數": verified_items,
                    "狀態": grid_status
                })
            else:
                history_data.append({
                    "項番": display_idx,
                    "伝票番号": o_no,
                    "仕入先": info.get("vendor", "-"),
                    "納品予定日": info.get("expected_delivery", "-"),
                    "担当者": info.get("operator", "-"),
                    "取込日時": info.get("upload_date", "-"),
                    "総品目数": total_items,
                    "検収完了数": verified_items,
                    "ステータス": grid_status
                })
            display_idx += 1
        
        if history_data:
            st.dataframe(pd.DataFrame(history_data), use_container_width=True, hide_index=True)
            
            col_del1, col_del2 = st.columns(2)
            with col_del1:
                target_to_delete = st.selectbox(t["del_select_label"], options=active_orders, key="delete_order_select", label_visibility="collapsed")
            with col_del2:
                if st.button(t["del_btn_label"], type="primary", use_container_width=True):
                    if target_to_delete in db["manifest_by_order"]:
                        del db["manifest_by_order"][target_to_delete]
                        save_data(db)
                        st.rerun()
        else:
            st.text(t["no_manifest_msg"])
    else:
        st.text(t["no_manifest_msg"])
# ==========================================
# PART 4-1: Tab2 狀態初始化與 PDA 盲刷通道
# ==========================================
with tab2:
    if "current_verified_jan" not in st.session_state:
        st.session_state.current_verified_jan = ""
    if "temp_name_ja" not in st.session_state:
        st.session_state.temp_name_ja = ""
    if "temp_expected_count" not in st.session_state:
        st.session_state.temp_expected_count = 0
    if "temp_actual_count" not in st.session_state:
        st.session_state.temp_actual_count = 0
    if "show_dup_warning" not in st.session_state:
        st.session_state.show_dup_warning = False
    if "pda_error_msg" not in st.session_state:
        st.session_state.pda_error_msg = ""

    raw_options = []
    all_raw_orders = sorted(list(db["manifest_by_order"].keys()), reverse=True)
    
    for o_no in all_raw_orders:
        doc = db["manifest_by_order"][o_no]
        if doc.get("archived_order") is not True:
            raw_options.append(o_no)
    
    if raw_options:
        if st.session_state.lang == "zh":
            placeholder_text = "請選擇入庫單號"
        else:
            placeholder_text = "伝票番号を選択してください"
            
        order_options = [placeholder_text] + raw_options
        selected_order = st.selectbox(t["order_no"], options=order_options, index=0, key="tab2_receiving_order_select")
        
        if selected_order != placeholder_text:
            current_doc = db["manifest_by_order"].get(selected_order, {})
            current_info = current_doc.get("info", {})
            current_manifest_pool = current_doc.get("items", {})
            
            # 💡 依據語系各自獨立生成，徹底修正 c 漏字與 None 錯位大表
            if st.session_state.lang == "zh":
                meta_df = pd.DataFrame([
                    {"欄位": "供應商", "內容": current_info.get("vendor", "-")},
                    {"欄位": "預計入庫", "內容": current_info.get("expected_delivery", "-")},
                    {"欄位": "操作人員", "內容": current_info.get("operator", "-")}
                ])
                st.dataframe(
                    meta_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "欄位": st.column_config.TextColumn(width="small"),
                        "內容": st.column_config.TextColumn(width="medium")
                    }
                )
            else:
                meta_df = pd.DataFrame([
                    {"項目": "仕入先", "content": current_info.get("vendor", "-")},
                    {"項目": "納品予定日", "content": current_info.get("expected_delivery", "-")},
                    {"項目": "担当者", "content": current_info.get("operator", "-")}
                ])
                st.dataframe(
                    meta_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "項目": st.column_config.TextColumn(width="small"),
                        "content": st.column_config.TextColumn(label="内容", width="medium")
                    }
                )
            st.markdown("---")
            
            def handle_pda_scan_secure():
                current_key_name = f"pda_input_slot_{selected_order}_{st.session_state.pda_key}"
                raw_input = st.session_state[current_key_name].strip()
                
                # 💡 將 ITF 自動還原成 JAN 碼
                target_jan = itf_to_jan13(raw_input)
                
                # 🔒 完美的 16 個空格縮排（相對於 def 有 4 個空格）
                if target_jan and current_manifest_pool:
                    if target_jan in current_manifest_pool:
                        item = current_manifest_pool[target_jan]
                        st.session_state.current_verified_jan = target_jan
                        st.session_state.temp_name_ja = item["name_ja"]
                        st.session_state.temp_expected_count = item["expected_count"]
                        st.session_state.temp_actual_count = item["expected_count"]  
                        st.session_state.show_dup_warning = (item.get("status") == "決收點貨" or item.get("status") == "已點收驗收")
                        st.session_state.pda_error_msg = ""
                    else:
                        st.session_state.current_verified_jan = "ERROR_NOT_FOUND"
                        st.session_state.pda_error_msg = t["jan_not_found"]
                        
                # 🔒 key + 1 必須在 if 結束後、函式結束前執行
                st.session_state.pda_key += 1


            st.text_input(t["scan_jan"], key=f"pda_input_slot_{selected_order}_{st.session_state.pda_key}", on_change=handle_pda_scan_secure)

            if st.session_state.current_verified_jan == "ERROR_NOT_FOUND":
                st.error(st.session_state.pda_error_msg.replace("！", ""))
                st.session_state.current_verified_jan = ""
                st.session_state.temp_name_ja = ""
                st.session_state.temp_expected_count = 0
                st.session_state.temp_actual_count = 0
                st.session_state.show_dup_warning = False
            # ==========================================
            # PART 4-2 (上): Tab2 確認提交表單與動態欄位生成
            # ==========================================
            if st.session_state.current_verified_jan and st.session_state.current_verified_jan != "ERROR_NOT_FOUND":
                st.markdown("---")
                if st.session_state.show_dup_warning:
                    st.warning(t["dup_warning"].replace("？", "").replace("！", ""))
                    
                info_df = pd.DataFrame([
                    {"Item_Key": "JAN Code", "Item_Val": st.session_state.current_verified_jan},
                    {"Item_Key": "商品名", "Item_Val": st.session_state.temp_name_ja},
                    {"Item_Key": "預計應到數/予定数", "Item_Val": str(st.session_state.temp_expected_count)}
                ])
                
                st.dataframe(
                    info_df,
                    hide_index=True,
                    column_config={
                        "Item_Key": st.column_config.TextColumn(label="", width="medium"),
                        "Item_Val": st.column_config.TextColumn(label="", width="large")
                    },
                    use_container_width=False
                )
                
                # 宣告一個動態列數快取計數器
                if f"row_count_{selected_order}" not in st.session_state:
                    st.session_state[f"row_count_{selected_order}"] = 1

                with st.form("verification_gate_form", clear_on_submit=False):
                    collected_rows_data = []
                    
                    # 💾 自資料庫取出目前 JAN 碼對應的原始預設數值
                    target_jan = st.session_state.current_verified_jan
                    db_item = current_manifest_pool.get(target_jan, {})
                    
                    # 讀取箱數與箱入數預設值
                    db_expected_cases = db_item.get("expected_cases", 10)  
                    db_pcs_per_case = db_item.get("pcs_per_case", 10)      

                    # 動態迴圈畫出多個輸入欄位
                    for idx in range(st.session_state[f"row_count_{selected_order}"]):
                        st.markdown(f"**項目組合 {idx + 1}**" if st.session_state.lang == "zh" else f"**アイテム組み合わせ {idx + 1}**")
                        
                        # 初始狀態填入預設值：第一組自動帶入 Data 數值，新增組預設為 0
                        if idx == 0:
                            init_cases = int(db_expected_cases)
                            init_per_case = int(db_pcs_per_case)
                            init_actual = int(st.session_state.temp_actual_count) 
                        else:
                            init_cases = 0
                            init_per_case = 0
                            init_actual = 0

                        # 🛠️ 完整回復並優化您的分欄結構 (箱數、箱入數、驗收數量、Lot批次、有效期限)
                        col_box, col_per, col_field1, col_field2, col_field3 = st.columns([1, 1, 1, 1.8, 1.8])
                        
                        with col_box:
                            r_cases = st.number_input(
                                "箱數" if st.session_state.lang == "zh" else "箱数", 
                                min_value=0, 
                                value=init_cases, 
                                step=1, 
                                key=f"box_r_{selected_order}_{idx}"
                            )
                        with col_per:
                            r_per_case = st.number_input(
                                "箱入數" if st.session_state.lang == "zh" else "入数", 
                                min_value=0, 
                                value=init_per_case, 
                                step=1,
                                key=f"per_r_{selected_order}_{idx}"
                            )
                        with col_field1:
                            r_actual = st.number_input(
                                t["actual"], 
                                min_value=0, 
                                value=init_actual, 
                                step=1,
                                key=f"act_r_{selected_order}_{idx}"
                            )
                        with col_field2:
                            lot_field_label = t.get("lot_no_label", "Lot 批次")
                            r_lot = st.text_input(lot_field_label, value="", key=f"lot_r_{selected_order}_{idx}")
                        with col_field3:
                            r_expiry = st.text_input(t["expiry"], value="", placeholder="2026/1/1", key=f"exp_r_{selected_order}_{idx}")
                        
                        # 蒐集包含新欄位的完整資料
                        collected_rows_data.append({
                            "actual": r_actual, 
                            "lot": r_lot, 
                            "expiry": r_expiry,
                            "cases": r_cases,
                            "pcs_per_case": r_per_case
                        })
                        st.markdown("---")
                    
                    # 🔒 完整回復您的表單雙按鈕排版
                    col_form_btn1, col_form_btn2 = st.columns(2)
                    with col_form_btn1:
                        submit_btn = st.form_submit_button(t["submit"], use_container_width=True)
                    with col_form_btn2:
                        if st.form_submit_button("+ 增加期限與批次欄位", use_container_width=True):
                            st.session_state[f"row_count_{selected_order}"] += 1
                            st.rerun()
                    # ==========================================
                    # PART 4-2 (下): 資料校驗與資料庫持久化回寫
                    # ==========================================
                    if submit_btn:
                        is_all_rows_valid = True
                        error_message_to_show = ""
                        validated_rows = []
                        
                        # 第一步：校驗人員填寫的每一列資料格式
                        for idx, row_data in enumerate(collected_rows_data):
                            c_actual = row_data["actual"]
                            c_lot = row_data["lot"].strip()
                            c_exp = row_data["expiry"].strip()
                            
                            # 取出新增的箱數與箱入數
                            c_cases = row_data["cases"]
                            c_per_case = row_data["pcs_per_case"]
                            
                            if not c_lot and not c_exp:
                                is_all_rows_valid = False
                                error_message_to_show = f"第 {idx + 1} 組錯誤：批次與有效期限不能同時空白" if st.session_state.lang == "zh" else f"第 {idx + 1} 組エラー：ロット番号と賞味期限を同時に空白にすることはできません"
                                break
                            
                            is_this_date_ok = True
                            standard_expiry_str = ""
                            
                            if c_exp:
                                cleaned_date = c_exp.replace("/", "-")
                                match_ymd = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", cleaned_date)
                                match_ym = re.match(r"^(\d{4})-(\d{1,2})$", cleaned_date)
                                
                                if match_ymd:
                                    year, month, day = match_ymd.groups()
                                    try:
                                        validated_date = datetime.date(int(year), int(month), int(day))
                                        standard_expiry_str = validated_date.strftime("%Y/%m/%d")
                                    except ValueError:
                                        is_this_date_ok = False
                                elif match_ym:
                                    year, month = match_ym.groups()
                                    try:
                                        if 1 <= int(month) <= 12:
                                            standard_expiry_str = f"{int(year)}/{int(month):02d}"
                                        else:
                                            is_this_date_ok = False
                                    except ValueError:
                                        is_this_date_ok = False
                                else:
                                    is_this_date_ok = False
                            
                            if not is_this_date_ok:
                                is_all_rows_valid = False
                                error_message_to_show = t["date_err"]
                                break
                            
                            # 儲存驗證通過的完整資料（包含箱數與箱入數）
                            validated_rows.append({
                                "actual": c_actual, 
                                "lot": c_lot, 
                                "expiry": standard_expiry_str,
                                "cases": c_cases,
                                "pcs_per_case": c_per_case
                            })

                        # 處理校驗結果並正式寫入資料庫
                        if not is_all_rows_valid:
                            st.error(error_message_to_show)
                        else:
                            target_jan = st.session_state.current_verified_jan
                            # 先把舊的副行清掉（若重複點收時避免無限疊加副行）
                            sub_keys_to_del = [k for k in current_manifest_pool.keys() if current_manifest_pool[k].get("is_sub_row") and current_manifest_pool[k].get("parent_jan") == target_jan]
                            for sk in sub_keys_to_del:
                                del current_manifest_pool[sk]
                            
                            # 第二步：將資料正式回寫入庫單 (主副行分行獨立存儲結構)
                            for idx, v_row in enumerate(validated_rows):
                                c_actual = v_row["actual"]
                                c_lot = v_row["lot"]
                                c_exp = v_row["expiry"]
                                
                                # 💾【實體庫存持久化】確保實體名冊乾淨無損
                                db["inventory"].append({
                                    "jan_code": target_jan, 
                                    "name_ja": current_manifest_pool[target_jan]["name_ja"],
                                    "lot_no": c_lot, 
                                    "expiry": c_exp, 
                                    "stock": c_actual
                                })
                                
                                if idx == 0:
                                    # 第一個 Lot 組合直接記錄在原始的主鍵 JAN 碼下
                                    current_manifest_pool[target_jan]["actual_count"] = c_actual
                                    current_manifest_pool[target_jan]["lot_no"] = c_lot
                                    current_manifest_pool[target_jan]["expiry"] = c_exp
                                    current_manifest_pool[target_jan]["status"] = "決收點貨"
                                else:
                                    # 額外的 Lot 組合自動增開獨立副行，確保在畫面上與 Excel 中拆開呈現
                                    sub_key = f"{target_jan}_sub_{idx}_{c_lot}_{c_exp.replace('/', '')}"
                                    current_manifest_pool[sub_key] = {
                                        "name_ja": current_manifest_pool[target_jan]["name_ja"],
                                        "expected_count": 0,
                                        "actual_count": c_actual,
                                        "lot_no": c_lot,
                                        "expiry": c_exp,
                                        "status": "決收點貨",
                                        "is_sub_row": True,
                                        "parent_jan": target_jan
                                    }
                            
                            # 💾 安全同步雲端
                            save_data(db)
                            
                            st.success(t["success"])
                            st.session_state[f"row_count_{selected_order}"] = 1
                            st.session_state.current_verified_jan = ""
                            st.session_state.temp_name_ja = ""
                            st.session_state.temp_expected_count = 0
                            st.session_state.temp_actual_count = 0
                            st.session_state.show_dup_warning = False
                            st.rerun()

            st.markdown("---")
            st.text(t["filter_mode"])
            filter_mode = st.radio("Filter Mode", [t["filter_all"], t["filter_short"]], label_visibility="collapsed")
            
            if st.session_state.lang == "zh":
                jan_col = "JAN 條碼"
                name_col = "商品名稱"
                req_col = "預計應到數量"
                act_col = "實到數量"
                short_col = "差異數量"
                lot_col = "Lot 批次"
                exp_col = "有效期限"
                status_col = "狀態"
            else:
                jan_col = "JAN Code"
                name_col = "商品名"
                req_col = "予定数"
                act_col = "納品数"
                short_col = "差異"
                lot_col = "ロット番号"
                exp_col = "賞味期限"
                status_col = "ステータス"
            # 💡【Tab2 核心合算門神】計算該單據各 JAN 碼的總實到數量（主行+所有副行）
            jan_total_actual_map = {}
            for k, v in current_manifest_pool.items():
                real_jan = v.get("parent_jan", k) if v.get("is_sub_row") else k
                if real_jan not in jan_total_actual_map:
                    jan_total_actual_map[real_jan] = 0
                jan_total_actual_map[real_jan] += v["actual_count"]

            receiving_report_list = []
            for k, v in current_manifest_pool.items():
                real_jan = v.get("parent_jan", k) if v.get("is_sub_row") else k
                
                # 副行預計數/差異數皆為 0；主行差異數扣除副行實到，避免產生負數
                if v.get("is_sub_row"):
                    calc_expected = 0
                    calc_shortage = 0
                    display_jan = real_jan
                else:
                    calc_expected = v["expected_count"]
                    calc_shortage = v["expected_count"] - jan_total_actual_map.get(real_jan, 0)
                    display_jan = k
                
                if v.get("status") == "決收點貨":
                    item_status = "驗貨完畢" if st.session_state.lang == "zh" else "検収完了"
                else:
                    item_status = "未點收" if st.session_state.lang == "zh" else "未検収"
                
                # 過濾模式判斷：若選擇「僅顯示有差異品項」，且差異為 0，則跳過不顯示
                if filter_mode == t["filter_short"] and calc_shortage == 0:
                    continue

                receiving_report_list.append({
                    jan_col: display_jan,
                    name_col: v["name_ja"],
                    req_col: calc_expected,      
                    act_col: v["actual_count"],
                    short_col: calc_shortage,    
                    lot_col: v.get("lot_no", ""),
                    exp_col: v.get("expiry", ""),
                    status_col: item_status
                })
            
            if receiving_report_list:
                df_receiving = pd.DataFrame(receiving_report_list)
                
                # 精準 CSV 原始名冊順序黏合錨點（保持與原始 CSV 順序一致）
                csv_original_order = {}
                order_idx = 0
                for item_key, item_val in current_manifest_pool.items():
                    if not item_val.get("is_sub_row"):
                        csv_original_order[item_key] = order_idx
                        order_idx += 1

                temp_sort_csv_idx = []
                temp_sort_is_sub = []

                for index, row in df_receiving.iterrows():
                    current_row_jan = str(row[jan_col]).strip()
                    pool_item_key = list(current_manifest_pool.keys())[index]
                    is_sub_flag = 1 if current_manifest_pool[pool_item_key].get("is_sub_row") else 0
                    
                    temp_sort_csv_idx.append(csv_original_order.get(current_row_jan, 9999))
                    temp_sort_is_sub.append(is_sub_flag)

                df_receiving["_sort_csv_idx"] = temp_sort_csv_idx
                df_receiving["_sort_sub"] = temp_sort_is_sub

                # 執行雙層穩定排序，確保副行緊跟在主行下方
                df_receiving = df_receiving.sort_values(
                    by=["_sort_csv_idx", "_sort_sub"],
                    ascending=[True, True],
                    kind="stable"
                ).drop(columns=["_sort_csv_idx", "_sort_sub"])

                st.dataframe(df_receiving, use_container_width=True, hide_index=True)
                
                #  當前入庫單結案按鈕 (完成驗貨)
                st.markdown("---")
                archive_btn_label = " 完成本單驗貨（移至歷史存檔）" if st.session_state.lang == "zh" else " 検収完了（履歴に移動）"
                if st.button(archive_btn_label, type="primary", use_container_width=True, key=f"archive_order_btn_{selected_order}"):
                    db["manifest_by_order"][selected_order]["archived_order"] = True
                    save_data(db)
                    st.success(f"單據 {selected_order} 已成功結案並移至歷史存檔區域！")
                    st.rerun()
            else:
                st.info("無符合目前過濾條件的項目。" if st.session_state.lang == "zh" else "該当する項目がありません。")
# ==========================================
# PART 5: 整個完整的 Tab3 歷史單據區塊 (消滅負數升級版 - 上)
# ==========================================
with tab3:
    if st.session_state.lang == "zh":
        st.subheader("查詢")
    else:
        st.text(t["history_detail_title"])
        
    all_raw_orders = sorted(list(db["manifest_by_order"].keys()), reverse=True)
    
    if all_raw_orders:
        sorted_all_orders = []
        for o_no in all_raw_orders:
            doc = db["manifest_by_order"][o_no]
            # 💡 只有手動完成了「完成驗貨」結案的單據，才會判定進入歷史存檔
            if doc.get("archived_order") is True:
                sorted_all_orders.append(o_no)

        review_order_no_input = st.text_input("t3_search_input", value="", key="t3_archive_review_textinput", label_visibility="collapsed")
        review_order_no = review_order_no_input.strip()
        
        if review_order_no != "" and review_order_no in sorted_all_orders:
            target_doc = db["manifest_by_order"][review_order_no]
            target_info = target_doc.get("info", {})
            target_pool = target_doc.get("items", {})
            
            if st.session_state.lang == "zh":
                meta_df_t3 = pd.DataFrame([
                    {"欄位": "供應商", "內容": target_info.get("vendor", "-")},
                    {"欄位": "預計入庫日", "內容": target_info.get("expected_delivery", "-")},
                    {"欄位": "操作人員", "內容": target_info.get("operator", "-")}, # 👈 已修正為 }
                    {"欄位": "上傳日", "內容": target_info.get("upload_date", "-")}
                ])
            else:
                meta_df_t3 = pd.DataFrame([
                    {"項目": "仕入先", "content": target_info.get("vendor", "-")},
                    {"項目": "納品予定日", "content": target_info.get("expected_delivery", "-")},
                    {"項目": "担当者", "content": target_info.get("operator", "-")},
                    {"項目": "取込日時", "content": target_info.get("upload_date", "-")}
                ])
                
            st.dataframe(
                meta_df_t3, 
                hide_index=True,
                use_container_width=False,
                column_config={
                    "欄位": st.column_config.TextColumn(width="medium"),
                    "內容": st.column_config.TextColumn(width="large"),
                    "項目": st.column_config.TextColumn(width="medium"),
                    "content": st.column_config.TextColumn(label="内容", width="large")
                }
            )
            st.markdown("---")
            
            # 歷史追查大表的標頭同步根據語系純進化分流
            if st.session_state.lang == "zh":
                jan_col = "JAN 條碼"
                name_col = "商品名稱"
                req_col = "預計應到數量"
                act_col = "實到數量"
                short_col = "差異數量"
                lot_col = "Lot 批次"
                exp_col = "有效期限"
                status_col = "狀態"
            else:
                jan_col = "JAN Code"
                name_col = "商品名"
                req_col = "予定数"
                act_col = "納品数"
                short_col = "差異"
                lot_col = "ロット番号"
                exp_col = "賞味期限"
                status_col = "ステータス"

            # 💡【Tab3 歷史區核心合算門神】計算該 JAN 碼的總實到數量（主行+所有副行）
            jan_total_actual_map_t3 = {}
            for k, v in target_pool.items():
                real_jan = v.get("parent_jan", k) if v.get("is_sub_row") else k
                if real_jan not in jan_total_actual_map_t3:
                    jan_total_actual_map_t3[real_jan] = 0
                jan_total_actual_map_t3[real_jan] += v["actual_count"]

            report_list = []
            for k, v in target_pool.items():
                real_jan = v.get("parent_jan", k) if v.get("is_sub_row") else k
                
                # 💡【關鍵校正】副行預計數/差異數皆為 0；主行差異數扣除副行實到，避免產生負數
                if v.get("is_sub_row"):
                    calc_expected = 0
                    calc_shortage = 0
                    display_jan = real_jan
                else:
                    calc_expected = v["expected_count"]
                    calc_shortage = v["expected_count"] - jan_total_actual_map_t3.get(real_jan, 0)
                    display_jan = k
                
                if v.get("status") == "決收點貨":
                    item_status = "驗貨完畢" if st.session_state.lang == "zh" else "検収完了"
                else:
                    item_status = "未點收" if st.session_state.lang == "zh" else "未検収"
                
                report_list.append({
                    jan_col: display_jan,
                    name_col: v["name_ja"],
                    req_col: calc_expected,      
                    act_col: v["actual_count"],
                    short_col: calc_shortage,    
                    lot_col: v.get("lot_no", ""),
                    exp_col: v.get("expiry", ""),
                    status_col: item_status
                })
            if report_list:
                df_report = pd.DataFrame(report_list)
                # 💡【歷史區：精準 CSV 原始名冊順序黏合錨點】
                csv_original_order_t3 = {}
                order_idx_t3 = 0
                for item_key, item_val in target_pool.items():
                    if not item_val.get("is_sub_row"):
                        csv_original_order_t3[item_key] = order_idx_t3
                        order_idx_t3 += 1

                temp_sort_csv_idx_t3 = []
                temp_sort_is_sub_t3 = []

                for index, row in df_report.iterrows():
                    current_row_jan = str(row[jan_col]).strip()
                    pool_item_key = list(target_pool.keys())[index]
                    is_sub_flag = 1 if target_pool[pool_item_key].get("is_sub_row") else 0
                    
                    temp_sort_csv_idx_t3.append(csv_original_order_t3.get(current_row_jan, 9999))
                    temp_sort_is_sub_t3.append(is_sub_flag)

                df_report["_sort_csv_idx"] = temp_sort_csv_idx_t3
                df_report["_sort_sub"] = temp_sort_is_sub_t3

                # 執行雙層穩定排序
                df_report = df_report.sort_values(
                    by=["_sort_csv_idx", "_sort_sub"],
                    ascending=[True, True],
                    kind="stable"
                ).drop(columns=["_sort_csv_idx", "_sort_sub"])

                st.dataframe(df_report, use_container_width=True, hide_index=True)
                
                # 💡【核心修正】確保歷史單據下載的 Excel 同步套用無負數結構，維持與畫面完全一致
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                    df_report.to_excel(writer, index=False, sheet_name=f"Order_{review_order_no}")
                    
                st.download_button(
                    label=t["export_excel_btn"],
                    data=excel_buffer.getvalue(),
                    file_name=f"ARCHIVE_REPORT_{review_order_no}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"t3_excel_download_gate_{review_order_no}"
                )
        elif review_order_no != "" and review_order_no not in sorted_all_orders:
            if st.session_state.lang == "zh":
                st.error("該單據尚未完成點貨或單號不存在")
            else:
                st.error("伝票番号が正しくないか、検収が完了していません")
        st.markdown("---")
        if st.session_state.lang == "zh":
            st.text("歷史單據總覽")
        else:
            st.text(t["history_main_title"])
            
        archived_data = []
        for o_no in sorted_all_orders:
            doc = db["manifest_by_order"][o_no]
            pool = doc.get("items", {})
            total_items = len(pool)
            verified_items = sum(1 for item in pool.values() if item.get("status") == "決收點貨")
            info = doc.get("info", {})
            
            # 💡【精準三分法狀態分流：純中文版】
            if verified_items == total_items:
                status_label_zh = "全數驗收"
            elif verified_items > 0:
                status_label_zh = "部分驗收"
            else:
                status_label_zh = "未驗收"

            # 💡【精準三分法狀態分流：純日文版】
            if verified_items == total_items:
                status_label_ja = "全数検収"
            elif verified_items > 0:
                status_label_ja = "一部検収"
            else:
                status_label_ja = "未検収"
            
            if st.session_state.lang == "zh":
                archived_data.append({
                    "入庫單號": o_no,
                    "供應商": info.get("vendor", "-"),
                    "預計入庫日": info.get("expected_delivery", "-"),
                    "操作人員": info.get("operator", "-"),
                    "上傳日": info.get("upload_date", "-"),
                    "驗貨日期": info.get("upload_date", "-"),
                    "總品項數": total_items,
                    "狀態": status_label_zh
                })
            else:
                archived_data.append({
                    "伝票番号": o_no,
                    "仕入先": info.get("vendor", "-"),
                    "納品予定日": info.get("expected_delivery", "-"),
                    "担当者": info.get("operator", "-"),
                    "取込日時": info.get("upload_date", "-"),
                    "検収日": info.get("upload_date", "-"),
                    "総品目数": total_items,
                    "ステータス": status_label_ja
                })
                
        if archived_data:
            df_archived = pd.DataFrame(archived_data)
            df_archived.insert(0, "序號/項番", range(1, len(df_archived) + 1))
            st.dataframe(df_archived, use_container_width=True, hide_index=True)
        else:
            st.caption("-")
    else:
        st.caption("-")
# ==========================================
# PART 6: Tab4 實體盤點獨立雲端閘門
# ==========================================
with tab4:
    # --- 只在 Tab4 範圍內初始化 ---
    if "t4_form_key" not in st.session_state:
        st.session_state.t4_form_key = 0
    # ---------------------------

    # 確保語系邏輯與您的全域設定同步
    is_zh = getattr(st.session_state, "lang", "zh") == "zh"
    
    # 雙語輔助函式
    def _(zh, ja):
        return zh if is_zh else ja

    # 1. 物理隔離：建立專屬於 Tab 4 的本地變數與檔案，與全域獨立
    try:
        # 使用您原有的連線函式
        sheet_t4 = get_google_sheet("tab4")
        raw_data_t4 = sheet_t4.get_all_records()
        
        # 整理成原本程式預期的 t4_data 結構
        t4_data = {"inventory_sheets": {}}
        for row in raw_data_t4:
            # 💡 核心防禦：強制將從雲端讀出來的 sheet_id 轉為標準字串！
            s_id = str(row.get("sheet_id", "default")).strip() 
            
            if s_id not in t4_data["inventory_sheets"]:
                t4_data["inventory_sheets"][s_id] = {
                    "info": {
                        "operator": str(row.get("operator", "")),
                        "upload_date": str(row.get("upload_date", ""))
                    },
                    "items": []
                }
            
            # --- 關鍵修正：嚴格處理 is_counted ---
            val = row.get("is_counted", False)
            
            # 將各種可能的型別轉為布林值 (處理字串、空值、數字)
            if isinstance(val, str):
                row["is_counted"] = val.lower() in ['true', '1', 'yes']
            else:
                row["is_counted"] = bool(val)
            
            t4_data["inventory_sheets"][s_id]["items"].append(row)
            
    except Exception as e:
        st.error(f"雲端讀取失敗: {e}")
        t4_data = {"inventory_sheets": {}}

    # 2. 專屬存檔安全函式
    def _tab4_isolated_save(data_to_save):
        try:
            sheet = get_google_sheet("tab4")
            # 攤平資料：將字典轉回 DataFrame
            all_rows = []
            for s_id, content in data_to_save["inventory_sheets"].items():
                for item in content["items"]:
                    item["sheet_id"] = s_id  # 確保 sheet_id 有寫入
                    all_rows.append(item)
            
            df_to_save = pd.DataFrame(all_rows)
            
            # 清空並寫入 (先寫表頭，再寫資料)
            sheet.clear()
            if not df_to_save.empty:
                sheet.update([df_to_save.columns.values.tolist()] + df_to_save.values.tolist())
        except Exception as e:
            st.error(f"雲端存檔失敗: {e}")
    # 1. 導入新實體盤點名冊
    st.subheader(_("1. 盤點明細", "1. 棚卸データ"))
    
    col_inv_up1, col_inv_up2 = st.columns(2)
    with col_inv_up1:
        inv_sheet_id = st.text_input(_("盤點單號(必填)", "棚卸番号(必須)"), key=f"inv_sheet_id_input_t4_{st.session_state.t4_form_key}").strip()
    with col_inv_up2:
        inv_operator = st.text_input(_("盤點人員 (必填)", "担当者 (必須)"), key=f"inv_operator_input_t4_{st.session_state.t4_form_key}").strip()
        
    uploaded_inv_file = st.file_uploader(
        _("上傳盤點明細 CSV (格式: jan_code, name_ja, location, expiry, stock)", "棚卸明細CSVをアップロード (jan_code, name_ja, location, expiry, stock)"), 
        type=["csv"], 
        key=f"uploaded_inv_file_uploader_t4_{st.session_state.t4_form_key}"
    )
    
    if st.button(_("確認", "登録"), type="primary", key="submit_new_inv_sheet_btn_t4"):
        if not inv_sheet_id or not inv_operator or uploaded_inv_file is None:
            st.error(_("錯誤：請填寫盤點單號、人員並上傳 CSV 檔案", "エラー：棚卸番号、担当者、CSVファイルを入力・添付してください"))
        else:
            try:
                df_inv_upload = pd.read_csv(uploaded_inv_file, dtype={"jan_code": str, "location": str, "expiry": str})
                required_inv_cols = ["jan_code", "name_ja", "location", "expiry", "stock"]
                
                if all(col in df_inv_upload.columns for col in required_inv_cols):
                    t4_data["inventory_sheets"][inv_sheet_id] = {
                        "info": {
                            "operator": inv_operator,
                            "upload_date": datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                        },
                        "items": []
                    }
                    
                    for i, row in df_inv_upload.iterrows():
                        t4_data["inventory_sheets"][inv_sheet_id]["items"].append({
                            "jan_code": str(row["jan_code"]).strip(),
                            "name_ja": str(row["name_ja"]).strip(),
                            "location": str(row["location"]).strip() if pd.notna(row["location"]) else "",
                            "expiry": str(row["expiry"]).strip() if pd.notna(row["expiry"]) else "",
                            "stock": int(row["stock"]) if pd.notna(row["stock"]) else 0,
                            "is_counted": False,
                            "actual_stock": 0
                        })
                        
                    _tab4_isolated_save(t4_data)
                    st.session_state.t4_form_key += 1
                    st.session_state["clear_t4_form"] = True
                    st.session_state["msg_success"] = _(f"成功導入盤點明細：{inv_sheet_id}", f"棚卸明細 {inv_sheet_id} が登録されました")
                    st.rerun()
                else:
                    st.error(_("CSV欄位錯誤，必須包含: jan_code, name_ja, location, expiry, stock", "CSVヘッダー不正: jan_code, name_ja, location, expiry, stock"))
            except Exception as e:
                st.error(f"{_('解析錯誤', '解析エラー')}: {str(e)}")
    
    # 檢查是否有成功訊息
    if "msg_success" in st.session_state and st.session_state["msg_success"]:
        st.success(st.session_state["msg_success"])
        st.session_state["msg_success"] = None

    # 2. 選擇欲執行的盤點表單
    st.subheader(_("2. 選擇盤點表單", "2. 棚卸明細の選択"))
    sheet_options = list(t4_data["inventory_sheets"].keys())
    
    if sheet_options:
        sorted_sheets = sorted([str(opt) for opt in sheet_options if opt], reverse=True)
        
        col_select, col_delete = st.columns([4, 1])
        with col_select:
            selected_sheet = st.selectbox(
                _("請選擇盤點明細", "棚卸明細を選択してください"),
                options=sorted_sheets,
                key="active_inventory_sheet_selector_t4"
            )
        with col_delete:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(_("刪除", "削除"), key="del_btn_t4"):
                st.session_state["confirm_delete_t4"] = True
        
        # 刪除確認邏輯
        if st.session_state.get("confirm_delete_t4"):
            st.warning(_(f"確定要刪除盤點單 {selected_sheet} 嗎？", f"{selected_sheet} を削除しますか？"))
            d_c1, d_c2 = st.columns(2)
            if d_c1.button(_("確認刪除", "はい、削除します"), type="primary", key="confirm_del_btn_t4"):
                del t4_data["inventory_sheets"][selected_sheet]
                _tab4_isolated_save(t4_data)
                st.session_state["confirm_delete_t4"] = False
                st.rerun()
            if d_c2.button(_("取消", "いいえ"), key="cancel_del_btn_t4"):
                st.session_state["confirm_delete_t4"] = False
                st.rerun()

        if selected_sheet:
            current_sheet_data = t4_data["inventory_sheets"][selected_sheet]
            inventory_list = current_sheet_data.get("items", [])
            sheet_info = current_sheet_data.get("info", {})
            
            st.info(f"{_('目前操作內容', '選択伝票')}：{selected_sheet} | {_('建立時間', '登録時間')}：{sheet_info.get('upload_date')} | {_('盤點負責人', '担当者')}：{sheet_info.get('operator')}")
            
            # PDA 條碼掃描通道
            st.markdown(f"### {_(' 掃描條碼', 'バーコードスキャン')}")
            if f"scan_counter_{selected_sheet}" not in st.session_state:
                st.session_state[f"scan_counter_{selected_sheet}"] = 0
            
            scan_input_key = f"pda_box_{selected_sheet}_{st.session_state[f'scan_counter_{selected_sheet}']}"
            scan_input = st.text_input(_("請將游標停在此處並使用 PDA 刷條碼", "JANコードをスキャンしてください"), key=scan_input_key)
            if scan_input:
                scanned_jan = str(scan_input).strip()
                all_matches_indices = []
                for idx, item in enumerate(inventory_list):
                    item_jan = str(item.get("jan_code", "")).strip()
                    if item_jan == scanned_jan or item_jan.lstrip('0') == scanned_jan.lstrip('0'):
                        all_matches_indices.append(idx)
                
                if not all_matches_indices:
                    st.error(_(f"警告：條碼 {scanned_jan} 不在此明細中", f"警告：{scanned_jan} はこのリストにありません"))
                else:
                    st.markdown(f"### {_('條碼比對結果', 'バーコード照合結果')}")
                    st.warning(f"{_('商品品名', '商品名')}： {inventory_list[all_matches_indices[0]].get('name_ja', '未知商品')}")
                    
                    input_results = {}
                    allow_submit = True 
                    if len(all_matches_indices) > 1:
                        st.markdown(_("偵測到此商品有複數貨位或效期組合，請在下方確認並輸入數量：", "複数のロケーションまたは賞味期限が検出されました。数量を入力してください："))
                    
                    for m_idx in all_matches_indices:
                        target_item = inventory_list[m_idx]
                        has_counted = target_item.get("is_counted", False)
                        with st.container(border=True):
                            if has_counted:
                                st.error(_("提示：此商品之前已完成盤點！", "注意：この商品は既に棚卸完了しています！"))
                            col_det, col_warn = st.columns([3, 2])
                            with col_det:
                                st.markdown(f"{_('貨位', 'ロケーション')}： `{target_item.get('location', '無')}`")
                                st.markdown(f"{_('效期', '使用期限')}： `{target_item.get('expiry', '無')}`")
                                st.write(f"{_('庫存數', '在庫数')}: **{target_item.get('stock', 0)}**")
                            with col_warn:
                                if has_counted:
                                    override_check = st.checkbox(_("確認覆蓋原數據", "既存データを上書きする"), key=f"pda_override_check_{selected_sheet}_{m_idx}")
                                    if not override_check: allow_submit = False
                                    actual_input = st.number_input(_("重新輸入", "再入力"), min_value=0, value=int(target_item.get('actual_stock', 0)), step=1, key=f"pda_actual_input_retry_{selected_sheet}_{m_idx}", disabled=not override_check)
                                else:
                                    actual_input = st.number_input(_("請輸入盤點數量", "実棚数を入力"), min_value=0, value=int(target_item.get('stock', 0)), step=1, key=f"pda_actual_input_normal_{selected_sheet}_{m_idx}")
                                input_results[m_idx] = actual_input
                    
                    st.markdown(" ")
                    if st.button(_("確認提交", "確定"), type="primary", use_container_width=True, key=f"pda_confirm_all_btn_{selected_sheet}", disabled=not allow_submit):
                        for idx_key, qty_val in input_results.items():
                            t4_data["inventory_sheets"][selected_sheet]["items"][idx_key]["actual_stock"] = qty_val
                            t4_data["inventory_sheets"][selected_sheet]["items"][idx_key]["is_counted"] = True
                        _tab4_isolated_save(t4_data)
                        st.session_state[f"scan_counter_{selected_sheet}"] += 1
                        st.success(_("條碼資料已確認更新！", "データが更新されました！"))
                        st.rerun()

            # 3. 盤點進度動態清單
            st.markdown("---")
            st.markdown(f"### {_('盤點進度', '棚卸状況')}")
            uncounted_list = []
            counted_list = []
            for idx, item in enumerate(inventory_list):
                row_data = {
                    _("條碼 (JAN)", "JANコード"): item.get("jan_code", ""),
                    _("商品品名", "商品名"): item.get("name_ja", ""),
                    _("貨位", "ロケーション"): item.get("location", ""),
                    _("有效期限", "賞味期限"): item.get("expiry", ""),
                    _("在庫數", "實在庫数"): item.get("stock", 0)
                }
                if item.get("is_counted", False):
                    act_qty = item.get("actual_stock", 0)
                    row_data[_("盤點數", "實棚数")] = act_qty
                    row_data[_("庫存差異", "差異")] = act_qty - item.get("stock", 0)
                    counted_list.append(row_data)
                else:
                    uncounted_list.append(row_data)
            
            col_tab_left, col_tab_right = st.columns(2)
            with col_tab_left:
                st.markdown(f"{_('未盤點品項', '未棚卸品目')} ({len(uncounted_list)} {_('筆', '件')})")
                if uncounted_list:
                    st.dataframe(pd.DataFrame(uncounted_list), use_container_width=True, hide_index=True)
                else:
                    st.success(_("本張單據所有品項已全數盤點完畢", "すべての品目の棚卸が完了しました"))
            with col_tab_right:
                st.markdown(f"{_('已盤點品項', '棚卸完了品目')} ({len(counted_list)} {_('筆', '件')})")
                if counted_list:
                    st.dataframe(pd.DataFrame(counted_list), use_container_width=True, hide_index=True)
                else:
                    st.text(_("暫無已盤點數據", "データなし"))

            # 匯出報表
            st.markdown(" ")
            if inventory_list:
                full_report = []
                for item in inventory_list:
                    is_cnt = item.get("is_counted", False)
                    full_report.append({
                        "JAN Code": item.get("jan_code", ""), 
                        "商品名": item.get("name_ja", ""), 
                        "貨位": item.get("location", ""),
                        "有效期限": item.get("expiry", ""), 
                        "原系統庫存": item.get("stock", 0), 
                        "實際盤點數": item.get("actual_stock", 0) if is_cnt else _("未盤點", "未棚卸"),
                        "狀態": _("已盤點", "完了") if is_cnt else _("未盤點", "未完了")
                    })
                inv_excel_buffer = io.BytesIO()
                with pd.ExcelWriter(inv_excel_buffer, engine="openpyxl") as writer:
                    pd.DataFrame(full_report).to_excel(writer, index=False, sheet_name="棚卸実績")
                st.download_button(
                    label=_("匯出 Excel", "Excel出力"), 
                    data=inv_excel_buffer.getvalue(),
                    file_name=f"INV_{selected_sheet}_{datetime.date.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"inv_excel_download_t4_{selected_sheet}"
                )
    else:
        st.warning(_("目前系統中尚無任何盤點明細，請由上方區域導入您的第一張 CSV 盤點明細", "棚卸伝票がありません。上のフォームからインポートしてください。"))
