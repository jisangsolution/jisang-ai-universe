import os
import sys
import subprocess
import urllib.request
import requests
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st

# [Step 0] 환경 설정 (강제 실행 모드)
def setup_environment():
    required_packages = ["streamlit", "google-generativeai", "requests", "reportlab", "pandas", "plotly"]
    for pkg in required_packages:
        try: __import__(pkg.replace("-", "_"))
        except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules: setup_environment()

import google.generativeai as genai

# [Step 1] API 키 로드 (이중 인코딩 방지)
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
# [Engine 1] PNU & 좌표 마스터
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    if not kakao_key: return None, None, None, "카카오 키 없음"
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    try:
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                b_code = addr['b_code']
                mount_cd = "2" if addr.get('mountain_yn') == 'Y' else "1"
                main = addr['main_address_no'].zfill(4)
                sub = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                pnu = f"{b_code}{mount_cd}{main}{sub}"
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr, "OK"
        return None, None, None, "주소 검색 실패"
    except Exception as e: return None, None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 융합 (강제 연결)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_basic(pnu):
        # 국토부 토지대장
        if not land_go_key and not data_go_key: return {"status": "NO_KEY", "msg": "키 없음"}
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        try:
            res = requests.get(url, params={"serviceKey": land_go_key or data_go_key, "pnu": pnu, "numOfRows": 1}, timeout=5)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "status": "SUCCESS",
                    "지목": item.findtext("lndcgrCodeNm"),
                    "면적": item.findtext("lndpclAr"),
                    "공시지가": item.findtext("pblntfPclnd")
                }
            return {"status": "EMPTY", "msg": "데이터 없음"}
        except Exception as e: return {"status": "ERROR", "msg": str(e)}

    @staticmethod
    def get_land_features(pnu):
        # V-World 토지특성
        if not vworld_key: return {"도로": "-", "형상": "-"}
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key, "domain": "https://share.streamlit.io",
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO", "attrfilter": f"pnu:like:{pnu}"
        }
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get('response', {}).get('status') == 'OK':
                    feat = data['response']['result']['featureCollection']['features'][0]['properties']
                    return {
                        "도로": feat.get('road_side_nm', '정보없음'),
                        "형상": feat.get('lad_shpe_nm', '정보없음')
                    }
        except: pass
        return {"도로": "확인중", "형상": "확인중"}

# --------------------------------------------------------------------------------
# [Engine 3] AI 인사이트
# --------------------------------------------------------------------------------
def get_unicorn_insight(addr, land, feat):
    if not api_key: return "AI 연결 필요"
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    l_info = f"면적:{land.get('면적','-')}m2, 공시지가:{land.get('공시지가','-')}원"
    f_info = f"도로:{feat.get('도로','-')}, 형상:{feat.get('형상','-')}"
    
    prompt = f"""
    당신은 0.1% 부동산 투자 전문가입니다. 
    주소: {addr} / 팩트: {l_info}, {f_info}
    
    이 땅의 '숨겨진 가치(Money Point)'를 3가지로 분석하세요:
    1. 💎 가치 재평가: 겉보기 등급 vs 실제 잠재력 (도로/형상 기반).
    2. 🏗️ 개발 시나리오: 최적의 건축 용도 (창고? 빌라? 카페?).
    3. 💰 투자 전략: 지금 사야 하는가? 법인으로 사야 하는가?
    """
    try: return model.generate_content(prompt).text
    except: return "AI 분석 중... (잠시 후 다시 시도)"

# --------------------------------------------------------------------------------
# [UI] 대시보드
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide", page_icon="🦄")

with st.sidebar:
    st.header("🦄 지상 AI")
    st.caption("Ver 10.1 (Syntax Fix)")
    addr = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 유니콘 분석 실행", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr

st.title("지상 AI 부동산 종합 솔루션")

if st.session_state.get('run'):
    target = st.session_state['addr']
    map_placeholder = st.empty()
    
    with st.status("🔍 돈이 되는 정보를 채굴 중입니다...", expanded=True) as status:
        pnu, coords, info, msg = get_pnu_and_coords(target)
        
        if pnu:
            map_placeholder.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)
            
            land_res = MasterFactEngine.get_land_basic(pnu)
            feat_res = MasterFactEngine.get_land_features(pnu)
            ai_text = get_unicorn_insight(target, land_res, feat_res)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            st.divider()
            
            # [수정 완료] 대괄호 닫기 오류 수정됨
            c1, c2 = st.columns([1, 1.5]) 
            
            with c1:
                st.subheader("📊 팩트 체크 (Money Base)")
                with st.container(border=True):
                    # 토지대장
                    if land_res.get('status') == 'SUCCESS':
                        st.success("✅ 국토부 데이터 확보")
                        st.write(f"• **면적**: {float(land_res['면적']):,.1f}㎡")
                        st.write(f"• **공시지가**: {int(land_res['공시지가']):,}원")
                    else:
                        st.warning(f"⚠️ 국토부 연결 지연: {land_res.get('msg')}")
                    
                    st.markdown("---")
                    
                    # V-World
                    if feat_res['도로'] != "확인중":
                        st.success("✅ 도로/형상 정보 확보")
                        st.write(f"• **도로조건**: {feat_res['도로']}")
                        st.write(f"• **토지형상**: {feat_res['형상']}")
                    else:
                        st.info("ℹ️ 토지특성 분석 중...")

            with c2:
                st.subheader("💡 유니콘 투자 전략")
                st.info(ai_text)
        else:
            st.error(f"주소 오류: {msg}")
