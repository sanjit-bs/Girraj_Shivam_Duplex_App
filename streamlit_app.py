import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date
import datetime
import math
import re
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================================================================================================
####################################### Paper Sheet Stock #######################################
# ================================================================================================

APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyNDd8Zybovl7rso9STNpyqmqxQRUZC80h_qo59UA03iGDYLiWmEJLnGqlG2KFWXPMT/exec"

COLUMNS_MASTER = [
    "Product", "Width", "Length", "GSM", "Grus", "Pcs", "Challan Weight", "Remark"
]

COLUMNS_HISTORY = [
    "Date", "Type", "Product", "Width", "Length", "GSM", "Grus", "Pcs", 
    "Challan Weight", "Weight", "Diff Weight", "Remark"
]

st.set_page_config(page_title="Paper Sheet Stock Manager", layout="wide")

# ------------------------------------------------------
# 🔐 ACCESS CONTROL / SIDEBAR AUTHENTICATION
# ------------------------------------------------------
st.sidebar.title("🔐 Access Control")
admin_pin = st.sidebar.text_input("Enter Admin PIN to edit:", type="password")

# Change "1234" to your preferred security PIN
IS_ADMIN = (admin_pin == "1234")

if IS_ADMIN:
    st.sidebar.success("🔓 Admin Mode Active")
    tab_entry, tab_history = st.tabs(["⚡ Record Transaction", "📜 Stock & History Log"])
else:
    st.sidebar.info("👁️ View-Only Mode Active")
    tab_history = st.tabs(["📜 Stock & History Log"])[0]

# --- Standalone Converter Tool ---
with st.expander("📐 Quick CM to Inches Converter"):
    col_cm1, col_cm2 = st.columns(2)

    with col_cm1:
        h_cm = st.number_input(
            "Width (CM)",
            min_value=0.0,
            step=0.1,
            format="%.2f",
            key="standalone_h_cm_converter",
        )

    with col_cm2:
        w_cm = st.number_input(
            "Length (CM)",
            min_value=0.0,
            step=0.1,
            format="%.2f",
            key="standalone_w_cm_converter",
        )

    if h_cm > 0 or w_cm > 0:
        h_inch = round(h_cm / 2.54, 2)
        w_inch = round(w_cm / 2.54, 2)

        st.success(
            f"**Converted Dimensions:** {h_inch:.2f}″ (W) × {w_inch:.2f}″ (L)\n\n"
            f"*Original:* {h_cm:.2f} cm × {w_cm:.2f} cm"
        )

def clean_date_column(df, col_name="Date"):
    if df.empty or col_name not in df.columns:
        return df
    def convert_val(val):
        if pd.isna(val) or str(val).strip() == "": return ""
        val_str = str(val).strip()
        if "T" in val_str or "Z" in val_str:
            dt = pd.to_datetime(val_str, errors="coerce", utc=True)
            if pd.notna(dt): return dt.tz_convert("Asia/Kolkata").strftime("%d/%m/%Y")
        try:
            dt = pd.to_datetime(val_str, format="%d/%m/%Y", errors="coerce")
            if pd.notna(dt): return dt.strftime("%d/%m/%Y")
        except Exception:
            pass
        dt = pd.to_datetime(val_str, errors="coerce")
        if pd.notna(dt): return dt.strftime("%d/%m/%Y")
        return val_str
    df[col_name] = df[col_name].apply(convert_val)
    return df

def get_calc_weight(w, l, gsm, pcs):
    try:
        return round((((float(w) * float(l) * float(gsm)) / 1550) / 1000) * int(pcs), 3)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0.000

def get_calc_pcs(w, l, gsm, weight):
    try:
        return int(round((float(weight) * 1000 * 1550) / (float(w) * float(l) * float(gsm))))
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

