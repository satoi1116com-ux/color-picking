# sttest8.py (改6)
# 機能改善：participant_idを全結果ファイルに追加、実験タスク（階層選択/カラーピッカー）の順序をランダム化し、その順序を記録
# 完全版：管理者アップロード（即時反映）＋一覧管理（再生/ダウンロード/削除）＋参加者フロー
import streamlit as st
import time, random, io, csv, base64, os
from typing import List, Dict
import streamlit.components.v1 as components
from pathlib import Path

# ---------- 設定 ----------
st.set_page_config(page_title="階層的色選択実験", layout="wide")
RESULTS_CSV = 'results.csv'
COLOR_RESULTS_CSV = 'color_results.csv'
UPLOAD_DIR = Path('uploads')
UPLOAD_DIR.mkdir(exist_ok=True)

# --- メタ結果保存用ファイル（最終アンケート） ---
META_RESULTS_CSV = 'meta_results.csv'

def append_meta_csv(row: dict):
    # ヘッダーに task_order を追加
    header = ['participant_id','task_order','timestamp','q1','q2','q3','q4','q5','q6','q7','q8','q9','q10','q11','q12','q13','q14','q15','q16','q17','q18','n_color_picks','n_hierarchical_trials']
    exists = os.path.exists(META_RESULTS_CSV)
    with open(META_RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

# ---------- ユーティリティ ----------
def safe_rerun():
    """Streamlit のバージョン差に対処してアプリを再実行するユーティリティ（フォールバックあり）。"""
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
    except Exception:
        return

def clamp(v, a, b):
    return max(a, min(b, v))

def path_to_hsl_separated(path: List[int]):
    baseHues = [0, 120, 240]
    hueDeltas = [0, 60, 15, 8, 4, 2, 1, 0.5] 
    satBase = 70
    lightBase = 50
    # 変更点1: 明度と彩度の順番を入れ替え
    stepAttribute = ['hue','hue','hue','lightness','lightness','saturation','saturation','final']
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
        # 変更点2: ロジックを新しい順番に合わせる
        elif attr == 'saturation':
            # 6,7段階目(i=5,6)が彩度になる
            satChange = 25 if i == 5 else 15 
            S += m * satChange
        elif attr == 'lightness':
            # 4,5段階目(i=3,4)が明度になる
            lightChange = 20 if i == 3 else 10
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
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
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
    # ヘッダーに participant_id を追加
    header = ['participant_id','trial','audioName','path','finalHex','finalH','finalS','finalL','stepRTs_ms','totalRT_ms','timestamp','practice']
    exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def append_color_csv(row: Dict):
    # ヘッダーに participant_id を追加
    header = ['participant_id','trial','audioName','pickedHex','pickedH','pickedS','pickedL','timestamp']
    exists = os.path.exists(COLOR_RESULTS_CSV)
    with open(COLOR_RESULTS_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

def render_audio_player(audio_bytes: bytes, mime: str='audio/wav', autoplay=False, loop=False, height=90):
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

# ---------- session 初期化 ----------
if 'page' not in st.session_state:
    st.session_state['page'] = 'consent'
if 'participant_id' not in st.session_state:
    st.session_state['participant_id'] = f"{int(time.time())}_{random.randint(1000,9999)}"
# ★★★ 実験順序をランダム化するためのセッション状態を追加 ★★★
if 'task_order' not in st.session_state:
    # 'stage' は階層的選択、 'color_picker' は自由選択
    tasks = ['stage', 'color_picker']
    random.shuffle(tasks)
    st.session_state['task_order'] = tasks

if 'audio_files' not in st.session_state: st.session_state['audio_files'] = []
if 'trials_order' not in st.session_state: st.session_state['trials_order'] = []
if 'current_trial_index' not in st.session_state: st.session_state['current_trial_index'] = 0
if 'results' not in st.session_state: st.session_state['results'] = []
if 'current_path' not in st.session_state: st.session_state['current_path'] = []
if 'step_start_time' not in st.session_state: st.session_state['step_start_time'] = None
if 'step_rts' not in st.session_state: st.session_state['step_rts'] = []
if 'practice' not in st.session_state: st.session_state['practice'] = False
if 'played_this_stage' not in st.session_state: st.session_state['played_this_stage'] = False
if 'listening_complete' not in st.session_state: st.session_state['listening_complete'] = False
if 'continuous_play_mode' not in st.session_state: st.session_state['continuous_play_mode'] = False
if 'color_picker_continuous_play' not in st.session_state: st.session_state['color_picker_continuous_play'] = False
if 'color_picker_listening_complete' not in st.session_state: st.session_state['color_picker_listening_complete'] = False
if 'settings' not in st.session_state:
    st.session_state['settings'] = {'shuffle_trials': True, 'once_per_stage': False, 'autoplay': False, 'loop_audio': False}
if 'color_trials_order' not in st.session_state: st.session_state['color_trials_order'] = []
if 'color_trial_index' not in st.session_state: st.session_state['color_trial_index'] = 0
if 'color_results' not in st.session_state: st.session_state['color_results'] = []
if 'last_uploaded_names' not in st.session_state: st.session_state['last_uploaded_names'] = []

# ---------- uploads/ からの自動読み込み（参加者用） ----------
if not st.session_state.get('audio_files'):
    try:
        files_on_disk = sorted([p for p in UPLOAD_DIR.iterdir() if p.is_file()])
    except Exception:
        files_on_disk = []
    if files_on_disk:
        st.session_state['audio_files'] = []
        for p in files_on_disk:
            try:
                with open(p, 'rb') as f: data = f.read()
                ext = p.suffix.lower().lstrip('.')
                mime = 'audio/wav'
                if ext in ['mp3']: mime = 'audio/mpeg'
                elif ext in ['ogg']: mime = 'audio/ogg'
                elif ext in ['m4a','mp4','aac']: mime = 'audio/mp4'
                st.session_state['audio_files'].append({'id': f"disk_{p.stem}", 'name': p.name, 'safe_name': p.name, 'data': data, 'mime': mime})
            except Exception as e:
                st.warning(f"failed to load {p.name}: {e}")
        if not st.session_state.get('trials_order'):
            n = len(st.session_state['audio_files'])
            if n == 0:
                st.session_state['trials_order'] = [None]
            else:
                st.session_state['trials_order'] = list(range(n))
                if st.session_state['settings'].get('shuffle_trials', True):
                    random.shuffle(st.session_state['trials_order'])
                st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()

# ---------- UI: 管理者/参加者ページ選択（簡易） ----------
st.title("階層的色選択実験 (管理・参加者)")
st.markdown("---")

def go_to(p):
    st.session_state['page'] = p
    safe_rerun()

# ---------- 管理者判定 ----------
qparams = st.experimental_get_query_params()
is_admin = ('admin' in qparams and qparams['admin'] and str(qparams['admin'][0]).lower() in ['1','true','yes'])

# ---------- 管理者ページ ----------
if is_admin:
    st.header("管理者: 音声アップロード / ログ確認")
    st.markdown("uploads フォルダに音声ファイルを配置すると参加者ページで利用できます。")
    uploaded = st.file_uploader("音声ファイルをアップロード（複数可）", accept_multiple_files=True, type=['wav','mp3','ogg','m4a'])
    if uploaded:
        saved_count = 0
        for f in uploaded:
            try:
                data = f.read()
                safe_name = safe_filename(f.name)
                save_path = UPLOAD_DIR / safe_name
                with open(save_path, 'wb') as out:
                    out.write(data)
                saved_count += 1
            except Exception as e:
                st.error(f"ファイル保存に失敗しました ({f.name}): {e}")
        
        reloaded = []
        try:
            files_on_disk = sorted([p for p in UPLOAD_DIR.iterdir() if p.is_file()])
            for p in files_on_disk:
                with open(p, 'rb') as fh: data = fh.read()
                ext = p.suffix.lower().lstrip('.')
                mime = 'audio/wav'
                if ext in ['mp3']: mime = 'audio/mpeg'
                elif ext in ['ogg']: mime = 'audio/ogg'
                elif ext in ['m4a','mp4','aac']: mime = 'audio/mp4'
                reloaded.append({'id': f"disk_{p.stem}", 'name': p.name, 'safe_name': p.name, 'data': data, 'mime': mime})
            st.session_state['audio_files'] = reloaded
        except Exception as e:
            st.error(f"uploads フォルダ読み込み失敗: {e}")

        n = len(st.session_state['audio_files'])
        st.session_state['trials_order'] = list(range(n)) if n > 0 else [None]
        if n > 0 and st.session_state['settings'].get('shuffle_trials', True):
            random.shuffle(st.session_state['trials_order'])
        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
        st.session_state['current_trial_index'] = 0
        st.session_state['color_trial_index'] = 0
        st.session_state['results'] = []
        st.session_state['current_path'] = []
        st.session_state['played_this_stage'] = False
        st.session_state['color_results'] = []
        st.session_state['listening_complete'] = False
        st.session_state['continuous_play_mode'] = False
        st.session_state['color_picker_listening_complete'] = False
        st.session_state['color_picker_continuous_play'] = False
        st.success(f"{saved_count} 件を保存・反映しました（合計 {n} 件）。")
        safe_rerun()

    if st.button("手動: トライアル順リセット＆実験初期化"):
        n = len(st.session_state.get('audio_files', []))
        st.session_state['trials_order'] = list(range(n)) if n > 0 else [None]
        if n > 0 and st.session_state['settings'].get('shuffle_trials', True):
            random.shuffle(st.session_state['trials_order'])
        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
        st.session_state['current_trial_index'] = 0
        st.session_state['color_trial_index'] = 0
        st.session_state['results'] = []
        st.session_state['current_path'] = []
        st.session_state['played_this_stage'] = False
        st.session_state['color_results'] = []
        st.session_state['listening_complete'] = False
        st.session_state['continuous_play_mode'] = False
        st.session_state['color_picker_listening_complete'] = False
        st.session_state['color_picker_continuous_play'] = False
        st.success("初期化しました。")
        safe_rerun()

    st.markdown("---")
    st.subheader("現在読み込まれているファイル（管理）")
    audio_list = st.session_state.get('audio_files', [])
    if not audio_list:
        st.write("まだファイルが読み込まれていません。")
    else:
        for idx, a in enumerate(audio_list):
            cols = st.columns([3,1,1,1,1])
            with cols[0]: st.markdown(f"**{idx+1}. {a.get('name')}**")
            with cols[1]:
                if st.button("再生", key=f"play_{a.get('safe_name')}_{idx}"):
                    render_audio_player(a.get('data'), mime=a.get('mime'), autoplay=True, loop=False, height=100)
            with cols[2]: st.download_button(f"Download", data=a.get('data'), file_name=a.get('name'), mime=a.get('mime'), key=f"dl_{a.get('safe_name')}_{idx}")
            with cols[3]:
                if st.button("削除", key=f"del_{a.get('safe_name')}_{idx}"):
                    filepath = UPLOAD_DIR / a.get('safe_name')
                    if filepath.exists(): filepath.unlink()
                    st.session_state['audio_files'] = [x for x in st.session_state['audio_files'] if x.get('safe_name') != a.get('safe_name')]
                    st.success(f"{a.get('safe_name')} を削除しました。反映するには「手動リセット」を押してください。")
                    safe_rerun()
    st.markdown("---")
    st.header("ログ / 結果のダウンロード")
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, 'r', encoding='utf-8') as f:
            st.download_button("results.csv をダウンロード", data=f.read(), file_name="results.csv", mime="text/csv")
    if os.path.exists(COLOR_RESULTS_CSV):
        with open(COLOR_RESULTS_CSV, 'r', encoding='utf-8') as f:
            st.download_button("color_results.csv をダウンロード", data=f.read(), file_name="color_results.csv", mime="text/csv")
    if os.path.exists(META_RESULTS_CSV):
        with open(META_RESULTS_CSV, 'r', encoding='utf-8') as f:
            st.download_button("meta_results.csv をダウンロード", data=f.read(), file_name="meta_results.csv", mime="text/csv")

# 参加者ページフロー
# consent
elif st.session_state.get('page') == 'consent':
    st.header("同意書 / 研究について")
    st.markdown("""
    ### 1.	実験の目的と意義
    本実験では、人々が音や音楽を聴いた際に色を想起する知覚現象を扱う実験において、2種類の色選択手法を比較します。こちらの現象についての実験を行い、実験データの分析を行うことで、今後の同分野の研究で、より信頼性の高いデータを収集するための最適な実験環境を提案することを目的としています。
    ### 2.	実験の概要
    本実験は、オンラインにて実施します。参加者の皆様には、静かな環境でPCとヘッドホンまたはイヤホンをご用意いただき、画面の指示に従って作業を進めていただきます。提示される音刺激に対して下記の二つの手法を用いて想起した色を選択する作業を行っていただきます。・カラーピッカー ・段階的な色選択 各手法で色を選択した直後に、色選択に関するアンケートに回答してください。さらに、全手法での色選択及びアンケート回答後には、全体のアンケートに回答してください。二つの手法の順序は参加者ごとに異なります。作業時間は休憩時間5分を含めて計45分を想定しています。
    ### 3.	実験参加に伴う危険
    ヘッドホンを装着してディスプレイを見ながら、提示される音を聴いて画面上で色の選択を繰り返し行っていただくため、疲労や精神的負担を感じてしまう可能性があります。実験中にそのような危険性を感じた場合には、いつでも実験の中断、または参加の取り消しを行うことができます。実験は全体で45分程度を予定しています。また、実験中には5分ほどの休憩を設定していますが、疲労を感じた場合は適宜休憩をとっていただくことが可能です。 
    ### 4.	個人情報の取り扱いについて
    本実験で記録するすべてのデータは、本研究の目的以外に使用されることはありません。またそれらデータは、名前や個人情報を一切記載せず、実験参加者ごとに付与したIDによって外部に流出することの無いよう、厳重に管理されます。また本同意書は実験責任者の鍵付き保管庫にて施錠の上、保管されます。
    ### 5.	問い合わせ先について
    実験担当者	筑波大学情報学群情報メディア創成学類 4年 山﨑聖生 e-mail: s2210284@u.tsukuba.ac.jp
    実験責任者	筑波大学図書館情報メディア系 助教 飯野なみ 〒305-8550 茨城県つくば市春日1-2 e-mail: niino@slis.tsukuba.ac.jp
    本実験は、図書館情報メディア系研究倫理審査委員会の承認を得て実施しています
    """)        
    if st.checkbox("実験に同意します"):
        if st.button("次へ"):
            go_to('audio_check')

# audio check
elif st.session_state.get('page') == 'audio_check':
    st.header("音量・再生チェック")
    st.markdown("・ヘッドフォンを着用してください。\n・「テスト音を再生」で音が聞こえるか確認してください。\n・問題なければ「再生確認済みにチェック」を入れて次へ進んでください。")
    sample_b64, sample_mime, first_name = None, None, None
    if st.session_state.get('audio_files'):
        first = st.session_state['audio_files'][0]
        sample_b64 = base64.b64encode(first['data']).decode('ascii')
        sample_mime = first.get('mime','audio/wav')
        first_name = first.get('name')
    html_js = f"""
    <div><button id="playTone">テスト音を再生</button><button id="stopTone">テスト音停止</button><span id="toneInfo"></span><br/><br/></div>
    {'<div><div>サンプル刺激: <strong>'+first_name+'</strong></div><button id="playSample">サンプルを再生</button><button id="stopSample">サンプル停止</button><audio id="sampleAudio" style="display:none"><source src="data:'+sample_mime+';base64,'+sample_b64+'"></audio></div>' if sample_b64 else ''}
    <script>
    let audioCtx = null, osc = null;
    document.getElementById("playTone").onclick = () => {{
        if(!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if(osc) osc.stop();
        osc = audioCtx.createOscillator();
        let gain = audioCtx.createGain();
        osc.type = 'sine'; osc.frequency.value = 880; gain.gain.value = 0.05;
        osc.connect(gain); gain.connect(audioCtx.destination); osc.start();
        document.getElementById("toneInfo").textContent = "再生中 (880Hz)";
    }};
    document.getElementById("stopTone").onclick = () => {{ if(osc) osc.stop(); osc = null; document.getElementById("toneInfo").textContent=''; }};
    const sampleEl = document.getElementById("sampleAudio");
    if(sampleEl) {{
        document.getElementById("playSample").onclick = () => sampleEl.play();
        document.getElementById("stopSample").onclick = () => {{ sampleEl.pause(); sampleEl.currentTime = 0; }};
    }}
    </script>"""
    components.html(html_js, height=200)
    if st.checkbox("再生確認済み（聞こえた・音量問題なし）", key="audio_checked"):
        # ★★★ 最初のタスクへ遷移するよう修正 ★★★
        if st.button("次へ（実験開始）"):
            first_task = st.session_state['task_order'][0]
            go_to(first_task)

# stage (階層的色選択)
elif st.session_state.get('page') == 'stage':
    st.header("実験 — 段階的な色選択")
    if st.session_state['current_trial_index'] >= len(st.session_state['trials_order']):
        st.info("すべての試行が終了しました。短いアンケートにお答えください。")
        time.sleep(0.5)
        go_to('questionnaire') # stage の後のアンケートへ
        
    else:
        idx = st.session_state['trials_order'][st.session_state['current_trial_index']]
        audio_name = '(なし)' if idx is None else st.session_state['audio_files'][idx]['name']
        st.write(f"トライアル {st.session_state['current_trial_index']+1} / {len(st.session_state['trials_order'])} — 音声: {audio_name}")
        audio_bytes = None
        if idx is not None:
            audio_bytes = st.session_state['audio_files'][idx]['data']
            audio_mime = st.session_state['audio_files'][idx].get('mime','audio/wav')

        if not st.session_state.get('listening_complete'):
            st.markdown("---")
            st.subheader(f"トライアル {st.session_state['current_trial_index']+1} の再生")
            st.info("まず、今回の音刺激を一度最後までお聞きください。\n\n再生が終了したら、下のボタンを押して色選択に進んでください。")
            render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=False)
            if st.button("再生が終了したので、色選択に進む"):
                st.session_state['listening_complete'] = True
                safe_rerun()
        else:
            colp, _ = st.columns([3,1])
            with colp:
                st.markdown("**再生コントロール**")
                if not st.session_state.get('continuous_play_mode'):
                    if st.button("色選択中に再生を続ける（ループ再生）"):
                        st.session_state['continuous_play_mode'] = True; safe_rerun()
                else:
                    if st.button("再生を停止"):
                        st.session_state['continuous_play_mode'] = False; safe_rerun()
                if st.session_state.get('continuous_play_mode'):
                    st.write("ループ再生中...")
                    render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=True)
            
            st.markdown("---")
            st.markdown("### 色選択（8段階）")
            current_step_number = len(st.session_state.get('current_path', [])) + 1
            st.write(f"段階 {current_step_number} / 8")
            options = [{'digit': d, 'hex': hsl_to_hex(path_to_hsl_separated(st.session_state['current_path'] + [d]))} for d in [0,1,2]]
            cols = st.columns(3)
            for i, opt in enumerate(options):
                with cols[i]:
                    st.markdown(f'<div style="height:140px;border-radius:10px;background:{opt["hex"]};display:flex;align-items:center;justify-content:center;font-weight:bold;color:#000;margin-bottom:8px"><div style="text-align:center">選択肢 {i+1}<br><small>{opt["hex"]}</small></div></div>', unsafe_allow_html=True)
                    if st.button(f"この色を選ぶ ({i+1})", key=f"sel_{st.session_state['current_trial_index']}_{current_step_number}_{i}"):
                        if st.session_state['step_start_time'] is None: st.session_state['step_start_time'] = time.time()
                        rt_ms = int((time.time() - st.session_state['step_start_time'])*1000)
                        st.session_state['step_rts'].append(rt_ms)
                        st.session_state['current_path'].append(opt['digit'])
                        st.session_state['step_start_time'] = None
                        if len(st.session_state['current_path']) >= 8:
                            final_hsl = path_to_hsl_separated(st.session_state['current_path'])
                            trial_record = {
                                'participant_id': st.session_state.get('participant_id'), # ★★★ participant_id を追加
                                'trial': st.session_state['current_trial_index']+1, 'audioName': audio_name,
                                'path': ''.join(map(str,st.session_state['current_path'])), 'finalHex': hsl_to_hex(final_hsl),
                                'finalH': round(final_hsl['H'],2), 'finalS': final_hsl['S'], 'finalL': final_hsl['L'],
                                'stepRTs_ms': '|'.join(map(str,st.session_state.get('step_rts',[]))), 'totalRT_ms': sum(st.session_state.get('step_rts', [])),
                                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'practice': False
                            }
                            append_result_csv(trial_record)
                            st.session_state['current_trial_index'] += 1
                            st.session_state['current_path'] = []
                            st.session_state['step_rts'] = []
                            st.session_state['listening_complete'] = False
                            st.session_state['continuous_play_mode'] = False
                            time.sleep(0.3)
                        safe_rerun()

