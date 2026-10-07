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
CATEGORIES = ["Health", "Household items", "Leisure", "Rent", "Studies", "Transport", "Clothes", "Food", "Other"]

def load_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    return pd.DataFrame(columns=["Date", "Person", "Category", "Amount", "Merchant", "Note", "Card Number", "Who Paid", "Split"])

def save_expense(data):
    df = load_data()
    df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

st.set_page_config(page_title="Expense Tracker", layout="wide")
st.title("Expense Tracker - Mariel & Mauricio")

tab1, tab2, tab3 = st.tabs(["Add Expense", "Dashboard", "Export"])

with tab1:
    st.header("Record a New Expense")
    
    # Receipt Scanner Section
    st.subheader("1. Attach a Receipt (Optional)")
    uploaded_file = st.file_uploader("Upload receipt image", type=["jpg", "png", "jpeg"])
    extracted_data = {}
    
    if uploaded_file is not None:
            if st.button("Read Receipt with AI"):
                if "GEMINI_API_KEY" not in st.secrets:
                    st.error("API Key is missing in secrets.")
                else:
                    with st.spinner("Analyzing receipt..."):
                        try:
                            # Usamos el modelo estándar actual de visión
                            model = genai.GenerativeModel('gemini-3.8-flash')
                            
                            image_parts = [{"mime_type": uploaded_file.type, "data": uploaded_file.getvalue()}]
                            
                            prompt = """
                            Analyze this receipt image. Extract the information and output ONLY a valid JSON object with this exact structure, with no extra text or markdown formatting outside of it:
                            {
                                "merchant": "Name of the store",
                                "total_amount": 0.0,
                                "card_number": "Payment Method or Last 4 digits",
                                "items": [{"name": "item name", "price": 0.0}]
                            }
                            """
                            
                            response = model.generate_content([prompt, image_parts[0]])
                            
                            # Limpieza robusta del texto devuelto por la IA
                            text_response = response.text.strip()
                            if text_response.startswith("```json"):
                                text_response = text_response[7:]
                            if text_response.endswith("```"):
                                text_response = text_response[:-3]
                                
                            extracted_data = json.loads(text_response.strip())
                            st.success("Receipt processed successfully!")
                            
                            # Mostrar los ítems encontrados
                            st.write("**Items found in receipt:**")
                            items_list = extracted_data.get("items", [])
                            if items_list:
                                st.table(pd.DataFrame(items_list))
                            else:
                                st.info("No individual items detected, but total amount was read.")
                                
                        except Exception as e:
                            st.error(f"Could not read the receipt automatically. Error details: {str(e)}")
                            st.info("Please enter data manually below.")

    # Main Expense Form
    st.subheader("2. Expense Details")
    with st.form("expense_form"):
        col1, col2 = st.columns(2)
        with col1:
            exp_date = st.date_input("Date", date.today())
            person = st.selectbox("Person (Who does this expense belong to?)", PERSONS)
            category = st.selectbox("Category", CATEGORIES)
            merchant = st.text_input("Merchant", value=extracted_data.get("merchant", ""))
            note = st.text_input("Note")
        with col2:
            amount = st.number_input("Amount", min_value=0.0, step=0.01, value=float(extracted_data.get("total_amount", 0.0)))
            card_number = st.text_input("Card Number / Payment Method", value=extracted_data.get("card_number", ""))
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
        st.dataframe(df.tail(10))
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
