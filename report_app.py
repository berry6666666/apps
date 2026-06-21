"""
報案系統 v4.0 — 強化版
新增：統計儀表板 / 搜尋篩選 / HTML 匯出 / 嚴重等級 / 並排 Diff / 鍵盤快捷鍵
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import os, re, json, base64, io, threading, webbrowser
from datetime import datetime

# ─── Persistence ─────────────────────────────────────────────
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
RECORDS_FILE = os.path.join(_SCRIPT_DIR, "issue_records.json")
KEYWORDS_FILE= os.path.join(_SCRIPT_DIR, "log_keywords.txt")
EXPORTS_DIR  = os.path.join(_SCRIPT_DIR, "exports")

# ─── Color Palette ───────────────────────────────────────────
BG_DARK    = "#2D3A4A"
BG_PANEL   = "#222E3C"
BG_LIGHT   = "#F5F6F8"
BG_CARD    = "#FFFFFF"
BG_INPUT   = "#EDF0F5"
ACCENT     = "#D9623A"
SUCCESS    = "#3DAF77"
WARNING    = "#E0A93A"
INFO       = "#5088C5"
DANGER     = "#E53E3E"
TEXT_DARK  = "#2C3A4A"
TEXT_MID   = "#5A6472"
TEXT_LIGHT = "#F8F9FA"
TEXT_MUTED = "#9DAABA"
BORDER     = "#DDE2EA"
DIFF_DEL   = "#FEF7EE"
DIFF_ADD   = "#F0FFF4"
DOT_GREEN  = "#3DAF77"
DOT_YELLOW = "#E0A93A"
KW_TAG_BG  = "#C0522A"
LOG_BG     = "#1E2837"
LOG_FG     = "#DCE4EE"
LOG_KW_FG  = "#F0B755"
SH_COMPARE = "#354A61"
SH_REPORT  = "#4A3028"
SH_LOG     = "#27433A"
SH_DASH    = "#2D3A50"

SEVERITY_COLORS = {
    "低": ("#3DAF77", "#D1FAE5"),
    "中": ("#E0A93A", "#FEF3C7"),
    "高": ("#E53E3E", "#FEE2E2"),
    "嚴重": ("#7C3AED", "#EDE9FE"),
}

RCP_FIELDS = [
    "Tool ID", "RCP MODIFY TIME", "RCP SCAN TIME",
    "SCAN END TIME", "LOT ID", "RCP NAME",
]

_DEFAULT_KEYWORDS = [
    "ERROR","error","FAIL","FAILED","ALARM","WARNING",
    "ABORT","TIMEOUT","CRITICAL","EXCEPTION","FAULT",
    "CRASH","REJECTED","INTERLOCKED",
]

# ─── Image helpers ────────────────────────────────────────────
def _img_to_b64(img):
    buf = io.BytesIO()
    fmt = img.format or "PNG"
    if fmt not in ("PNG","JPEG","BMP","GIF"): fmt = "PNG"
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()

def _b64_to_img(s):
    return Image.open(io.BytesIO(base64.b64decode(s)))

# ─── Persistence ─────────────────────────────────────────────
def save_records(records):
    serial = []
    for rec in records:
        r = {k: v for k, v in rec.items() if k != "images"}
        r["log_hits"] = [[ln, line, kws] for ln, line, kws in rec.get("log_hits", [])]
        imgs = []
        for name, img in rec.get("images", []):
            try: imgs.append({"name": name, "data": _img_to_b64(img)})
            except: pass
        r["images"] = imgs
        serial.append(r)
    try:
        with open(RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(serial, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[warn] save: {e}")

def load_records():
    if not os.path.exists(RECORDS_FILE): return []
    try:
        with open(RECORDS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out = []
        for r in raw:
            imgs = [(e["name"], _b64_to_img(e["data"]))
                    for e in r.get("images", []) if "name" in e and "data" in e]
            r["images"] = imgs
            r["log_hits"] = [(int(ln), line, kws)
                             for ln, line, kws in r.get("log_hits", [])]
            out.append(r)
        return out
    except Exception as e:
        print(f"[warn] load: {e}")
        return []

# ─── Keywords ────────────────────────────────────────────────
def load_keywords():
    if not os.path.exists(KEYWORDS_FILE):
        _write_default_keywords()
        return list(_DEFAULT_KEYWORDS)
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            kws = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
        return kws or list(_DEFAULT_KEYWORDS)
    except:
        return list(_DEFAULT_KEYWORDS)

def _write_default_keywords():
    try:
        with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
            f.write("# Log TS 關鍵字清單 — 每行一個，# 開頭為註解\n\n")
            for kw in _DEFAULT_KEYWORDS: f.write(kw + "\n")
    except: pass

ISSUE_KEYWORDS = load_keywords()

# ─── RCP Parser ──────────────────────────────────────────────
def _parse_date_time(date_str, time_str):
    dm = re.match(r'(\d{1,2})-(\d{1,2})-(\d{4})', date_str.strip())
    if dm:
        return f"{dm.group(3)}/{dm.group(1).zfill(2)}/{dm.group(2).zfill(2)} {time_str.strip()}"
    return f"{date_str.strip()} {time_str.strip()}"

def parse_rcp_text(text):
    data = {f: "" for f in RCP_FIELDS}
    m = re.search(r'Record\s+LotRecord\s+"([^"]+)"', text)
    if m: data["LOT ID"] = m.group(1).strip()
    m = re.search(r'\{[^}]*"AMAT"\s*,\s*"PrimeVision"\s*,\s*"([^"]+)"\s*\}', text, re.IGNORECASE)
    if m: data["Tool ID"] = m.group(1).strip()
    m = re.search(r'Field\s+ResultTimeStamp\s+\d+\s*\{\s*"([^"]+)"\s*,\s*"?(\d{1,2}:\d{2}:\d{2})"?\s*\}', text, re.IGNORECASE)
    if m: data["RCP SCAN TIME"] = _parse_date_time(m.group(1), m.group(2))
    m = re.search(r'Field\s+FileTimeStamp\s+\d+\s*\{\s*"([^"]+)"\s*,\s*"?(\d{1,2}:\d{2}:\d{2})"?\s*\}', text, re.IGNORECASE)
    if m: data["SCAN END TIME"] = _parse_date_time(m.group(1), m.group(2))
    m = re.search(r'Field\s+RecipeID\s+\d+\s*\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\}', text, re.IGNORECASE)
    if m:
        data["RCP NAME"]        = m.group(1).strip()
        data["RCP MODIFY TIME"] = _parse_date_time(m.group(2), m.group(3))
    return data

def diff_dicts(golden, issue):
    rows = []
    for k in RCP_FIELDS:
        g, i = golden.get(k, ""), issue.get(k, "")
        if not g and not i:   status = "empty"
        elif not g:           status = "only_issue"
        elif not i:           status = "only_golden"
        elif g == i:          status = "match"
        else:                 status = "mismatch"
        rows.append((k, g, i, status))
    return rows

# ─── Log Scanner ─────────────────────────────────────────────
_LOG_TS_RE = re.compile(r'^([A-Za-z]{3})\s+(\d{1,2}),\s+(\d{2}:\d{2}:\d{2})')
_MONTH_MAP = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}

def _parse_log_ts(line, ref_year):
    m = _LOG_TS_RE.match(line)
    if not m: return None
    try:
        mon = _MONTH_MAP.get(m.group(1), 0)
        if not mon: return None
        h, mi, s = (int(x) for x in m.group(3).split(":"))
        return datetime(ref_year, mon, int(m.group(2)), h, mi, s)
    except: return None

def _parse_rcp_dt(s, ref_year):
    for fmt in ("%Y/%m/%d %H:%M:%S","%Y-%m-%d %H:%M:%S","%Y/%m/%d %H:%M","%Y-%m-%d %H:%M"):
        try: return datetime.strptime(s.strip(), fmt)
        except: continue
    return None

def scan_log_keywords(text, keywords, scan_start=None, scan_end=None):
    use_range = scan_start and scan_end
    ref_year  = scan_start.year if use_range else datetime.now().year
    hits, in_range, skipped = [], 0, 0
    for lineno, line in enumerate(text.splitlines(), 1):
        ts = _parse_log_ts(line, ref_year)
        if use_range:
            if ts is None: skipped += 1; continue
            if not (scan_start <= ts <= scan_end): continue
            in_range += 1
        matched = [kw for kw in keywords if kw in line]
        if matched: hits.append((lineno, line, matched))
    return hits, in_range, skipped

# ─── HTML Export ─────────────────────────────────────────────
def export_html(rec):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    fname = os.path.join(EXPORTS_DIR, f"issue_{rec['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    diff_rows = diff_dicts(rec.get("golden", {}), rec.get("issue", {}))
    diff_html = ""
    for field, g_val, i_val, status in diff_rows:
        color = "#FEF3C7" if status == "mismatch" else ("#F0FFF4" if status == "match" else "#F9FAFB")
        dot   = "🟡" if status == "mismatch" else ("🟢" if status == "match" else "⚪")
        diff_html += f"""
        <tr style="background:{color}">
          <td style="padding:6px 10px;font-size:13px">{dot}</td>
          <td style="padding:6px 10px;font-weight:600;font-size:13px">{field}</td>
          <td style="padding:6px 10px;font-family:monospace;font-size:12px">{g_val or '—'}</td>
          <td style="padding:6px 10px;font-family:monospace;font-size:12px;color:{'#B45309' if status=='mismatch' else '#1a1a2e'}">{i_val or '—'}</td>
        </tr>"""
    log_html = ""
    for lineno, line, kws in rec.get("log_hits", []):
        kw_badges = "".join(f'<span style="background:#C0522A;color:#fff;padding:1px 6px;border-radius:4px;font-size:11px;margin-left:4px">{k}</span>' for k in kws)
        log_html += f'<div style="background:#1E2837;color:#F0B755;padding:5px 10px;margin:2px 0;border-radius:4px;font-family:monospace;font-size:12px"><span style="color:#94A3B8;margin-right:8px">L{lineno}</span>{line.strip()[:160]}{kw_badges}</div>'
    img_html = ""
    for name, img in rec.get("images", []):
        thumb = img.copy(); thumb.thumbnail((280, 200))
        buf = io.BytesIO(); thumb.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        img_html += f'<div style="display:inline-block;margin:6px;text-align:center"><img src="data:image/png;base64,{b64}" style="border-radius:6px;border:1px solid #ddd"><br><small style="color:#666">{name}</small></div>'
    sev_color = SEVERITY_COLORS.get(rec.get("severity","中"), ("#E0A93A","#FEF3C7"))
    html = f"""<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="UTF-8">