# Sync Callbacks (ONLY ACTIVE IN 'USED' MODE - PURCHASED IS UNTOUCHED)
def sync_grus(w, l, gsm, action_type):
    k = st.session_state.form_key
    g = st.session_state.get(f"g_{k}", 0.0)
    pcs = int(round(g * 144))
    st.session_state[f"p_{k}"] = pcs
    if action_type == "Used":
        st.session_state[f"cw_{k}"] = get_calc_weight(w, l, gsm, pcs)

def sync_pcs(w, l, gsm, action_type):
    k = st.session_state.form_key
    pcs = st.session_state.get(f"p_{k}", 0)
    st.session_state[f"g_{k}"] = round(float(pcs) / 144.0, 2)
    if action_type == "Used":
        st.session_state[f"cw_{k}"] = get_calc_weight(w, l, gsm, pcs)

def sync_weight(w, l, gsm, action_type):
    if action_type == "Used":
        k = st.session_state.form_key
        wt = st.session_state.get(f"cw_{k}", 0.0)
        pcs = get_calc_pcs(w, l, gsm, wt)
        st.session_state[f"p_{k}"] = pcs
        st.session_state[f"g_{k}"] = round(float(pcs) / 144.0, 2)

@st.cache_data(ttl=5)
def fetch_all_data():
    try:
        response = requests.get(f"{APPS_SCRIPT_URL}?action=read_all", timeout=30)
        data = response.json()
        master_df = pd.DataFrame(data.get("master", []))
        history_df = pd.DataFrame(data.get("history", []))
        history_df = clean_date_column(history_df, "Date")

        for col in COLUMNS_MASTER:
            if col not in master_df.columns:
                master_df[col] = 0.0 if col in ["Grus", "Pcs", "Challan Weight"] else ""
        for col in COLUMNS_HISTORY:
            if col not in history_df.columns:
                history_df[col] = 0.0 if col in ["Grus", "Pcs", "Weight", "Challan Weight", "Diff Weight"] else ""
        return master_df[COLUMNS_MASTER], history_df[COLUMNS_HISTORY]
    except Exception:
        return pd.DataFrame(columns=COLUMNS_MASTER), pd.DataFrame(columns=COLUMNS_HISTORY)

def send_update_to_sheet(params):
    try:
        res = requests.get(APPS_SCRIPT_URL, params=params, timeout=30)
        if res.json().get("status") == "success":
            st.toast("✅ Stock updated successfully!")
            st.cache_data.clear()
            st.session_state.form_key += 1
            st.rerun()
        else:
            st.error(f"Backend Error: {res.json().get('message')}")
    except Exception as e:
        st.error(f"Transaction failed: {e}")

# Main Data Fetching
sheet_df, history_df = fetch_all_data()

st.markdown("---")
st.subheader("📄 Paper Sheet Stock Manager")

if "form_key" not in st.session_state:
    st.session_state.form_key = 0
fk = st.session_state.form_key

