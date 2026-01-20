import os
import sys
import subprocess
import requests
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st

# [Step 0] 스마트 런처
def setup_environment():
    required = ["streamlit", "google-generativeai", "requests", "pandas", "plotly"]
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

# [Step 1] API 키 로드 (자동 보정)
def get_clean_key(key_name):
    raw_key = st.secrets.get(key_name, "")
    if "%" in raw_key: return unquote(raw_key)
    return raw_key

api_key = get_clean_key("GOOGLE_API_KEY")
data_go_key = get_clean_key("DATA_GO_KR_KEY")
land_go_key = get_clean_key("LAND_GO_KR_KEY")
kakao_key = st.secrets.get("KAKAO_API_KEY", "")
vworld_key = st.secrets.get("VWORLD_API_KEY", "") # [NEW] 새 키 적용

if api_key: genai.configure(api_key=api_key)

# --------------------------------------------------------------------------------
# [Engine 1] PNU & 좌표 마스터
# --------------------------------------------------------------------------------
def get_pnu_and_coords(address):
    if not kakao_key: return None, None, None, "카카오 키 없음"
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {kakao_key}"}
        resp = requests.get(url, headers=headers, params={"query": address}, timeout=5)
        if resp.status_code == 200:
            docs = resp.json().get('documents')
            if docs:
                addr = docs[0]['address']
                pnu = f"{addr['b_code']}{'2' if addr.get('mountain_yn')=='Y' else '1'}{addr['main_address_no'].zfill(4)}{addr['sub_address_no'].zfill(4) if addr['sub_address_no'] else '0000'}"
                return pnu, (float(docs[0]['y']), float(docs[0]['x'])), addr, "OK"
        return None, None, None, "주소 검색 실패"
    except Exception as e: return None, None, None, str(e)

# --------------------------------------------------------------------------------
# [Engine 2] 데이터 융합 (V-World 연결 강화)
# --------------------------------------------------------------------------------
class MasterFactEngine:
    @staticmethod
    def get_land_basic(pnu):
        # 국토부 토지대장
        target_key = land_go_key or data_go_key
        if not target_key: return {"status": "NO_KEY", "msg": "키 없음"}
        
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        try:
            # unquote된 키로 시도
            res = requests.get(url, params={"serviceKey": target_key, "pnu": pnu, "numOfRows": 1}, timeout=5)
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
        # [핵심] V-World 토지특성 (새 키 적용 확인)
        if not vworld_key: return {"도로": "키 없음", "형상": "키 없음"}
        
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key, 
            "domain": "https://share.streamlit.io", # 도메인 필수
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO", 
            "attrfilter": f"pnu:like:{pnu}"
        }
        try:
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            if data.get('response', {}).get('status') == 'OK':
                feat = data['response']['result']['featureCollection']['features'][0]['properties']
                return {
                    "도로": feat.get('road_side_nm', '정보없음'),
                    "형상