# questionnaire (段階的選択の後)
elif st.session_state.get('page') == 'questionnaire':
    st.header("短いアンケート（段階的な色選択について）")
    with st.form("qform_stage"):
        q1 = st.radio("Q1.満足度: あなたが選んだ色は、音から感じたイメージとどの程度一致していましたか？", ("1: 全く一致しない", "2: かなり一致しない", "3: 少し一致しない", "4: どちらともいえない", "5: 少し一致する", "6: かなり一致する", "7: 完璧に一致する"))
        q2 = st.radio("Q2.操作感: 色の選択操作は、どの程度、簡単で直感的でしたか？", ("1: 非常に難しい", "2: かなり難しい", "3: 少し難しい", "4: どちらともいえない", "5: 少し簡単", "6: かなり簡単", "7: 非常に簡単"))
        q3 = st.radio("Q3.認知的負荷: 色を選ぶ作業は、精神的にどの程度大変でしたか？", ("1: 全く大変でない", "2: あまり大変でない", "3: 少し大変だった", "4: どちらともいえない", "5: やや大変だった", "6: かなり大変だった", "7: 非常に大変だった"))
        if st.form_submit_button("次へ"):
            st.session_state.setdefault('meta_answers', {})['q1'] = q1
            st.session_state.setdefault('meta_answers', {})['q2'] = q2
            st.session_state.setdefault('meta_answers', {})['q3'] = q3
            
            # ★★★ 次のタスクまたは最終アンケートへ遷移 ★★★
            current_task_index = st.session_state['task_order'].index('stage')
            if current_task_index + 1 < len(st.session_state['task_order']):
                next_task = st.session_state['task_order'][current_task_index + 1]
                go_to(next_task)
            else:
                go_to('final_survey')

