# sttest3.py
# 改良版 Streamlit 実験アプリ
# - safe_rerun 対応
# - 管理者アップロードが即時反映（uploads/ に保存）
# - stage 完了で questionnaire へ遷移
# - color_picker は stage と同じトライアル順で実行、完了で post_questionnaire へ
import streamlit as st
import time, random, io, csv, base64, os
from typing import List, Dict
import streamlit.components.v1 as components
from pathlib import Path

# ---------- 設定 ----------
st.set_page_config(page_title="階層的色選択実験 (sttest3)", layout="wide")

RESULTS_CSV = 'results.csv'
COLOR_RESULTS_CSV = 'color_results.csv'
UPLOAD_DIR = Path('uploads')
UPLOAD_DIR.mkdir(exist_ok=True)

# ---------- ユーティリティ関数 ----------
def safe_rerun():
    """Streamlit のバージョン差に対処してアプリを再実行するユーティリティ。
    - 可能なら st.experimental_rerun()
    - 次に st.rerun()
    - どちらも無ければクエリパラメータを書き換えて reload させる
    """
    if hasattr(st, "experimental_rerun"):
        try:
            st.experimental_rerun()
            return
        except Exception:
            pass
    if hasattr(st, "rerun"):
        try:
            st.rerun()
            return
        except Exception:
            pass
    try:
        params = st.experimental_get_query_params()
        params["_rerun_ts"] = int(time.time()*1000)
        st.experimental_set_query_params(**params)
        st.stop()
    except Exception as e:
        raise RuntimeError("safe_rerun failed: cannot programmatically rerun the Streamlit app in this environment.") from e

def clamp(v, a, b):
    return max(a, min(b, v))

def path_to_hsl_separated(path: List[int]):
    baseHues = [0, 120, 240]
    hueDeltas = [0, 30, 15, 8, 4, 2, 1, 0.5]
    satBase = 70
    lightBase = 50
    stepAttribute = ['hue','hue','hue','saturation','saturation','lightness','lightness','final']

    filled = path + [1] * (8 - len(path))
    H = baseHues[filled[0]] if filled[0] < len(baseHues) else 0
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

