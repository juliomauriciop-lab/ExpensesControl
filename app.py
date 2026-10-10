import streamlit as st
import pandas as pd
import google.generativeai as genai
from datetime import date, datetime
import calendar
import json
import io
from streamlit_gsheets import GSheetsConnection

# Setup Gemini API
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Setup Google Sheets Connection
conn = st.connection("gsheets", type=GSheetsConnection)

PERSONS = ["Mariel", "Mauricio"] 
ASSIGN_OPTIONS = ["Mariel", "Mauricio", "Mariel & Mauricio (split)"] 
CATEGORIES = ["Health", "Household items", "Leisure", "Rent", "Studies", "Transport", "Clothes", "Food", "Other"]

CARD_OWNERS = {
    "7931": "Mauricio",
    "2090": "Mauricio",
    "7526": "Mariel"
}

def load_data():
    try:
        df = conn.read(worksheet="Expenses", usecols=list(range(8)), ttl=0)
        df = df.dropna(how="all")
        if "Date" in df.columns:
            # Convertimos a datetime para permitir filtrado mensual robusto
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        if df.empty or len(df.columns) < 8:
            return pd.DataFrame(columns=["Date", "Person", "Category", "Amount", "Merchant", "Note", "Card Number", "Who Paid"])
        return df
    except Exception as e:
        return pd.DataFrame(columns=["Date", "Person", "Category", "Amount", "Merchant", "Note", "Card Number", "Who Paid"])

def save_data_to_sheet(df):
    df_upload = df.copy()
    if "Date" in df_upload.columns:
        # Formateamos las fechas de vuelta a string limpio para Google Sheets
        df_upload["Date"] = pd.to_datetime(df_upload["Date"]).dt.strftime('%Y-%m-%d')
    conn.update(worksheet="Expenses", data=df_upload)
    st.cache_data.clear()

def save_expense(data):
    df = load_data()
    df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
    save_data_to_sheet(df)

def save_multiple_expenses(data_list):
    df = load_data()
    df = pd.concat([df, pd.DataFrame(data_list)], ignore_index=True)
    save_data_to_sheet(df)

def detect_who_paid(card_number_str):
    if card_number_str:
        for card, owner in CARD_OWNERS.items():
            if card in str(card_number_str):
                return owner
    return PERSONS[0]

# --- Navegación Mensual Global ---
if "month_offset" not in st.session_state:
    st.session_state.month_offset = 0

def render_month_nav(key_prefix):
    today = date.today()
    m = today.month - 1 + st.session_state.month_offset
    y = today.year + m // 12
    m = m % 12 + 1
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("◀ Previous", key=f"prev_{key_prefix}", use_container_width=True):
            st.session_state.month_offset -= 1
            st.rerun()
    with col2:
        st.markdown(f"<h3 style='text-align: center; margin-top: -10px;'>{calendar.month_name[m]} {y}</h3>", unsafe_allow_html=True)
    with col3:
        if st.button("Next ▶", key=f"next_{key_prefix}", use_container_width=True):
            st.session_state.month_offset += 1
            st.rerun()
    return m, y

st.set_page_config(page_title="Expense Tracker", layout="wide")
st.title("Expense Tracker - Mariel & Mauricio")

if "receipt_processed" not in st.session_state:
    st.session_state.receipt_processed = False
if "receipt_data" not in st.session_state:
    st.session_state.receipt_data = None
if "receipt_items" not in st.session_state:
    st.session_state.receipt_items = None

tab1, tab2, tab3, tab4 = st.tabs(["Add Expense", "Dashboard", "History", "Export"])

