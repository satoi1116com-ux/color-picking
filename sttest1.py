# streamlittest1.py
# Streamlit版：階層的色選択実験（サーバ側計測の簡易実装）
import streamlit as st
import time
import random
import io
import csv
from typing import List, Dict

st.set_page_config(page_title="階層的色選択実験（Python/Streamlit版）", layout="wide")
st.title("階層的色選択実験（Python/Streamlit版）")

def clamp(v, a, b):
    return max(a, min(b, v))

def path_to_hsl_separated(path: List[int]):
    baseHues = [0, 120, 240]
    hueDeltas = [0, 30, 15, 8, 4, 2, 1, 0.5]
    satBase = 70
    lightBase = 50
    stepAttribute = ['hue','hue','hue','saturation','saturation','lightness','lightness','final']

    filled = path + [1] * (8 - len(path))
    H = baseHues[filled[0]]
    S = satBase
    L = lightBase
    for i in range(1, 8):
        m = filled[i] - 1
        attr = stepAttribute[i]
        if attr == 'hue':
            delta = hueDeltas[i] if i < len(hueDeltas) else 5
            H += m * delta
        elif attr == 'saturation':
            satChange = 18 if i == 3 else 8
            S += m * satChange
        elif attr == 'lightness':
            lightChange = 12 if i == 5 else 6
            L += m * lightChange
        elif attr == 'final':
            H += m * 1.5
            S += m * 2
            L += m * 1.2
    H = (H % 360 + 360) % 360
    S = clamp(round(S), 8, 95)
    L = clamp(round(L), 3, 95)
    return {'H': H, 'S': S, 'L': L}

def hsl_to_hex(hsl: Dict[str, float]):
    h = hsl['H'] / 360.0
    s = hsl['S'] / 100.0
    l = hsl['L'] / 100.0

    def hue2rgb(p, q, t):
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1/6:
            return p + (q - p) * 6 * t
        if t < 1/2:
            return q
        if t < 2/3:
            return p + (q - p) * (2/3 - t) * 6
        return p

    if s == 0:
        r = g = b = l
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue2rgb(p, q, h + 1/3)
        g = hue2rgb(p, q, h)
        b = hue2rgb(p, q, h - 1/3)

    def to_hex(x):
        return format(int(round(x * 255)), '02x')
    return f"#{to_hex(r)}{to_hex(g)}{to_hex(b)}"

# session state defaults
if 'audio_files' not in st.session_state:
    st.session_state['audio_files'] = []
if 'trials_order' not in st.session_state:
    st.session_state['trials_order'] = []
if 'current_trial_index' not in st.session_state:
    st.session_state['current_trial_index'] = -1
if 'results' not in st.session_state:
    st.session_state['results'] = []
if 'current_path' not in st.session_state:
    st.session_state['current_path'] = []
if 'step_start_time' not in st.session_state:
    st.session_state['step_start_time'] = None
if 'step_rts' not in st.session_state:
    st.session_state['step_rts'] = []
if 'practice' not in st.session_state:
    st.session_state['practice'] = False
if 'in_experiment' not in st.session_state:
    st.session_state['in_experiment'] = False
if 'selected_candidate' not in st.session_state:
    st.session_state['selected_candidate'] = None
if 'last_rt' not in st.session_state:
    st.session_state['last_rt'] = '-'
if 'total_rt' not in st.session_state:
    st.session_state['total_rt'] = '-'

# sidebar controls
with st.sidebar:
    st.header('実験コントロール')
    uploaded = st.file_uploader("オーディオファイル (複数可)", type=['wav','mp3','ogg','m4a'], accept_multiple_files=True)
    shuffle_trials = st.checkbox('トライアル順をシャッフル', value=False)
    practice_mode = st.checkbox('練習モード（データ保存しない）', value=False)
    col1, col2 = st.columns(2)
    with col1:
        if st.button('読み込み'):
            files = uploaded or []
            st.session_state['audio_files'] = []
            for f in files:
                st.session_state['audio_files'].append({'name': f.name, 'data': f.read()})
            st.success(f"{len(st.session_state['audio_files'])} files loaded")
            st.session_state['results'] = []
            st.session_state['current_trial_index'] = -1
    with col2:
        if st.button('リセット'):
            st.session_state['audio_files'] = []
            st.session_state['trials_order'] = []
            st.session_state['current_trial_index'] = -1
            st.session_state['results'] = []
            st.session_state['current_path'] = []
            st.session_state['in_experiment'] = False
            st.success('リセットしました')

    if st.button('実験開始'):
        st.session_state['practice'] = practice_mode
        n = len(st.session_state['audio_files'])
        if n == 0:
            st.session_state['trials_order'] = [None]
        else:
            st.session_state['trials_order'] = list(range(n))
        if shuffle_trials:
            random.shuffle(st.session_state['trials_order'])
        st.session_state['current_trial_index'] = -1
        st.session_state['results'] = []
        st.session_state['in_experiment'] = True
        st.rerun()

    st.markdown('---')
    if st.session_state['results']:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['trial','audioName','path','finalHex','finalH','finalS','finalL','stepRTs_ms','totalRT_ms','timestamp','practice'])
        for r in st.session_state['results']:
            writer.writerow([
                r['trial'], r['audioName'], ''.join(map(str, r['path'])), r['finalHex'],
                round(r['finalHSL']['H'],2), r['finalHSL']['S'], r['finalHSL']['L'],
                '|'.join(map(str, r['stepRTs'])), r['totalRT'], r['timestamp'], r['practice']
            ])
        st.download_button('CSV ダウンロード', data=output.getvalue(), file_name='color_selection_results.csv', mime='text/csv')

