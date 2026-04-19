import streamlit as st
import pandas as pd


def render_editor(df: pd.DataFrame, key: str):
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("✅ 全選匯出", key=f"{key}_export_all"):
            df["export"] = True
    with c2:
        if st.button("全部取消匯出", key=f"{key}_export_none"):
            df["export"] = False

    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "export": st.column_config.CheckboxColumn("匯出", width="small"),
            "correct": st.column_config.SelectboxColumn("正確答案（1-4）", options=["1", "2", "3", "4"], width="small"),
            "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
        },
        disabled=["subject", "qtype"],
        key=key,
    )
    selected = edited[edited["export"] == True].copy()
    return edited, selected