def append_result_csv(row: Dict):
    header = ['trial','audioName','path','finalHex','finalH','finalS','finalL','stepRTs_ms','totalRT_ms','timestamp','practice']
    exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def append_color_csv(row: Dict):
    header = ['trial','audioName','pickedHex','pickedH','pickedS','pickedL','timestamp']
    exists = os.path.exists(COLOR_RESULTS_CSV)
    with open(COLOR_RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def render_audio_player(audio_bytes: bytes, mime: str='audio/wav', autoplay=False, loop=False, height=80):
    if audio_bytes is None:
        st.write("音声ファイルが読み込まれていません。")
        return
    b64 = base64.b64encode(audio_bytes).decode('ascii')
    autoplay_attr = 'autoplay' if autoplay else ''
    loop_attr = 'loop' if loop else ''
    html = f"""
    <audio controls {autoplay_attr} {loop_attr} style="width:100%">
      <source src="data:{mime};base64,{b64}">
      Your browser does not support the audio element.
    </audio>
    """
    components.html(html, height=height)

def safe_filename(name: str) -> str:
    name = os.path.basename(name)
    return "".join(c for c in name if c.isalnum() or c in "._-")

# ---------- セッション初期値 ----------
if 'page' not in st.session_state:
    st.session_state['page'] = 'consent'
if 'audio_files' not in st.session_state:
    st.session_state['audio_files'] = []  # [{'id','name','safe_name','data','mime','duration_s'}]
if 'trials_order' not in st.session_state:
    st.session_state['trials_order'] = []
if 'current_trial_index' not in st.session_state:
    st.session_state['current_trial_index'] = 0
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
if 'played_this_stage' not in st.session_state:
    st.session_state['played_this_stage'] = False
if 'settings' not in st.session_state:
    st.session_state['settings'] = {
        'shuffle_trials': True,
        'once_per_stage': False,
        'autoplay': False,
        'loop_audio': False
    }

# color_picker 用 state (stage と同じ順序で回す)
if 'color_trials_order' not in st.session_state:
    st.session_state['color_trials_order'] = []
if 'color_trial_index' not in st.session_state:
    st.session_state['color_trial_index'] = 0
if 'color_results' not in st.session_state:
    st.session_state['color_results'] = []

# 管理者トラッキング（アップロード重複防止）
if 'last_uploaded_names' not in st.session_state:
    st.session_state['last_uploaded_names'] = []

# ---------- 管理者判定 ----------
qparams = st.experimental_get_query_params()
is_admin = ('admin' in qparams and qparams['admin'] and str(qparams['admin'][0]).lower() in ['1','true','yes'])

# ---------- 管理者ページ（アップロード即時反映） ----------
if is_admin:
    st.title("管理者ページ（隠し）")
    st.markdown("**注意**: 本番運用では必ず認証を導入してください。")

    uploaded = st.file_uploader("オーディオファイルをアップロード (複数可)",
                                type=['wav','mp3','ogg','m4a'], accept_multiple_files=True, key='admin_uploader')

    # 管理者操作系 UI
    st.markdown("---")
    st.header("実験設定")
    st.session_state['settings']['shuffle_trials'] = st.checkbox("トライアル順をシャッフル", value=st.session_state['settings'].get('shuffle_trials', True))
    st.session_state['settings']['autoplay'] = st.checkbox("各段階で自動再生を試みる (ブラウザでブロックされるかもしれません)", value=st.session_state['settings'].get('autoplay', False))
    st.session_state['settings']['once_per_stage'] = st.checkbox("各段階で1回だけ再生する", value=st.session_state['settings'].get('once_per_stage', False))
    st.session_state['settings']['loop_audio'] = st.checkbox("再生をループさせる (自由再生モード)", value=st.session_state['settings'].get('loop_audio', False))
    st.session_state['practice'] = st.checkbox("練習モード（保存しない）", value=st.session_state.get('practice', False))

    st.markdown("---")
    st.header("アップロードと初期化（即時反映）")
    if uploaded:
        uploaded_names = [f.name for f in uploaded]
        if uploaded_names != st.session_state['last_uploaded_names']:
            # 新規セットを受け取ったときのみ処理
            st.session_state['last_uploaded_names'] = uploaded_names
            st.session_state['audio_files'] = []
            for f in uploaded:
                data = f.read()
                safe_name = safe_filename(f.name)
                save_path = UPLOAD_DIR / safe_name
                try:
                    with open(save_path, 'wb') as out:
                        out.write(data)
                except Exception as e:
                    st.error(f"ファイル保存に失敗しました: {e}")
                    continue
                # 登録
                st.session_state['audio_files'].append({
                    'id': f"stim_{len(st.session_state['audio_files'])+1:03}",
                    'name': f.name,
                    'safe_name': safe_name,
                    'data': data,
                    'mime': f.type or 'audio/wav'
                })
            # trials_order を生成・同期
            n = len(st.session_state['audio_files'])
            if n == 0:
                st.session_state['trials_order'] = [None]
            else:
                st.session_state['trials_order'] = list(range(n))
            if st.session_state['settings'].get('shuffle_trials', True):
                random.shuffle(st.session_state['trials_order'])
            st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
            st.session_state['current_trial_index'] = 0
            st.session_state['color_trial_index'] = 0
            st.session_state['results'] = []
            st.session_state['current_path'] = []
            st.session_state['played_this_stage'] = False
            st.session_state['color_results'] = []
            st.success(f"{n} 件をアップロード・登録しました。")
            # 反映のためリロード
            try:
                safe_rerun()
            except Exception:
                pass

    # 初期化ボタン（手動）
    if st.button("手動: トライアル順リセット＆実験初期化"):
        n = len(st.session_state.get('audio_files', []))
        if n == 0:
            st.session_state['trials_order'] = [None]
        else:
            st.session_state['trials_order'] = list(range(n))
        if st.session_state['settings'].get('shuffle_trials', True):
            random.shuffle(st.session_state['trials_order'])
        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
        st.session_state['current_trial_index'] = 0
        st.session_state['color_trial_index'] = 0
        st.session_state['results'] = []
        st.session_state['current_path'] = []
        st.session_state['played_this_stage'] = False
        st.session_state['color_results'] = []
        st.success("初期化しました。")
        try:
            safe_rerun()
        except Exception:
            pass

    st.markdown("---")
    st.subheader("現在読み込まれているファイル（preview）")
    st.write([{'id': a.get('id'), 'name': a.get('name'), 'mime': a.get('mime')} for a in st.session_state.get('audio_files', [])])
    st.write("trials_order:", st.session_state.get('trials_order'))
    st.write("color_trials_order:", st.session_state.get('color_trials_order'))

    st.markdown("---")
    st.header("ログ / 結果のダウンロード")
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, 'r', encoding='utf-8') as f:
            data = f.read()
        st.download_button("results.csv をダウンロード", data=data, file_name="results.csv", mime="text/csv")
    else:
        st.write("results.csv はまだありません。")
    if os.path.exists(COLOR_RESULTS_CSV):
        with open(COLOR_RESULTS_CSV, 'r', encoding='utf-8') as f:
            cdata = f.read()
        st.download_button("color_results.csv をダウンロード", data=cdata, file_name="color_results.csv", mime="text/csv")

    if st.button("結果ファイルをリセット（削除）"):
        if os.path.exists(RESULTS_CSV):
            os.remove(RESULTS_CSV)
        if os.path.exists(COLOR_RESULTS_CSV):
            os.remove(COLOR_RESULTS_CSV)
        st.success("results, color_results を削除しました。")

    st.markdown("---")
    st.write("管理者ページを閉じると参加者用の画面に戻ります。URLから `?admin=1` を削除してください。")
    st.stop()