# color picker (自由色選択)
elif st.session_state.get('page') == 'color_picker':
    st.header("実験 — 自由な色選択")
    st.markdown("このページでは、それぞれの音刺激に対して自由に色を選んでいただきます。全ての音について選び終わるとアンケートへ進みます。")

    if st.session_state['color_trial_index'] >= len(st.session_state['color_trials_order']):
        st.info("全ての音刺激について色の選択が終わりました。短いアンケートにお答えください。")
        time.sleep(0.5)
        go_to('post_questionnaire') # color_picker の後のアンケートへ
    else:
        cidx = st.session_state['color_trials_order'][st.session_state['color_trial_index']]
        audio_name = '(なし)' if cidx is None else st.session_state['audio_files'][cidx]['name']
        st.write(f"トライアル {st.session_state['color_trial_index']+1} / {len(st.session_state['color_trials_order'])} — 音声: {audio_name}")
        
        audio_bytes = None
        if cidx is not None:
            audio_bytes = st.session_state['audio_files'][cidx]['data']
            audio_mime = st.session_state['audio_files'][cidx].get('mime','audio/wav')

        if not st.session_state.get('color_picker_listening_complete'):
            st.markdown("---")
            st.subheader(f"トライアル {st.session_state['color_trial_index']+1} の再生")
            st.info("まず、今回の音刺激を一度最後までお聞きください。\n\n再生が終了したら、下のボタンを押して色選択に進んでください。")
            render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=False)
            if st.button("再生が終了したので、色選択に進む", key="cp_finish_listening"):
                st.session_state['color_picker_listening_complete'] = True
                safe_rerun()
        else:
            col1, col2 = st.columns([1,1])
            with col1:
                st.markdown("**再生コントロール**")
                if not st.session_state.get('color_picker_continuous_play'):
                    if st.button("色選択中に再生を続ける（ループ再生）", key="cp_start_continuous"):
                        st.session_state['color_picker_continuous_play'] = True; safe_rerun()
                else:
                    if st.button("再生を停止", key="cp_stop_continuous"):
                        st.session_state['color_picker_continuous_play'] = False; safe_rerun()
                
                if st.session_state.get('color_picker_continuous_play'):
                    st.write("ループ再生中...")
                    render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=True)
                
                picked = st.color_picker("この音に最も近いと思う色を選んでください", "#00ff00", key=f"picker_{st.session_state['color_trial_index']}")
                
                if st.button("この色を保存して次へ"):
                    def hex_to_hsl(hexc):
                        hexc=hexc.lstrip('#'); r=int(hexc[0:2],16)/255.0; g=int(hexc[2:4],16)/255.0; b=int(hexc[4:6],16)/255.0
                        maxc,minc=max(r,g,b),min(r,g,b); l=(maxc+minc)/2
                        if maxc==minc: h=s=0
                        else:
                            d=maxc-minc; s=d/(2-maxc-minc) if l>0.5 else d/(maxc+minc)
                            if maxc==r: h=(g-b)/d+(6 if g<b else 0)
                            elif maxc==g: h=(b-r)/d+2
                            else: h=(r-g)/d+4
                            h=(h*60)%360
                        return {'H': round(h,2), 'S': round(s*100,2), 'L': round(l*100,2)}
                    picked_hsl = hex_to_hsl(picked)
                    row = {
                        'participant_id': st.session_state.get('participant_id'), # ★★★ participant_id を追加
                        'trial': st.session_state['color_trial_index']+1, 'audioName': audio_name,
                        'pickedHex': picked, 'pickedH': picked_hsl['H'], 'pickedS': picked_hsl['S'], 'pickedL': picked_hsl['L'],
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
                    }
                    append_color_csv(row)
                    st.session_state['color_results'].append(row)
                    st.session_state['color_trial_index'] += 1
                    st.session_state['color_picker_listening_complete'] = False
                    st.session_state['color_picker_continuous_play'] = False
                    safe_rerun()
            with col2:
                st.markdown("**色のプレビュー**")
                st.markdown(f'<div style="width:100%;height:250px;background-color:{picked};border:1px solid #d3d3d3;border-radius:5px;"></div>', unsafe_allow_html=True)
                st.write(f"HEX: `{picked}`")

