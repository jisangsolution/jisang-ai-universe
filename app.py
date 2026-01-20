import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# [Step 0] 환경 설정: 필수 라이브러리 강제 설치
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    
    # 폰트 설치 (시각화용)
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules: setup_environment()

import google.generativeai as genai

# [Step 1] API 키 로드 (안전 장치)
def get_clean_key(key_name):
    raw_key = st.secrets.get(key_name, "")
    if "%" in raw_key: return unquote(raw_key)
    return raw_key

api_key = get_clean_key("GOOGLE_API_KEY")
data_go_key = get_clean_key("DATA_GO_KR_KEY")
land_go_key = get_clean_key("LAND_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
vworld_key = st.secrets.get("VWORLD_API_KEY", "")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 좌표 & PNU 생성 (가장 안정적)
# --------------------------------------------------------------------------------
def get_location_data(address):
    if not kakao_key: return None, None, "카카오 키 없음"
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {kakao_key}"}
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                # PNU 생성
                b_code = addr['b_code']
                mount = "2" if addr.get('mountain_yn') == 'Y' else "1"
                main = addr['main_address_no'].zfill(4)
                sub = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                pnu = f"{b_code}{mount}{main}{sub}"
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr
    except: pass
    return None, None, None

# --------------------------------------------------------------------------------
# [Engine 2] 하이브리드 데이터 수집 (API + Failover)
# --------------------------------------------------------------------------------
class HybridDataEngine:
    @staticmethod
    def get_land_info(pnu):
        # 1. 국토부 API 시도
        try:
            target_key = land_go_key or data_go_key
            if target_key:
                url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
                # 인코딩/디코딩 키 모두 시도
                for k in [target_key, unquote(target_key)]:
                    try:
                        res = requests.get(url, params={"serviceKey": k, "pnu": pnu, "numOfRows": 1}, timeout=4)
                        if res.status_code == 200:
                            root = ET.fromstring(res.content)
                            item = root.find('.//item')
                            if item is not None:
                                return {
                                    "source": "국토부API",
                                    "지목": item.findtext("lndcgrCodeNm"),
                                    "면적": item.findtext("lndpclAr"),
                                    "공시지가": item.findtext("pblntfPclnd")
                                }
                    except: continue
        except: pass
        
        # 2. 실패 시 기본값 리턴 (AI 추론 유도용)
        return {"source": "AI추론", "지목": "추정필요", "면적": "-", "공시지가": "-"}

    @staticmethod
    def get_vworld_info(pnu):
        # 1. V-World API 시도
        try:
            if vworld_key:
                url = "http://api.vworld.kr/req/data"
                params = {
                    "key": vworld_key, "domain": "https://share.streamlit.io",
                    "service": "data", "version": "2.0", "request": "getfeature",
                    "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO", 
                    "attrfilter": f"pnu:like:{pnu}"
                }
                res = requests.get(url, params=params, timeout=3).json()
                if res.get('response', {}).get('status') == 'OK':
                    feat = res['response']['result']['featureCollection']['features'][0]['properties']
                    return {
                        "source": "V-World",
                        "도로": feat.get('road_side_nm', '미상'),
                        "형상": feat.get('lad_shpe_nm', '미상')
                    }
        except: pass
        return {"source": "AI추론", "도로": "현장확인필요", "형상": "현장확인필요"}

# --------------------------------------------------------------------------------
# [Engine 3] 불사신 AI 분석 (데이터 유무 상관없이 분석)
# --------------------------------------------------------------------------------
def get_immortal_insight(addr, land, feat):
    if not api_key: return "AI 분석 불가 (API 키 확인)"
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 상황별 프롬프트 자동 전환
    if land['source'] == '국토부API':
        data_context = f"확보된 데이터 - 면적:{land['면적']}m2, 공시지가:{land['공시지가']}원, 도로:{feat['도로']}"
        mission = "확보된 실데이터를 바탕으로 정밀 수익성 분석을 수행하세요."
    else:
        data_context = "현재 정부 전산망 응답 지연으로 실시간 데이터 확보 실패."
        mission = f"주소지({addr})의 지리적 특성과 통상적인 지역 시세를 바탕으로 '가상 시나리오'를 분석하세요. (예: 이 지역은 주로 공장 용지로 쓰임 등)"

    prompt = f"""
    당신은 대한민국 0.1% 부동산 개발 전문가입니다.
    대상: {addr}
    상황: {data_context}
    
    [미션] {mission}
    
    다음 3가지 항목으로 '돈이 되는 보고서'를 작성하십시오:
    1. 📍 입지 가치: 해당 지역(읍/면/동)의 개발 호재 및 분위기.
    2. 🏗️ 개발 추천: (데이터가 없다면 가정하여) 가장 적합한 건축 용도 (창고? 전원주택?).
    3. 💰 투자 조언: 지금 매수 타이밍인가? 법인 설립이 유리한가?
    """
    try: return model.generate_content(prompt).text
    except: return "AI가 지역 데이터를 분석하고 있습니다..."

# --------------------------------------------------------------------------------
# [UI] 불사신 대시보드 (Ver 12.0)
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Immortal", layout="wide", page_icon="🦄")

st.markdown("""
<style>
    .success-box { padding:15px; border-radius:10px; background-color:#e6fffa; border-left:5px solid #00cc99; }
    .warning-box { padding:15px; border-radius:10px; background-color:#fff3cd; border-left:5px solid #ffc107; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("Ver 12.0 (Immortal Engine)")
    addr = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 무조건 분석 실행", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr

st.title("지상 AI 부동산 종합 솔루션")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    with st.status("🔍 가용한 모든 데이터를 수집 중입니다...", expanded=True) as status:
        # 1. 위치 확보
        pnu, coords, addr_info = get_location_data(target)
        
        if pnu:
            # 2. 데이터 수집 (실패해도 죽지 않음)
            land_data = HybridDataEngine.get_land_info(pnu)
            feat_data = HybridDataEngine.get_vworld_info(pnu)
            
            # 3. AI 분석 (상황에 맞춰 대응)
            ai_report = get_immortal_insight(target, land_data, feat_data)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            # 4. 지도 (무조건 표시)
            st.map(pd