<title>Issue #{rec['id']} 報告</title>
<style>
  body{{font-family:-apple-system,'PingFang TC',sans-serif;background:#F5F6F8;color:#2C3A4A;margin:0;padding:24px}}
  .card{{background:#fff;border-radius:12px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:15px;margin:0 0 12px;color:#D9623A}}
  table{{width:100%;border-collapse:collapse}} th{{background:#2D3A4A;color:#fff;padding:8px 10px;text-align:left;font-size:13px}}
  .badge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600}}
</style></head><body>
<div class="card">
  <h1>⚑ Issue #{rec['id']} 報案報告</h1>
  <div style="color:#888;font-size:13px">{rec['time']} &nbsp;｜&nbsp; {rec.get('golden_file','—')} vs {rec.get('issue_file','—')}</div>
  <div style="margin-top:8px">
    <span class="badge" style="background:{sev_color[1]};color:{sev_color[0]}">嚴重度：{rec.get('severity','中')}</span>
    {''.join(f'<span class="badge" style="background:#EDE9FE;color:#7C3AED;margin-left:6px">{t}</span>' for t in rec.get('tags',[]))}
  </div>
</div>
<div class="card"><h2>RCP 欄位比對</h2>
  <table><tr><th></th><th>欄位</th><th>Golden</th><th>Issue</th></tr>{diff_html}</table>
</div>
<div class="card"><h2>Issue 描述</h2><p style="font-size:14px;line-height:1.7">{rec['desc']}</p></div>
{'<div class="card"><h2>Log TS 命中（' + str(len(rec.get("log_hits",[]))) + ' 筆）</h2>' + log_html + '</div>' if rec.get('log_hits') else ''}
{'<div class="card"><h2>截圖附件</h2>' + img_html + '</div>' if rec.get('images') else ''}
<div style="text-align:center;color:#aaa;font-size:12px;margin-top:16px">報案系統 v4.0 · 匯出時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
</body></html>"""
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    return fname

# ─── Scroll helper ────────────────────────────────────────────
def _make_scrollable(parent, bg):
    vsb    = ttk.Scrollbar(parent, orient="vertical")
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, yscrollcommand=vsb.set)
    vsb.configure(command=canvas.yview)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner  = tk.Frame(canvas, bg=bg)
    wid    = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
    def _mw(e):
        if e.delta > 0 and canvas.yview()[0] <= 0: return
        canvas.yview_scroll(int(-1*(e.delta/120)), "units")
    canvas.bind("<MouseWheel>", _mw)
    inner.bind("<MouseWheel>", _mw)
    return canvas, inner, vsb

# ═══════════════════════════════════════════════════════════════
class ReportApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("報案系統 v4.0 — RCP Issue Reporter")
        self.geometry("1520x920")
        self.minsize(1200, 750)
        self.configure(bg=BG_DARK)

        self.golden_data   = {}
        self.issue_data    = {}
        self.report_images = []
        self._photo_refs   = []
        self.issue_records = load_records()
        self.log_raw_text  = ""
        self.log_hits      = []
        self.log_filename  = ""
        self.log_t_start   = None
        self.log_t_end     = None
        self.log_in_range  = 0
        self.log_skipped   = 0
        self._log_scanning = False

        # 篩選狀態
        self._filter_text     = tk.StringVar()
        self._filter_severity = tk.StringVar(value="全部")
        self._sort_col        = "id"
        self._sort_asc        = False

        self._build_ui()
        self._bind_shortcuts()
        self.current_section = None
        self._nav_select("dashboard")
        if self.issue_records:
            self._update_badge()
            self._refresh_issue_list()

    # ── 鍵盤快捷鍵 ────────────────────────────────────────────
    def _bind_shortcuts(self):
        self.bind("<Control-r>", lambda e: self._run_compare())
        self.bind("<Control-l>", lambda e: self._pick_log_file())
        self.bind("<Control-Return>", lambda e: self._submit_report())
        self.bind("<Control-e>", lambda e: self._export_selected())
        self.bind("<F1>", lambda e: self._nav_select("dashboard"))
        self.bind("<F2>", lambda e: self._nav_select("main"))
        self.bind("<F3>", lambda e: self._nav_select("tool_issue"))

    # ── Sidebar ────────────────────────────────────────────────
    def _build_ui(self):
        self.sidebar = tk.Frame(self, bg=BG_PANEL, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_f = tk.Frame(self.sidebar, bg=BG_PANEL, pady=18)
        logo_f.pack(fill="x")
        tk.Label(logo_f, text="⚑", font=("Arial", 24), bg=BG_PANEL, fg=ACCENT).pack()
        tk.Label(logo_f, text="報案系統", font=("Arial", 13, "bold"), bg=BG_PANEL, fg=TEXT_LIGHT).pack()
        tk.Label(logo_f, text="RCP Issue Reporter v4.0", font=("Arial", 7), bg=BG_PANEL, fg=TEXT_MUTED).pack(pady=(2,0))
        tk.Frame(self.sidebar, bg="#374D65", height=1).pack(fill="x", padx=16, pady=6)

        self.nav_buttons = {}
        self.issue_count_lbl = None
        for key, icon, label, shortcut in [
            ("dashboard",  "▦",  "儀表板",   "F1"),
            ("main",       "⊞",  "報案作業", "F2"),
            ("tool_issue", "☰",  "Tool Issue","F3"),
        ]:
            self.nav_buttons[key] = self._make_nav_btn(key, icon, label, shortcut)

        tk.Frame(self.sidebar, bg="#374D65", height=1).pack(fill="x", padx=16, pady=8)
        tk.Label(self.sidebar, text="快捷鍵", font=("Arial", 8, "bold"), bg=BG_PANEL, fg=TEXT_MUTED).pack(anchor="w", padx=16)
        for txt in ["Ctrl+R  開始比對", "Ctrl+L  選 Log", "Ctrl+↵  提交報案", "Ctrl+E  匯出報告"]:
            tk.Label(self.sidebar, text=txt, font=("Arial", 7), bg=BG_PANEL, fg="#3D5270").pack(anchor="w", padx=20, pady=1)

        tk.Label(self.sidebar, text="v4.0.0", font=("Arial", 8), bg=BG_PANEL, fg="#3D5270").pack(side="bottom", pady=10)

        self.content = tk.Frame(self, bg=BG_LIGHT)
        self.content.pack(side="left", fill="both", expand=True)

        self.pages = {}
        self.pages["dashboard"]  = self._build_dashboard_page()
        self.pages["main"]       = self._build_main_page()
        self.pages["tool_issue"] = self._build_tool_issue_page()

    def _make_nav_btn(self, key, icon, label, shortcut=""):
        frame = tk.Frame(self.sidebar, bg=BG_PANEL, cursor="hand2")
        frame.pack(fill="x", padx=10, pady=2)
        icon_l = tk.Label(frame, text=icon, font=("Arial", 13), bg=BG_PANEL, fg=TEXT_MUTED, width=2, anchor="w")
        icon_l.pack(side="left", padx=(10, 5), pady=10)
        text_l = tk.Label(frame, text=label, font=("Arial", 11), bg=BG_PANEL, fg=TEXT_MUTED, anchor="w")
        text_l.pack(side="left", pady=10)
        if shortcut:
            tk.Label(frame, text=shortcut, font=("Arial", 7), bg=BG_PANEL, fg="#3D5270").pack(side="right", padx=6)
        frame._icon = icon_l
        frame._text = text_l
        frame._badge = None
        if key == "tool_issue":
            badge = tk.Label(frame, text="0", font=("Arial", 8, "bold"), bg="#374D65", fg=TEXT_MUTED, padx=5, pady=1)
            badge.pack(side="right", padx=(0, 30))
            frame._badge = badge
            self.issue_count_lbl = badge
        for w in (frame, icon_l, text_l):
            w.bind("<Button-1>", lambda e, k=key: self._nav_select(k))
            w.bind("<Enter>",    lambda e, f=frame: self._nav_hover(f, True))
            w.bind("<Leave>",    lambda e, f=frame: self._nav_hover(f, False))
        return frame

    def _nav_hover(self, frame, hover):
        if frame == self.nav_buttons.get(self.current_section): return
        c = "#243552" if hover else BG_PANEL
        frame.configure(bg=c); frame._icon.configure(bg=c); frame._text.configure(bg=c)
        if frame._badge: frame._badge.configure(bg=c)

    def _nav_select(self, key):
        if self.current_section and self.current_section in self.nav_buttons:
            old = self.nav_buttons[self.current_section]
            old.configure(bg=BG_PANEL); old._icon.configure(bg=BG_PANEL, fg=TEXT_MUTED); old._text.configure(bg=BG_PANEL, fg=TEXT_MUTED)
            if old._badge: old._badge.configure(bg=BG_PANEL)
            if self.current_section in self.pages: self.pages[self.current_section].pack_forget()
        self.current_section = key
        btn = self.nav_buttons[key]
        btn.configure(bg=ACCENT); btn._icon.configure(bg=ACCENT, fg=TEXT_LIGHT); btn._text.configure(bg=ACCENT, fg=TEXT_LIGHT)
        if btn._badge: btn._badge.configure(bg="#C0391B")
        self.pages[key].pack(fill="both", expand=True)
        if key == "dashboard": self._refresh_dashboard()

    def _update_badge(self):
        if self.issue_count_lbl:
            self.issue_count_lbl.configure(text=str(len(self.issue_records)))

    # ══════════════════════════════════════════════════════════
    # 儀表板
    # ══════════════════════════════════════════════════════════
    def _build_dashboard_page(self):
        page = tk.Frame(self.content, bg=BG_LIGHT)
        hdr = tk.Frame(page, bg=BG_DARK, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="▦  儀表板", font=("Arial", 15, "bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=24, pady=14)
        tk.Label(hdr, text="Issue 統計總覽", font=("Arial", 10), bg=BG_DARK, fg=TEXT_MUTED).pack(side="left", padx=4)

        canvas, inner, _ = _make_scrollable(page, BG_LIGHT)

        # 統計卡片列
        self._dash_cards_frame = tk.Frame(inner, bg=BG_LIGHT)
        self._dash_cards_frame.pack(fill="x", padx=20, pady=(16,8))

        # 嚴重度分布
        sev_outer = tk.Frame(inner, bg=BG_LIGHT)
        sev_outer.pack(fill="x", padx=20, pady=8)
        tk.Frame(sev_outer, bg=ACCENT, width=3).pack(side="left", fill="y", padx=(0,8))
        tk.Label(sev_outer, text="嚴重度分布", font=("Arial", 11, "bold"), bg=BG_LIGHT, fg=TEXT_DARK).pack(side="left")
        self._dash_sev_frame = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        self._dash_sev_frame.pack(fill="x", padx=20, pady=(0,12))

        # 關鍵字 Top 10
        kw_outer = tk.Frame(inner, bg=BG_LIGHT)
        kw_outer.pack(fill="x", padx=20, pady=8)
        tk.Frame(kw_outer, bg=ACCENT, width=3).pack(side="left", fill="y", padx=(0,8))
        tk.Label(kw_outer, text="Log 關鍵字命中排行", font=("Arial", 11, "bold"), bg=BG_LIGHT, fg=TEXT_DARK).pack(side="left")
        self._dash_kw_frame = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        self._dash_kw_frame.pack(fill="x", padx=20, pady=(0,12))

        # 最近 5 筆
        rec_outer = tk.Frame(inner, bg=BG_LIGHT)
        rec_outer.pack(fill="x", padx=20, pady=8)
        tk.Frame(rec_outer, bg=ACCENT, width=3).pack(side="left", fill="y", padx=(0,8))
        tk.Label(rec_outer, text="最近報案", font=("Arial", 11, "bold"), bg=BG_LIGHT, fg=TEXT_DARK).pack(side="left")
        self._dash_recent_frame = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        self._dash_recent_frame.pack(fill="x", padx=20, pady=(0,20))

        return page

    def _refresh_dashboard(self):
        # 統計卡片
        for w in self._dash_cards_frame.winfo_children(): w.destroy()
        total   = len(self.issue_records)
        n_high  = sum(1 for r in self.issue_records if r.get("severity") in ("高","嚴重"))
        n_kwhit = sum(len(r.get("log_hits",[])) for r in self.issue_records)
        n_img   = sum(len(r.get("images",[])) for r in self.issue_records)
        for i, (val, lbl, color) in enumerate([
            (str(total),   "總 Issue 數",    INFO),
            (str(n_high),  "高/嚴重等級",    DANGER),
            (str(n_kwhit), "Log 命中總數",   WARNING),
            (str(n_img),   "附件圖片總數",   SUCCESS),
        ]):
            card = tk.Frame(self._dash_cards_frame, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=0, column=i, sticky="nsew", padx=(0,10) if i<3 else 0)
            self._dash_cards_frame.columnconfigure(i, weight=1)
            tk.Frame(card, bg=color, height=3).pack(fill="x")
            tk.Label(card, text=val, font=("Arial", 28, "bold"), bg=BG_CARD, fg=color).pack(pady=(12,2))
            tk.Label(card, text=lbl, font=("Arial", 10), bg=BG_CARD, fg=TEXT_MID).pack(pady=(0,12))

        # 嚴重度分布橫條
        for w in self._dash_sev_frame.winfo_children(): w.destroy()
        sev_count = {"低":0,"中":0,"高":0,"嚴重":0}
        for r in self.issue_records:
            sev = r.get("severity","中")
            if sev in sev_count: sev_count[sev] += 1
        max_c = max(sev_count.values(), default=1) or 1
        for sev, cnt in sev_count.items():
            fg, bg_c = SEVERITY_COLORS[sev]
            row = tk.Frame(self._dash_sev_frame, bg=BG_CARD)
            row.pack(fill="x", padx=16, pady=6)
            tk.Label(row, text=sev, font=("Arial", 10, "bold"), bg=BG_CARD, fg=fg, width=4, anchor="w").pack(side="left")
            bar_bg = tk.Frame(row, bg=BORDER, height=18)
            bar_bg.pack(side="left", fill="x", expand=True, padx=10)
            bar_bg.update_idletasks()
            bar_w = int(bar_bg.winfo_reqwidth() * cnt / max_c) or 0
            tk.Frame(bar_bg, bg=fg, height=18, width=bar_w).place(x=0, y=0)
            tk.Label(row, text=str(cnt), font=("Arial", 10, "bold"), bg=BG_CARD, fg=fg, width=3, anchor="e").pack(side="left")

        # 關鍵字排行
        for w in self._dash_kw_frame.winfo_children(): w.destroy()
        kw_freq = {}
        for r in self.issue_records:
            for kw in r.get("log_keywords", []):
                kw_freq[kw] = kw_freq.get(kw, 0) + 1
        top10 = sorted(kw_freq.items(), key=lambda x: -x[1])[:10]
        if not top10:
            tk.Label(self._dash_kw_frame, text="尚無 Log 命中資料", font=("Arial", 10), bg=BG_CARD, fg=TEXT_MUTED, pady=20).pack()
        else:
            max_f = top10[0][1] or 1
            for kw, freq in top10:
                row = tk.Frame(self._dash_kw_frame, bg=BG_CARD)
                row.pack(fill="x", padx=16, pady=4)
                tk.Label(row, text=kw, font=("Courier", 9, "bold"), bg=KW_TAG_BG, fg=TEXT_LIGHT, padx=5, pady=1, width=14, anchor="w").pack(side="left")
                bar_bg = tk.Frame(row, bg=BORDER, height=14)
                bar_bg.pack(side="left", fill="x", expand=True, padx=10)
                bar_bg.update_idletasks()
                bar_w = int(200 * freq / max_f)
                tk.Frame(bar_bg, bg=KW_TAG_BG, height=14, width=bar_w).place(x=0, y=0)
                tk.Label(row, text=str(freq), font=("Arial", 9), bg=BG_CARD, fg=TEXT_MID, width=3, anchor="e").pack(side="left")

        # 最近報案
        for w in self._dash_recent_frame.winfo_children(): w.destroy()
        recent = list(reversed(self.issue_records))[:5]
        if not recent:
            tk.Label(self._dash_recent_frame, text="尚無報案紀錄", font=("Arial", 10), bg=BG_CARD, fg=TEXT_MUTED, pady=20).pack()
        else:
            for rec in recent:
                sev = rec.get("severity","中")
                fg, bg_c = SEVERITY_COLORS[sev]
                row = tk.Frame(self._dash_recent_frame, bg=BG_CARD)
                row.pack(fill="x", padx=12, pady=5)
                tk.Label(row, text=f"#{rec['id']}", font=("Arial", 10, "bold"), bg=BG_CARD, fg=INFO, width=4, anchor="w").pack(side="left")
                tk.Label(row, text=rec['time'], font=("Arial", 9), bg=BG_CARD, fg=TEXT_MID, width=15, anchor="w").pack(side="left")
                tk.Label(row, text=sev, font=("Arial", 8, "bold"), bg=bg_c, fg=fg, padx=6, pady=1).pack(side="left", padx=6)
                desc_short = rec['desc'][:50] + ("…" if len(rec['desc'])>50 else "")
                tk.Label(row, text=desc_short, font=("Arial", 9), bg=BG_CARD, fg=TEXT_DARK, anchor="w").pack(side="left", fill="x", expand=True)
                tk.Button(row, text="詳情", font=("Arial", 8), bg=BG_LIGHT, fg=INFO, relief="flat",
                          padx=8, pady=2, cursor="hand2",
                          command=lambda r=rec: self._show_issue_detail(r)).pack(side="right", padx=4)
                tk.Frame(self._dash_recent_frame, bg=BORDER, height=1).pack(fill="x", padx=12)

    # ══════════════════════════════════════════════════════════
    # 報案作業頁
    # ══════════════════════════════════════════════════════════
    def _build_main_page(self):
        page = tk.Frame(self.content, bg=BG_LIGHT)
        hdr = tk.Frame(page, bg=BG_DARK, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="報案作業", font=("Arial", 15, "bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=24, pady=14)
        tk.Label(hdr, text="RCP 比對 ＋ 報案資訊　｜　Auto Log TS", font=("Arial", 10), bg=BG_DARK, fg=TEXT_MUTED).pack(side="left", padx=4)

        body = tk.Frame(page, bg=BG_LIGHT)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)

        left_col  = self._build_left_column(body)
        right_col = self._build_log_panel(body)
        left_col.grid(row=0, column=0, sticky="nsew")
        tk.Frame(body, bg=BORDER, width=1).grid(row=0, column=0, sticky="nse")
        right_col.grid(row=0, column=1, sticky="nsew")
        return page

    # ── 左欄：RCP比對 + 報案資訊 ──────────────────────────────
    def _build_left_column(self, parent):
        col = tk.Frame(parent, bg=BG_LIGHT)
        col.rowconfigure(0, weight=3)
        col.rowconfigure(1, weight=2)
        col.columnconfigure(0, weight=1)
        self._build_compare_panel(col).grid(row=0, column=0, sticky="nsew")
        tk.Frame(col, bg=BORDER, height=1).grid(row=0, column=0, sticky="sew")
        self._build_screenshot_panel(col).grid(row=1, column=0, sticky="nsew")
        return col

    def _build_compare_panel(self, parent):
        panel = tk.Frame(parent, bg=BG_LIGHT)
        shdr = tk.Frame(panel, bg=SH_COMPARE, height=38)
        shdr.pack(fill="x"); shdr.pack_propagate(False)
        tk.Label(shdr, text="⊞  RCP 比對", font=("Arial", 11, "bold"), bg=SH_COMPARE, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=8)

        canvas = tk.Canvas(panel, bg=BG_LIGHT, highlightthickness=0)
        vsb = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG_LIGHT)
        wid = canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        pad = 12
        cards_row = tk.Frame(inner, bg=BG_LIGHT)
        cards_row.pack(fill="x", padx=pad, pady=(10,6))
        cards_row.columnconfigure(0, weight=1); cards_row.columnconfigure(1, weight=1)
        self.golden_card = self._build_rcp_card(cards_row, "GOLDEN RCP", "基準", SUCCESS, 0)
        self.issue_card  = self._build_rcp_card(cards_row, "ISSUE RCP",  "問題", ACCENT,  1)

        btn_row = tk.Frame(inner, bg=BG_LIGHT)
        btn_row.pack(fill="x", padx=pad, pady=(2,6))
        tk.Button(btn_row, text="▶ 開始比對  Ctrl+R",
                  font=("Arial", 9, "bold"), bg=BG_DARK, fg=TEXT_LIGHT,
                  relief="flat", padx=16, pady=6, cursor="hand2",
                  activebackground=ACCENT, activeforeground=TEXT_LIGHT,
                  command=self._run_compare).pack(side="left")
        tk.Button(btn_row, text="並排 Diff ↗",
                  font=("Arial", 8), bg="#354A61", fg=TEXT_LIGHT,
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._show_side_by_side_diff).pack(side="left", padx=6)
        self.compare_status = tk.Label(btn_row, text="", font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MID)
        self.compare_status.pack(side="left", padx=8)
        leg = tk.Frame(btn_row, bg=BG_LIGHT)
        leg.pack(side="right")
        for dot_c, txt in [(DOT_GREEN,"一致"),(DOT_YELLOW,"不一致")]:
            lf = tk.Frame(leg, bg=BG_LIGHT); lf.pack(side="left", padx=4)
            tk.Label(lf, text="●", font=("Arial", 9), bg=BG_LIGHT, fg=dot_c).pack(side="left")
            tk.Label(lf, text=txt, font=("Arial", 7), bg=BG_LIGHT, fg=TEXT_MID).pack(side="left")

        diff_hdr = tk.Frame(inner, bg=BG_DARK)
        diff_hdr.pack(fill="x", padx=pad)
        tk.Label(diff_hdr, text="", bg=BG_DARK, width=2, padx=4, pady=5).pack(side="left")
        for txt, w in [("欄位",14),("Golden",18),("Issue",18)]:
            tk.Label(diff_hdr, text=txt, font=("Arial", 8, "bold"),
                     bg=BG_DARK, fg=TEXT_LIGHT, anchor="w", width=w, padx=6, pady=5).pack(side="left")

        self.diff_frame = tk.Frame(inner, bg=BG_LIGHT)
        self.diff_frame.pack(fill="x", padx=pad, pady=(0,10))
        tk.Label(self.diff_frame, text="載入兩個 RCP 後點選「開始比對」",
                 font=("Arial", 9), bg=BG_LIGHT, fg=TEXT_MUTED, pady=18).pack()
        return panel

    def _build_rcp_card(self, parent, title, subtitle, color, col):
        card = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=(0,5) if col==0 else (5,0))
        tk.Frame(card, bg=color, height=3).pack(fill="x")
        inner = tk.Frame(card, bg=BG_CARD, padx=10, pady=8)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, font=("Arial", 10, "bold"), bg=BG_CARD, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(inner, text=subtitle, font=("Arial", 7), bg=BG_CARD, fg=TEXT_MUTED).pack(anchor="w", pady=(1,5))
        file_var = tk.StringVar(value="尚未選擇")
        row = tk.Frame(inner, bg=BG_CARD); row.pack(fill="x")
        tk.Label(row, textvariable=file_var, font=("Arial", 7), bg=BG_INPUT, fg=TEXT_MID, anchor="w",
                 padx=5, pady=3, width=14).pack(side="left", fill="x", expand=True)
        tag = "golden" if col==0 else "issue"
        tk.Button(row, text="選擇", font=("Arial", 7, "bold"),
                  bg=color, fg=TEXT_LIGHT if color!=SUCCESS else "#0D4A2E",
                  relief="flat", padx=6, pady=3, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=lambda c=None, t=tag: self._pick_rcp_file(card, t)).pack(side="left", padx=(3,0))
        preview = scrolledtext.ScrolledText(
            inner, height=5, font=("Courier", 7), bg=BG_INPUT, fg=TEXT_DARK,
            relief="flat", wrap="word", state="disabled", highlightthickness=0, borderwidth=0)
        preview.pack(fill="x", pady=(5,0))
        card._file_var = file_var; card._data = {}; card._preview = preview; card._raw = ""
        return card

    def _pick_rcp_file(self, card, tag):
        path = filedialog.askopenfilename(title=f"選擇 {tag.upper()} RCP 檔案",
                                          filetypes=[("文字檔案","*.txt"),("所有檔案","*.*")])
        if not path: return
        try:    raw = open(path, "r", encoding="utf-8-sig").read()
        except: raw = open(path, "r", encoding="big5", errors="replace").read()
        card._raw  = raw
        card._data = parse_rcp_text(raw)
        card._file_var.set(os.path.basename(path))
        card._preview.configure(state="normal")
        card._preview.delete("1.0", "end")
        for f in RCP_FIELDS:
            card._preview.insert("end", f"{f}:\n  {card._data.get(f) or '（未找到）'}\n\n")
        card._preview.configure(state="disabled")
        if tag == "golden": self.golden_data = card._data
        else:               self.issue_data  = card._data

    def _run_compare(self):
        if not self.golden_data and not self.issue_data:
            messagebox.showwarning("提示", "請先載入至少一個 RCP 檔案。"); return
        rows = diff_dicts(self.golden_data, self.issue_data)
        for w in self.diff_frame.winfo_children(): w.destroy()
        active  = [r for r in rows if r[3] != "empty"]
        n_match = sum(1 for r in active if r[3]=="match")
        n_miss  = sum(1 for r in active if r[3]=="mismatch")
        self.compare_status.configure(text=f"● {n_match} 一致　● {n_miss} 不一致",
                                       fg=ACCENT if n_miss else DOT_GREEN)
        for i, (key, g_val, i_val, status) in enumerate(rows):
            bg = BG_CARD if i%2==0 else BG_LIGHT
            if status=="match":    dot_c,g_fg,i_fg = DOT_GREEN,TEXT_DARK,TEXT_DARK
            elif status=="mismatch": dot_c,g_fg,i_fg,bg = DOT_YELLOW,TEXT_DARK,"#B45309",DIFF_DEL
            elif status in ("only_issue","only_golden"): dot_c,g_fg,i_fg = DOT_YELLOW,TEXT_MUTED,TEXT_MUTED
            else: dot_c,g_fg,i_fg = TEXT_MUTED,TEXT_MUTED,TEXT_MUTED
            rf = tk.Frame(self.diff_frame, bg=bg); rf.pack(fill="x")
            tk.Label(rf, text="●", font=("Arial",10), bg=bg, fg=dot_c, padx=4, pady=6).pack(side="left")
            tk.Label(rf, text=key, font=("Arial",8,"bold"), bg=bg, fg=TEXT_DARK, anchor="w", width=14, padx=3, pady=6).pack(side="left")
            tk.Frame(rf, bg=BORDER, width=1).pack(side="left", fill="y", padx=1)
            tk.Label(rf, text=g_val or "—", font=("Courier",8), bg=bg, fg=g_fg, anchor="w", width=18, padx=5, pady=6, wraplength=130).pack(side="left")
            tk.Frame(rf, bg=BORDER, width=1).pack(side="left", fill="y", padx=1)
            tk.Label(rf, text=i_val or "—", font=("Courier",8), bg=bg, fg=i_fg, anchor="w", width=18, padx=5, pady=6, wraplength=130).pack(side="left")
            tk.Frame(self.diff_frame, bg=BORDER, height=1).pack(fill="x")

    # ── 並排 Diff 視窗 ────────────────────────────────────────
    def _show_side_by_side_diff(self):
        g_raw = getattr(self.golden_card, "_raw", "")
        i_raw = getattr(self.issue_card,  "_raw", "")
        if not g_raw and not i_raw:
            messagebox.showinfo("提示", "請先載入 RCP 檔案。"); return
        win = tk.Toplevel(self)
        win.title("並排 Diff — Golden vs Issue")
        win.geometry("1100x720")
        win.configure(bg=BG_DARK)
        hdr = tk.Frame(win, bg=BG_DARK)
        hdr.pack(fill="x")
        tk.Label(hdr, text="並排 RCP 文字比較", font=("Arial",13,"bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=20, pady=10)
        tk.Label(hdr, text="黃色 = 僅本側有此行  ｜  紅色 = 兩側行不一致", font=("Arial",9), bg=BG_DARK, fg=TEXT_MUTED).pack(side="left", padx=4)
        tk.Button(hdr, text="關閉", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT, relief="flat",
                  padx=12, pady=5, command=win.destroy).pack(side="right", padx=16, pady=8)

        pane = tk.PanedWindow(win, orient="horizontal", bg=BG_DARK, sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=8, pady=8)

        g_lines = (g_raw or "").splitlines()
        i_lines = (i_raw or "").splitlines()
        max_len = max(len(g_lines), len(i_lines))
        g_lines += [""] * (max_len - len(g_lines))
        i_lines += [""] * (max_len - len(i_lines))

        def _make_diff_pane(title, lines, other_lines, color):
            f = tk.Frame(pane, bg=BG_DARK)
            tk.Label(f, text=title, font=("Arial",10,"bold"), bg=color, fg=TEXT_LIGHT, pady=6).pack(fill="x")
            txt = scrolledtext.ScrolledText(f, font=("Courier",9), bg=LOG_BG, fg=LOG_FG,
                                             relief="flat", wrap="none", padx=8, pady=6, state="normal")
            txt.pack(fill="both", expand=True)
            txt.tag_configure("diff",   background="#3B2A1A", foreground="#F0B755")
            txt.tag_configure("add",    background="#1A3020", foreground="#86EFAC")
            txt.tag_configure("empty",  background="#1A2030", foreground="#475569")
            for ln, (line, other) in enumerate(zip(lines, other_lines), 1):
                prefix = f"{ln:4d} │ "
                if line == other:   tag = ""
                elif line == "":    tag = "empty"
                elif other == "":   tag = "add"
                else:               tag = "diff"
                txt.insert("end", prefix + line + "\n", tag)
            txt.configure(state="disabled")
            return f

        g_pane = _make_diff_pane(f"GOLDEN: {self.golden_card._file_var.get()}", g_lines, i_lines, SH_COMPARE)
        i_pane = _make_diff_pane(f"ISSUE:  {self.issue_card._file_var.get()}",  i_lines, g_lines, "#4A3028")
        pane.add(g_pane); pane.add(i_pane)

    # ── 報案資訊 panel ────────────────────────────────────────
    def _build_screenshot_panel(self, parent):
        panel = tk.Frame(parent, bg=BG_LIGHT)
        shdr = tk.Frame(panel, bg=SH_REPORT, height=34)
        shdr.pack(fill="x"); shdr.pack_propagate(False)
        tk.Label(shdr, text="✎  報案資訊", font=("Arial", 10, "bold"), bg=SH_REPORT, fg=TEXT_LIGHT).pack(side="left", padx=14, pady=7)

        canvas = tk.Canvas(panel, bg=BG_LIGHT, highlightthickness=0)
        vsb = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG_LIGHT)
        wid = canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        pad = 12
        # 嚴重度 + 標籤
        meta_card = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        meta_card.pack(fill="x", padx=pad, pady=(10,6))
        mi = tk.Frame(meta_card, bg=BG_CARD, padx=10, pady=8); mi.pack(fill="x")
        tk.Label(mi, text="嚴重度", font=("Arial", 8), bg=BG_CARD, fg=TEXT_MID).pack(anchor="w")
        sev_row = tk.Frame(mi, bg=BG_CARD); sev_row.pack(fill="x", pady=(4,6))
        self._sev_var = tk.StringVar(value="中")
        for sev in ("低","中","高","嚴重"):
            fg, bg_c = SEVERITY_COLORS[sev]
            rb = tk.Radiobutton(sev_row, text=sev, variable=self._sev_var, value=sev,
                                font=("Arial", 9, "bold"), bg=BG_CARD, fg=fg,
                                selectcolor=bg_c, activebackground=BG_CARD,
                                relief="flat", cursor="hand2", indicatoron=0,
                                padx=8, pady=3)
            rb.pack(side="left", padx=(0,5))
        tk.Label(mi, text="標籤（逗號分隔）", font=("Arial", 8), bg=BG_CARD, fg=TEXT_MID).pack(anchor="w", pady=(4,2))
        self.tags_entry = tk.Entry(mi, font=("Arial", 9), bg=BG_INPUT, fg=TEXT_DARK, relief="flat",
                                   highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.tags_entry.pack(fill="x")
        self.tags_entry.insert(0, "例：Alarm, Process, Hardware")

        self._sec(inner, "Issue 描述", pad)
        desc_card = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        desc_card.pack(fill="x", padx=pad, pady=(0,8))
        di = tk.Frame(desc_card, bg=BG_CARD, padx=10, pady=8); di.pack(fill="x")
        tk.Label(di, text="詳細描述問題現象、發生時間、重現步驟：", font=("Arial", 8), bg=BG_CARD, fg=TEXT_MID).pack(anchor="w")
        self.desc_text = tk.Text(di, height=5, font=("Arial", 9), bg=BG_INPUT, fg=TEXT_DARK,
                                  relief="flat", wrap="word", padx=7, pady=5,
                                  highlightthickness=1, highlightcolor=ACCENT,
                                  highlightbackground=BORDER, insertbackground=ACCENT)
        self.desc_text.pack(fill="x", pady=(5,0))
        self.desc_text.insert("end", "例如：設備在測試時出現異常…")
        self.desc_text.bind("<FocusIn>", self._clear_placeholder)

        self._sec(inner, "附加截圖", pad)
        img_card = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        img_card.pack(fill="x", padx=pad, pady=(0,8))
        img_top = tk.Frame(img_card, bg=BG_CARD, padx=10, pady=7); img_top.pack(fill="x")
        tk.Button(img_top, text="＋ 上傳截圖", font=("Arial", 8, "bold"),
                  bg=ACCENT, fg=TEXT_LIGHT, relief="flat", padx=10, pady=4, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._upload_images).pack(side="left")
        self.img_count_lbl = tk.Label(img_top, text="尚未上傳", font=("Arial", 7), bg=BG_CARD, fg=TEXT_MUTED)
        self.img_count_lbl.pack(side="left", padx=6)
        tk.Button(img_top, text="清除", font=("Arial", 7), bg=BG_LIGHT, fg=TEXT_MID,
                  relief="flat", padx=6, pady=3, cursor="hand2",
                  command=self._clear_images).pack(side="right")
        self.img_grid = tk.Frame(img_card, bg=BG_CARD)
        self.img_grid.pack(fill="x", padx=10, pady=(0,8))

        sub_row = tk.Frame(inner, bg=BG_LIGHT)
        sub_row.pack(fill="x", padx=pad, pady=(6,14))
        tk.Button(sub_row, text="📋  提交報案  Ctrl+↵", font=("Arial", 10, "bold"),
                  bg=ACCENT, fg=TEXT_LIGHT, relief="flat", padx=24, pady=9, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._submit_report).pack(side="left")
        self.submit_status = tk.Label(sub_row, text="", font=("Arial", 8), bg=BG_LIGHT, fg=DOT_GREEN)
        self.submit_status.pack(side="left", padx=8)
        return panel

    def _sec(self, parent, text, padx):
        f = tk.Frame(parent, bg=BG_LIGHT); f.pack(fill="x", padx=padx, pady=(10,3))
        tk.Frame(f, bg=ACCENT, width=3).pack(side="left", fill="y", padx=(0,6))
        tk.Label(f, text=text, font=("Arial", 9, "bold"), bg=BG_LIGHT, fg=TEXT_DARK).pack(side="left")

    def _clear_placeholder(self, e):
        if self.desc_text.get("1.0","end-1c").startswith("例如："): self.desc_text.delete("1.0","end")

    # ── Log panel ─────────────────────────────────────────────
    def _build_log_panel(self, parent):
        panel = tk.Frame(parent, bg=BG_LIGHT)
        shdr = tk.Frame(panel, bg=SH_LOG, height=38)
        shdr.pack(fill="x"); shdr.pack_propagate(False)
        tk.Label(shdr, text="📋  Auto Log TS", font=("Arial", 11, "bold"), bg=SH_LOG, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=8)

        pick_row = tk.Frame(panel, bg=BG_LIGHT, pady=8)
        pick_row.pack(fill="x", padx=12)
        self.log_file_var = tk.StringVar(value="尚未選擇 Log 檔案")
        tk.Label(pick_row, textvariable=self.log_file_var, font=("Arial", 8),
                 bg=BG_INPUT, fg=TEXT_MID, anchor="w", padx=8, pady=4).pack(side="left", fill="x", expand=True)
        tk.Button(pick_row, text="選擇 Log  Ctrl+L", font=("Arial", 9, "bold"),
                  bg=SH_LOG, fg=TEXT_LIGHT, relief="flat", padx=12, pady=4, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._pick_log_file).pack(side="left", padx=(6,0))
        tk.Button(pick_row, text="清除", font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MID,
                  relief="flat", padx=6, pady=4, cursor="hand2",
                  command=self._clear_log).pack(side="left", padx=(4,0))

        self.log_status_var = tk.StringVar(value="")
        self.log_status_lbl = tk.Label(panel, textvariable=self.log_status_var,
                                        font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MUTED, anchor="w", padx=12)
        self.log_status_lbl.pack(fill="x")

        kw_outer = tk.Frame(panel, bg=BG_LIGHT)
        kw_outer.pack(fill="x", padx=12, pady=(2,4))
        kw_left = tk.Frame(kw_outer, bg=BG_LIGHT); kw_left.pack(side="left", fill="x", expand=True)
        tk.Label(kw_left, text="監控關鍵字：", font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MUTED).pack(side="left")
        self.kw_pills_frame = tk.Frame(kw_left, bg=BG_LIGHT); self.kw_pills_frame.pack(side="left", fill="x", expand=True)
        self._refresh_kw_pills()
        tk.Button(kw_outer, text="✏ 編輯關鍵字", font=("Arial", 7, "bold"),
                  bg="#354A61", fg=TEXT_LIGHT, relief="flat", padx=7, pady=3, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._open_keyword_editor).pack(side="right", padx=(6,0))

        hit_hdr = tk.Frame(panel, bg=BG_DARK, height=28)
        hit_hdr.pack(fill="x", padx=12); hit_hdr.pack_propagate(False)
        tk.Label(hit_hdr, text="偵測結果", font=("Arial", 8, "bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=8, pady=5)
        self.hit_count_lbl = tk.Label(hit_hdr, text="", font=("Arial", 8, "bold"), bg=BG_DARK, fg=WARNING)
        self.hit_count_lbl.pack(side="right", padx=8)

        _, self.log_hit_inner, _ = _make_scrollable(panel, LOG_BG)
        tk.Label(self.log_hit_inner, text="選擇 Log 檔案後自動掃描關鍵字",
                 font=("Arial", 9), bg=LOG_BG, fg="#475569", pady=30).pack()
        return panel

    def _refresh_kw_pills(self):
        for w in self.kw_pills_frame.winfo_children(): w.destroy()
        for kw in ISSUE_KEYWORDS[:8]:
            tk.Label(self.kw_pills_frame, text=kw, font=("Arial", 7),
                     bg="#DDE8F0", fg="#2C4A62", padx=5, pady=1).pack(side="left", padx=(0,3))
        if len(ISSUE_KEYWORDS) > 8:
            tk.Label(self.kw_pills_frame, text=f"+{len(ISSUE_KEYWORDS)-8}", font=("Arial", 7),
                     bg=BG_LIGHT, fg=TEXT_MUTED).pack(side="left")

    def _open_keyword_editor(self):
        editor = tk.Toplevel(self)
        editor.title("編輯關鍵字清單"); editor.geometry("480x520")
        editor.configure(bg=BG_LIGHT); editor.grab_set()
        hdr = tk.Frame(editor, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text="✏  Log TS 關鍵字清單", font=("Arial", 12, "bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=10)
        info = tk.Frame(editor, bg="#EDF3FA"); info.pack(fill="x")
        tk.Label(info, text="每行一個關鍵字　　# 開頭為註解\n儲存後下次選擇 Log 時自動生效",
                 font=("Arial", 8), bg="#EDF3FA", fg="#3A5A7A", anchor="w",
                 justify="left", padx=14, pady=6).pack(fill="x")
        txt_f = tk.Frame(editor, bg=BG_LIGHT); txt_f.pack(fill="both", expand=True, padx=14, pady=10)
        txt = scrolledtext.ScrolledText(txt_f, font=("Courier", 10), bg="#FAFBFC", fg=TEXT_DARK,
                                         relief="flat", wrap="none", padx=10, pady=8,
                                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                                         insertbackground=ACCENT)
        txt.pack(fill="both", expand=True)
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, "r", encoding="utf-8") as f: txt.insert("end", f.read())
        else:
            txt.insert("end", "# Log TS 關鍵字清單\n\n" + "\n".join(_DEFAULT_KEYWORDS) + "\n")
        btn_row = tk.Frame(editor, bg=BG_LIGHT); btn_row.pack(fill="x", padx=14, pady=(0,14))
        save_status = tk.Label(btn_row, text="", font=("Arial", 8), bg=BG_LIGHT, fg=DOT_GREEN)
        save_status.pack(side="right", padx=8)
        def _save():
            global ISSUE_KEYWORDS
            content = txt.get("1.0","end")
            try:
                with open(KEYWORDS_FILE, "w", encoding="utf-8") as f: f.write(content)
                ISSUE_KEYWORDS = load_keywords(); self._refresh_kw_pills()
                save_status.configure(text=f"✓ 已儲存　共 {len(ISSUE_KEYWORDS)} 個")
            except Exception as e: save_status.configure(text=f"❌ 失敗：{e}", fg="#F87171")
        tk.Button(btn_row, text="💾  儲存", font=("Arial", 10, "bold"),
                  bg=ACCENT, fg=TEXT_LIGHT, relief="flat", padx=18, pady=7, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT, command=_save).pack(side="left")
        tk.Button(btn_row, text="關閉", font=("Arial", 9), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=14, pady=7, cursor="hand2", command=editor.destroy).pack(side="left", padx=8)

    def _pick_log_file(self):
        path = filedialog.askopenfilename(title="選擇 Log 檔案",
                                          filetypes=[("Log","*.txt *.log"),("所有","*.*")])
        if not path: return
        self._log_set_loading(os.path.basename(path))
        scan_start_str = self.issue_data.get("RCP SCAN TIME","").strip()
        scan_end_str   = self.issue_data.get("SCAN END TIME","").strip()
        def _worker():
            try:
                global ISSUE_KEYWORDS; ISSUE_KEYWORDS = load_keywords()
                try:    raw = open(path,"r",encoding="utf-8-sig").read()
                except: raw = open(path,"r",encoding="big5",errors="replace").read()
                ref_year = datetime.now().year
                t_start = _parse_rcp_dt(scan_start_str, ref_year) if scan_start_str else None
                t_end   = _parse_rcp_dt(scan_end_str,   ref_year) if scan_end_str   else None
                hits, in_range, skipped = scan_log_keywords(raw, ISSUE_KEYWORDS, t_start, t_end)
            except Exception as e:
                self.after(0, lambda: self._log_set_error(str(e))); return
            self.after(0, lambda: self._log_scan_done(path, raw, hits, t_start, t_end, in_range, skipped))
        threading.Thread(target=_worker, daemon=True).start()

    def _log_set_loading(self, filename):
        self.log_file_var.set(filename)
        self.log_status_var.set("⏳ 掃描中，請稍候…")
        self.log_status_lbl.configure(fg=TEXT_MUTED)
        self.hit_count_lbl.configure(text="")
        for w in self.log_hit_inner.winfo_children(): w.destroy()
        tk.Label(self.log_hit_inner, text="⏳  正在讀取並掃描 Log…",
                 font=("Arial", 9), bg=LOG_BG, fg="#64748B", pady=30).pack()

    def _log_set_error(self, msg):
        self.log_status_var.set(f"❌ 讀取失敗：{msg}")
        self.log_status_lbl.configure(fg="#F87171")

    def _log_scan_done(self, path, raw, hits, t_start=None, t_end=None, in_range=0, skipped=0):
        self.log_raw_text = raw; self.log_filename = os.path.basename(path)
        self.log_hits = hits; self.log_t_start = t_start; self.log_t_end = t_end
        self.log_in_range = in_range; self.log_skipped = skipped
        self._render_log_hits()

    _BATCH = 25

    def _render_log_hits(self):
        for w in self.log_hit_inner.winfo_children(): w.destroy()
        total = self.log_raw_text.count("\n")+1
        n = len(self.log_hits)
        t_start = self.log_t_start; t_end = self.log_t_end; in_rng = self.log_in_range
        if n == 0:
            if t_start and t_end:
                rs = f"{t_start.strftime('%m/%d %H:%M:%S')} ~ {t_end.strftime('%m/%d %H:%M:%S')}"
                self.log_status_var.set(f"範圍 {rs}　共 {in_rng:,} 行　未發現 Issue 關鍵字 ✓")
            else:
                self.log_status_var.set(f"共 {total:,} 行 — 未發現 Issue 關鍵字 ✓")
            self.log_status_lbl.configure(fg=DOT_GREEN)
            self.hit_count_lbl.configure(text="")
            tk.Label(self.log_hit_inner, text="✓  未發現任何 Issue 關鍵字",
                     font=("Arial", 10), bg=LOG_BG, fg=DOT_GREEN, pady=30).pack()
            return
        if t_start and t_end:
            rs = f"{t_start.strftime('%m/%d %H:%M:%S')} ~ {t_end.strftime('%m/%d %H:%M:%S')}"
            self.log_status_var.set(f"範圍 {rs}　共 {in_rng:,} 行　發現 {n} 筆命中")
        else:
            self.log_status_var.set(f"共 {total:,} 行 — 發現 {n} 筆命中")
        self.log_status_lbl.configure(fg=WARNING)
        self.hit_count_lbl.configure(text=f"⚠ {n} 筆命中")
        self._log_progress_lbl = tk.Label(self.log_hit_inner, text=f"載入中… 0 / {n}",
                                           font=("Arial", 8), bg=LOG_BG, fg="#64748B")
        self._log_progress_lbl.pack(pady=(6,0))
        self._render_batch(list(self.log_hits), 0, n)

    def _render_batch(self, hits, offset, total):
        batch = hits[offset:offset+self._BATCH]
        if offset == 0 and hasattr(self,"_log_progress_lbl"):
            try: self._log_progress_lbl.destroy()
            except: pass
        for lineno, line, kws in batch:
            row = tk.Frame(self.log_hit_inner, bg="#1E2B3C",
                           highlightbackground="#2E3F55", highlightthickness=1)
            row.pack(fill="x", pady=1, padx=4)
            tk.Label(row, text=f"L{lineno}", font=("Courier",7,"bold"),
                     bg="#2A3D55", fg="#94A3B8", padx=6, pady=4).pack(side="left")
            kw_f = tk.Frame(row, bg="#1E2B3C"); kw_f.pack(side="right", padx=5, pady=3)
            for kw in kws:
                tk.Label(kw_f, text=kw, font=("Arial",7,"bold"),
                         bg=KW_TAG_BG, fg=TEXT_LIGHT, padx=4, pady=1).pack(side="left", padx=(0,2))
            tk.Label(row, text=line.strip()[:130], font=("Courier",8),
                     bg="#1E2B3C", fg=LOG_KW_FG, anchor="w", padx=8, pady=4,
                     wraplength=360).pack(side="left", fill="x", expand=True)
        next_offset = offset + self._BATCH
        if next_offset < total:
            prog = tk.Label(self.log_hit_inner, text=f"載入中… {next_offset} / {total}",
                            font=("Arial",7), bg=LOG_BG, fg="#475569")
            prog.pack()
            self.after(0, lambda p=prog: (p.destroy(), self._render_batch(hits, next_offset, total)))
        else:
            tk.Button(self.log_hit_inner, text="📄  查看完整 Log",
                      font=("Arial",8), bg="#1E2B3C", fg="#94A3B8", relief="flat",
                      padx=10, pady=5, cursor="hand2",
                      activebackground="#2A3D55", activeforeground=TEXT_LIGHT,
                      command=self._show_full_log).pack(pady=8)

    def _clear_log(self):
        self.log_raw_text=""; self.log_hits=[]; self.log_filename=""
        self.log_file_var.set("尚未選擇 Log 檔案"); self.log_status_var.set("")
        self.hit_count_lbl.configure(text="")
        for w in self.log_hit_inner.winfo_children(): w.destroy()
        tk.Label(self.log_hit_inner, text="選擇 Log 檔案後自動掃描關鍵字",
                 font=("Arial",9), bg=LOG_BG, fg="#475569", pady=30).pack()

    def _show_full_log(self):
        if not self.log_raw_text: return
        win = tk.Toplevel(self); win.title(f"完整 Log — {self.log_filename}")
        win.geometry("960x700"); win.configure(bg=LOG_BG)
        hdr = tk.Frame(win, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text=f"📄  {self.log_filename}", font=("Arial",12,"bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text=f"⚠ {len(self.log_hits)} 筆命中",
                 font=("Arial",9), bg=BG_DARK, fg=WARNING).pack(side="right", padx=16)
        prog_var = tk.StringVar(value="載入中…")
        prog_lbl = tk.Label(win, textvariable=prog_var, font=("Arial",8), bg=LOG_BG, fg="#64748B")
        prog_lbl.pack(anchor="w", padx=12, pady=(4,0))
        txt = scrolledtext.ScrolledText(win, font=("Courier",9), bg=LOG_BG, fg=LOG_FG,
                                         relief="flat", wrap="none", padx=12, pady=8,
                                         highlightthickness=0, state="disabled")
        txt.pack(fill="both", expand=True)
        txt.tag_configure("hit_line", background="#1B3050", foreground=LOG_KW_FG)
        txt.tag_configure("kw", foreground="#FB923C", font=("Courier",9,"bold"))
        tk.Button(win, text="關閉", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=14, pady=5, command=win.destroy).pack(pady=6)
        hit_linenos = {h[0] for h in self.log_hits}
        kw_pattern  = re.compile("|".join(re.escape(k) for k in ISSUE_KEYWORDS))
        all_lines   = self.log_raw_text.splitlines(); total_lines = len(all_lines); CHUNK = 500
        def _insert_chunk(start):
            txt.configure(state="normal")
            end = min(start+CHUNK, total_lines)
            for i in range(start, end):
                lineno = i+1; line = all_lines[i]
                if lineno in hit_linenos:
                    ls = txt.index("end")
                    txt.insert("end", line+"\n", "hit_line")
                    for m in kw_pattern.finditer(line):
                        txt.tag_add("kw", f"{ls}+{m.start()}c", f"{ls}+{m.end()}c")
                else: txt.insert("end", line+"\n")
            txt.configure(state="disabled")
            if end < total_lines:
                prog_var.set(f"載入中… {end:,} / {total_lines:,} 行")
                win.after(0, lambda: _insert_chunk(end))
            else:
                prog_lbl.destroy()
                if self.log_hits: txt.configure(state="normal"); txt.see(f"{self.log_hits[0][0]}.0"); txt.configure(state="disabled")
        win.after(50, lambda: _insert_chunk(0))

    # ── Image ─────────────────────────────────────────────────
    def _upload_images(self):
        paths = filedialog.askopenfilenames(title="選擇截圖",
                                            filetypes=[("圖片","*.png *.jpg *.jpeg *.bmp *.gif *.webp"),("所有","*.*")])
        for p in paths:
            try: self.report_images.append((os.path.basename(p), Image.open(p)))
            except Exception as ex: messagebox.showerror("錯誤", f"無法開啟 {p}：{ex}")
        self._refresh_img_grid()

    def _clear_images(self):
        self.report_images.clear(); self._photo_refs.clear(); self._refresh_img_grid()

    def _refresh_img_grid(self):
        for w in self.img_grid.winfo_children(): w.destroy()
        self._photo_refs.clear()
        if not self.report_images:
            self.img_count_lbl.configure(text="尚未上傳")
            tk.Label(self.img_grid, text="點選上方按鈕上傳截圖",
                     font=("Arial",8), bg=BG_CARD, fg=TEXT_MUTED, pady=10).pack(); return
        self.img_count_lbl.configure(text=f"已上傳 {len(self.report_images)} 張")
        for idx, (name, img) in enumerate(self.report_images):
            c, r = idx%3, idx//3
            cell = tk.Frame(self.img_grid, bg=BG_INPUT, highlightbackground=BORDER, highlightthickness=1)
            cell.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            self.img_grid.columnconfigure(c, weight=1)
            thumb = img.copy(); thumb.thumbnail((90,65))
            ph = ImageTk.PhotoImage(thumb); self._photo_refs.append(ph)
            tk.Label(cell, image=ph, bg=BG_INPUT).pack(pady=(5,1))
            tk.Label(cell, text=name[:12]+("…" if len(name)>12 else ""),
                     font=("Arial",6), bg=BG_INPUT, fg=TEXT_MID).pack(pady=(0,3))
            tk.Button(cell, text="✕", font=("Arial",6), bg=BG_INPUT, fg=ACCENT,
                      relief="flat", cursor="hand2", borderwidth=0,
                      command=lambda i=idx: self._remove_img(i)).place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)

    def _remove_img(self, idx):
        if 0 <= idx < len(self.report_images):
            self.report_images.pop(idx); self._refresh_img_grid()

    # ── Submit ────────────────────────────────────────────────
    def _submit_report(self):
        desc = self.desc_text.get("1.0","end-1c").strip()
        if not desc or desc.startswith("例如："):
            messagebox.showwarning("提示","請先輸入 Issue 描述。"); return
        tags_raw = self.tags_entry.get().strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip() and not t.strip().startswith("例")] if tags_raw else []
        hit_kws = list(dict.fromkeys(kw for _,_,kws in self.log_hits for kw in kws))
        record = {
            "id":           len(self.issue_records)+1,
            "time":         datetime.now().strftime("%Y-%m-%d %H:%M"),
            "desc":         desc,
            "severity":     self._sev_var.get(),
            "tags":         tags,
            "images":       list(self.report_images),
            "golden":       dict(self.golden_data),
            "issue":        dict(self.issue_data),
            "golden_file":  self.golden_card._file_var.get(),
            "issue_file":   self.issue_card._file_var.get(),
            "log_file":     self.log_filename,
            "log_hits":     list(self.log_hits),
            "log_keywords": hit_kws,
        }
        for field in RCP_FIELDS:
            record[field] = self.issue_data.get(field) or self.golden_data.get(field) or "—"
        self.issue_records.append(record)
        save_records(self.issue_records)
        self._refresh_issue_list()
        self._update_badge()
        self.report_images = []; self._photo_refs.clear()
        self._refresh_img_grid()
        self.desc_text.delete("1.0","end")
        self._sev_var.set("中")
        self.submit_status.configure(text=f"✓ 已提交 Issue #{record['id']}")
        self.after(600, lambda: self._nav_select("tool_issue"))

    # ══════════════════════════════════════════════════════════
    # Tool Issue 頁面 — 含搜尋/篩選/排序/匯出
    # ══════════════════════════════════════════════════════════
    def _build_tool_issue_page(self):
        page = tk.Frame(self.content, bg=BG_LIGHT)
        hdr = tk.Frame(page, bg=BG_DARK, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="Tool Issue", font=("Arial",15,"bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=24, pady=14)

        # 操作列
        toolbar = tk.Frame(page, bg="#EEF1F6", pady=8)
        toolbar.pack(fill="x", padx=12)

        # 搜尋框
        search_f = tk.Frame(toolbar, bg="#EEF1F6"); search_f.pack(side="left")
        tk.Label(search_f, text="🔍", font=("Arial",11), bg="#EEF1F6", fg=TEXT_MID).pack(side="left")
        search_entry = tk.Entry(search_f, textvariable=self._filter_text, font=("Arial",9),
                                 bg=BG_CARD, fg=TEXT_DARK, relief="flat", width=24,
                                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        search_entry.pack(side="left", padx=4, ipady=4)
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_issue_list())
        tk.Label(search_f, text="搜尋描述/Tool ID/LOT ID", font=("Arial",7), bg="#EEF1F6", fg=TEXT_MUTED).pack(side="left", padx=4)

        # 嚴重度篩選
        tk.Label(toolbar, text="嚴重度：", font=("Arial",9), bg="#EEF1F6", fg=TEXT_MID).pack(side="left", padx=(14,2))
        sev_cb = ttk.Combobox(toolbar, textvariable=self._filter_severity, width=6, state="readonly",
                               values=["全部","低","中","高","嚴重"])
        sev_cb.pack(side="left")
        sev_cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_issue_list())

        # 按鈕群
        tk.Button(toolbar, text="Ctrl+E  匯出選取", font=("Arial",8,"bold"),
                  bg=INFO, fg=TEXT_LIGHT, relief="flat", padx=10, pady=5, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._export_selected).pack(side="right", padx=4)
        tk.Button(toolbar, text="全選", font=("Arial",8),
                  bg=BG_LIGHT, fg=TEXT_MID, relief="flat", padx=8, pady=5, cursor="hand2",
                  command=self._select_all).pack(side="right", padx=2)
        tk.Button(toolbar, text="清除選取", font=("Arial",8),
                  bg=BG_LIGHT, fg=TEXT_MID, relief="flat", padx=8, pady=5, cursor="hand2",
                  command=self._clear_selection).pack(side="right", padx=2)

        self._col_defs = [
            ("",               3),("☐",             2),("#",             3),
            ("時間",           12),("嚴重度",          5),("Tool ID",      10),
            ("RCP NAME",       14),("LOT ID",          10),("RCP MODIFY TIME",16),
            ("RCP SCAN TIME",  14),("SCAN END TIME",   14),("Log TS",       0),("Issue 描述", 0),
        ]
        th = tk.Frame(page, bg=BG_DARK)
        th.pack(fill="x")
        for label, w in self._col_defs:
            kw = {"width": w} if w else {}
            tk.Label(th, text=label, font=("Arial",8,"bold"), bg=BG_DARK, fg=TEXT_LIGHT,
                     anchor="w", padx=6, pady=6, **kw).pack(
                         side="left", fill="x" if not w else None, expand=True if not w else False)

        _, self.issue_list_inner, _ = _make_scrollable(page, BG_LIGHT)
        self._selected_ids = set()
        self._show_empty_placeholder()
        return page

    def _show_empty_placeholder(self):
        tk.Label(self.issue_list_inner, text="尚無報案紀錄。完成報案後資料將顯示於此。",
                 font=("Arial",11), bg=BG_LIGHT, fg=TEXT_MUTED, pady=60).pack()

    def _filtered_records(self):
        q   = self._filter_text.get().lower()
        sev = self._filter_severity.get()
        out = []
        for r in self.issue_records:
            if sev != "全部" and r.get("severity","中") != sev: continue
            if q and not any(q in str(r.get(f,"")).lower() for f in ["desc","Tool ID","LOT ID","RCP NAME","time"]): continue
            out.append(r)
        # sort
        col = self._sort_col
        out.sort(key=lambda r: r.get(col, ""), reverse=not self._sort_asc)
        return out

    def _select_all(self):
        for r in self._filtered_records(): self._selected_ids.add(r["id"])
        self._refresh_issue_list()

    def _clear_selection(self):
        self._selected_ids.clear(); self._refresh_issue_list()

    def _export_selected(self):
        targets = [r for r in self.issue_records if r["id"] in self._selected_ids]
        if not targets:
            # export all filtered
            targets = self._filtered_records()
        if not targets:
            messagebox.showinfo("提示","無可匯出的資料。"); return
        exported = []
        for r in targets:
            try: exported.append(export_html(r))
            except Exception as e: messagebox.showerror("錯誤", f"匯出 #{r['id']} 失敗：{e}")
        if exported:
            msg = f"已匯出 {len(exported)} 份報告至：\n{EXPORTS_DIR}"
            if messagebox.askyesno("匯出完成", msg + "\n\n是否開啟資料夾？"):
                try: os.startfile(EXPORTS_DIR)
                except: webbrowser.open(f"file://{EXPORTS_DIR}")

    def _refresh_issue_list(self):
        for w in self.issue_list_inner.winfo_children(): w.destroy()
        records = self._filtered_records()
        if not records:
            self._show_empty_placeholder(); return

        for i, rec in enumerate(reversed(records)):
            bg = BG_CARD if i%2==0 else BG_LIGHT
            selected = rec["id"] in self._selected_ids
            if selected: bg = "#EFF6FF"
            row = tk.Frame(self.issue_list_inner, bg=bg)
            row.pack(fill="x")

            # 刪除
            tk.Button(row, text="🗑", font=("Arial",10), bg=bg, fg="#C0392B",
                      relief="flat", cursor="hand2", borderwidth=0,
                      activebackground=bg, activeforeground=ACCENT,
                      command=lambda rid=rec["id"]: self._delete_record(rid)).pack(side="left", padx=(6,1), pady=5)
            # 勾選
            chk_var = tk.BooleanVar(value=selected)
            chk = tk.Checkbutton(row, variable=chk_var, bg=bg, relief="flat",
                                  activebackground=bg, cursor="hand2",
                                  command=lambda v=chk_var, rid=rec["id"]: self._toggle_select(v, rid))
            chk.pack(side="left", padx=2)

            cd = self._col_defs
            sev = rec.get("severity","中")
            sev_fg, sev_bg = SEVERITY_COLORS.get(sev, (TEXT_MID, BG_INPUT))
            for txt, w, fg, font_str in [
                (f"#{rec['id']}",            cd[2][1],  TEXT_MUTED, "Arial 8"),
                (rec["time"],                cd[3][1],  TEXT_MID,   "Arial 8"),
            ]:
                tk.Label(row, text=txt or "—", font=font_str, bg=bg, fg=fg, anchor="w",
                         width=w, padx=6, pady=7).pack(side="left")
            # 嚴重度 badge
            tk.Label(row, text=sev, font=("Arial",7,"bold"), bg=sev_bg, fg=sev_fg,
                     padx=5, pady=2, width=cd[4][1]).pack(side="left", padx=4)
            for txt, w, fg, font_str in [
                (rec.get("Tool ID","—"),         cd[5][1],  TEXT_DARK,  "Courier 8"),
                (rec.get("RCP NAME","—"),         cd[6][1],  TEXT_DARK,  "Courier 8"),
                (rec.get("LOT ID","—"),           cd[7][1],  TEXT_DARK,  "Courier 8"),
                (rec.get("RCP MODIFY TIME","—"),  cd[8][1],  TEXT_DARK,  "Courier 8"),
                (rec.get("RCP SCAN TIME","—"),    cd[9][1],  TEXT_DARK,  "Courier 8"),
                (rec.get("SCAN END TIME","—"),    cd[10][1], TEXT_DARK,  "Courier 8"),
            ]:
                tk.Label(row, text=txt or "—", font=font_str, bg=bg, fg=fg, anchor="w",
                         width=w, padx=6, pady=7).pack(side="left")

            # Log TS pills
            log_cell = tk.Frame(row, bg=bg); log_cell.pack(side="left", fill="x", expand=True, padx=4)
            log_kws = rec.get("log_keywords",[])
            if log_kws:
                pf = tk.Frame(log_cell, bg=bg); pf.pack(side="left", pady=4)
                for kw in log_kws[:3]:
                    pill = tk.Label(pf, text=kw, font=("Arial",7,"bold"),
                                    bg=KW_TAG_BG, fg=TEXT_LIGHT, padx=4, pady=1, cursor="hand2")
                    pill.pack(side="left", padx=(0,3))
                    pill.bind("<Button-1>", lambda e, r=rec: self._show_log_detail(r))
                if len(log_kws)>3:
                    tk.Label(pf, text=f"+{len(log_kws)-3}", font=("Arial",7), bg=bg, fg=TEXT_MUTED).pack(side="left")
            else:
                tk.Label(log_cell, text="—", font=("Arial",8), bg=bg, fg=TEXT_MUTED, pady=7).pack(side="left")

            # 描述 + 標籤
            n_img = len(rec["images"])
            desc_short = rec["desc"][:35]+("…" if len(rec["desc"])>35 else "")
            desc_f = tk.Frame(row, bg=bg); desc_f.pack(side="left", fill="x", expand=True)
            tags = rec.get("tags",[])
            if tags:
                tag_f = tk.Frame(desc_f, bg=bg); tag_f.pack(anchor="w")
                for tag in tags[:3]:
                    tk.Label(tag_f, text=tag, font=("Arial",6), bg="#EDE9FE", fg="#7C3AED",
                             padx=4, pady=0).pack(side="left", padx=(0,2))
            desc_lbl = tk.Label(desc_f, text=desc_short+(f"  📷{n_img}" if n_img else ""),
                                 font=("Arial",8,"underline"), bg=bg, fg=INFO,
                                 anchor="w", padx=6, pady=3, cursor="hand2")
            desc_lbl.pack(side="left")
            desc_lbl.bind("<Button-1>", lambda e, r=rec: self._show_issue_detail(r))

            # 匯出按鈕
            tk.Button(row, text="⬇ HTML", font=("Arial",7,"bold"),
                      bg="#EFF6FF", fg=INFO, relief="flat", padx=6, pady=3, cursor="hand2",
                      command=lambda r=rec: self._export_one(r)).pack(side="right", padx=6)

            tk.Frame(self.issue_list_inner, bg=BORDER, height=1).pack(fill="x")

    def _toggle_select(self, var, rid):
        if var.get(): self._selected_ids.add(rid)
        else:         self._selected_ids.discard(rid)

    def _export_one(self, rec):
        try:
            path = export_html(rec)
            if messagebox.askyesno("匯出完成", f"已匯出 Issue #{rec['id']}\n{path}\n\n是否立即開啟？"):
                webbrowser.open(f"file://{path}")
        except Exception as e:
            messagebox.showerror("錯誤", str(e))

    def _delete_record(self, rec_id):
        if not messagebox.askyesno("確認刪除", f"確定要刪除 Issue #{rec_id} 嗎？"): return
        self.issue_records = [r for r in self.issue_records if r["id"] != rec_id]
        self._selected_ids.discard(rec_id)
        save_records(self.issue_records)
        self._update_badge(); self._refresh_issue_list()

    # ── Log detail popup ──────────────────────────────────────
    def _show_log_detail(self, rec):
        popup = tk.Toplevel(self)
        popup.title(f"Issue #{rec['id']} — Log TS 詳情")
        popup.geometry("860x600"); popup.configure(bg=LOG_BG); popup.grab_set()
        hdr = tk.Frame(popup, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text=f"📋  {rec.get('log_file','—')}", font=("Arial",12,"bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text=f"⚠ {len(rec.get('log_hits',[]))} 筆命中",
                 font=("Arial",9), bg=BG_DARK, fg=WARNING).pack(side="right", padx=16)
        if not rec.get("log_hits"):
            tk.Label(popup, text="此報案未包含 Log TS 資料。",
                     font=("Arial",11), bg=LOG_BG, fg="#475569", pady=40).pack()
            tk.Button(popup, text="關閉", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
                      relief="flat", padx=14, pady=5, command=popup.destroy).pack(pady=8); return
        kw_bar = tk.Frame(popup, bg="#1E293B"); kw_bar.pack(fill="x")
        tk.Label(kw_bar, text="命中關鍵字：", font=("Arial",8), bg="#1E293B", fg="#94A3B8",
                 padx=12, pady=6).pack(side="left")
        for kw in rec.get("log_keywords",[]):
            tk.Label(kw_bar, text=kw, font=("Arial",7,"bold"), bg=KW_TAG_BG, fg=TEXT_LIGHT,
                     padx=5, pady=2).pack(side="left", padx=(0,4))
        _, body, _ = _make_scrollable(popup, LOG_BG)
        for lineno, line, kws in rec["log_hits"]:
            row = tk.Frame(body, bg="#1E293B", highlightbackground="#334155", highlightthickness=1)
            row.pack(fill="x", pady=2, padx=8)
            tk.Label(row, text=f"L{lineno}", font=("Courier",7,"bold"),
                     bg="#334155", fg="#94A3B8", padx=5, pady=4).pack(side="left")
            kf = tk.Frame(row, bg="#1E293B"); kf.pack(side="right", padx=6, pady=3)
            for kw in kws:
                tk.Label(kf, text=kw, font=("Arial",7,"bold"), bg=KW_TAG_BG, fg=TEXT_LIGHT,
                         padx=4, pady=1).pack(side="left", padx=(0,2))
            tk.Label(row, text=line.strip()[:150], font=("Courier",8),
                     bg="#1E293B", fg=LOG_KW_FG, anchor="w",
                     padx=8, pady=4, wraplength=620).pack(side="left", fill="x", expand=True)
        tk.Button(popup, text="關閉", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=14, pady=5, command=popup.destroy).pack(pady=10)

    # ── Issue detail popup ────────────────────────────────────
    def _show_issue_detail(self, rec):
        popup = tk.Toplevel(self)
        popup.title(f"Issue #{rec['id']} 詳情")
        popup.geometry("840x700"); popup.configure(bg=BG_LIGHT); popup.grab_set()
        hdr = tk.Frame(popup, bg=BG_DARK); hdr.pack(fill="x")
        sev = rec.get("severity","中"); sev_fg, sev_bg = SEVERITY_COLORS.get(sev,(TEXT_MID,BG_INPUT))
        tk.Label(hdr, text=f"Issue #{rec['id']}  —  {rec['time']}",
                 font=("Arial",13,"bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=20, pady=12)
        tk.Label(hdr, text=sev, font=("Arial",10,"bold"), bg=sev_bg, fg=sev_fg,
                 padx=10, pady=4).pack(side="left", padx=8)
        tk.Button(hdr, text="⬇ 匯出 HTML", font=("Arial",9,"bold"),
                  bg=INFO, fg=TEXT_LIGHT, relief="flat", padx=14, pady=6, cursor="hand2",
                  command=lambda: self._export_one(rec)).pack(side="right", padx=16, pady=8)
        _, body, _ = _make_scrollable(popup, BG_LIGHT)
        pad = 20

        # 標籤列
        tags = rec.get("tags",[])
        if tags:
            tf = tk.Frame(body, bg=BG_LIGHT); tf.pack(fill="x", padx=pad, pady=(12,4))
            tk.Label(tf, text="標籤：", font=("Arial",9), bg=BG_LIGHT, fg=TEXT_MID).pack(side="left")
            for tag in tags:
                tk.Label(tf, text=tag, font=("Arial",9,"bold"), bg="#EDE9FE", fg="#7C3AED",
                         padx=8, pady=2).pack(side="left", padx=(0,6))

        self._popup_sec(body, "RCP 欄位比對", pad)
        tbl = tk.Frame(body, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        tbl.pack(fill="x", padx=pad, pady=(0,12))
        th = tk.Frame(tbl, bg=BG_DARK); th.pack(fill="x")
        tk.Label(th, text="", bg=BG_DARK, width=2, padx=4, pady=5).pack(side="left")
        for t,w in [("欄位",18),("Golden 值",22),("Issue 值",22)]:
            tk.Label(th, text=t, font=("Arial",9,"bold"), bg=BG_DARK, fg=TEXT_LIGHT,
                     anchor="w", width=w, padx=8, pady=5).pack(side="left")
        for j, (field, g_val, i_val, status) in enumerate(diff_dicts(rec["golden"], rec["issue"])):
            bg = BG_CARD if j%2==0 else BG_LIGHT
            dot_c = DOT_GREEN if status=="match" else (DOT_YELLOW if status=="mismatch" else TEXT_MUTED)
            i_fg  = "#B45309" if status=="mismatch" else TEXT_DARK
            if status=="mismatch": bg = DIFF_DEL
            rf = tk.Frame(tbl, bg=bg); rf.pack(fill="x")
            tk.Label(rf, text="●", font=("Arial",11), bg=bg, fg=dot_c, padx=6, pady=6).pack(side="left")
            tk.Label(rf, text=field, font=("Arial",9,"bold"), bg=bg, fg=TEXT_DARK, width=18, anchor="w", padx=4, pady=6).pack(side="left")
            tk.Frame(rf, bg=BORDER, width=1).pack(side="left", fill="y")
            tk.Label(rf, text=g_val or "—", font=("Courier",9), bg=bg, fg=TEXT_DARK, width=22, anchor="w", padx=8, pady=6).pack(side="left")
            tk.Frame(rf, bg=BORDER, width=1).pack(side="left", fill="y")
            tk.Label(rf, text=i_val or "—", font=("Courier",9), bg=bg, fg=i_fg, width=22, anchor="w", padx=8, pady=6).pack(side="left")
            tk.Frame(tbl, bg=BORDER, height=1).pack(fill="x")

        self._popup_sec(body, "Issue 描述", pad)
        desc_f = tk.Frame(body, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        desc_f.pack(fill="x", padx=pad, pady=(0,12))
        tk.Label(desc_f, text=rec["desc"], font=("Arial",10), bg=BG_CARD, fg=TEXT_DARK,
                 anchor="w", wraplength=740, justify="left", padx=14, pady=12).pack(fill="x")

        log_kws = rec.get("log_keywords",[])
        if log_kws:
            self._popup_sec(body, f"Log TS  ({rec.get('log_file','—')})", pad)
            lf = tk.Frame(body, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
            lf.pack(fill="x", padx=pad, pady=(0,12))
            pr = tk.Frame(lf, bg=BG_CARD, padx=12, pady=10); pr.pack(fill="x")
            for kw in log_kws:
                tk.Label(pr, text=kw, font=("Arial",9,"bold"), bg=KW_TAG_BG, fg=TEXT_LIGHT,
                         padx=6, pady=2).pack(side="left", padx=(0,5))
            tk.Label(lf, text=f"共 {len(rec.get('log_hits',[]))} 行命中",
                     font=("Arial",8), bg=BG_CARD, fg=TEXT_MUTED, padx=12, pady=(0,8)).pack(anchor="w")

        if rec["images"]:
            self._popup_sec(body, f"截圖 ({len(rec['images'])} 張)", pad)
            img_f = tk.Frame(body, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
            img_f.pack(fill="x", padx=pad, pady=(0,16))
            gf = tk.Frame(img_f, bg=BG_CARD); gf.pack(fill="x", padx=12, pady=10)
            popup._img_refs = []
            for idx, (name, img) in enumerate(rec["images"]):
                c, r = idx%3, idx//3
                cell = tk.Frame(gf, bg=BG_INPUT, highlightbackground=BORDER, highlightthickness=1)
                cell.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
                gf.columnconfigure(c, weight=1)
                thumb = img.copy(); thumb.thumbnail((180,130))
                ph = ImageTk.PhotoImage(thumb); popup._img_refs.append(ph)
                il = tk.Label(cell, image=ph, bg=BG_INPUT, cursor="hand2")
                il.pack(pady=(8,4))
                il.bind("<Button-1>", lambda e, im=img, nm=name: self._show_full_image(im, nm))
                tk.Label(cell, text=name[:20]+("…" if len(name)>20 else ""),
                         font=("Arial",8), bg=BG_INPUT, fg=TEXT_MID).pack(pady=(0,6))
            tk.Label(img_f, text="（點擊圖片可放大檢視）",
                     font=("Arial",8), bg=BG_CARD, fg=TEXT_MUTED).pack(pady=(0,8))

        tk.Button(body, text="關閉", font=("Arial",10), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=20, pady=8, cursor="hand2",
                  command=popup.destroy).pack(pady=16)

    def _popup_sec(self, parent, text, pad):
        f = tk.Frame(parent, bg=BG_LIGHT); f.pack(fill="x", padx=pad, pady=(12,4))
        tk.Frame(f, bg=ACCENT, width=3).pack(side="left", fill="y", padx=(0,7))
        tk.Label(f, text=text, font=("Arial",10,"bold"), bg=BG_LIGHT, fg=TEXT_DARK).pack(side="left")

    def _show_full_image(self, img, name):
        win = tk.Toplevel(self); win.title(name); win.configure(bg=BG_DARK)
        disp = img.copy(); disp.thumbnail((1100,750))
        win.geometry(f"{disp.width}x{disp.height+40}")
        ph = ImageTk.PhotoImage(disp); win._ph = ph
        tk.Label(win, image=ph, bg=BG_DARK).pack(expand=True)
        tk.Button(win, text="關閉", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=14, pady=5, command=win.destroy).pack(pady=6)


if __name__ == "__main__":
    try:
        from PIL import Image, ImageTk
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable,"-m","pip","install","Pillow","-q"])
        from PIL import Image, ImageTk
    app = ReportApp()
    app.mainloop()