# ------------------------------------------------------
# TAB 1: RECORD TRANSACTION (ADMIN ONLY)
# ------------------------------------------------------
if IS_ADMIN:
    with tab_entry:
        st.markdown("**Transaction Type & Date**")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            action_type = st.radio("Transaction Type", ["Purchased", "Used"], horizontal=True, key=f"type_{fk}")
        with col_t2:
            txn_date = st.date_input("Date", value=date.today(), key=f"dt_{fk}")

        st.markdown("---")
        st.markdown("**🔍 Product & Specifications Selection**")
        
        df_clean = sheet_df.copy()
        for c in ["Product", "Width", "Length", "GSM"]:
            df_clean[c] = df_clean[c].astype(str).str.strip()
        
        def get_sel(key):
            v = st.session_state.get(key, "")
            return v if v and not v.startswith("Select") and v != "➕ Add New..." else None

        cp = get_sel(f"sp_{fk}")
        cw = get_sel(f"sw_{fk}")
        cl = get_sel(f"sl_{fk}")
        cg = get_sel(f"sg_{fk}")

        def get_opts(col):
            t = df_clean.copy()
            if col != "Product" and cp: t = t[t["Product"] == cp]
            if col != "Width" and cw: t = t[t["Width"] == cw]
            if col != "Length" and cl: t = t[t["Length"] == cl]
            if col != "GSM" and cg: t = t[t["GSM"] == cg]
            return sorted(list(set(t[col].unique()))) if not t.empty else []

        ap = get_opts("Product")
        aw = get_opts("Width")
        al = get_opts("Length")
        ag = get_opts("GSM")

        if len(ap) == 1 and not cp: st.session_state[f"sp_{fk}"] = ap[0]
        if len(aw) == 1 and not cw: st.session_state[f"sw_{fk}"] = aw[0]
        if len(al) == 1 and not cl: st.session_state[f"sl_{fk}"] = al[0]
        if len(ag) == 1 and not cg: st.session_state[f"sg_{fk}"] = ag[0]

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            opts_p = ["Select Product...", "➕ Add New..."] + ap
            sel_p = st.selectbox("Product", opts_p, key=f"sp_{fk}")
            final_p = st.text_input("New Product", key=f"np_{fk}") if sel_p == "➕ Add New..." else (sel_p if sel_p != "Select Product..." else "")

        with c2:
            opts_w = ["Select Width...", "➕ Add New..."] + aw
            sel_w = st.selectbox("Width", opts_w, key=f"sw_{fk}")
            final_w = st.text_input("New Width", key=f"nw_{fk}") if sel_w == "➕ Add New..." else (sel_w if sel_w != "Select Width..." else "")

        with c3:
            opts_l = ["Select Length...", "➕ Add New..."] + al
            sel_l = st.selectbox("Length", opts_l, key=f"sl_{fk}")
            final_l = st.text_input("New Length", key=f"nl_{fk}") if sel_l == "➕ Add New..." else (sel_l if sel_l != "Select Length..." else "")

        with c4:
            opts_g = ["Select GSM...", "➕ Add New..."] + ag
            sel_g = st.selectbox("GSM", opts_g, key=f"sg_{fk}")
            final_g = st.text_input("New GSM", key=f"ng_{fk}") if sel_g == "➕ Add New..." else (sel_g if sel_g != "Select GSM..." else "")

        if final_p and final_w and final_l and final_g:
            match = df_clean[
                (df_clean["Product"].str.lower() == final_p.lower()) & 
                (pd.to_numeric(df_clean["Width"], errors='coerce') == float(final_w)) & 
                (pd.to_numeric(df_clean["Length"], errors='coerce') == float(final_l)) & 
                (pd.to_numeric(df_clean["GSM"], errors='coerce') == float(final_g))
            ]
            
            is_existing_item = not match.empty
            curr_grus = float(pd.to_numeric(match["Grus"]).sum()) if is_existing_item else 0.0
            curr_pcs = int(pd.to_numeric(match["Pcs"]).sum()) if is_existing_item else 0
            curr_cw = float(pd.to_numeric(match["Challan Weight"]).sum()) if is_existing_item else 0.0

            st.info(f"**Current Stock:** {curr_grus:.2f} Grus | {curr_pcs} Pcs | Challan Weight: {curr_cw:.3f} Kg")

            st.markdown("---")
            st.markdown("**📝 Entry Details**")

            for key in [f"g_{fk}", f"p_{fk}", f"cw_{fk}"]:
                if key not in st.session_state:
                    st.session_state[key] = 0.0 if "g" in key or "cw" in key else 0

            e1, e2, e3 = st.columns(3)
            with e1:
                grus_val = st.number_input("Grus", min_value=0.0, step=0.1, format="%.2f", key=f"g_{fk}", on_change=sync_grus, args=(final_w, final_l, final_g, action_type))
            with e2:
                pcs_val = st.number_input("Pcs (Grus × 144)", min_value=0, step=1, key=f"p_{fk}", on_change=sync_pcs, args=(final_w, final_l, final_g, action_type))
            with e3:
                cw_val = st.number_input("Challan Weight (Kg)", min_value=0.0, step=0.001, format="%.3f", key=f"cw_{fk}", on_change=sync_weight, args=(final_w, final_l, final_g, action_type))
            
            wt_val = get_calc_weight(final_w, final_l, final_g, pcs_val)
            diff_weight_calc = 0.0

            if action_type == "Purchased":
                diff_weight_calc = round(cw_val - wt_val, 3)
                st.caption(f"Calculated Weight: **{wt_val:.3f} Kg** | Diff Weight (Challan - Calculated): **{diff_weight_calc:.3f} Kg**")
            
            remark = st.text_input("Remark", key=f"rm_{fk}")

            adj_check = False
            if action_type == "Used":
                rem_wt = round(curr_cw - cw_val, 3)
                st.caption(f"Remaining / Extra Stock Weight after usage: **{rem_wt:.3f} Kg**")
                if rem_wt != 0:
                    adj_check = st.checkbox("Weight Adjustment (Adjust this remaining weight into 'Diff Weight' and clear stock)", key=f"adj_{fk}")
                    if adj_check:
                        st.warning(f"✅ {rem_wt:.3f} Kg will be logged as Diff Weight. Stock Challan Weight will become 0.000 Kg.")

            if st.button("Submit Entry", type="primary", key=f"btn_{fk}"):
                if grus_val == 0 and pcs_val == 0 and cw_val == 0:
                    st.warning("Please specify a quantity higher than 0.")
                elif action_type == "Used" and pcs_val > curr_pcs and not adj_check:
                    st.error(f"Cannot subtract {pcs_val} Pcs. Available stock is only {curr_pcs} Pcs.")
                elif action_type == "Used" and cw_val > curr_cw and not adj_check:
                    st.error(f"Cannot subtract {cw_val:.3f} Kg. Available Challan stock is only {curr_cw:.3f} Kg.")
                else:
                    with st.spinner("Updating..."):
                        if action_type == "Purchased":
                            new_grus = curr_grus + grus_val
                            new_pcs = curr_pcs + pcs_val
                            new_cw = curr_cw + cw_val
                            final_diff_weight = diff_weight_calc
                        else: 
                            new_grus = curr_grus - grus_val
                            new_pcs = curr_pcs - pcs_val
                            if adj_check:
                                final_diff_weight = rem_wt
                                new_cw = 0.0
                                new_grus = 0.0
                                new_pcs = 0
                            else:
                                final_diff_weight = 0.0
                                new_cw = curr_cw - cw_val

                        if new_cw <= 0:
                            new_cw = 0.0
                            new_grus = 0.0
                            new_pcs = 0

                        params = {
                            "action": "update_stock",
                            "date": txn_date.strftime("%d/%m/%Y"),
                            "type": action_type,
                            "product": final_p,
                            "width": final_w,
                            "length": final_l,
                            "gsm": final_g,
                            "grus_change": float(grus_val),
                            "pcs_change": int(pcs_val),
                            "weight_change": float(wt_val), 
                            "challan_weight_change": float(cw_val),
                            "diff_weight_change": float(final_diff_weight),
                            "new_grus": float(round(new_grus, 2)),
                            "new_pcs": int(new_pcs),
                            "new_challan_weight": float(round(new_cw, 3)),
                            "remark": remark.strip(),
                        }
                        send_update_to_sheet(params)
        else:
            st.info("Select Product, Width, Length, and GSM to proceed.")

# ------------------------------------------------------
# TAB 2: STOCK & HISTORY LOG (READ-ONLY FOR ALL)
# ------------------------------------------------------
with tab_history:
    st.markdown("**📋 Current Master Stock**")
    st.dataframe(sheet_df, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.markdown("**📜 Transaction History**")
    st.dataframe(history_df, use_container_width=True, hide_index=True)
