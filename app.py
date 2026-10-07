import streamlit as st
import pandas as pd
import google.generativeai as genai
from datetime import date
import json
import os
import io

# Setup Gemini API (The key will be stored in Streamlit Cloud Secrets)
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

DATA_FILE = "expenses.csv"
PERSONS = ["Mariel", "Mauricio"]
ASSIGN_OPTIONS = ["Mariel", "Mauricio", "Split"]
CATEGORIES = ["Health", "Household items", "Leisure", "Rent", "Studies", "Transport", "Clothes", "Food", "Other"]

def load_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    return pd.DataFrame(columns=["Date", "Person", "Category", "Amount", "Merchant", "Note", "Card Number", "Who Paid", "Split"])

def save_expense(data):
    df = load_data()
    df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

def save_multiple_expenses(data_list):
    df = load_data()
    df = pd.concat([df, pd.DataFrame(data_list)], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

st.set_page_config(page_title="Expense Tracker", layout="wide")
st.title("Expense Tracker - Mariel & Mauricio")

# Initialize session state for receipt processing
if "receipt_processed" not in st.session_state:
    st.session_state.receipt_processed = False
if "receipt_data" not in st.session_state:
    st.session_state.receipt_data = None
if "receipt_items" not in st.session_state:
    st.session_state.receipt_items = None

tab1, tab2, tab3 = st.tabs(["Add Expense", "Dashboard", "Export"])

with tab1:
    st.header("Record Expenses")
    
    # Choose between uploading a receipt or entering manually
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
                            # Using the specific required model
                            model = genai.GenerativeModel('gemini-3.8-flash')
                            image_parts = [{"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}]
                            
                            # Prompt instructing the AI to auto-categorize
                            prompt = f"""
                            Analyze this receipt image. Extract the information and output ONLY a valid JSON object with this exact structure, with no extra text or markdown formatting:
                            {{
                                "merchant": "Name of the store",
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
                                
                            extracted_data = json.loads(text_response.strip())
                            
                            items = extracted_data.get("items", [])
                            df_items = pd.DataFrame(items)
                            
                            if not df_items.empty:
                                if "category" not in df_items.columns:
                                    df_items["category"] = "Other"
                                # Ensure AI didn't invent a category
                                df_items["category"] = df_items["category"].apply(lambda x: x if x in CATEGORIES else "Other")
                                # Default assign to Split
                                df_items["Assign To"] = "Split"
                            
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
            
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                exp_date = st.date_input("Receipt Date", date.today())
            with col_b:
                merchant = st.text_input("Merchant", value=merchant_val)
            with col_c:
                who_paid = st.selectbox("Who paid the total?", PERSONS)
                
            st.write("✏️ **Double-click any cell below to change the Category or who the item belongs to:**")
            
            # Interactive editable table
            edited_df = st.data_editor(
                st.session_state.receipt_items,
                column_config={
                    "name": "Item Name",
                    "price": st.column_config.NumberColumn("Price", format="$%.2f", min_value=0.0),
                    "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
                    "Assign To": st.column_config.SelectboxColumn("Assign To", options=ASSIGN_OPTIONS, required=True)
                },
                hide_index=True,
                use_container_width=True
            )
            
            # Dynamic Summary Calculations
            st.subheader("3. Summary Before Saving")
            total_mariel = 0.0
            total_mauricio = 0.0
            
            for _, row in edited_df.iterrows():
                p = float(row.get("price", 0.0))
                assign = row.get("Assign To", "Split")
                if assign == "Mariel":
                    total_mariel += p
                elif assign == "Mauricio":
                    total_mauricio += p
                else:
                    total_mariel += (p / 2)
                    total_mauricio += (p / 2)
                    
            st.info(f"**Total to register:** Mariel: **${total_mariel:.2f}** | Mauricio: **${total_mauricio:.2f}** | Grand Total: **${total_mariel + total_mauricio:.2f}**")
            
            if st.button("Save All Receipt Items as Expenses", type="primary"):
                expenses_to_save = []
                
                for _, row in edited_df.iterrows():
                    item_name = row.get("name", "Item")
                    price = float(row.get("price", 0.0))
                    cat = row.get("category", "Other")
                    assign = row.get("Assign To", "Split")
                    
                    if assign == "Split":
                        expenses_to_save.append({"Date": exp_date, "Person": "Mariel", "Category": cat, "Amount": price/2, "Merchant": merchant, "Note": item_name, "Card Number": card_val, "Who Paid": who_paid, "Split": True})
                        expenses_to_save.append({"Date": exp_date, "Person": "Mauricio", "Category": cat, "Amount": price/2, "Merchant": merchant, "Note": item_name, "Card Number": card_val, "Who Paid": who_paid, "Split": True})
                    else:
                        expenses_to_save.append({"Date": exp_date, "Person": assign, "Category": cat, "Amount": price, "Merchant": merchant, "Note": item_name, "Card Number": card_val, "Who Paid": who_paid, "Split": False})
                
                save_multiple_expenses(expenses_to_save)
                
                # Reset state after saving
                st.session_state.receipt_processed = False
                st.session_state.receipt_data = None
                st.session_state.receipt_items = None
                st.success("All items saved successfully! You can check the Dashboard.")
                
    else:
        st.subheader("Manual Expense Details")
        with st.form("expense_form"):
            col1, col2 = st.columns(2)
            with col1:
                exp_date = st.date_input("Date", date.today())
                person = st.selectbox("Person (Who does this expense belong to?)", PERSONS)
                category = st.selectbox("Category", CATEGORIES)
                merchant = st.text_input("Merchant")
                note = st.text_input("Note")
            with col2:
                amount = st.number_input("Amount", min_value=0.0, step=0.01)
                card_number = st.text_input("Card Number / Payment Method")
                who_paid = st.selectbox("Who Paid?", PERSONS)
                split = st.checkbox("Split 50/50 between Mariel and Mauricio?")
                
            submitted = st.form_submit_button("Save Expense")
            
            if submitted:
                if split:
                    amount_per_person = amount / 2
                    for p in PERSONS:
                        expense = {"Date": exp_date, "Person": p, "Category": category, "Amount": amount_per_person, 
                                   "Merchant": merchant, "Note": note, "Card Number": card_number, "Who Paid": who_paid, "Split": True}
                        save_expense(expense)
                else:
                    expense = {"Date": exp_date, "Person": person, "Category": category, "Amount": amount, 
                               "Merchant": merchant, "Note": note, "Card Number": card_number, "Who Paid": who_paid, "Split": False}
                    save_expense(expense)
                st.success("Expense saved successfully!")

with tab2:
    st.header("Dashboard & Visualizations")
    df = load_data()
    if not df.empty:
        st.subheader("Total Expenses per Person")
        st.bar_chart(df.groupby("Person")["Amount"].sum())
        
        st.subheader("Recent Expenses")
        st.dataframe(df.tail(15))
    else:
        st.info("No expenses recorded yet.")

with tab3:
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
