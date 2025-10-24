# sttest3.py
# 完全版：管理者アップロード（即時反映）＋一覧管理（再生/ダウンロード/削除）＋参加者フロー
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

# --- メタ結果保存用ファイル（最終アンケート） ---
META_RESULTS_CSV = 'meta_results.csv'

def append_meta_csv(row: dict):
    header = ['participant_id','timestamp','q1','q2','q3','q4','q5','q6','q7','q8','q9','q10','q11','q12','q13','q14','q15','q16','q17','q18','n_color_picks','n_hierarchical_trials']
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
    # フォールバック：クエリパラメータ更新して再描画を促す
    try:
        params = st.experimental_get_query_params()
        params["_rerun_ts"] = int(time.time()*1000)
        st.experimental_set_query_params(**params)
        st.stop()
    except Exception:
        # 最終手段：何もしない（環境によっては手動更新が必要）
        return

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
    # H:[0,360], S:[0,100], L:[0,100]
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
if 'audio_files' not in st.session_state:
    st.session_state['audio_files'] = []  # [{'id','name','safe_name','data','mime'}]
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
# color picker state
if 'color_trials_order' not in st.session_state:
    st.session_state['color_trials_order'] = []
if 'color_trial_index' not in st.session_state:
    st.session_state['color_trial_index'] = 0
if 'color_results' not in st.session_state:
    st.session_state['color_results'] = []
# admin tracking
if 'last_uploaded_names' not in st.session_state:
    st.session_state['last_uploaded_names'] = []

# participant_id を一意に生成（consent 同意時に使うがセッションに無ければ生成）
if 'participant_id' not in st.session_state:
    st.session_state['participant_id'] = f"{int(time.time())}_{random.randint(1000,9999)}"

# ---------- uploads/ からの自動読み込み（参加者用） ----------
# 参加者セッションで audio_files が空の場合、uploads フォルダを読み込んで session_state にセットする
if not st.session_state.get('audio_files'):
    try:
        files_on_disk = sorted([p for p in UPLOAD_DIR.iterdir() if p.is_file()])
    except Exception:
        files_on_disk = []
    if files_on_disk:
        st.session_state['audio_files'] = []
        for p in files_on_disk:
            try:
                with open(p, 'rb') as f:
                    data = f.read()
                ext = p.suffix.lower().lstrip('.')
                mime = 'audio/wav'
                if ext in ['mp3']:
                    mime = 'audio/mpeg'
                elif ext in ['ogg']:
                    mime = 'audio/ogg'
                elif ext in ['m4a','mp4','aac']:
                    mime = 'audio/mp4'
                st.session_state['audio_files'].append({
                    'id': f"disk_{p.stem}",
                    'name': p.name,
                    'safe_name': p.name,
                    'data': data,
                    'mime': mime
                })
            except Exception as e:
                st.warning(f"failed to load {p.name}: {e}")
        # trials_order を自動生成（空なら）
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

