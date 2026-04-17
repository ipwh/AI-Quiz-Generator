import streamlit as st
import pandas as pd
import requests

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
)
from services.cache_service import load_cache, save_cache
from extractors.extract import extract_text

from exporters.export_kahoot import export_kahoot
from exporters.export_wayground_docx import export_wayground_docx

from services.google_oauth import (
    build_google_oauth_flow,
    oauth_is_configured,
    get_redirect_uri,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)
from services.google_forms_api import create_quiz_form


# =========================
# 工具：把內部資料（options list）轉成老師易編輯格式（option_1~4）
# =========================

def to_editor_df(data):
    rows = []
    for q in data or []:
        opts = q.get('options', [])
        if not isinstance(opts, list):
            opts = []
        opts = [str(x) for x in opts][:4]
        while len(opts) < 4:
            opts.append('')

        corr = q.get('correct', ['1'])
        if isinstance(corr, list) and corr:
            corr_val = str(corr[0])
        else:
            corr_val = str(corr) if corr else '1'

        rows.append({
            'type': q.get('type', 'single'),
            'question': q.get('question', ''),
            'option_1': opts[0],
            'option_2': opts[1],
            'option_3': opts[2],
            'option_4': opts[3],
            'correct': corr_val,
            'explanation': q.get('explanation', ''),  # 內部保留（匯出不包含）
            'needs_review': bool(q.get('needs_review', False)),
        })
    return pd.DataFrame(rows)


EDITOR_COLUMN_CONFIG = {
    'correct': st.column_config.SelectboxColumn(
        '正確答案（1-4）',
        help='1=option_1, 2=option_2, 3=option_3, 4=option_4',
        options=['1','2','3','4'],
        required=True,
        width='small',
    ),
    'needs_review': st.column_config.CheckboxColumn(
        '需教師確認',
        help='AI 推測答案或內容不確定時會標示（匯出不會顯示）',
        width='small',
    ),
    'type': st.column_config.TextColumn(
        '題型',
        help='single=單選題（系統內部用）',
        width='small',
    ),
}


st.set_page_config(page_title='AI 題目生成器', layout='wide')
st.title('🏫 香港中學 AI 題目生成器（整合版｜多 API｜Google Forms 直出｜無 OCR）')

# =========================
# Sidebar：API 設定（簡易/進階）
# =========================
st.sidebar.header('🔌 AI API 設定')

preset = st.sidebar.selectbox(
    '快速選擇（簡易）',
    ['DeepSeek（推薦）', 'OpenAI', 'Azure OpenAI', '自訂（OpenAI 相容）'],
    help='一般老師建議用「DeepSeek」或「OpenAI」。IT 才需要自訂或 Azure。'
)

api_key = st.sidebar.text_input('API Key', type='password')

# 預設
if preset == 'DeepSeek（推薦）':
    default_base = 'https://api.deepseek.com/v1'
    default_model = 'deepseek-chat'
elif preset == 'OpenAI':
    default_base = 'https://api.openai.com/v1'
    default_model = 'gpt-4o-mini'
else:
    default_base = ''
    default_model = ''

# 簡易模式：只顯示基本
base_url = st.sidebar.text_input('Base URL（含 /v1）', value=default_base, disabled=(preset in ['DeepSeek（推薦）','OpenAI']))
model = st.sidebar.text_input('Model', value=default_model, disabled=(preset in ['DeepSeek（推薦）','OpenAI']))

azure_endpoint = ''
azure_deployment = ''
azure_api_version = '2024-02-15-preview'

with st.sidebar.expander('⚙️ 進階設定（IT/管理員）', expanded=(preset == 'Azure OpenAI')):
    st.caption('若使用 Azure OpenAI，請在此填寫。')
    azure_endpoint = st.text_input('Azure Endpoint', value='')
    azure_deployment = st.text_input('Deployment name', value='')
    azure_api_version = st.text_input('API version', value='2024-02-15-preview')

# API 測試
st.sidebar.subheader('🔑 API 測試')

def test_openai_compatible(key: str, base: str, mdl: str):
    if not key:
        return False, '未輸入 API Key'
    if not base or not mdl:
        return False, '未填 Base URL 或 Model'
    url = base.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    payload = {'model': mdl, 'messages': [{'role':'user','content':'Reply with OK'}], 'temperature': 0}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
    except requests.exceptions.Timeout:
        return False, 'Timeout：請換網絡/稍後再試'
    except requests.exceptions.RequestException as e:
        return False, f'網絡錯誤：{e}'
    if r.status_code == 200:
        return True, '✅ 測試成功'
    if r.status_code in (401,403):
        return False, '❌ 401/403：請重貼 Key / 權限不足'
    if r.status_code == 402:
        return False, '❌ 402：請檢查餘額/套餐'
    if r.status_code == 429:
        return False, '⚠️ 429：請稍後再試'
    return False, f'❌ HTTP {r.status_code}: {r.text[:200]}'


