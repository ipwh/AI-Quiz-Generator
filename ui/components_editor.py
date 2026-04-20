
import streamlit as st
import pandas as pd


def render_editor(df: pd.DataFrame, key: str):
    """Render the data editor and return (edited_df, selected_df)."""

    if df is None or df.empty:
        return df, df

    # Bulk selection helpers
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("✅ 全選匯出", key=f"{key}_export_all"):
            df["export"] = True
    with c2:
        if st.button("全部取消匯出", key=f"{key}_export_none"):
            df["export"] = False

    # Disable validation columns (display only)
    disabled_cols = ["subject", "qtype", "validation_ok", "validation_errors"]
    disabled_cols = [c for c in disabled_cols if c in df.columns]

    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "export": st.column_config.CheckboxColumn("匯出", width="small"),
            "validation_ok": st.column_config.CheckboxColumn("通過檢查", width="small"),
            "validation_errors": st.column_config.TextColumn("檢查訊息", width="large"),
            "correct": st.column_config.SelectboxColumn("正確答案（1-4）", options=["1", "2", "3", "4"], width="small"),
            "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
        },
        disabled=disabled_cols,
        key=key,
    )

    selected = edited[edited["export"] == True].copy() if "export" in edited.columns else edited.copy()
    return edited, selected
