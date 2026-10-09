import streamlit as st
import pandas as pd
import google.generativeai as genai
from datetime import date, datetime
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
        # ttl=0 obliga a Streamlit a descargar siempre la versión en vivo de Google Sheets, ignorando la caché
        df = conn.read(worksheet="Expenses", usecols=list(range(8)), ttl=0)
        df = df.dropna(how="all")
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
        if df.empty or len(df.columns) < 8:
            return pd.DataFrame(columns=["Date", "Person", "Category", "Amount", "Merchant", "Note", "Card Number", "Who Paid"])
        return df
    except Exception as e:
        return pd.DataFrame(columns=["Date", "Person", "Category", "Amount", "Merchant", "Note", "Card Number", "Who Paid"])

def save_data_to_sheet(df):
    df_upload = df.copy()
    if "Date" in df_upload.columns:
        df_upload["Date"] = df_upload["Date"].astype(str)
    
    # Sobrescribe el sheet con la data actualizada
    conn.update(worksheet="Expenses", data=df_upload)
    
    # Limpia cualquier caché residual en la memoria de la app
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

st.set_page_config(page_title="Expense Tracker", layout="wide")
st.title("Expense Tracker - Mariel & Mauricio")

if "receipt_processed" not in st.session_state:
    st.session_state.receipt_processed = False
if "receipt_data" not in st.session_state:
    st.session_state.receipt_data = None
if "receipt_items" not in st.session_state:
    st.session_state.receipt_items = None

tab1, tab2, tab3, tab4 = st.tabs(["Add Expense", "Dashboard", "History (Edit Data)", "Export"])

with tab1:
    st.header("Record Expenses")
    
    input_method = st.radio("How do you want to add an expense?", ["Upload Receipt", "Manual Entry"])
    
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
                            Analyze this receipt image. Extract the information and output ONLY a valid JSON object with this exact structure, with no extra text or markdown formatting. 
                            IMPORTANT: Do NOT include literal newlines, tabs, or unescaped control characters inside the string values:
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
                            
                            text_response = response.text.strip()
                            if text_response.startswith("```json"):
                                text_response = text_response[7:]
                            if text_response.endswith("```"):
                                text_response = text_response[:-3]
                                
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
                            st.success("Receipt processed successfully!")
                            
                        except Exception as e:
                            st.error(f"Could not read the receipt automatically. Error details: {str(e)}")
        
        if st.session_state.receipt_processed and st.session_state.receipt_items is not None:
            st.divider()
            st.subheader("2. Review and Edit Receipt Items")
            
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
            
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                exp_date = st.date_input("Receipt Date", value=parsed_date, format="DD/MM/YYYY")
            with col_b:
                merchant = st.text_input("Merchant", value=merchant_val)
            with col_c:
                card_number_input = st.text_input("Card Number", value=card_val)
            with col_d:
                who_paid = st.selectbox("Who paid the total?", PERSONS, index=payer_index)
                
            st.write("✏️ **Double-click any cell below to change the Category or who the item belongs to:**")
            
            col_btn1, col_btn2, col_btn3 = st.columns(3)
            if col_btn1.button("Assign All to Mauricio"):
                st.session_state.receipt_items["Assign To"] = "Mauricio"
                st.rerun()
            if col_btn2.button("Assign All to Mariel"):
                st.session_state.receipt_items["Assign To"] = "Mariel"
                st.rerun()
            if col_btn3.button("Assign All to Split"):
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
            
            st.subheader("3. Summary Before Saving")
            total_mariel = 0.0
            total_mauricio = 0.0
            
            for _, row in edited_df.iterrows():
                p = float(row.get("price", 0.0))
                assign = row.get("Assign To", "Mariel & Mauricio (split)")
                if assign == "Mariel":
                    total_mariel += p
                elif assign == "Mauricio":
                    total_mauricio += p
                else:
                    total_mariel += (p / 2)
                    total_mauricio += (p / 2)
                    
            st.info(f"**Total to register:** Mariel: **£{total_mariel:.2f}** | Mauricio: **£{total_mauricio:.2f}** | Grand Total: **£{total_mariel + total_mauricio:.2f}**")
            
            if st.button("Save All Receipt Items as Expenses", type="primary"):
                expenses_to_save = []
                
                for _, row in edited_df.iterrows():
                    item_name = row.get("name", "Item")
                    price = float(row.get("price", 0.0))
                    cat = row.get("category", "Other")
                    assign = row.get("Assign To", "Mariel & Mauricio (split)")
                    
                    expenses_to_save.append({
                        "Date": exp_date, 
                        "Person": assign, 
                        "Category": cat, 
                        "Amount": price, 
                        "Merchant": merchant, 
                        "Note": item_name, 
                        "Card Number": card_number_input, 
                        "Who Paid": who_paid
                    })
                
                save_multiple_expenses(expenses_to_save)
                
                st.session_state.receipt_processed = False
                st.session_state.receipt_data = None
                st.session_state.receipt_items = None
                st.success("All items saved successfully! You can check the History tab.")
                st.rerun()
                
    else:
        st.subheader("Manual Expense Details")
        with st.form("expense_form"):
            col1, col2 = st.columns(2)
            with col1:
                exp_date = st.date_input("Date", date.today(), format="DD/MM/YYYY")
                person = st.selectbox("Person (Who does this expense belong to?)", ASSIGN_OPTIONS)
                category = st.selectbox("Category", CATEGORIES)
                merchant = st.text_input("Merchant")
                note = st.text_input("Note")
            with col2:
                amount = st.number_input("Amount (£)", min_value=0.0, step=0.01)
                card_number = st.text_input("Card Number / Payment Method")
                who_paid = st.selectbox("Who Paid?", PERSONS)
                
            submitted = st.form_submit_button("Save Expense")
            
            if submitted:
                expense = {
                    "Date": exp_date, 
                    "Person": person, 
                    "Category": category, 
                    "Amount": amount, 
                    "Merchant": merchant, 
                    "Note": note, 
                    "Card Number": card_number, 
                    "Who Paid": who_paid
                }
                save_expense(expense)
                st.success("Expense saved successfully!")