#col_admin, col_participant = st.columns(2)
#with col_admin:
#    st.subheader("管理者ツール")
#    if st.button("管理ページへ（ファイルアップロード・ログ確認）"):
#        st.session_state['page'] = 'admin'
#with col_participant:
#    st.subheader("参加者")
#    if st.button("参加者ページへ（実験を開始）"):
#        st.session_state['page'] = 'consent'

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
    new_names = []
    if uploaded:
        uploaded_names = []
        saved_count = 0
        new_names = []
        for f in uploaded:
            try:
                data = f.read()
                uploaded_names.append(f.name)
                safe_name = safe_filename(f.name)
                save_path = UPLOAD_DIR / safe_name
                with open(save_path, 'wb') as out:
                    out.write(data)
                saved_count += 1
            except Exception as e:
                st.error(f"ファイル保存に失敗しました ({f.name}): {e}")

        # last_uploaded_names を更新
        st.session_state['last_uploaded_names'] = uploaded_names

        # ディスクから再読み込みして session_state['audio_files'] を確実に更新
        reloaded = []
        try:
            files_on_disk = sorted([p for p in UPLOAD_DIR.iterdir() if p.is_file()])
        except Exception as e:
            files_on_disk = []
            st.error(f"uploads フォルダ読み込み失敗: {e}")

        for p in files_on_disk:
            try:
                with open(p, 'rb') as fh:
                    data = fh.read()
                ext = p.suffix.lower().lstrip('.')
                mime = 'audio/wav'
                if ext in ['mp3']:
                    mime = 'audio/mpeg'
                elif ext in ['ogg']:
                    mime = 'audio/ogg'
                elif ext in ['m4a','mp4','aac']:
                    mime = 'audio/mp4'
                reloaded.append({'id': f"disk_{p.stem}", 'name': p.name, 'safe_name': p.name, 'data': data, 'mime': mime})
            except Exception as e:
                st.warning(f"{p.name} の再読み込みに失敗: {e}")

        st.session_state['audio_files'] = reloaded

        # トライアル順を更新
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
        st.success(f"{saved_count} 件を保存・反映しました（合計 {n} 件）。")

        try:
            safe_rerun()
        except Exception:
            # フォールバック: クエリパラメータ更新
            params = st.experimental_get_query_params()
            params["_admin_ts"] = int(time.time()*1000)
            st.experimental_set_query_params(**params)
            st.stop()

    elif uploaded and not new_names:
        st.info("アップロードは検出されましたがファイル名が前回と同じため、新規反映は行いませんでした。")

    # 手動初期化ボタン
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
    st.subheader("現在読み込まれているファイル（管理）")

    audio_list = st.session_state.get('audio_files', [])
    if not audio_list:
        st.write("まだファイルが読み込まれていません。アップロードしてください。")
    else:
        for idx, a in enumerate(audio_list):
            cols = st.columns([3,1,1,1,1])
            with cols[0]:
                st.markdown(f"**{idx+1}. {a.get('name')}**  (`{a.get('id')}`)")
                st.write(f"mime: {a.get('mime')}")
            with cols[1]:
                if st.button("再生", key=f"play_{a.get('safe_name')}_{idx}"):
                    try:
                        render_audio_player(a.get('data'), mime=a.get('mime'), autoplay=True, loop=False, height=100)
                    except Exception as e:
                        st.error(f"再生に失敗しました: {e}")
            with cols[2]:
                try:
                    st.download_button(f"Download", data=a.get('data'), file_name=a.get('name'), mime=a.get('mime'), key=f"dl_{a.get('safe_name')}_{idx}")
                except Exception as e:
                    st.error(f"ダウンロード準備に失敗: {e}")
            with cols[3]:
                if st.button("削除", key=f"del_{a.get('safe_name')}_{idx}"):
                    removed_name = a.get('safe_name')
                    filepath = UPLOAD_DIR / removed_name
                    try:
                        if filepath.exists():
                            filepath.unlink()
                    except Exception as e:
                        st.error(f"ファイル削除に失敗しました: {e}")
                    new_audio_files = [x for x in st.session_state['audio_files'] if x.get('safe_name') != removed_name]
                    st.session_state['audio_files'] = new_audio_files
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
                    st.success(f"{removed_name} を削除しました。")
                    try:
                        safe_rerun()
                    except Exception:
                        pass
            with cols[4]:
                pass

        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("すべて削除（uploads フォルダを空にする）"):
                failures = []
                for p in list(UPLOAD_DIR.iterdir()):
                    try:
                        if p.is_file():
                            p.unlink()
                    except Exception as e:
                        failures.append(str(p))
                st.session_state['audio_files'] = []
                st.session_state['trials_order'] = [None]
                st.session_state['color_trials_order'] = [None]
                st.session_state['current_trial_index'] = 0
                st.session_state['color_trial_index'] = 0
                st.session_state['results'] = []
                st.session_state['color_results'] = []
                if failures:
                    st.warning(f"いくつかのファイルが削除できませんでした: {failures}")
                else:
                    st.success("uploads フォルダ内のファイルを全て削除しました。")
                try:
                    safe_rerun()
                except Exception:
                    pass
        with col_b:
            if st.button("uploads フォルダの内容を再読み込み"):
                new_files = []
                try:
                    files_on_disk = sorted([p for p in UPLOAD_DIR.iterdir() if p.is_file()])
                except Exception:
                    files_on_disk = []
                for p in files_on_disk:
                    try:
                        with open(p,'rb') as f:
                            data = f.read()
                        ext = p.suffix.lower().lstrip('.')
                        mime = 'audio/wav'
                        if ext in ['mp3']:
                            mime = 'audio/mpeg'
                        elif ext in ['ogg']:
                            mime = 'audio/ogg'
                        elif ext in ['m4a','mp4','aac']:
                            mime = 'audio/mp4'
                        new_files.append({'id': f"disk_{p.stem}", 'name': p.name, 'safe_name': p.name, 'data': data, 'mime': mime})
                    except Exception as e:
                        st.warning(f"failed to load {p.name}: {e}")
                st.session_state['audio_files'] = new_files
                n = len(new_files)
                if n == 0:
                    st.session_state['trials_order'] = [None]
                else:
                    st.session_state['trials_order'] = list(range(n))
                    if st.session_state['settings'].get('shuffle_trials', True):
                        random.shuffle(st.session_state['trials_order'])
                st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
                st.session_state['current_trial_index'] = 0
                st.session_state['color_trial_index'] = 0
                st.success("uploads フォルダを再読み込みしました。")
                try:
                    safe_rerun()
                except Exception:
                    pass

    st.markdown("---")
    st.header("ログ / 結果のダウンロード")
    if os.path.exists(RESULTS_CSV):
        with open(RESULTS_CSV, 'r', encoding='utf-8') as f:
            data = f.read()
        st.download_button("results.csv をダウンロード", data=data, file_name="results.csv", mime="text/csv")
    if os.path.exists(COLOR_RESULTS_CSV):
        with open(COLOR_RESULTS_CSV, 'r', encoding='utf-8') as f:
            data = f.read()
        st.download_button("color_results.csv をダウンロード", data=data, file_name="color_results.csv", mime="text/csv")
    if os.path.exists(META_RESULTS_CSV):
        with open(META_RESULTS_CSV, 'r', encoding='utf-8') as f:
            data = f.read()
        st.download_button("meta_results.csv をダウンロード", data=data, file_name="meta_results.csv", mime="text/csv")

