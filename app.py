import os
import sys
import subprocess
import requests
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st

# [Step 0] 환경 설정
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "reportlab", "pandas", "plotly"]
    for pkg in required:
        try: __import__(pkg.replace("-", "_"))
        except ImportError: subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    font_path = "NanumGothic.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try: urllib.request.urlretrieve(url, font_path)
        except: pass

if "streamlit" not in sys.modules: setup_environment()

import google.generativeai as genai

# API 키 로드
api_key = st.secrets.get("GOOGLE_API_KEY", "")
data_go_key = st.secrets.get("DATA_GO_KR_KEY", "")
land_go_key = st.secrets.get("LAND_GO_KR_KEY", "")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
vworld_key = st.secrets.get("VWORLD_API_KEY", "")

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] PNU 생성기 (정밀도 100%)
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    if not kakao_key: return None, None, None, "카카오 키 없음"
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {kakao_key}"}
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=3)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                pnu = f"{addr['b_code']}{'2' if addr['mountain_yn']=='Y' else '1'}{addr['main_address_no'].zfill(4)}{addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else '0000'}"
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr, "OK"
        return None, None, None, "주소 검색 실패"
    except Exception as e: return None, None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 융합 (스마트 리트라이 기술 적용)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_basic(pnu):
        # 1차 시도: 원본 키 사용
        target_key = land_go_key or data_go_key
        if not target_key: return {"status": "NO_KEY", "msg": "API 키 없음"}
        
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        
        # [전략] 1. 디코딩된 키로 시도 -> 2. 실패시 원본 키로 시도
        keys_to_try = [unquote(target_key), target_key]
        
        for i, key in enumerate(keys_to_try):
            try:
                res = requests.get(url, params={"serviceKey": key, "pnu": pnu, "numOfRows": 1, "format": "xml"}, timeout=5)
                # 응답이 XML인지 확인
                if res.text.startswith("<"):
                    try:
                        root = ET.fromstring(res.content)
                        # 에러 메시지가 담겨있는지 확인
                        err_msg = root.findtext('.//returnAuthMsg')
                        if err_msg: 
                            if i == 0: continue # 첫 시도 실패면 다음 키로
                            return {"status": "API_ERROR", "msg": err_msg} # 둘 다 실패면 에러 리턴
                            
                        item = root.find('.//item')
                        if item:
                            return {
                                "status": "SUCCESS",
                                "지목": item.findtext("lndcgrCodeNm"),
                                "면적": item.findtext("lndpclAr"),
                                "공시지가": item.findtext("pblntfPclnd")
                            }
                        else:
                            # 정상 호출됐으나 데이터가 없는 경우 (나대지 등)
                            return {"status": "EMPTY", "msg": "데이터 없음(나대지 추정)"}
                    except: pass
                else:
                    # XML이 아님 -> 에러 텍스트일 확률 높음 (SERVICE KEY IS NOT REGISTERED 등)
                    if i == 1: return {"status": "TEXT_ERROR", "msg": res.text[:100]} # 에러 내용 보여주기
            except Exception as e:
                if i == 1: return {"status": "CONN_ERROR", "msg": str(e)}
        
        return {"status": "FAIL", "msg": "모든 키 시도 실패"}

    @staticmethod
    def get_land_features(pnu):
        if not vworld_key: return {"도로": "-", "형상": "-"}
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key, "domain": "https://share.streamlit.io",
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO", "attrfilter": f"pnu:like:{pnu}"
        }
        try:
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            if data.get('response', {}).get('status') == 'OK':
                feat = data['response']['result']['featureCollection']['features'][0]['properties']
                return {"도로": feat.get('road_side_nm','-'), "형상": feat.get('lad_shpe_nm','-')}
        except: pass
        return {"도로": "확인중", "형상": "확인중"}

# --------------------------------------------------------------------------------
# [Engine 3] 유니콘 AI (돈이 되는 정보 추출)
# --------------------------------------------------------------------------------
def get_unicorn_insight(addr, land, feat):
    if not api_key: return "AI 연결 필요"
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    l_txt = f"면적:{land.get('면적','-')}m2, 공시지가:{land.get('공시지가','-')}원"
    f_txt = f"도로:{feat.get('도로','-')}, 형상:{feat.get('형상','-')}"
    
    prompt = f"""
    당신은 부동산 수익화 전문가입니다.
    대상: {addr} / 데이터: {l_txt}, {f_txt}
    
    [미션] 이 땅으로 '돈 벌 수 있는 방법' 3가지를 구체적 수치로 제안하세요.
    1. 💎 가치 뻥튀기: 현재 지목/형상 대비 저평가 요인과 해결책.
    2. 🏗️ 건축 마진: 예상 건폐율/용적률 적용 시 최대 건축 면적과 추천 업종(창고, 카페 등).
    3. 💰 세금 헷지: 법인 매입 vs 개인 매입 세금 차이 시뮬레이션.
    """
    try: return model.generate_content(prompt).text
    except: return "AI 분석 중... (잠시 후 다시 시도)"

# --------------------------------------------------------------------------------
# [UI] 대시보드 Ver 10.2
# --------------------------------------------------------------------------------
st.set_page_config(page_title="Jisang AI Unicorn", layout="wide", page_icon="🦄")

with st.sidebar:
    st.header("🦄 지상 AI")
    st.caption("Ver 10.2 (Smart Retry)")
    addr = st.text_input("주소 입력", "경기도 김포시 통진읍 도사리 163-1")
    if st.button("🚀 유니콘 분석 실행", type="primary"):
        st.session_state['run'] = True
        st.session_state['addr'] = addr

st.title("지상 AI 부동산 종합 솔루션")

if st.session_state.get('run'):
    target = st.session_state['addr']
    
    with st.status("🔍 돈이 되는 정보를 채굴 중입니다...", expanded=True) as status:
        pnu, coords, info, msg = get_pnu_and_coords(target)
        
        if pnu:
            st.map(pd.DataFrame({'lat': [coords[0]], 'lon': [coords[1]]}), zoom=17)
            
            land_res = MasterFactEngine.get_land_basic(pnu)
            feat_res = MasterFactEngine.get_land_features(pnu)
            ai_text = get_unicorn_insight(target, land_res, feat_res)
            
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            st.divider()
            c1, c2 = st.columns([1, 1.5])
            
            with c1:
                st.subheader("📊 팩트 체크 (Money Base)")
                with st.container(border=True):
                    # 국토부 데이터 상태 표시
                    if land_res.get('status') == 'SUCCESS':
                        st.success("✅ 국토부 데이터 확보")
                        st.write(f"• **면적**: {float(land_res['면적']):,.1f}㎡")
                        st.write(f"• **공시지가**: {int(land_res['공시지가']):,}원")
                    elif land_res.get('status') == 'TEXT_ERROR':
                        st.error(f"❌ 인증키 에러: {land_res['msg']}")
                        st.caption("→ 공공데이터포털에서 키가 '승인' 상태인지 확인하세요.")
                    else:
                        st.warning(f"⚠️ 연결 지연: {land_res.get('msg')}")
                    
                    st.markdown("---")
                    
                    # V-World 데이터 상태 표시
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