# post_questionnaire (自由選択の後)
elif st.session_state.get('page') == 'post_questionnaire':
    st.header("短いアンケート（自由な色選択について）")
    with st.form("post_qform"):
        q4 = st.radio("Q1.満足度: あなたが選んだ色は、音から感じたイメージとどの程度一致していましたか？", ("1: 全く一致しない", "2: かなり一致しない", "3: 少し一致しない", "4: どちらともいえない", "5: 少し一致する", "6: かなり一致する", "7: 完璧に一致する"))
        q5 = st.radio("Q2.操作感: 色の選択操作は、どの程度、簡単で直感的でしたか？", ("1: 非常に難しい", "2: かなり難しい", "3: 少し難しい", "4: どちらともいえない", "5: 少し簡単", "6: かなり簡単", "7: 非常に簡単"))
        q6 = st.radio("Q3.認知的負荷: 色を選ぶ作業は、精神的にどの程度大変でしたか？", ("1: 全く大変でない", "2: あまり大変でない", "3: 少し大変だった", "4: どちらともいえない", "5: やや大変だった", "6: かなり大変だった", "7: 非常に大変だった"))
        if st.form_submit_button("次へ"):
            st.session_state.setdefault('meta_answers', {})['q4'] = q4
            st.session_state.setdefault('meta_answers', {})['q5'] = q5
            st.session_state.setdefault('meta_answers', {})['q6'] = q6

            # ★★★ 次のタスクまたは最終アンケートへ遷移 ★★★
            current_task_index = st.session_state['task_order'].index('color_picker')
            if current_task_index + 1 < len(st.session_state['task_order']):
                next_task = st.session_state['task_order'][current_task_index + 1]
                go_to(next_task)
            else:
                go_to('final_survey')