# 参加者ページフロー（consent -> audio_check -> stage -> questionnaire -> color_picker -> post_questionnaire -> final_survey -> end）

# consent
if st.session_state.get('page') == 'consent':
    st.header("同意書 / 研究について")
    st.markdown("""
    ### 1.	実験の目的と意義
    本実験では、人々が音や音楽を聴いた際に色を想起する知覚現象を扱う実験において、2種類の色選択手法を比較します。こちらの現象についての実験を行い、実験データの分析を行うことで、今後の同分野の研究で、より信頼性の高いデータを収集するための最適な実験環境を提案することを目的としています。

    ### 2.	実験の概要
    本実験は、オンラインにて実施します。参加者の皆様には、静かな環境でPCとヘッドホンまたはイヤホンをご用意いただき、画面の指示に従って作業を進めていただきます。
    提示される音刺激に対して下記の二つの手法を用いて想起した色を選択する作業を行っていただきます。
    ・カラーピッカー
    ・段階的な色選択
    各手法で色を選択した直後に、色選択に関するアンケートに回答してください。さらに、全手法での色選択及びアンケート回答後には、全体のアンケートに回答してください。
    二つの手法の順序は参加者ごとに異なります。作業時間は休憩時間5分を含めて計45分を想定しています。

    ### 3.	実験参加に伴う危険
    ヘッドホンを装着してディスプレイを見ながら、提示される音を聴いて画面上で色の選択を繰り返し行っていただくため、疲労や精神的負担を感じてしまう可能性があります。実験中にそのような危険性を感じた場合には、いつでも実験の中断、または参加の取り消しを行うことができます。実験は全体で45分程度を予定しています。また、実験中には5分ほどの休憩を設定していますが、疲労を感じた場合は適宜休憩をとっていただくことが可能です。 

    ### 4.	実験参加の可否について
    本実験への参加は自由意志です。また, 一度同意した後でも同意を取り消すことが可能であり, それによる不利益はありません。

    ### 5.	個人情報の取り扱いについて
    本実験で記録するすべてのデータは、本研究の目的以外に使用されることはありません。またそれらデータは、名前や個人情報を一切記載せず、実験参加者ごとに付与したIDによって外部に流出することの無いよう、厳重に管理されます。
    また本同意書は実験責任者の鍵付き保管庫にて施錠の上、保管されます。

    ### 6.	問い合わせ先について
    実験担当者	筑波大学情報学群情報メディア創成学類 4年 山﨑聖生 
                            e-mail: s2210284@u.tsukuba.ac.jp
    
    実験責任者	筑波大学図書館情報メディア系 助教 飯野なみ
    〒305-8550 茨城県つくば市春日1-2 
    e-mail: niino@slis.tsukuba.ac.jp

    本実験は、図書館情報メディア系研究倫理審査委員会の承認を得て実施しています
    
    """)        
    
    if st.checkbox("実験に同意します"):
        if st.button("次へ"):
            go_to('audio_check')
    else:
        st.write("同意しない場合はウィンドウを閉じてください。")

