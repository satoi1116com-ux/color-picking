# streamlit_colorpicker_experiment.py
# Streamlit 実験：連続フルカラーピッカー版
import streamlit as st
import time
import random
import io
import csv
from typing import List, Dict, Any, Optional
from datetime import datetime

st.set_page_config(page_title="連続カラーピッカー実験", layout="wide")
st.title("連続カラーピッカー実験（st.color_picker 使用）")

# ---------------- utilities ----------------
def hex_to_rgb(hexstr: str):
    h = hexstr.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hsl(r:int,g:int,b:int):
    # r,g,b in 0-255 -> H,S,L (H:0-360, S,L:0-100)
    r_, g_, b_ = r/255.0, g/255.0, b/255.0
    mx = max(r_, g_, b_)
    mn = min(r_, g_, b_)
    diff = mx - mn
    l = (mx + mn) / 2.0
    if diff == 0:
        h = 0.0
        s = 0.0
    else:
        s = diff / (2.0 - mx - mn) if l > 0.5 else diff / (mx + mn)
        if mx == r_:
            h = (g_ - b_) / diff + (6 if g_ < b_ else 0)
        elif mx == g_:
            h = (b_ - r_) / diff + 2
        else:
            h = (r_ - g_) / diff + 4
        h = h * 60.0
    return {'H': round(h,2), 'S': round(s*100,2), 'L': round(l*100,2)}

def hsl_from_hex(hexstr: str):
    r,g,b = hex_to_rgb(hexstr)
    return rgb_to_hsl(r,g,b)

# ---------------- session state defaults ----------------
if 'audio_files' not in st.session_state:
    st.session_state['audio_files'] = []  # list of dict {'name','data'}
if 'trials_order' not in st.session_state:
    st.session_state['trials_order'] = []
if 'current_trial' not in st.session_state:
    st.session_state['current_trial'] = -1
if 'results' not in st.session_state:
    st.session_state['results'] = []
if 'practice' not in st.session_state:
    st.session_state['practice'] = False
if 'trial_start_time' not in st.session_state:
    st.session_state['trial_start_time'] = None
if 'current_color' not in st.session_state:
    st.session_state['current_color'] = '#7f7f7f'  # 初期色
if 'shuffle' not in st.session_state:
    st.session_state['shuffle'] = False

# ---------------- sidebar: controls ----------------
with st.sidebar:
    st.header("実験コントロール（カラーピッカー版）")
    uploaded = st.file_uploader("オーディオファイルを選択（複数可）", type=['wav','mp3','ogg','m4a'], accept_multiple_files=True)
    st.session_state['shuffle'] = st.checkbox("トライアル順をシャッフル", value=st.session_state['shuffle'])
    st.session_state['practice'] = st.checkbox("練習モード（保存しない）", value=st.session_state['practice'])
    # ボタン群
    col1, col2 = st.columns(2)
    with col1:
        if st.button("読み込み"):
            files = uploaded or []
            st.session_state['audio_files'] = []
            for f in files:
                st.session_state['audio_files'].append({'name': f.name, 'data': f.read()})
            st.success(f"{len(st.session_state['audio_files'])} ファイルを読み込みました")
            # reset experiment
            st.session_state['results'] = []
            st.session_state['current_trial'] = -1
            st.session_state['trial_start_time'] = None
    with col2:
        if st.button("全リセット"):
            st.session_state['audio_files'] = []
            st.session_state['trials_order'] = []
            st.session_state['current_trial'] = -1
            st.session_state['results'] = []
            st.session_state['trial_start_time'] = None
            st.session_state['current_color'] = '#7f7f7f'
            st.success("リセットしました")

    if st.button("実験開始"):
        n = len(st.session_state['audio_files'])
        if n == 0:
            # audio が無ければ1試行（音なし）
            st.session_state['trials_order'] = [None]
        else:
            st.session_state['trials_order'] = list(range(n))
        if st.session_state['shuffle']:
            random.shuffle(st.session_state['trials_order'])
        st.session_state['current_trial'] = 0
        st.session_state['results'] = []
        st.session_state['trial_start_time'] = time.time()
        st.success("実験を開始しました（最初の試行へ）")

    st.markdown("---")
    # CSV ダウンロード（保存済み結果）
    if st.session_state['results']:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['trial','audioName','color_hex','finalH','finalS','finalL','rt_ms','timestamp','practice'])
        for r in st.session_state['results']:
            writer.writerow([r['trial'], r['audioName'], r['color_hex'],
                             r['finalHSL']['H'], r['finalHSL']['S'], r['finalHSL']['L'],
                             r['rt_ms'], r['timestamp'], r['practice']])
        st.download_button("結果CSVをダウンロード", data=buf.getvalue(), file_name="colorpicker_results.csv", mime="text/csv")

