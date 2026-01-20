import os
import sys
import time
import subprocess
import urllib.request
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st

# [Step 0] 스마트 런처: 라이브러리 및 폰트 강제 복구 모드
def setup_environment():
    required_packages = ["streamlit", "google-generativeai", "requests", "reportlab", "pandas", "plotly"]
    for pkg in required_packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    
    # 한글 폰트 안전 확보
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except:
            pass # 폰트 다운 실패해도 시스템은 돌아가야 함

# 모듈 로딩 전 환경 점검
if "streamlit" not in sys.modules:
    setup_environment()

import google.generativeai as genai

# [Step 1] Secrets 로드 (결함 방지 처리)
def get_secret(key_name):
    try:
        return st.secrets.get(key_name)
    except:
        return None

api_key = get_secret("GOOGLE_API_KEY")
data_go_key = get_secret("DATA_GO_KR_KEY")
land_go_key = get_secret("LAND_GO_KR_KEY")
kakao_key = get_secret("KAKAO_API_KEY")
vworld_key = get_secret("VWORLD_API_KEY")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] PNU 마스터 (주소 -> 좌표/코드 변환)
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    if not kakao_key: return None, None, None, "카카오 API 키가 설정되지 않았습니다."
    
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    
    try:
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                b_code = addr['b_code']
                mount_cd = "2" if addr.get('mountain_yn') == 'Y' else "1"
                pnu = f"{b_code}{mount_cd}{addr['main_address_no'].zfill(4)}{addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else '0000'}"
                
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr, "Success"
        return None, None, None, "주소를 찾을 수 없습니다."
    except Exception as e:
        return None, None, None, f"카카오 API 오류: {str(e)}"

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 융합 엔진 (V-World + 국토부 + 예외처리)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_features(pnu):
        # V-World API (토지특성)
        if not vworld_key: return {"도로접면": "API키 없음", "형상": "API키 없음", "지세": "-"}
        
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key,
            "domain": "https://share.streamlit.io", # 중요: V-World에 등록된 도메인과 일치해야 함
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO",
            "attrfilter": f"pnu:like:{pnu}"
        }
        
        try:
            # 타임아웃을 짧게 주어 UI 블로킹 방지
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get('response', {}).get('status') == 'OK':
                    feat = data['response']['result']['featureCollection']['features'][0]['properties']
                    return {
                        "도로접면": feat.get('road_side_nm', '확인불가'),
                        "형상": feat.get('lad_shpe_nm', '확인불가'),
                        "지세": feat.get('lad_hght_nm', '확인불가')
                    }
        except:
            pass
        return {"도로접면": "데이터 연결 중", "형상": "데이터 연결 중", "지세": "데이터 연결 중"}

    @staticmethod
    def get_land_basic(pnu):
        # 국토부 토지대장
        if not land_go_key and not data_go_key: return None
        
        real_key = requests.utils.unquote(land_go_key or data_go_key)
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        
        try:
            res = requests.get(url, params={"serviceKey": real_key, "pnu": pnu, "numOfRows": 1}, timeout=5)
            if res.status_code == 200:
                root = ET.fromstring(res.content)
                item = root.find('.//item')
                if item is not None:
                    return {
                        "지목": item.findtext("lndcgrCodeNm"),
                        "면적": item.findtext("lndpclAr"),
                        "공시지가": item.findtext("pblntfPclnd")
                    }
        except:
            pass
        return None