# audio check
elif st.session_state.get('page') == 'audio_check':
    st.header("音量・再生チェック")
    st.markdown("""
    ・ヘッドフォンを着用してください。  
    ・「テスト音を再生」で音が聞こえるか確認してください。  
    ・問題なければ「再生確認済みにチェック」を入れて次へ進んでください。  
    """)

    sample_b64 = None
    sample_mime = None
    first_name = None
    if st.session_state.get('audio_files'):
        first = st.session_state['audio_files'][0]
        sample_b64 = base64.b64encode(first['data']).decode('ascii')
        sample_mime = first.get('mime','audio/wav')
        first_name = first.get('name')

    html_js = """
    <div>
      <button id="playTone">テスト音を再生</button>
      <button id="stopTone">テスト音停止</button>
      <span style="margin-left:10px" id="toneInfo"></span>
      <br/><br/>
    """
    if sample_b64:
        html_js += f"""
        <div>
          <div>サンプル刺激: <strong>{first_name}</strong></div>
          <button id="playSample">サンプルを再生</button>
          <button id="stopSample">サンプル停止</button>
          <audio id="sampleAudio" style="display:none">
            <source src="data:{sample_mime};base64,{sample_b64}">
          </audio>
        </div>
        <br/>
        """
    html_js += """
    </div>
    <script>
    let audioCtx = null;
    let osc = null;
    document.getElementById("playTone").addEventListener("click", async function(){
        if(!audioCtx){ audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
        if(osc){ osc.stop(); osc.disconnect(); }
        osc = audioCtx.createOscillator();
        let gain = audioCtx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 880;
        gain.gain.value = 0.05;
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        document.getElementById("toneInfo").textContent = "再生中 (880Hz)";
    });
    document.getElementById("stopTone").addEventListener("click", function(){
        if(osc){ try{ osc.stop(); }catch(e){}; osc.disconnect(); osc = null; document.getElementById("toneInfo").textContent=''; }
    });
    const sampleEl = document.getElementById("sampleAudio");
    if(sampleEl){
      document.getElementById("playSample").addEventListener("click", function(){
        sampleEl.play();
      });
      document.getElementById("stopSample").addEventListener("click", function(){
        sampleEl.pause(); sampleEl.currentTime = 0;
      });
    }
    </script>
    """
    components.html(html_js, height=200)

    st.checkbox("再生確認済み（聞こえた・音量問題なし）", key="audio_checked")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("戻る（同意ページ）"):
            go_to('consent')
    with col2:
        if st.session_state.get('audio_checked'):
            if st.button("次へ（実験開始）"):
                if not st.session_state.get('trials_order'):
                    n = len(st.session_state.get('audio_files', []))
                    if n == 0:
                        st.session_state['trials_order'] = [None]
                    else:
                        st.session_state['trials_order'] = list(range(n))
                        if st.session_state['settings'].get('shuffle_trials', True):
                            random.shuffle(st.session_state['trials_order'])
                        st.session_state['color_trials_order'] = st.session_state['trials_order'].copy()
                go_to('stage')
        else:
            st.write("「再生確認済み」にチェックを入れてください。")

# stage
elif st.session_state.get('page') == 'stage':
    st.header("実験 — 刺激提示と色選択")

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
    audio_name = '(なし)' if idx is None else st.session_state['audio_files'][idx]['name'] if st.session_state.get('audio_files') else '(なし)'
    st.write(f"トライアル {st.session_state['current_trial_index']+1} / {len(st.session_state['trials_order'])} — 音声: {audio_name}")

    audio_bytes = None
    audio_mime = 'audio/wav'
    if idx is not None and st.session_state.get('audio_files'):
        audio_bytes = st.session_state['audio_files'][idx]['data']
        audio_mime = st.session_state['audio_files'][idx].get('mime','audio/wav')

    colp, colq = st.columns([3,1])
    with colp:
        st.markdown("**再生コントロール**")
        if st.session_state['settings'].get('autoplay') and st.session_state['settings'].get('once_per_stage') and not st.session_state.get('played_this_stage'):
            render_audio_player(audio_bytes, mime=audio_mime, autoplay=True, loop=st.session_state['settings'].get('loop_audio', False))
            st.session_state['played_this_stage'] = True
            st.write("自動再生を試みました（ブラウザでブロックされる可能性あり）。")
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
        if st.button("次のトライアルへ（スキップ）←後で消す"):
            st.session_state['current_trial_index'] += 1
            st.session_state['current_path'] = []
            st.session_state['step_rts'] = []
            st.session_state['played_this_stage'] = False
            safe_rerun()

    # 色選択（8段階）
    st.markdown("### 色選択（8段階）")
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