with tab1:
    st.header("Record Expenses")
    input_method = st.radio("Method", ["Upload Receipt", "Manual Entry"], horizontal=True, label_visibility="collapsed")
    st.divider()
    
    if input_method == "Upload Receipt":
        st.subheader("1. Upload and Process Receipt")
        uploaded_file = st.file_uploader("Upload receipt image", type=["jpg", "png", "jpeg"])
        
        if uploaded_file is not None:
            if st.button("Read Receipt with AI"):
                if "GEMINI_API_KEY" not in st.secrets:
                    st.error("API Key is missing in secrets.")
                else:
                    with st.spinner("Analyzing receipt and categorizing items..."):
                        try:
                            model = genai.GenerativeModel('gemini-3.8-flash')
                            image_parts = [{"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}]
                            
                            prompt = f"""
                            Analyze this receipt image. Extract the information and output ONLY a valid JSON object with this exact structure, with no extra text or markdown formatting:
                            {{
                                "merchant": "Name of the store",
                                "date": "YYYY-MM-DD",
                                "total_amount": 0.0,
                                "card_number": "Payment Method or Last 4 digits",
                                "items": [
                                    {{
                                        "name": "item name", 
                                        "price": 0.0, 
                                        "category": "Choose the best match from: {', '.join(CATEGORIES)}. Default to 'Other'."
                                    }}
                                ]
                            }}
                            """
                            response = model.generate_content([prompt, image_parts[0]])
                            text_response = response.text.strip().replace("```json", "").replace("```", "")
                            extracted_data = json.loads(text_response.strip(), strict=False)
                            
                            items = extracted_data.get("items", [])
                            df_items = pd.DataFrame(items)
                            
                            if not df_items.empty:
                                if "category" not in df_items.columns:
                                    df_items["category"] = "Other"
                                df_items["category"] = df_items["category"].apply(lambda x: x if x in CATEGORIES else "Other")
                                df_items["Assign To"] = "Mariel & Mauricio (split)"
                            
                            st.session_state.receipt_processed = True
                            st.session_state.receipt_data = extracted_data
                            st.session_state.receipt_items = df_items
                            st.toast("✅ Receipt processed successfully!")
                            
                        except Exception as e:
                            st.error(f"Could not read the receipt automatically. Error details: {str(e)}")
        
        if st.session_state.receipt_processed and st.session_state.receipt_items is not None:
            st.divider()
            
            # Split Screen View
            col_img, col_data = st.columns([1, 2])
            
            with col_img:
                st.image(uploaded_file, caption="Scanned Receipt", use_container_width=True)
                
            with col_data:
                st.subheader("2. Review and Edit")
                merchant_val = st.session_state.receipt_data.get('merchant', '')
                card_val = st.session_state.receipt_data.get('card_number', '')
                receipt_date_str = st.session_state.receipt_data.get('date', '')
                
                parsed_date = date.today()
                if receipt_date_str:
                    try:
                        parsed_date = datetime.strptime(receipt_date_str, "%Y-%m-%d").date()
                    except ValueError:
                        pass
                
                detected_payer = detect_who_paid(card_val)
                payer_index = PERSONS.index(detected_payer) if detected_payer in PERSONS else 0
                
                col_a, col_b = st.columns(2)
                with col_a:
                    exp_date = st.date_input("Receipt Date", value=parsed_date, format="DD/MM/YYYY")
                    merchant = st.text_input("Merchant", value=merchant_val)
                with col_b:
                    card_number_input = st.text_input("Card Number", value=card_val)
                    who_paid = st.radio("Who paid?", PERSONS, index=payer_index, horizontal=True)
                    
                st.write("✏️ **Double-click any cell below to change Category or Assignment:**")
                
                col_btn1, col_btn2, col_btn3 = st.columns(3)
                if col_btn1.button("Assign All: Mauricio", use_container_width=True):
                    st.session_state.receipt_items["Assign To"] = "Mauricio"
                    st.rerun()
                if col_btn2.button("Assign All: Mariel", use_container_width=True):
                    st.session_state.receipt_items["Assign To"] = "Mariel"
                    st.rerun()
                if col_btn3.button("Assign All: Split", use_container_width=True):
                    st.session_state.receipt_items["Assign To"] = "Mariel & Mauricio (split)"
                    st.rerun()
                    
                edited_df = st.data_editor(
                    st.session_state.receipt_items,
                    column_config={
                        "name": "Item Name",
                        "price": st.column_config.NumberColumn("Price", format="£%.2f", min_value=0.0),
                        "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
                        "Assign To": st.column_config.SelectboxColumn("Assign To", options=ASSIGN_OPTIONS, required=True)
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                st.session_state.receipt_items = edited_df
                
                total_mariel = sum([float(r.get("price", 0)) for _, r in edited_df.iterrows() if r.get("Assign To") == "Mariel"])
                total_mauricio = sum([float(r.get("price", 0)) for _, r in edited_df.iterrows() if r.get("Assign To") == "Mauricio"])
                total_split = sum([float(r.get("price", 0)) / 2 for _, r in edited_df.iterrows() if r.get("Assign To") == "Mariel & Mauricio (split)"])
                
                grand_mariel = total_mariel + total_split
                grand_mauricio = total_mauricio + total_split
                
                st.info(f"**Total:** Mariel: **£{grand_mariel:.2f}** | Mauricio: **£{grand_mauricio:.2f}** | Grand Total: **£{grand_mariel + grand_mauricio:.2f}**")
                
                if st.button("Save All Receipt Items", type="primary", use_container_width=True):
                    expenses_to_save = []
                    for _, row in edited_df.iterrows():
                        expenses_to_save.append({
                            "Date": exp_date, 
                            "Person": row.get("Assign To", "Mariel & Mauricio (split)"), 
                            "Category": row.get("category", "Other"), 
                            "Amount": float(row.get("price", 0.0)), 
                            "Merchant": merchant, 
                            "Note": row.get("name", "Item"), 
                            "Card Number": card_number_input, 
                            "Who Paid": who_paid
                        })
                    save_multiple_expenses(expenses_to_save)
                    st.session_state.receipt_processed = False
                    st.session_state.receipt_data = None
                    st.session_state.receipt_items = None
                    st.toast("✅ All items saved successfully!")
                    st.rerun()
                
    else:
        # Manual Entry with UI Improvements
        with st.form("expense_form"):
            col1, col2 = st.columns(2)
            with col1:
                exp_date = st.date_input("Date", date.today(), format="DD/MM/YYYY")
                person = st.radio("Person", ASSIGN_OPTIONS, horizontal=True)
                merchant = st.text_input("Merchant")
                note = st.text_input("Note")
            with col2:
                amount = st.number_input("Amount (£)", min_value=0.0, step=0.01)
                who_paid = st.radio("Who Paid?", PERSONS, horizontal=True)
                card_number = st.text_input("Card / Last 4 Digits")
                
            st.write("**Category**")
            category = st.radio("Category", CATEGORIES, horizontal=True, label_visibility="collapsed")
            
            submitted = st.form_submit_button("Save Expense", type="primary", use_container_width=True)
            if submitted:
                save_expense({
                    "Date": exp_date, "Person": person, "Category": category, 
                    "Amount": amount, "Merchant": merchant, "Note": note, 
                    "Card Number": card_number, "Who Paid": who_paid
                })
                st.toast("✅ Expense saved successfully!")

with tab2:
    st.header("Dashboard")
    current_m, current_y = render_month_nav("dash")
    st.divider()
    
    df = load_data()
    if not df.empty and "Date" in df.columns:
        # Filter by selected month
        month_mask = (df["Date"].dt.month == current_m) & (df["Date"].dt.year == current_y)
        month_df = df[month_mask].copy()
        
        if not month_df.empty:
            # Prepare data for metrics and charts (Splits divided)
            eff_df_list = []
            for _, row in month_df.iterrows():
                if row["Person"] == "Mariel & Mauricio (split)":
                    r1, r2 = row.copy(), row.copy()
                    r1["Person"], r2["Person"] = "Mariel", "Mauricio"
                    r1["Amount"] = r2["Amount"] = float(row["Amount"]) / 2
                    eff_df_list.extend([r1, r2])
                else:
                    eff_df_list.append(row)
                    
            eff_df = pd.DataFrame(eff_df_list)
            
            # --- KPI Metrics ---
            total_month = eff_df["Amount"].sum()
            mariel_total = eff_df[eff_df["Person"] == "Mariel"]["Amount"].sum()
            mauricio_total = eff_df[eff_df["Person"] == "Mauricio"]["Amount"].sum()
            
            m1, m2, m3 = st.columns(3)
            m1.metric("💰 Total Month", f"£{total_month:.2f}")
            m2.metric("👩 Mariel Total", f"£{mariel_total:.2f}")
            m3.metric("👨 Mauricio Total", f"£{mauricio_total:.2f}")
            st.divider()
            
            st.write("📊 **Filters**")
            selected_person = st.radio("Filter charts by:", ["All", "Mariel", "Mauricio"], horizontal=True)
            plot_df = eff_df[eff_df["Person"] == selected_person] if selected_person != "All" else eff_df
                
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                st.subheader("Cumulative Expenses (Daily)")
                
                line_df = plot_df.copy().sort_values("Date")
                
                if not line_df.empty:
                    if selected_person == "All":
                        daily_sum = line_df.groupby(["Date", "Person"])["Amount"].sum().reset_index()
                        daily_pivot = daily_sum.pivot(index="Date", columns="Person", values="Amount").fillna(0)
                        cumulative_df = daily_pivot.cumsum()
                    else:
                        daily_sum = line_df.groupby("Date")["Amount"].sum().reset_index()
                        daily_sum = daily_sum.set_index("Date")
                        cumulative_df = daily_sum.cumsum()
                        
                    # Convertir el eje X a texto (Día/Mes) para eliminar las horas
                    cumulative_df.index = cumulative_df.index.strftime('%d/%m')
                    
                    st.line_chart(cumulative_df)
                else:
                    st.info("Not enough data for line chart.")
            with col_c2:
                st.subheader("Expenses by Category")
                if selected_person == "All":
                    st.bar_chart(plot_df.groupby(["Person", "Category"])["Amount"].sum().unstack())
                else:
                    st.bar_chart(plot_df.groupby("Category")["Amount"].sum())
        else:
            st.info("No expenses recorded for this month.")
    else:
        st.info("No expenses recorded yet in Google Sheets.")

with tab3:
    st.header("Expense History")
    current_m, current_y = render_month_nav("hist")
    st.divider()
    
    df = load_data()
    if not df.empty and "Date" in df.columns:
        month_mask = (df["Date"].dt.month == current_m) & (df["Date"].dt.year == current_y)
        display_df = df[month_mask].copy()
        
        if not display_df.empty:
            filter_person = st.radio("Filter History:", ["All"] + ASSIGN_OPTIONS, horizontal=True)
            if filter_person != "All":
                display_df = display_df[display_df["Person"] == filter_person]
                
            st.write("✏️ Edit cells or delete rows below. Click **Save Changes** when finished.")
            
            edited_history = st.data_editor(
                display_df, 
                num_rows="dynamic", 
                use_container_width=True,
                column_config={
                    "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                    "Amount": st.column_config.NumberColumn("Amount", format="£%.2f")
                }
            )
            
            if st.button("Save Changes to History", type="primary"):
                original_df = df.copy()
                
                deleted_indices = set(display_df.index) - set(edited_history.index)
                original_df = original_df.drop(index=deleted_indices)
                
                modified_rows = edited_history[edited_history.index.isin(original_df.index)]
                original_df.update(modified_rows)
                
                new_rows = edited_history[~edited_history.index.isin(original_df.index)]
                if not new_rows.empty:
                    original_df = pd.concat([original_df, new_rows])
                    
                save_data_to_sheet(original_df)
                st.toast("✅ History updated successfully!")
                st.rerun()
        else:
            st.info("No expenses recorded for this month.")
    else:
        st.info("No expenses recorded yet.")

with tab4:
    st.header("Export Data")
    df = load_data()
    if not df.empty:
        # Restaurar a string antes de exportar para no tener problemas en Excel
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime('%d/%m/%Y')
        excel_data = io.BytesIO()
        with pd.ExcelWriter(excel_data, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Expenses')
        
        st.download_button(
            label="Download Complete Excel Report",
            data=excel_data.getvalue(),
            file_name="Expense_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("No data available to export.")
