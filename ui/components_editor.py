import streamlit as st
import pandas as pd


def render_editor(df: pd.DataFrame, key: str):
    """Render the data editor and return (edited_df, selected_df).

    ✅ 強化：若沒有任何檢查訊息，預設隱藏 validation 欄位以騰出空間。
    - 可用 toggle 手動開關顯示檢查欄位。
    """

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

    # Auto decide whether to show validation columns
    show_validation_default = True
    if "validation_ok" in df.columns and "validation_errors" in df.columns:
        no_errors = df["validation_errors"].fillna("").astype(str).str.strip().eq("").all()
        all_ok = df["validation_ok"].fillna(False).astype(bool).all()
        if all_ok and no_errors:
            show_validation_default = False

    show_validation = st.toggle(
        "顯示檢查訊息欄位（validation）",
        value=show_validation_default,
        key=f"{key}_show_validation",
        help="如全部通過檢查且沒有訊息，系統會預設收起以騰出空間。",
    )

    df_to_edit = df.copy()
    if not show_validation:
        drop_cols = [c for c in ["validation_ok", "validation_errors"] if c in df_to_edit.columns]
        if drop_cols:
            df_to_edit = df_to_edit.drop(columns=drop_cols)

    # Disable validation columns (display only) + other protected cols
    disabled_cols = ["subject", "qtype", "validation_ok", "validation_errors"]
    disabled_cols = [c for c in disabled_cols if c in df_to_edit.columns]

    # Build column config dynamically (avoid referencing dropped cols)
    column_config = {}
    if "export" in df_to_edit.columns:
        column_config["export"] = st.column_config.CheckboxColumn("匯出", width="small")
    if "validation_ok" in df_to_edit.columns:
        column_config["validation_ok"] = st.column_config.CheckboxColumn("通過檢查", width="small")
    if "validation_errors" in df_to_edit.columns:
        column_config["validation_errors"] = st.column_config.TextColumn("檢查訊息", width="large")
    if "correct" in df_to_edit.columns:
        column_config["correct"] = st.column_config.SelectboxColumn(
            "正確答案（1-4）",
            options=["1", "2", "3", "4"],
            width="small",
        )
    if "needs_review" in df_to_edit.columns:
        column_config["needs_review"] = st.column_config.CheckboxColumn("需教師確認", width="small")

    edited = st.data_editor(
        df_to_edit,
        use_container_width=True,
        num_rows="dynamic",
        column_config=column_config,
        disabled=disabled_cols,
        key=key,
    )

    selected = edited[edited["export"] == True].copy() if "export" in edited.columns else edited.copy()
    return edited, selected