# questionnaire
elif st.session_state.get('page') == 'questionnaire':
    st.header("短いアンケート")
    with st.form("qform_stage"):

        st.markdown("Q1.満足度")
        q1 = st.radio("あなたが選んだ色は、音から感じたイメージとどの程度一致していましたか？", ("1: 全く一致しない" ,"2: かなり一致しない" ,"3: 少し一致しない" ,"4: どちらともいえない" ,"5: 少し一致する" ,"6: かなり一致する" ,"7: 完璧に一致する"))
        st.markdown("Q2.操作感")
        q2 = st.radio("色の選択操作は、どの程度、簡単で直感的でしたか？", ("1: 非常に難しい" ,"2: かなり難しい" ,"3: 少し難しい" ,"4: どちらともいえない" ,"5: 少し簡単" ,"6: かなり簡単" ,"7: 非常に簡単"))
        st.markdown("Q③.認知的負荷")
        q3 = st.radio("色を選ぶ作業は、精神的にどの程度大変でしたか？", ("1: 全く大変でない" ,"2: あまり大変でない" ,"3: 少し大変だった" ,"4: どちらともいえない" ,"5: やや大変だった" ,"6: かなり大変だった" ,"7: 非常に大変だった"))


        submitted = st.form_submit_button("次へ")
        if submitted:
            st.session_state.setdefault('meta_answers', {})['q1'] = q1
            st.session_state.setdefault('meta_answers', {})['q2'] = q2
            st.session_state.setdefault('meta_answers', {})['q3'] = q3
            go_to('color_picker')

# color picker
elif st.session_state.get('page') == 'color_picker':
    st.header("自由色選択ページ（各音刺激ごとに1色選んでください）")
    st.markdown("このページでは、それぞれの音刺激に対して自由に色を選んでいただきます。全ての音について選び終わると次のアンケートへ進みます。")

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
        st.session_state['page'] = 'post_questionnaire'
        safe_rerun()
    else:
        cidx = st.session_state['color_trials_order'][st.session_state['color_trial_index']]
        audio_name = '(なし)' if cidx is None else st.session_state['audio_files'][cidx]['name'] if st.session_state.get('audio_files') else '(なし)'
        st.write(f"トライアル {st.session_state['color_trial_index']+1} / {len(st.session_state['color_trials_order'])} — 音声: {audio_name}")

        audio_bytes = None
        audio_mime = 'audio/wav'
        if cidx is not None and st.session_state.get('audio_files'):
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

# post / final / end
elif st.session_state.get('page') == 'post_questionnaire':
    st.header("個別アンケート")
    with st.form("post_qform"):

        st.markdown("Q1.満足度")
        q4 = st.radio("あなたが選んだ色は、音から感じたイメージとどの程度一致していましたか？", ("1: 全く一致しない" ,"2: かなり一致しない" ,"3: 少し一致しない" ,"4: どちらともいえない" ,"5: 少し一致する" ,"6: かなり一致する" ,"7: 完璧に一致する"))
        st.markdown("Q2.操作感")
        q5 = st.radio("色の選択操作は、どの程度、簡単で直感的でしたか？", ("1: 非常に難しい" ,"2: かなり難しい" ,"3: 少し難しい" ,"4: どちらともいえない" ,"5: 少し簡単" ,"6: かなり簡単" ,"7: 非常に簡単"))
        st.markdown("Q3.認知的負荷")
        q6 = st.radio("色を選ぶ作業は、精神的にどの程度大変でしたか？", ("1: 全く大変でない" ,"2: あまり大変でない" ,"3: 少し大変だった" ,"4: どちらともいえない" ,"5: やや大変だった" ,"6: かなり大変だった" ,"7: 非常に大変だった"))

        submitted = st.form_submit_button("次へ")
        if submitted:
            st.session_state.setdefault('meta_answers', {})['q4'] = q4
            st.session_state.setdefault('meta_answers', {})['q5'] = q5
            st.session_state.setdefault('meta_answers', {})['q6'] = q6
            st.session_state['page'] = 'final_survey'
            safe_rerun()