# ---------- 参加者ページ ----------
def go_to(page):
    st.session_state['page'] = page
    safe_rerun()

st.title("階層的色選択実験（参加者画面）")

page = st.session_state.get('page','consent')

if page == 'consent':
    st.header("同意ページ")
    st.markdown("ここに実験の目的・所要時間・個人情報の扱いなどを明記してください。")
    if st.checkbox("実験に同意します"):
        if st.button("次へ"):
            go_to('stage')
    else:
        st.write("同意しない場合はウィンドウを閉じてください。")

elif page == 'stage':
    st.header("実験 — 刺激提示と色選択")

    # safety: trials_order の整合性チェック (admin 初期化がなくても自動生成)
    n_audio = len(st.session_state.get('audio_files', []))
    if not st.session_state.get('trials_order'):
        if n_audio > 0:
            st.session_state['trials_order'] = list(range(n_audio))
        else:
            st.session_state['trials_order'] = [None]
        if st.session_state['settings'].get('shuffle_trials', True):
            random.shuffle(st.session_state['trials_order'])
        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()

    if 'current_trial_index' not in st.session_state or st.session_state['current_trial_index'] is None:
        st.session_state['current_trial_index'] = 0
    if st.session_state['current_trial_index'] < 0:
        st.session_state['current_trial_index'] = 0
    if st.session_state['current_trial_index'] >= len(st.session_state['trials_order']):
        st.info("すべての試行が終了しました。次に進みます。")
        time.sleep(0.2)
        go_to('questionnaire')

    idx = st.session_state['trials_order'][st.session_state['current_trial_index']]
    audio_name = '(なし)' if idx is None else st.session_state['audio_files'][idx]['name']
    st.write(f"トライアル {st.session_state['current_trial_index']+1} / {len(st.session_state['trials_order'])} — 音声: {audio_name}")

    audio_bytes = None
    audio_mime = 'audio/wav'
    if idx is not None:
        audio_bytes = st.session_state['audio_files'][idx]['data']
        audio_mime = st.session_state['audio_files'][idx].get('mime','audio/wav')

    colp, colq = st.columns([3,1])
    with colp:
        st.markdown("**再生コントロール**")
        if st.session_state['settings'].get('autoplay') and st.session_state['settings'].get('once_per_stage') and not st.session_state.get('played_this_stage'):
            render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=st.session_state['settings'].get('loop_audio', False))
            st.session_state['played_this_stage'] = True
            st.write("自動再生を試みました。ブラウザがブロックする場合は下の再生ボタンを押してください。")
        else:
            if st.button("再生 (Play)"):
                render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=st.session_state['settings'].get('loop_audio', False))
                st.session_state['played_this_stage'] = True
            if st.button("停止 (Stop)"):
                st.session_state['played_this_stage'] = False
                safe_rerun()
            if st.session_state['settings'].get('loop_audio', False):
                st.write("ループ再生モードが ON です。")

    with colq:
        if st.button("次のトライアルへ（スキップ）"):
            st.session_state['current_trial_index'] += 1
            st.session_state['current_path'] = []
            st.session_state['step_rts'] = []
            st.session_state['played_this_stage'] = False
            safe_rerun()

    # 色選択（階層的 8 段階）
    st.markdown("### 色選択（8段階の階層的選択）")
    current_step_number = len(st.session_state.get('current_path', [])) + 1
    st.write(f"段階 {current_step_number} / 8")

    options = []
    for digit in [0,1,2]:
        path = st.session_state['current_path'] + [digit]
        hsl = path_to_hsl_separated(path)
        hexc = hsl_to_hex(hsl)
        options.append({'digit': digit, 'hsl': hsl, 'hex': hexc})

    cols = st.columns(3)
    for i,opt in enumerate(options):
        with cols[i]:
            st.markdown(f"""
            <div style="height:140px;border-radius:10px;background:{opt['hex']};display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000;margin-bottom:8px">
              <div style="text-align:center">選択肢 {i+1}<br><small>{opt['hex']}</small></div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"この色を選ぶ ({i+1})", key=f"sel_{st.session_state['current_trial_index']}_{current_step_number}_{i}"):
                if st.session_state['step_start_time'] is None:
                    st.session_state['step_start_time'] = time.time()
                rt_ms = int((time.time() - st.session_state['step_start_time'])*1000) if st.session_state['step_start_time'] is not None else 0
                st.session_state['step_rts'].append(rt_ms)
                st.session_state['current_path'].append(opt['digit'])
                st.session_state['step_start_time'] = None
                st.session_state['played_this_stage'] = False

                if len(st.session_state['current_path']) >= 8:
                    total_rt = sum(st.session_state.get('step_rts', []))
                    final_hsl = path_to_hsl_separated(st.session_state['current_path'])
                    final_hex = hsl_to_hex(final_hsl)
                    trial_record = {
                        'trial': st.session_state['current_trial_index']+1,
                        'audioName': audio_name,
                        'path': ''.join(map(str,st.session_state['current_path'])),
                        'finalHex': final_hex,
                        'finalH': round(final_hsl['H'],2),
                        'finalS': final_hsl['S'],
                        'finalL': final_hsl['L'],
                        'stepRTs_ms': '|'.join(map(str,st.session_state.get('step_rts',[]))),
                        'totalRT_ms': total_rt,
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'practice': st.session_state.get('practice', False)
                    }
                    st.session_state['results'].append(trial_record)
                    if not st.session_state.get('practice', False):
                        append_result_csv({
                            'trial': trial_record['trial'],
                            'audioName': trial_record['audioName'],
                            'path': trial_record['path'],
                            'finalHex': trial_record['finalHex'],
                            'finalH': trial_record['finalH'],
                            'finalS': trial_record['finalS'],
                            'finalL': trial_record['finalL'],
                            'stepRTs_ms': trial_record['stepRTs_ms'],
                            'totalRT_ms': trial_record['totalRT_ms'],
                            'timestamp': trial_record['timestamp'],
                            'practice': trial_record['practice']
                        })
                    st.success(f"試行完了（{trial_record['trial']}） final={trial_record['finalHex']} RTms={trial_record['totalRT_ms']}")
                    st.session_state['current_trial_index'] += 1
                    st.session_state['current_path'] = []
                    st.session_state['step_rts'] = []
                    st.session_state['played_this_stage'] = False
                    time.sleep(0.3)
                    safe_rerun()
                else:
                    safe_rerun()

    st.write("現在までのセッション結果（このブラウザ）:")
    for r in st.session_state.get('results', []):
        st.text(f"Trial {r['trial']} | {r['audioName']} | path={r['path']} | final={r['finalHex']} | RTms={r['totalRT_ms']}")

elif page == 'questionnaire':
    st.header("短いアンケート")
    with st.form("qform"):
        q1 = st.radio("音の長さは適切でしたか？", ("短い", "適切", "長い"))
        q2 = st.text_area("何か気づいた点があれば書いてください（任意）")
        submitted = st.form_submit_button("次へ")
        if submitted:
            st.session_state.setdefault('meta_answers', {})['q1'] = q1
            st.session_state.setdefault('meta_answers', {})['q2'] = q2
            go_to('color_picker')

elif page == 'color_picker':
    st.header("自由色選択ページ（各音刺激ごとに1色選んでください）")
    st.markdown("このページでは、それぞれの音刺激に対して自由に色を選んでいただきます。全ての音について選び終わると次のアンケートへ進みます。")

    # stage と同じ順序を使う（存在すればコピー）
    if st.session_state.get('trials_order'):
        if not st.session_state.get('color_trials_order'):
            st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
    else:
        n_audio = len(st.session_state.get('audio_files', []))
        if not st.session_state.get('color_trials_order'):
            if n_audio > 0:
                st.session_state['color_trials_order'] = list(range(n_audio))
            else:
                st.session_state['color_trials_order'] = [None]
            if st.session_state['settings'].get('shuffle_trials', True):
                random.shuffle(st.session_state['color_trials_order'])

    if 'color_trial_index' not in st.session_state or st.session_state['color_trial_index'] is None:
        st.session_state['color_trial_index'] = 0
    if st.session_state['color_trial_index'] < 0:
        st.session_state['color_trial_index'] = 0

    if st.session_state['color_trial_index'] >= len(st.session_state['color_trials_order']):
        st.info("全ての音刺激について色の選択が終わりました。次へ進みます。")
        time.sleep(0.3)
        go_to('post_questionnaire')
    else:
        cidx = st.session_state['color_trials_order'][st.session_state['color_trial_index']]
        audio_name = '(なし)' if cidx is None else st.session_state['audio_files'][cidx]['name']
        st.write(f"トライアル {st.session_state['color_trial_index']+1} / {len(st.session_state['color_trials_order'])} — 音声: {audio_name}")

        audio_bytes = None
        audio_mime = 'audio/wav'
        if cidx is not None:
            audio_bytes = st.session_state['audio_files'][cidx]['data']
            audio_mime = st.session_state['audio_files'][cidx].get('mime','audio/wav')

        col1, col2 = st.columns([3,2])
        with col1:
            st.markdown("**再生**")
            if st.button("再生 (Play)"):
                render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=False)
            if st.button("停止 (Stop)"):
                safe_rerun()

        with col2:
            picked = st.color_picker("この音に最も近いと思う色を選んでください", "#00ff00", key=f"picker_{st.session_state['color_trial_index']}")
            st.write("選択した色：", picked)

            if st.button("この色を保存して次へ"):
                def hex_to_hsl(hexc):
                    hexc = hexc.lstrip('#')
                    r = int(hexc[0:2],16)/255.0
                    g = int(hexc[2:4],16)/255.0
                    b = int(hexc[4:6],16)/255.0
                    maxc = max(r,g,b)
                    minc = min(r,g,b)
                    l = (maxc+minc)/2
                    if maxc == minc:
                        h = s = 0
                    else:
                        d = maxc - minc
                        s = d / (2 - maxc - minc) if l > 0.5 else d / (maxc + minc)
                        if maxc == r:
                            h = (g - b) / d + (6 if g < b else 0)
                        elif maxc == g:
                            h = (b - r) / d + 2
                        else:
                            h = (r - g) / d + 4
                        h /= 6
                        h = (h * 360) % 360
                        s = round(s*100,2)
                        l = round(l*100,2)
                    return {'H': round(h,2), 'S': s, 'L': l}

                picked_hsl = hex_to_hsl(picked)
                row = {
                    'trial': st.session_state['color_trial_index']+1,
                    'audioName': audio_name,
                    'pickedHex': picked,
                    'pickedH': picked_hsl['H'],
                    'pickedS': picked_hsl['S'],
                    'pickedL': picked_hsl['L'],
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
                }
                st.session_state['color_results'].append(row)
                append_color_csv(row)
                st.session_state['color_trial_index'] += 1
                safe_rerun()

elif page == 'post_questionnaire':
    st.header("追加アンケート")
    if st.button("次へ（最終アンケートへ）"):
        go_to('final_survey')

elif page == 'final_survey':
    st.header("総合アンケート")
    with st.form("final"):
        age = st.text_input("年齢（任意）")
        gender = st.selectbox("性別（任意）", ["選択しない","男性","女性","その他"])
        submitted = st.form_submit_button("送信して終了")
        if submitted:
            st.session_state.setdefault('meta_answers', {})['age'] = age
            st.session_state.setdefault('meta_answers', {})['gender'] = gender
            go_to('end')

elif page == 'end':
    st.header("終了ページ")
    st.markdown("ご協力ありがとうございました。結果は保存されました。")
    if st.button("トップへ戻る（新しい参加者）"):
        st.session_state['page'] = 'consent'
        st.session_state['current_trial_index'] = 0
        st.session_state['color_trial_index'] = 0
        st.session_state['current_path'] = []
        st.session_state['step_rts'] = []
        st.session_state['results'] = []
        st.session_state['color_results'] = []
        st.session_state['played_this_stage'] = False
        safe_rerun()

st.markdown("---")
st.caption("注: ブラウザの自動再生ポリシーにより autoplay が効かないことがあります。音が鳴らない場合は手動で再生してください。")
