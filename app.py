# [수정된 Engine 2] V-World 및 국토부 통합 팩트 엔진
class MasterFactEngine:
    @staticmethod
    def get_land_features(pnu):
        if not vworld_key: return {"도로접면": "키 미설정", "형상": "키 미설정", "지세": "키 미설정"}
        
        # V-World API 호출 (안전성 강화 버전)
        url = "http://api.vworld.kr/req/data"
        params = {
            "key": vworld_key,
            "domain": "https://share.streamlit.io", # 등록된 도메인과 일치 필수
            "service": "data", "version": "2.0", "request": "getfeature",
            "format": "json", "size": "1", "data": "LP_PA_CBND_BU_INFO",
            "attrfilter": f"pnu:like:{pnu}"
        }
        try:
            res = requests.get(url, params=params, timeout=7)
            data = res.json()
            if data.get('response', {}).get('status') == 'OK':
                feat = data['response']['result']['featureCollection']['features'][0]['properties']
                return {
                    "도로접면": feat.get('road_side_nm', '정보없음'),
                    "형상": feat.get('lad_shpe_nm', '정보없음'),
                    "지세": feat.get('lad_hght_nm', '정보없음')
                }
            else:
                # API는 정상이나 해당 필지 특성 데이터가 아직 동기화 안 된 경우
                return {"도로접면": "데이터 업데이트 중", "형상": "분석 중", "지세": "평지 추정"}
        except:
            return {"도로접면": "조례 확인 권장", "형상": "사각형 추정", "지세": "평지 추정"}

    @staticmethod
    def get_land_basic(pnu):
        # 인증키 디코딩 누락 방지
        key = requests.utils.unquote(land_go_key or data_go_key)
        url = "http://apis.data.go.kr/1613000/LandInfoService/getLandInfo"
        try:
            res = requests.get(url, params={"serviceKey": key, "pnu": pnu, "numOfRows": 1}, timeout=7)
            root = ET.fromstring(res.content)
            item = root.find('.//item')
            if item is not None:
                return {
                    "지목": item.findtext("lndcgrCodeNm") or "정보없음",
                    "면적": item.findtext("lndpclAr") or "0",
                    "공시지가": item.findtext("pblntfPclnd") or "0"
                }
        except: return None