elif st.session_state.get('page') == 'final_survey':
    st.header("総合アンケート")
    with st.form("final"):
        st.markdown("Q1.総合評価")
        q7 = st.radio("二つの色選択手法のうち、「音を聴いて想起した色を選ぶ」という作業に対して、どちらが色選択において総合的に適している手法だと感じましたか？", ("1: 段階的に色選択する手法","2: カラーピッカーで直接選択する手法","3: どちらともいえない" ))
        st.markdown("Q2.総合評価の理由")
        q8 = st.text_input("Q1でそのように回答した理由を、具体的に教えてください")
        st.markdown("Q3.各手法の長所・短所")
        st.markdown("A:段階的に色選択する手法")
        q9 = st.text_input("長所", key="q9")
        q10 = st.text_input("短所", key="q10")
        st.markdown("B:カラーピッカーで色選択する手法")
        q11 = st.text_input("長所", key="q11")
        q12 = st.text_input("短所", key="q12")


        q13 = st.radio("Q7.年代", ("1: 10代","2: 20代","3: 30代","4: 40代","5: 50代","6: 60代以上", ))
        q14 = st.radio("Q8.性別", ("1: 男性","2: 女性","3: その他","4: 選択しない" ))
        
        st.markdown("Q9.デバイス環境について")
        st.markdown("あなたが実験で使用したPCとヘッドホンまたはイヤホンについて可能な範囲で詳しく教えてください。")
        q15 = st.text_input("・PC(デスクトップPCかノートPCか、OS、ブラウザ、画面サイズと解像度など)")
        q16 = st.text_input("・ヘッドホンまたはイヤホン(ヘッドホンかイヤホンか、有線か無線か、メーカー名、製品名など)")
        st.markdown("Q10.音楽経験")
        q17 = st.text_input("楽器の演奏経験（楽器名、年数）、歌唱経験、作曲やDTMの経験、バンド活動、音楽の学習歴（専門教育を受けた、独学など）など、音楽に関する経験を可能な範囲で詳しく教えてください。")
        st.markdown("Q11.色彩・美術・デザイン経験")
        q18 = st.text_input("絵画（油絵、水彩、イラストなど）、デザイン（グラフィック、Webなど）、写真、映像制作に関する学習歴や活動歴、色彩検定などの関連資格の有無など、色彩・美術・デザインに関する経験を可能な範囲で詳しく教えてください。")

        submitted = st.form_submit_button("送信して終了")
        if submitted:
            st.session_state.setdefault('meta_answers', {})['q7'] = q7
            st.session_state.setdefault('meta_answers', {})['q8'] = q8
            st.session_state.setdefault('meta_answers', {})['q9'] = q9
            st.session_state.setdefault('meta_answers', {})['q10'] = q10
            st.session_state.setdefault('meta_answers', {})['q11'] = q11
            st.session_state.setdefault('meta_answers', {})['q12'] = q12
            st.session_state.setdefault('meta_answers', {})['q13'] = q13
            st.session_state.setdefault('meta_answers', {})['q14'] = q14
            st.session_state.setdefault('meta_answers', {})['q15'] = q15
            st.session_state.setdefault('meta_answers', {})['q16'] = q16
            st.session_state.setdefault('meta_answers', {})['q17'] = q17
            st.session_state.setdefault('meta_answers', {})['q18'] = q18

            # --- メタ情報をCSVに保存 ---
            meta = st.session_state.get('meta_answers', {})
            participant_id = st.session_state.get('participant_id', f"{int(time.time())}_{random.randint(1000,9999)}")
            row = {
                'participant_id': participant_id,
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'q1': meta.get('q1',''),
                'q2': meta.get('q2',''),
                'q3': meta.get('q3',''),
                'q4': meta.get('q4',''),
                'q5': meta.get('q5',''),
                'q6': meta.get('q6',''),
                'q7': meta.get('q7',''),
                'q8': meta.get('q8',''),
                'q9': meta.get('q9',''),
                'q10': meta.get('q10',''),
                'q11': meta.get('q11',''),
                'q12': meta.get('q12',''),
                'q13': meta.get('q13',''),
                'q14': meta.get('q14',''),
                'q15': meta.get('q15',''),
                'q16': meta.get('q16',''),
                'q17': meta.get('q17',''),
                'q18': meta.get('q18',''),

                'n_color_picks': len(st.session_state.get('color_results', [])),
                'n_hierarchical_trials': len(st.session_state.get('results', []))
            }
            try:
                append_meta_csv(row)
            except Exception as e:
                st.error(f"メタデータの保存に失敗しました: {e}")

            st.session_state['page'] = 'end'
            safe_rerun()

elif st.session_state.get('page') == 'end':
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