# main UI
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader('インタラクティブ画面')
    status_text = '準備完了' if st.session_state['in_experiment'] else '未実行'
    st.write(f"状態: {status_text}")

    if st.session_state['current_trial_index'] == -1:
        st.write('現在のトライアル： -')
    else:
        total = len(st.session_state['trials_order'])
        st.write(f"現在のトライアル： {st.session_state['current_trial_index']+1} / {total}")

    if st.session_state['in_experiment']:
        if 'advance_requested' not in st.session_state:
            st.session_state['advance_requested'] = True
            st.session_state['current_trial_index'] += 1
            st.session_state['current_path'] = []
            st.session_state['step_rts'] = []
            st.session_state['last_rt'] = '-'
            st.session_state['total_rt'] = '-'

        if st.session_state['current_trial_index'] >= len(st.session_state['trials_order']):
            st.write('全トライアル完了')
            st.session_state['in_experiment'] = False
            st.session_state.pop('advance_requested', None)
        else:
            idx = st.session_state['trials_order'][st.session_state['current_trial_index']]
            audio_name = '(none)' if idx is None else st.session_state['audio_files'][idx]['name']
            st.write(f"音声： {audio_name}")
            if idx is not None:
                audio_bytes = st.session_state['audio_files'][idx]['data']
                st.audio(audio_bytes)

            current_step_number = len(st.session_state['current_path']) + 1
            st.write(f"段階： {current_step_number} / 8")

            options = []
            for digit in [0,1,2]:
                path = st.session_state['current_path'] + [digit]
                hsl = path_to_hsl_separated(path)
                hexc = hsl_to_hex(hsl)
                options.append({'digit': digit, 'hsl': hsl, 'hex': hexc})

            cols = st.columns(3)
            for i, opt in enumerate(options):
                with cols[i]:
                    st.markdown(f"<div style='height:140px;border-radius:8px;background:{opt['hex']};display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000'>({i+1})<br><small>{opt['hex']}</small></div>", unsafe_allow_html=True)
                    if st.button(f"選択 {i+1}", key=f"select_{st.session_state['current_trial_index']}_{i}"):
                        st.session_state['selected_candidate'] = {'digit': opt['digit'], 'hsl': opt['hsl'], 'hex': opt['hex'], 'displayedPos': i}
                        st.rerun()

            if st.session_state.get('selected_candidate'):
                sc = st.session_state['selected_candidate']
                st.write(f"選択済み： {sc['hex']} (option {sc['displayedPos']+1})")
                if st.session_state['step_start_time'] is None:
                    st.session_state['step_start_time'] = time.time()
                colc, cold = st.columns([1,1])
                with colc:
                    if st.button('決定 (Confirm)'):
                        rt_ms = int((time.time() - st.session_state['step_start_time']) * 1000)
                        st.session_state['step_rts'].append(rt_ms)
                        st.session_state['last_rt'] = rt_ms
                        st.session_state['current_path'].append(sc['digit'])
                        st.session_state['selected_candidate'] = None
                        st.session_state['step_start_time'] = None
                        if len(st.session_state['current_path']) >= 8:
                            total_rt = sum(st.session_state['step_rts'])
                            st.session_state['total_rt'] = total_rt
                            final_hsl = path_to_hsl_separated(st.session_state['current_path'])
                            final_hex = hsl_to_hex(final_hsl)
                            trial_record = {
                                'trial': st.session_state['current_trial_index']+1,
                                'audioName': audio_name,
                                'path': st.session_state['current_path'][:],
                                'stepRTs': st.session_state['step_rts'][:],
                                'totalRT': total_rt,
                                'finalHSL': final_hsl,
                                'finalHex': final_hex,
                                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                'practice': st.session_state['practice']
                            }
                            if not st.session_state['practice']:
                                st.session_state['results'].append(trial_record)
                            st.success(f"試行完了: {trial_record['trial']} | final={trial_record['finalHex']} | RTms={trial_record['totalRT']}")
                            time.sleep(0.4)
                            st.session_state['advance_requested'] = True
                            st.rerun()
                        else:
                            st.session_state['step_start_time'] = time.time()
                            st.rerun()
                with cold:
                    if st.button('選択をキャンセル (Cancel)'):
                        st.session_state['selected_candidate'] = None
                        st.session_state['step_start_time'] = None
                        st.rerun()
            else:
                if st.session_state['step_start_time'] is None:
                    st.session_state['step_start_time'] = time.time()

            st.write(f"反応時間 (各段階)： {st.session_state.get('last_rt','-')} ms")
            st.write(f"合計反応時間： {st.session_state.get('total_rt','-')} ms")
    else:
        st.info('実験を開始するとここにインタラクティブ画面が表示されます。サイドバーでファイルを読み込み「実験開始」を押してください。')

with col_right:
    st.subheader('結果ログ')
    if st.session_state['results']:
        for r in st.session_state['results']:
            st.text(f"Trial {r['trial']} | {r['audioName']} | path={''.join(map(str,r['path']))} | final={r['finalHex']} | RTms={r['totalRT']}")
    else:
        st.write('結果はここに表示されます（練習モードでは保存されません）。')

st.markdown('---')
st.markdown('**注意**: サーバ往復があるため、ブラウザ側での高精度RT計測とは差が出ます。高精度が必要ならクライアント（JS）側で計測し結果だけ送る方式を検討してください。')