# ---------------- main area ----------------
col_main, col_log = st.columns([3,1])

with col_main:
    st.subheader("インタラクティブ（色の選択）")
    if st.session_state['current_trial'] == -1:
        st.info("ファイルを読み込み、サイドバーの「実験開始」を押してください。")
    else:
        idx = st.session_state['trials_order'][st.session_state['current_trial']]
        audio_label = "(なし)" if idx is None else st.session_state['audio_files'][idx]['name']
        st.markdown(f"**トライアル**: {st.session_state['current_trial']+1} / {len(st.session_state['trials_order'])} 　|　 **音声**: {audio_label}")
        # 再生ボタン（st.audio）
        if idx is not None:
            st.audio(st.session_state['audio_files'][idx]['data'])

        # color picker
        st.markdown("色を自由に選択してください。満足したら「決定」を押してください。")
        # color_picker は常に現在の色を返すので session_state と同期させる
        picked = st.color_picker("色の選択 (フルカラーピッカー)", st.session_state.get('current_color', '#7f7f7f'))
        st.session_state['current_color'] = picked

        # start time は試行開始時にセットされるようにする
        if st.session_state['trial_start_time'] is None:
            st.session_state['trial_start_time'] = time.time()

        # 決定ボタン
        if st.button("決定（この色で確定）"):
            rt_ms = int((time.time() - st.session_state['trial_start_time']) * 1000)
            hsl = hsl_from_hex(picked)
            trial_record = {
                'trial': st.session_state['current_trial']+1,
                'audioName': audio_label,
                'color_hex': picked,
                'finalHSL': hsl,
                'rt_ms': rt_ms,
                'timestamp': datetime.now().isoformat(),
                'practice': st.session_state['practice']
            }
            if not st.session_state['practice']:
                st.session_state['results'].append(trial_record)
            st.success(f"記録: {picked} | RT={rt_ms} ms")
            # advance to next trial
            st.session_state['current_trial'] += 1
            st.session_state['trial_start_time'] = None
            # reset picked color to neutral (optional)
            st.session_state['current_color'] = picked  # 続けて同じ色を初期にする場合
            # end of experiment?
            if st.session_state['current_trial'] >= len(st.session_state['trials_order']):
                st.balloons()
                st.info("全トライアル終了しました。サイドバーからCSVをダウンロードできます。")
                st.session_state['current_trial'] = -1
            # rerender happens automatically on interaction

with col_log:
    st.subheader("ログ")
    if st.session_state['results']:
        # 最新10件を表示
        for r in st.session_state['results'][-10:][::-1]:
            st.write(f"#{r['trial']} {r['audioName']} {r['color_hex']} RT={r['rt_ms']}ms")
    else:
        st.write("記録なし")

st.markdown("---")
st.caption("注: 本実装は Streamlit のサーバ往復で RT を計測するため、ブラウザの高精度測定より誤差が出ます。高精度が必要ならクライアント側で計測し結果のみ送信する方式を推奨します。")