def test_azure(key: str, endpoint: str, deployment: str, api_version: str):
    if not key:
        return False, '未輸入 API Key'
    if not endpoint or not deployment:
        return False, '未填 Endpoint 或 Deployment'
    url = endpoint.rstrip('/') + f'/openai/deployments/{deployment}/chat/completions?api-version={api_version}'
    headers = {'api-key': key, 'Content-Type': 'application/json'}
    payload = {'messages': [{'role':'user','content':'Reply with OK'}], 'temperature': 0}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
    except requests.exceptions.Timeout:
        return False, 'Timeout：請換網絡/稍後再試'
    except requests.exceptions.RequestException as e:
        return False, f'網絡錯誤：{e}'
    if r.status_code == 200:
        return True, '✅ 測試成功'
    if r.status_code in (401,403):
        return False, '❌ 401/403：請重貼 Key / 檢查權限'
    if r.status_code == 429:
        return False, '⚠️ 429：請稍後再試'
    return False, f'❌ HTTP {r.status_code}: {r.text[:200]}'


if st.sidebar.button('🔍 測試 API', disabled=not bool(api_key)):
    if preset == 'Azure OpenAI':
        ok, msg = test_azure(api_key, azure_endpoint, azure_deployment, azure_api_version)
    else:
        ok, msg = test_openai_compatible(api_key, base_url, model)
    st.sidebar.success(msg) if ok else st.sidebar.error(msg)

st.sidebar.divider()

# =========================
# Sidebar：Google 連接（Google Forms API）
# =========================
st.sidebar.header('🟦 Google Forms 連接')
if not oauth_is_configured():
    st.sidebar.warning('⚠️ 尚未設定 Google OAuth（需在 Streamlit Secrets 設定 google_oauth_client）。')
else:
    # 取得/顯示目前登入狀態
    if 'google_creds' in st.session_state and st.session_state.google_creds:
        st.sidebar.success('✅ 已連接 Google（可直接建立 Google Form Quiz）')
        if st.sidebar.button('🔒 登出 Google'):
            st.session_state.google_creds = None
            st.rerun()
    else:
        # OAuth login link
        flow = build_google_oauth_flow(get_redirect_uri())
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        st.sidebar.markdown(f"[🔐 連接 Google（登入）]({auth_url})")
        st.sidebar.caption('首次會要求授權存取 Google Forms/Drive。')

# 接收 OAuth code
params = st.query_params
if oauth_is_configured() and 'code' in params and ('google_creds' not in st.session_state or not st.session_state.google_creds):
    try:
        creds = exchange_code_for_credentials(get_redirect_uri(), params.get('code'))
        st.session_state.google_creds = credentials_to_dict(creds)
        # 清掉 query string
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error('Google 登入失敗：' + str(e))

st.sidebar.divider()

# =========================
# 模式與科目
# =========================
mode = st.sidebar.radio('📂 試題來源模式', ['🪄 AI 生成新題目', '📄 匯入現有題目（AI 協助）'])
subject = st.sidebar.selectbox('📘 科目', [
    '中國語文','英國語文','數學','公民與社會發展','科學','物理','化學','生物',
    '資訊及通訊科技（ICT）','地理','歷史','公民、經濟及社會','中國歷史','宗教','經濟'
])

st.sidebar.subheader('📤 匯出')
st.sidebar.caption('Kahoot：Excel；Wayground：DOCX；Google Forms：直接建立（需先連接 Google）')

# session
if 'imported_text' not in st.session_state:
    st.session_state.imported_text = ''
if 'imported_data' not in st.session_state:
    st.session_state.imported_data = None
if 'generated_data' not in st.session_state:
    st.session_state.generated_data = None


def api_config():
    if preset == 'Azure OpenAI':
        return {
            'type': 'azure',
            'api_key': api_key,
            'endpoint': azure_endpoint,
            'deployment': azure_deployment,
            'api_version': azure_api_version,
            'label': preset,
        }
    # OpenAI compatible
    return {
        'type': 'openai_compat',
        'api_key': api_key,
        'base_url': base_url,
        'model': model,
        'label': preset,
    }


def can_call_ai(cfg: dict):
    if not cfg.get('api_key'):
        return False
    if cfg.get('type') == 'azure':
        return bool(cfg.get('endpoint')) and bool(cfg.get('deployment'))
    return bool(cfg.get('base_url')) and bool(cfg.get('model'))