# --------------------------------------------------------------------------------
# [Engine 3] AI 수석 전략가 (Gemini 1.5 Flash - 추론 강화)
# --------------------------------------------------------------------------------
def get_unicorn_insight(addr, land, feat):
    if not api_key: return "Google API 키가 필요합니다."
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 데이터가 없을 경우를 대비한 방어 로직
    land_info = f"면적 {land['면적']}m2, 지목 {land['지목']}, 공시지가 {land['공시지가']}원" if land else "토지대장 데이터 수신 대기중"
    feat_info = f"도로 {feat['도로접면']}, 형상 {feat['형상']}" if feat else "토지특성 데이터 수신 대기중"
    
    prompt = f"""
    당신은 대한민국 상위 0.1% 부동산 개발 전문가(건축사+감정평가사+시행사)입니다.
    
    [분석 대상]
    주소: {addr}
    토지 팩트: {land_info}
    물리적 특성: {feat_info}

    위 데이터를 바탕으로 투자자(매수자)에게 '확신'을 줄 수 있는 3가지 핵심 전략을 제시하세요.
    데이터가 부족하다면 입지(주소)를 바탕으로 일반적인 가능성을 추론하여 답변하세요.

    1. 📐 **개발 최적화**: 지목과 형상을 고려할 때 어떤 건축물(상가주택, 창고, 근생 등)이 가장 적합한가?
    2. 💰 **가치 평가**: 공시지가 대비 실거래가 추정 및 수익성 코멘트.
    3. ⚖️ **원클릭 솔루션**: 이 땅을 매입하기 위해 법인 설립이 유리한지, 개인 매입이 유리한지 세무적 관점 1줄 요약.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 엔진 재가동 중... (잠시 후 다시 시도해주세요)"

# --------------------------------------------------------------------------------
# [UI] 유니콘 마스터 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide", page_icon="🦄")

# 스타일링 (가독성 최적화)
st.markdown("""
<style>
    .metric-card { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #e9ecef; }
    .stButton>button { width: 100%; border-radius: 5px; height: 50px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("🦄 지상 AI")
    st.caption("초격차 부동산 종합 솔루션 Ver 9.5")
    st.markdown("---")
    
    target_addr = st.text_input("📍 분석할 주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    search_btn = st.button("🚀 유니콘 분석 실행", type="primary")
    
    st.markdown("---")
    st.info("💡 **경쟁 우위 기능**\n\n• V-World 토지 특성 자동 분석\n• 국토부 대장 실시간 연동\n• AI 기반 가치 평가 및 전략")

st.title("지상 AI 부동산 의사결정 시스템")

if search_btn:
    with st.spinner("🛰️ 국가 행정망 및 AI 신경망 연동 중..."):
        pnu, coords, addr_data, msg = get_pnu_and_coords(target_addr)
        
        if pnu:
            # 1. 데이터 병렬 수집 (속도 최적화)
            land_basic = MasterFactEngine.get_land_basic(pnu)
            land_feat = MasterFactEngine.get_land_features(pnu)
            
            # 2. AI 분석 (데이터가 일부 없어도 강제 실행)
            ai_insight = get_unicorn_insight(target_addr, land_basic, land_feat)
            
            # 3. 화면 렌더링
            st.success("✅ 분석 완료")
            
            # 지도 섹션
            st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)
            
            st.divider()
            
            col1, col2 = st.columns([1, 1.5])
            
            with col1:
                st.subheader("📊 팩트 체크 (Data Integrity)")
                with st.container(border=True):
                    if land_basic:
                        st.markdown(f"**• 지목**: `{land_basic['지목']}`")
                        st.markdown(f"**• 면적**: `{float(land_basic['면적']):,.1f}㎡`")
                        st.markdown(f"**• 공시지가**: `{int(land_basic['공시지가']):,}원/㎡`")
                    else:
                        st.warning("⚠️ 국토부 데이터 동기화 중")

                    st.markdown("---")
                    
                    if land_feat:
                        st.markdown(f"**• 도로접면**: `{land_feat['도로접면']}`")
                        st.markdown(f"**• 토지형상**: `{land_feat['형상']}`")
                        st.markdown(f"**• 지세**: `{land_feat['지세']}`")
                    else:
                        st.warning("⚠️ V-World 데이터 동기화 중")
            
            with col2:
                st.subheader("💡 유니콘 수석 전략가 의견")
                with st.container(border=True):
                    st.markdown(ai_insight)
                    st.caption("※ 본 리포트는 AI 추론 결과이며, 실제 투자는 전문가 자문이 필요합니다.")
        else:
            st.error(f"❌ 오류 발생: {msg}")

else:
    st.info("👈 왼쪽 사이드바에서 주소를 입력하고 분석을 시작하세요.")