# final_survey
elif st.session_state.get('page') == 'final_survey':
    st.header("総合アンケート")
    with st.form("final"):
        q7 = st.radio("Q1.総合評価: 二つの色選択手法のうち、「音を聴いて想起した色を選ぶ」という作業に対して、どちらが色選択において総合的に適している手法だと感じましたか？", ("1: 段階的に色選択する手法", "2: カラーピッカーで直接選択する手法", "3: どちらともいえない"))
        q8 = st.text_input("Q2.総合評価の理由: Q1でそのように回答した理由を、具体的に教えてください")
        st.markdown("Q3.各手法の長所・短所")
        q9 = st.text_input("A:段階的に色選択する手法 長所", key="q9")
        q10 = st.text_input("短所", key="q10")
        q11 = st.text_input("B:カラーピッカーで色選択する手法 長所", key="q11")
        q12 = st.text_input("短所", key="q12")
        q13 = st.radio("Q7.年代", ("1: 10代", "2: 20代", "3: 30代", "4: 40代", "5: 50代", "6: 60代以上"))
        q14 = st.radio("Q8.性別", ("1: 男性", "2: 女性", "3: その他", "4: 選択しない"))
        st.markdown("Q9.デバイス環境について")
        q15 = st.text_input("・PC(デスクトップPCかノートPCか、OS、ブラウザ、画面サイズと解像度など)")
        q16 = st.text_input("・ヘッドホンまたはイヤホン(ヘッドホンかイヤホンか、有線か無線か、メーカー名、製品名など)")
        q17 = st.text_input("Q10.音楽経験: 楽器の演奏経験（楽器名、年数）、歌唱経験、作曲やDTMの経験、バンド活動、音楽の学習歴（専門教育を受けた、独学など）など、音楽に関する経験を可能な範囲で詳しく教えてください。")
        q18 = st.text_input("Q11.色彩・美術・デザイン経験: 絵画（油絵、水彩、イラストなど）、デザイン（グラフィック、Webなど）、写真、映像制作に関する学習歴や活動歴、色彩検定などの関連資格の有無など、色彩・美術・デザインに関する経験を可能な範囲で詳しく教えてください。")
        submitted = st.form_submit_button("送信して終了")
        
        if submitted:
            is_valid = all([
                q8.strip(), q9.strip(), q10.strip(), q11.strip(), q12.strip(),
                q15.strip(), q16.strip(), q17.strip(), q18.strip()
            ])
            
            if not is_valid:
                st.error("未入力の項目があります。すべての質問にご回答ください。")
            else:
                meta_answers = st.session_state.setdefault('meta_answers', {})
                meta_answers.update({
                    'q7': q7, 'q8': q8, 'q9': q9, 'q10': q10, 'q11': q11, 'q12': q12,
                    'q13': q13, 'q14': q14, 'q15': q15, 'q16': q16, 'q17': q17, 'q18': q18
                })

                row_data = {
                    'participant_id': st.session_state.get('participant_id'),
                    'task_order': ' -> '.join(st.session_state.get('task_order', [])), # ★★★ task_order を記録
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    **{f'q{i}': meta_answers.get(f'q{i}', '') for i in range(1, 19)},
                    'n_color_picks': len(st.session_state.get('color_results', [])),
                    'n_hierarchical_trials': st.session_state['current_trial_index']
                }
                
                try:
                    append_meta_csv(row_data)
                    go_to('end')
                except Exception as e:
                    st.error(f"メタデータの保存に失敗しました: {e}")

# end
elif st.session_state.get('page') == 'end':
    st.header("終了ページ")
    st.markdown("ご協力ありがとうございました。結果は保存されました。")
    if st.button("トップへ戻る（新しい参加者）"):
        # セッション状態をクリアして新しい参加者を迎える
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        safe_rerun()

st.markdown("---")
st.caption("注: ブラウザの自動再生ポリシーにより autoplay が効かないことがあります。音が鳴らない場合は手動で再生してください。")