# =========================
# 模式一：AI 生成
# =========================
if mode == '🪄 AI 生成新題目':
    st.sidebar.subheader('🧮 題目數目')
    question_count = st.sidebar.selectbox('數目', [5,8,10,12,15,20], index=2)
    st.sidebar.subheader('🎯 難度')
    level_label = st.sidebar.radio('整體難度', ['基礎（理解與記憶）','標準（應用與理解）','進階（分析與思考）','混合（課堂活動建議）'])
    level_map = {
        '基礎（理解與記憶）':'easy',
        '標準（應用與理解）':'medium',
        '進階（分析與思考）':'hard',
        '混合（課堂活動建議）':'mixed'
    }
    level_code = level_map[level_label]

    st.subheader('🪄 AI 生成新題目')
    st.caption('上載教材（PDF / DOCX / TXT / PPTX / XLSX）。⚠️ 已移除 OCR，不接受圖片檔。')

    files = st.file_uploader('上載教材', accept_multiple_files=True, type=['pdf','docx','txt','pptx','xlsx'])

    if files:
        preview = ''.join(extract_text(f) for f in files)
        with st.expander('🔎 預覽：抽取到的文字（用來出題）', expanded=False):
            st.write(f'字數：約 {len(preview)}')
            st.text(preview[:1500] if preview else '（抽取結果為空：請改用 TXT/DOCX/文字型 PDF。）')

    cfg = api_config()
    can_generate = can_call_ai(cfg) and bool(files)

    if st.button('生成題目', disabled=not can_generate):
        text = ''.join(extract_text(f) for f in files)[:5000]
        if not text.strip():
            st.error('❌ 未能抽取到文字內容，請改用 TXT/DOCX/文字型 PDF。')
            st.stop()

        cache = load_cache()
        key = str(hash(text + subject + level_code + str(question_count) + cfg.get('label','') + cfg.get('model','') + cfg.get('deployment','')))

        if key in cache:
            st.session_state.generated_data = cache[key]
            st.info('✅ 使用題庫快取')
        else:
            with st.spinner('🤖 生成中...'):
                data = generate_questions(cfg, text, subject, level_code, question_count)
            cache[key] = data
            save_cache(cache)
            st.session_state.generated_data = data

    if st.session_state.generated_data:
        df = to_editor_df(st.session_state.generated_data)
        edited = st.data_editor(df, use_container_width=True, num_rows='dynamic', column_config=EDITOR_COLUMN_CONFIG, disabled=['type'])
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button('⬇️ Kahoot Excel', export_kahoot(edited), 'kahoot.xlsx')
        with col2:
            st.download_button('⬇️ Wayground DOCX', export_wayground_docx(edited, subject), 'wayground.docx')
        with col3:
            if oauth_is_configured() and st.session_state.get('google_creds'):
                if st.button('🟦 一鍵建立 Google Form Quiz'):
                    creds = credentials_from_dict(st.session_state.google_creds)
                    form_title = f'{subject} Quiz'
                    result = create_quiz_form(creds, form_title, edited)
                    st.success('✅ 已建立 Google Form Quiz')
                    st.write('編輯連結：', result.get('editUrl'))
                    st.write('發佈連結：', result.get('responderUrl'))
            else:
                st.info('先在左側「Google Forms 連接」登入 Google，才可一鍵建立。')


# =========================
# 模式二：匯入現有題目
# =========================
if mode == '📄 匯入現有題目（AI 協助）':
    st.subheader('📄 匯入現有題目（AI 協助整理）')

    def load_import_file_to_textbox():
        f = st.session_state.get('import_file')
        if f is None:
            return
        content = extract_text(f)
        st.session_state.imported_text = content or ''
        st.session_state.imported_data = None

    st.markdown('### 📎 上載 DOCX/TXT（自動載入到貼上框）')
    st.file_uploader('選擇檔案（DOCX/TXT）', type=['docx','txt'], key='import_file', on_change=load_import_file_to_textbox)

    use_ai_assist = st.checkbox('啟用 AI 協助整理題目（建議）', value=True)
    st.text_area('貼上題目內容', height=320, key='imported_text')

    cfg = api_config()
    can_run = bool(st.session_state.imported_text.strip())
    disable_btn = (not can_run) or (use_ai_assist and not can_call_ai(cfg))

    if st.button('✨ 整理並轉換', disabled=disable_btn):
        raw = st.session_state.imported_text.strip()
        with st.spinner('🧠 整理中...'):
            if use_ai_assist:
                data = assist_import_questions(cfg, raw, subject, allow_guess=True)
            else:
                data = parse_import_questions_locally(raw)
        st.session_state.imported_data = data

    if st.session_state.imported_data:
        df = to_editor_df(st.session_state.imported_data)
        edited = st.data_editor(df, use_container_width=True, num_rows='dynamic', column_config=EDITOR_COLUMN_CONFIG, disabled=['type'])
        col1, col2, col3 = st.columns(3)
        with col1:
            st.download_button('⬇️ Kahoot Excel', export_kahoot(edited), 'kahoot.xlsx')
        with col2:
            st.download_button('⬇️ Wayground DOCX', export_wayground_docx(edited, subject), 'wayground.docx')
        with col3:
            if oauth_is_configured() and st.session_state.get('google_creds'):
                if st.button('🟦 一鍵建立 Google Form Quiz'):
                    creds = credentials_from_dict(st.session_state.google_creds)
                    form_title = f'{subject} Quiz'
                    result = create_quiz_form(creds, form_title, edited)
                    st.success('✅ 已建立 Google Form Quiz')
                    st.write('編輯連結：', result.get('editUrl'))
                    st.write('發佈連結：', result.get('responderUrl'))
            else:
                st.info('先在左側「Google Forms 連接」登入 Google，才可一鍵建立。')
