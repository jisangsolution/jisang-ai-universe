import os
import sys
import subprocess
import urllib.request
import requests
from urllib.parse import unquote # [핵심] 키 디코딩 모듈
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st

# [Step 0] 스마트 런처
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

# [Step 1] API 키 로드 및 '무결성 처리'
def get_clean_key(key_name):
    raw_key = st.secrets.get(key_name, "")
    # [핵심] 키에 %가 있다면 디코딩하여 원본으로 복구 (이중 인코딩 방지)
    if "%" in raw_key:
        return unquote(raw_key)
    return raw_key

api_key = get_clean_key("GOOGLE_API_KEY")
data_go_key = get_clean_key("DATA_GO_KR_KEY") # 건축물대장
land_go_key = get_clean_key("LAND_GO_KR_KEY") # 토지대장
kakao_key = st.secrets.get("KAKAO_API_KEY", "") # 카카오는 그대로 사용
vworld_key = st.secrets.get("VWORLD_API_KEY", "") # V-World는 그대로 사용

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] PNU 마스터 (정밀 생성)
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
                b_code = addr['b_code'] # 법정동코드(10자리)
                
                # 산(Mountain) 여부: 'Y'면 2, 아니면 1
                mount_yn = addr.get('mountain_yn', 'N')
                mount_cd = "2" if mount_yn == 'Y' else "1"
                
                # 본번/부번 4자리 패딩 (매우 중요)
                main = addr['main_address_no'].zfill(4)
                sub = addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else "0000"
                
                # PNU 19자리 완성
                pnu = f"{b_code}{mount_cd}{main}{sub}"
                
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr, "OK"
        return None, None, None, "주소 검색 실패"
    except Exception as e:
        return None, None, None, f"카카오 에러: {e}"

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 융합 (디버깅 강화)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_basic(pnu):
        # 토지대장 (국토부)
        if not land_go_key and not data_go_key:
            return {"status": "KEY_ERROR", "msg": "API 키 미설정"}
        
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        # 키는 이미 위에서 unquote 처리됨
        params = {
            "serviceKey": land_go_key or data_go_key, 
            "pnu": pnu, 
            "numOfRows": 1, 
            "pageNo": 1,
            "format": "xml"
        }
        
        try:
            res = requests.get(url, params=params, timeout=10)
            if res.status_code == 200:
                try:
                    root = ET.fromstring(res.content)
                    item = root.find('.//item')
                    if item is not None:
                        return {
                            "status": "SUCCESS",
                            "지목": item.findtext("lndcgrCodeNm"),
                            "면적": item.findtext("lndpclAr"),
                            "공시지가": item.findtext("pblntfPclnd")
                        }
                    else:
                        # 결과 코드가 정상이지만 데이터가 없는 경우 (나대지 등)
                        result_msg = root.findtext('.//resultMsg')
                        return {"status": "EMPTY", "msg": result_msg}
                except:
                    return {"status": "PARSE_ERROR", "msg": "XML 파싱 실패"}
            else:
                return {"status": "HTTP_ERROR", "msg": f"Code {res.status_code}"}
        except Exception as e:
            return {"status": "CONN_ERROR", "msg": str(e)}

    @staticmethod
    def get_land_features(pnu):
        # V-World (토지특성)
        if not vworld_key: return {"도로": "-", "형상": "-", "지세": "-"}
        
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key,
            "domain": "https://share.streamlit.io", # [중요] 실제 서비스 도메인
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO",
            "attrfilter": f"pnu:like:{pnu}"
        }
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get('response', {}).get('status') == 'OK':
                    feat = data['response']['result']['featureCollection']['features'][0]['properties']
                    return {
                        "도로": feat.get('road_side_nm', '정보없음'),
                        "형상": feat.get('lad_shpe_nm', '정보없음'),
                        "지세": feat.get('lad_hght_nm', '정보없음')
                    }
        except: pass
        return {"도로": "확인중", "형상": "확인중", "지세": "확인중"}

# --------------------------------------------------------------------------------
# [Engine 3] AI 인사이트 (강제 실행 모드)
# --------------------------------------------------------------------------------
def get_unicorn_insight(addr, land_data, feat_data):
    if not api_key: return "AI 키가 설정되지 않았습니다."
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # 데이터가 없어도 주소 기반으로 추론하도록 유도
    l_info = f"면적 {land_data.get('면적','미상')}m2, 공시지가 {land_data.get('공시지가','미상')}원"
    f_info = f"도로 {feat_data.get('도로','-')}, 형상 {feat_data.get('형상','-')}"
    
    prompt = f"""
    당신은 부동산 개발 최상위 전문가입니다.
    대상: {addr}
    데이터: {l_info}, {f_info}
    
    데이터가 일부 누락되었더라도 '입지'를 기반으로 아래 내용을 반드시 분석해내세요:
    1. 개발 잠재력: 이 땅에 무엇을 지으면(창고, 상가주택 등) 가장 수익이 날까?
    2. 가치 평가: 공시지가 대비 실거래가 추정 및 투자의견.
    3. 세무 전략: 법인 설립이 유리한지 개인 매입이 유리한지 판단.
    """
    try: return model.generate_content(prompt).text
    except: return "AI 분석 중입니다... 잠시 후 다시 시도해주세요."

# --------------------------------------------------------------------------------
# [UI] 유니콘 대시보드 Ver 10.0
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide", page_icon="🦄")

st.markdown("""
<style>
    .metric-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b; }
    .success-box { background-color: #e6fffa; padding: 15px; border-radius: 10px; border-left: 5px solid #00cc99; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("🦄 지상 AI")
    st.caption("초격차 부동산 솔루션 Ver 10.0")
    addr = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 분석 실행 (강제 연결)", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr

st.title("지상 AI 부동산 종합 시스템")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    # 지도 영역 (가장 먼저 표시)
    map_placeholder = st.empty()
    
    with st.status("🔍 데이터 파이프라인 정밀 진단 중...", expanded=True) as status:
        st.write("1. 카카오 위성 좌표 및 PNU 생성...")
        pnu, coords, addr_info, msg = get_pnu_and_coords(target)
        
        if pnu:
            st.write(f"👉 생성된 PNU: {pnu} (정상)")
            map_placeholder.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)
            
            st.write("2. 국토부 토지대장 데이터 호출...")
            land_res = MasterFactEngine.get_land_basic(pnu)
            
            st.write("3. V-World 토지특성 데이터 호출...")
            feat_res = MasterFactEngine.get_land_features(pnu)
            
            st.write("4. AI 종합 분석 생성...")
            ai_text = get_unicorn_insight(target, land_res, feat_res)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            st.divider()
            
            # 결과 화면
            c1, c2 = st.columns([1, 1
