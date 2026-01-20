import os
import sys
import subprocess
import requests
import pandas as pd
import streamlit as st
from urllib.parse import unquote
import xml.etree.ElementTree as ET

# [Step 0] 환경 설정 및 라이브러리 검증
def setup_environment():
    required_packages = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except:
            pass

if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# [Step 1] API 키 로드 (이중 인코딩 방지 로직 적용)
def get_clean_key(key_name):
    raw_key = st.secrets.get(key_name, "")
    if "%" in raw_key:
        return unquote(raw_key)
    return raw_key

api_key = get_clean_key("GOOGLE_API_KEY")
data_go_key = get_clean_key("DATA_GO_KR_KEY")
land_go_key = get_clean_key("LAND_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
vworld_key = st.secrets.get("VWORLD_API_KEY", "")

if api_key:
    genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] 좌표 & PNU 생성 (안전성 최우선)
# --------------------------------------------------------------------------------
def get_location_data(address):
    if not kakao_key:
        return None, None, "카카오 API 키가 없습니다."
    
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {kakao_key}"}
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=5)
        
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                # PNU 생성 로직
                b_code = addr['b_code']
                mount = "2" if addr.get('mountain_yn') == 'Y' else "1"
                main = addr['main_address_no'].zfill(4)
                sub = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                pnu = f"{b_code}{mount}{main}{sub}"
                
                # 좌표 반환
                coords = (float(docs[0]['y']), float(docs[0]['x']))
                return pnu, coords, addr
            
        return None, None, "검색 결과가 없습니다."
    except Exception as e:
        return None, None, f"에러 발생: {str(e)}"

# --------------------------------------------------------------------------------
# [Engine 2] 하이브리드 데이터 수집 (API 오류 시 자동 우회)
# --------------------------------------------------------------------------------
class HybridDataEngine:
    @staticmethod
    def get_land_info(pnu):
        # 1. 국토부 API 시도
        target_key = land_go_key or data_go_key
        if target_key:
            url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
            keys_to_try = [target_key, unquote(target_key)]
            
            for k in keys_to_try:
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
                except:
                    continue
        
        # 2. 실패 시 기본값 (AI 추론용)
        return {"source": "AI추론", "지목": "확인필요", "면적": "0", "공시지가": "0"}

    @staticmethod
    def get_vworld_info(pnu):
        # 1. V-World API 시도
        if vworld_key:
            try:
                url = "http://api.vworld.kr/req/data"
                params = {
                    "key": vworld_key, 
                    "domain": "https://share.streamlit.io",
                    "service": "data", 
                    "version": "2.0", 
                    "request": "getfeature",
                    "format": "json", 
                    "size": "1", 
                    "data": "LP_PA_CBND_BU_INFO", 
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
            except:
                pass
                
        return {"source": "AI추론", "도로": "현장확인", "형상": "현장확인"}

# --------------------------------------------------------------------------------
# [Engine 3] 불사신 AI 분석 (데이터 유무 무관 실행)
# --------------------------------------------------------------------------------
def get_immortal_insight(addr, land, feat):
    if not api_key:
        return "Google AI API 키가 설정되지 않았습니다."
        
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 데이터 상태에 따른 프롬프트 분기
    if land['source'] == '국토부API':
        status_msg = f"확보된 데이터 - 면적: {land['면적']}m2, 공시지가: {land['공시지가']}원, 도로: {feat['도로']}"
        mission = "확보된 데이터를 바탕으로 정밀 수익성 분석을 수행하세요."
    else:
        status_msg = "정부 전산망 응답 지연으로 인해 정확한 수치 데이터 확보 실패."
        mission = f"주소지({addr})의 입지적 특성(위성지도 기반 추론)과 통상적인 용도지역을 가정하여 가상의 개발 시나리오를 제시하세요."

    prompt = f"""
    당신은 대한민국 상위 0.1% 부동산 개발 전문가입니다.
    
    [분석 대상]
    주소: {addr}
    상황: {status_msg}
    
    [미션]
    {mission}
    
    다음 3가지 항목으로 리포트를 작성하십시오:
    1. 📍 입지 및 잠재력: 해당 지역의 개발 호재 및 분위기.
    2. 🏗️ 개발 추천: (데이터가 없다면 가정하여) 가장 적합한 건축 용도 (창고? 전원주택? 근생?).
    3. 💰 투자 조언: 매수 타이밍과 법인 설립의 유리함 여부.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류가 발생했습니다: {str(e)}"

# --------------------------------------------------------------------------------
# [UI] 불사신 대시보드 (Ver 12.1 - Syntax Safe)
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Immortal", layout="wide", page_icon="🦄")

# CSS 스타일링
st.markdown("""
<style>
    .success-box { padding:15px; border-radius:10px; background-color:#e6fffa; border-left:5px solid #00cc99; }
    .warning-box { padding:15px; border-radius:10px; background-color:#fff3cd; border-left:5px solid #ffc107; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("Ver 12.1 (Syntax Perfect)")
    addr_input = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    
    if st.button("🚀 무조건 분석 실행", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr_input

st.title("지상 AI 부동산 종합 솔루션")

if st.session_state.get('run'):
    target_addr = st.session_state['addr']
    
    with st.status("🔍 가용한 모든 데이터를 수집 중입니다...", expanded=True) as status:
        # 1. 위치 확보
        pnu_code, coordinates, addr_info = get_location_data(target_addr)
        
        if pnu_code:
            # 2. 데이터 수집 (안전장치 가동)
            land_result = HybridDataEngine.get_land_info(pnu_code)
            feat_result = HybridDataEngine.get_vworld_info(pnu_code)
            
            # 3. AI 분석
            ai_report_text = get_immortal_insight(target_addr, land_result, feat_result)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            # 4. 지도 표시 (Syntax Error 원천 차단: 변수 분리)
            if coordinates:
                map_data = pd.DataFrame({'lat': [coordinates[0]], 'lon': [coordinates[1]]})
                st.map(map_data, zoom=16)
            
            st.divider()
            
            # 5. 결과 리포트 (컬럼 분리 안전하게)
            col1, col2 = st.columns([1, 1.5])
            
            with col1:
                st.subheader("📊 데이터 팩트 체크")
                
                # 국토부 데이터 표시
                if land_result['source'] == '국토부API':
                    st.markdown(f"""<div class="success-box">
                    <b>✅ 국토부 실데이터 확보</b><br>
                    • 지목: {land_result['지목']}<br>
                    • 면적: {float(land_result['면적']):,.1f}㎡<br>
                    • 공시지가: {int(land_result['공시지가']):,}원
                    </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div class="warning-box">
                    <b>⚠️ 국토부 데이터 지연 (AI 추론 모드)</b><br>
                    정부 서버 응답이 없어 AI가 주변 시세를 기반으로 분석합니다.<br>
                    <small>* 정확한 수치는 '디스코' 확인 권장</small>
                    </div>""", unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                # V-World 데이터 표시
                if feat_result['source'] == 'V-World':
                    st.markdown(f"""<div class="success-box">
                    <b>✅ V-World 특성 확보</b><br>
                    • 도로조건: {feat_result['도로']}<br>
                    • 토지형상: {feat_result['형상']}
                    </div>""", unsafe_allow_html
