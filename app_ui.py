import streamlit as st
import pandas as pd
import os
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
from core.transcriber import Transcriber
from core.llm_engine import LLMEngine
from core.excel_ops import ExcelExecutor
from core.audio_listener import AudioListener

# --- 1. Config ---
st.set_page_config(
    layout="wide", 
    page_title="Xcelord AI", 
    page_icon="📊",
    initial_sidebar_state="collapsed"
)

# --- 2. State & CSS ---
if "df" not in st.session_state:
    st.session_state.df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "file_path" not in st.session_state:
    st.session_state.file_path = "dummy_data.xlsx"
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "Dark"

# CSS Styles
dark_css = """
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .chat-container { background-color: #1f2937; border-radius: 15px; padding: 20px; border: 1px solid #374151; height: 60vh; overflow-y: auto; }
    .user-msg { text-align: right; color: #4ade80; margin-bottom: 10px; font-weight: bold; }
    .bot-msg { text-align: left; color: #60a5fa; margin-bottom: 10px; }
    div.stButton > button { border-radius: 8px; font-weight: 600; border: none; }
    div.stButton > button:first-child { background-color: #ef4444; color: white; }
</style>
"""
light_css = """
<style>
    .stApp { background-color: #f3f4f6; color: #1f2937; }
    .chat-container { background-color: #ffffff; border-radius: 15px; padding: 20px; border: 1px solid #e5e7eb; height: 60vh; overflow-y: auto; }
    .user-msg { text-align: right; color: #15803d; margin-bottom: 10px; font-weight: bold; }
    .bot-msg { text-align: left; color: #2563eb; margin-bottom: 10px; }
    div.stButton > button { border-radius: 8px; font-weight: 600; border: 1px solid #d1d5db; }
    div.stButton > button:first-child { background-color: #dc2626; color: white; }
</style>
"""
st.markdown(dark_css if st.session_state.theme_mode == "Dark" else light_css, unsafe_allow_html=True)

# --- 3. Initialize Engines ---
@st.cache_resource
def get_engines():
    listener = AudioListener() 
    try:
        listener.calibrate_noise()
    except:
        pass 
    return listener, Transcriber(), LLMEngine(), ExcelExecutor()

listener, transcriber, llm_engine, executor = get_engines()

# --- 4. Auto-Load on Startup ---
# This ensures the default file is processed immediately
if st.session_state.df is None and os.path.exists(st.session_state.file_path):
    success, initial_df, msg = executor.load_sheet(st.session_state.file_path)
    if success:
        st.session_state.df = initial_df
    else:
        # If loading fails, we just don't have data yet
        pass 

# ==========================================
#              TOP BAR
# ==========================================
col_title, col_toggle = st.columns([8, 1])
with col_title:
    st.title("Xcelord 📊")
with col_toggle:
    mode = st.radio("Theme", ["Dark", "Light"], horizontal=True, label_visibility="collapsed")
    if mode != st.session_state.theme_mode:
        st.session_state.theme_mode = mode
        st.rerun()

# ==========================================
#              SIDEBAR
# ==========================================
with st.sidebar:
    st.markdown("### 📂 Workspace Settings")
    
    uploaded_file = st.file_uploader("Upload New Sheet", type=["xlsx", "csv"])
    
    # --- FIXED UPLOAD LOGIC ---
    # Trigger load IMMEDIATELY after upload to fix dates
    if uploaded_file:
        file_path = f"temp_{uploaded_file.name}"
        
        # Only save and reload if it's a new file to avoid constant reloading
        if file_path != st.session_state.file_path:
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            st.session_state.file_path = file_path
            
            # Call the Robust Loader
            success, new_df, msg = executor.load_sheet(file_path)
            if success:
                st.session_state.df = new_df
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")
        
    if st.button("🔄 Reload Data Source"):
        if os.path.exists(st.session_state.file_path):
            success, new_df, msg = executor.load_sheet(st.session_state.file_path)
            if success:
                st.session_state.df = new_df
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")
        else:
            st.error("File not found.")

# ==========================================
#            MAIN LAYOUT
# ==========================================
col_grid, col_chat = st.columns([3, 1]) 

# 1. Grid View
with col_grid:
    if st.session_state.df is not None:
        gb = GridOptionsBuilder.from_dataframe(st.session_state.df)
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
        gb.configure_default_column(editable=True, groupable=True, minWidth=100)
        gb.configure_selection('single')
        gridOptions = gb.build()

        grid_response = AgGrid(
            st.session_state.df,
            gridOptions=gridOptions,
            update_mode=GridUpdateMode.VALUE_CHANGED,
            height=650,
            theme="streamlit" if st.session_state.theme_mode == "Dark" else "balham",
        )

        updated_df = grid_response['data']
        if not updated_df.equals(st.session_state.df):
            st.session_state.df = updated_df
            updated_df.to_excel(st.session_state.file_path, index=False)
            st.toast("Changes saved!", icon="💾")
    else:
        st.info("👈 Expand the sidebar to upload a file.")

# 2. Chat & Controls
with col_chat:
    # Chat History Display
    chat_html = '<div class="chat-container">'
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            chat_html += f'<div class="user-msg">👤 {msg["content"]}</div>'
        else:
            clean_content = msg["content"].replace("\n", "<br>")
            chat_html += f'<div class="bot-msg">🤖 {clean_content}</div>'
    chat_html += '</div>'
    
    st.markdown(chat_html, unsafe_allow_html=True)
    st.write("") 

    # Input Controls
    if st.button("🎙️ Record (Auto-Stop)"):
        with st.spinner("Listening..."):
            audio_file = listener.listen_and_record("temp_voice.wav")
            
            if audio_file:
                text = transcriber.transcribe(audio_file)
                if text and "Error" not in text:
                    st.session_state.chat_history.append({"role": "user", "content": text})
                    
                    if st.session_state.df is not None:
                        columns = list(st.session_state.df.columns)
                        code = llm_engine.generate_code(text, columns)
                        success, new_df, msg = executor.execute_code(st.session_state.df, code)
                        
                        if success:
                            st.session_state.df = new_df
                            executor.save_file(new_df, st.session_state.file_path)
                            st.session_state.chat_history.append({"role": "assistant", "content": f"✅ {msg}"})
                        else:
                            st.session_state.chat_history.append({"role": "assistant", "content": f"❌ {msg}"})
                        st.rerun()
                else:
                    st.error("No speech detected.")

    text_input = st.chat_input("Type command...")
    if text_input:
        st.session_state.chat_history.append({"role": "user", "content": text_input})
        if st.session_state.df is not None:
            columns = list(st.session_state.df.columns)
            code = llm_engine.generate_code(text_input, columns)
            success, new_df, msg = executor.execute_code(st.session_state.df, code)
            
            if success:
                st.session_state.df = new_df
                executor.save_file(new_df, st.session_state.file_path)
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ {msg}"})
            else:
                 st.session_state.chat_history.append({"role": "assistant", "content": f"❌ {msg}"})
            st.rerun()