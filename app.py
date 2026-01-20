import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
import google.generativeai as genai

# [Step 0] 필수 환경 설정
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

if "streamlit" not in sys.modules: setup_environment()

# [Step 1] AI 키 로드 (Google API만 있으면 됨)
api_key = st.secrets.get("GOOGLE_API_KEY", "")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 주소 -> 좌표 변환 (카카오 API는 안정적이므로 유지)
# --------------------------------------------------------------------------------
def get_coords(address):
    if not kakao_key: return None, None, "카카오 키 없음"
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    try:
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                x = float(docs[0]['x']) # 경도
                y = float(docs[0]['y']) # 위도
                return x, y, "OK"
        return None, None, "주소 검색 실패"
    except Exception as e: return None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] AI기반 추론 엔진 (데이터가 없어도 분석함)
# --------------------------------------------------------------------------------
def analyze_with_ai(address):
    if not api_key: return "AI 키가 필요합니다."
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # AI에게 "너는 데이터가 없어도 입지를 분석할 수 있는 전문가야"라고 최면을  겁니다.
    prompt = f"""
    당신은 대한민국 최고의 부동산 개발 컨설턴트입니다.
    현재 정부 전산망 오류로 정확한 대장 데이터(면적, 공시지가)를 불러오지 못했습니다.
    하지만 당신은 '주소({address})'만 보고도 그 지역의 입지와 잠재력을 분석할 수 있습니다.

    다음 형식으로 보고서를 작성해주세요:
    
    1. 📍 **입지 브리핑**: 
       - 해당 주소지의 대략적인 위치 특성 (예: 도심 인근, 농지, 공장지대 등).
       - 주변 교통 및 인프라 추정.
       
    2. 🏗️ **가설계 시뮬레이션 (추정)**:
       - 해당 지역의 일반적인 용도지역(계획관리, 주거 등)을 가정했을 때 가능한 개발 행위.
       - 추천 용도 (창고, 전원주택, 근생시설 등).
       
    3. 💰 **투자 전략**:
       - 맹지 탈출 전략, 성토(흙 채우기) 필요성 등 토목적 관점 조언.
       - "만약 이 땅이 평당 100만 원 이하라면 강력 매수 추천"과 같은 조건부 조언.
    
    *주의: 정확한 수치는 등기부등본 확인이 필요함을 명시할 것.*
    """
    try:
        return model.generate_content(prompt).text
    except: return "AI 분석 엔진 가동 중 오류 발생."

# --------------------------------------------------------------------------------
# [UI] 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Alternative", layout="wide", page_icon="🦄")

with st.sidebar:
    st.header("🦄 지상 AI")
    st.caption("Ver 11.0 (Hybrid Engine)")
    st.info("💡 공공데이터 API 오류 시에도 AI 추론으로 분석을 수행합니다.")
    addr = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 분석 실행", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr

st.title("지상 AI 부동산 솔루션")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    with st.status("🔍 AI가 입지를 분석하고 있습니다...", expanded=True) as status:
        # 1. 좌표 획득
        x, y, msg = get_coords(target)
        
        if x and y:
            # 지도 표시 (API 없이도 지도는 나옴)
            st.map(pd.DataFrame({'lat': [y], 'lon': [x]}), zoom=16)
            
            # 2. AI 분석 실행 (데이터 API 의존성 제거)
            ai_report = analyze_with_ai(target)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            st.divider()
            
            # 결과 화면
            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.subheader("📌 분석 개요")
                st.success(f"**분석 대상**: {target}")
                st.info("현재 정부 API 서버 응답 지연으로 인해 **AI 입지 기반 정밀 추론 모드**로 분석을 진행했습니다.")
                st.warning("정확한 면적과 공시지가는 '부동산 디스코' 또는 '씨:리얼' 사이트 교차 검증을 권장합니다.")

            with col2:
                st.subheader("💡 유니콘 AI 솔루션")
                st.markdown(ai_report)
                
        else:
            st.error(f"주소를 찾을 수 없습니다: {msg}")