with tab2:
    st.header("Dashboard & Visualizations")
    df = load_data()
    if not df.empty:
        st.write("📊 **Filters**")
        selected_person = st.selectbox("Filter charts by Person", ["All", "Mariel", "Mauricio"])
        
        eff_df_list = []
        for _, row in df.iterrows():
            if row["Person"] == "Mariel & Mauricio (split)":
                r1 = row.copy()
                r1["Person"] = "Mariel"
                r1["Amount"] = float(row["Amount"]) / 2
                
                r2 = row.copy()
                r2["Person"] = "Mauricio"
                r2["Amount"] = float(row["Amount"]) / 2
                
                eff_df_list.extend([r1, r2])
            else:
                eff_df_list.append(row)
                
        eff_df = pd.DataFrame(eff_df_list)
        
        if selected_person != "All":
            plot_df = eff_df[eff_df["Person"] == selected_person]
        else:
            plot_df = eff_df
            
        st.subheader(f"Total Expenses ({'All' if selected_person == 'All' else selected_person})")
        st.caption("Note: 'Split' expenses are automatically divided 50/50 between Mariel and Mauricio for accurate chart representation.")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.bar_chart(plot_df.groupby("Person")["Amount"].sum())
            
        with col_c2:
            if selected_person == "All":
                category_totals = plot_df.groupby(["Person", "Category"])["Amount"].sum().unstack()
                st.bar_chart(category_totals)
            else:
                category_totals = plot_df.groupby("Category")["Amount"].sum()
                st.bar_chart(category_totals)
    else:
        st.info("No expenses recorded yet in Google Sheets.")

with tab3:
    st.header("Expense History")
    df = load_data()
    if not df.empty:
        filter_person = st.selectbox("Filter History by Person", ["All"] + ASSIGN_OPTIONS)
        
        if filter_person != "All":
            display_df = df[df["Person"] == filter_person].copy()
        else:
            display_df = df.copy()
            
        st.write("✏️ You can edit the cells below or delete rows. Click 'Save Changes' below when finished.")
        
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
            if filter_person != "All":
                original_df = df.copy()
                
                deleted_indices = set(display_df.index) - set(edited_history.index)
                original_df = original_df.drop(index=deleted_indices)
                
                modified_rows = edited_history[edited_history.index.isin(original_df.index)]
                original_df.update(modified_rows)
                
                new_rows = edited_history[~edited_history.index.isin(original_df.index)]
                if not new_rows.empty:
                    original_df = pd.concat([original_df, new_rows])
                    
                save_data_to_sheet(original_df)
            else:
                save_data_to_sheet(edited_history)
                
            st.success("History updated successfully in Google Sheets!")
            st.rerun()
    else:
        st.info("No expenses recorded yet in Google Sheets.")

with tab4:
    st.header("Export Data")
    df = load_data()
    if not df.empty:
        excel_data = io.BytesIO()
        with pd.ExcelWriter(excel_data, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Expenses')
        
        st.download_button(
            label="Download Excel Report",
            data=excel_data.getvalue(),
            file_name="Expense_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.warning("No data available to export.")
