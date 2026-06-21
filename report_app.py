"""
RCP Issue Reporter v4.0
Features: search/filter, HTML export, side-by-side diff, keyboard shortcuts
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import os, re, json, base64, io, threading, webbrowser, sys
from datetime import datetime

# ─── Windows DPI 修正（防止模糊縮放）────────────────────────
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ─── Persistence ─────────────────────────────────────────────
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
RECORDS_FILE = os.path.join(_SCRIPT_DIR, "issue_records.json")
KEYWORDS_FILE= os.path.join(_SCRIPT_DIR, "log_keywords.txt")
EXPORTS_DIR  = os.path.join(_SCRIPT_DIR, "exports")

# ─── Color Palette ───────────────────────────────────────────
BG_DARK    = "#1B2B4B"
BG_PANEL   = "#111E33"
BG_LIGHT   = "#F5F3EF"
BG_CARD    = "#FFFFFF"
BG_INPUT   = "#EDEBE6"
ACCENT     = "#C4962A"
SUCCESS    = "#2D6A4F"
WARNING    = "#B7770D"
INFO       = "#2A4270"
DANGER     = "#C0392B"
TEXT_DARK  = "#1B2B4B"
TEXT_MID   = "#5A6478"
TEXT_LIGHT = "#F8F9FA"
TEXT_MUTED = "#8A9AB0"
BORDER     = "#DDD8CE"
DIFF_DEL   = "#FEF7EE"
DIFF_ADD   = "#F0FFF4"
DOT_GREEN  = "#2D6A4F"
DOT_YELLOW = "#C4962A"
KW_TAG_BG  = "#1B2B4B"
LOG_BG     = "#0F1A2E"
LOG_FG     = "#D4DCE8"
LOG_KW_FG  = "#E8C468"
SH_COMPARE = "#1B3A5C"
SH_REPORT  = "#2A1F10"
SH_LOG     = "#1A3A2A"

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
            f.write("# Log TS Keyword List — one keyword per line, # for comments\n\n")
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
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Issue #{rec['id']} Report</title>
<style>
  body{{font-family:-apple-system,sans-serif;background:#F5F3EF;color:#1B2B4B;margin:0;padding:24px}}
  .card{{background:#fff;border-radius:10px;padding:20px 24px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.06);border-left:4px solid #C4962A}}
  h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:13px;font-weight:700;margin:0 0 12px;color:#C4962A;text-transform:uppercase;letter-spacing:.05em}}
  table{{width:100%;border-collapse:collapse}} th{{background:#1B2B4B;color:#fff;padding:8px 10px;text-align:left;font-size:13px}}
  .badge{{display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700}}
</style></head><body>
<div class="card">
  <h1>⚑ Issue #{rec['id']} Report</h1>
  <div style="color:#8A9AB0;font-size:13px">{rec['time']} &nbsp;|&nbsp; {rec.get('golden_file','—')} vs {rec.get('issue_file','—')}</div>
  <div style="margin-top:8px">
    {''.join(f'<span class="badge" style="background:#1B2B4B;color:#F0D080;margin-right:6px">{t}</span>' for t in rec.get('tags',[]))}
  </div>
</div>
<div class="card"><h2>RCP Field Comparison</h2>
  <table><tr><th></th><th>Field</th><th>Golden</th><th>Issue</th></tr>{diff_html}</table>
</div>
<div class="card"><h2>Issue Description</h2><p style="font-size:14px;line-height:1.7">{rec['desc']}</p></div>
{'<div class="card"><h2>Log TS Hits (' + str(len(rec.get("log_hits",[]))) + ')</h2>' + log_html + '</div>' if rec.get('log_hits') else ''}
{'<div class="card"><h2>Screenshots</h2>' + img_html + '</div>' if rec.get('images') else ''}
<div style="text-align:center;color:#aaa;font-size:12px;margin-top:16px">RCP Issue Reporter v4.0 · Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
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
        self.title("RCP Issue Reporter v4.0")
        self.geometry("1400x860")
        self.minsize(900, 600)
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
        self._filter_text = tk.StringVar()
        self._sort_col    = "id"
        self._sort_asc    = False

        self._build_ui()
        self._bind_shortcuts()
        self.current_section = None
        self._nav_select("main")
        if self.issue_records:
            self._update_badge()
            self._refresh_issue_list()

    # ── 鍵盤快捷鍵 ────────────────────────────────────────────
    def _bind_shortcuts(self):
        self.bind("<Control-r>", lambda e: self._run_compare())
        self.bind("<Control-l>", lambda e: self._pick_log_file())
        self.bind("<Control-Return>", lambda e: self._submit_report())
        self.bind("<Control-e>", lambda e: self._export_selected())
        self.bind("<F1>", lambda e: self._nav_select("main"))
        self.bind("<F2>", lambda e: self._nav_select("tool_issue"))

    # ── Sidebar ────────────────────────────────────────────────
    def _build_ui(self):
        self.sidebar = tk.Frame(self, bg=BG_PANEL, width=190)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_f = tk.Frame(self.sidebar, bg=BG_PANEL, pady=18)
        logo_f.pack(fill="x")
        tk.Label(logo_f, text="⚑", font=("Arial", 24), bg=BG_PANEL, fg=ACCENT).pack()
        tk.Label(logo_f, text="Issue Reporter", font=("Arial", 13, "bold"), bg=BG_PANEL, fg=TEXT_LIGHT).pack()
        tk.Label(logo_f, text="RCP Issue Reporter v4.0", font=("Arial", 7), bg=BG_PANEL, fg=TEXT_MUTED).pack(pady=(2,0))
        tk.Frame(self.sidebar, bg="#374D65", height=1).pack(fill="x", padx=16, pady=6)

        self.nav_buttons = {}
        self.issue_count_lbl = None
        for key, icon, label, shortcut in [
            ("main",       "⊞",  "File Report", "F1"),
            ("tool_issue", "☰",  "Tool Issue",  "F2"),
        ]:
            self.nav_buttons[key] = self._make_nav_btn(key, icon, label, shortcut)

        tk.Frame(self.sidebar, bg="#374D65", height=1).pack(fill="x", padx=16, pady=8)
        tk.Label(self.sidebar, text="Shortcuts", font=("Arial", 8, "bold"), bg=BG_PANEL, fg=TEXT_MUTED).pack(anchor="w", padx=16)
        for txt in ["F1  File Report", "F2  Tool Issue", "Ctrl+R  Run Compare", "Ctrl+L  Pick Log", "Ctrl+↵  Submit", "Ctrl+E  Export"]:
            tk.Label(self.sidebar, text=txt, font=("Arial", 7), bg=BG_PANEL, fg="#3D5270").pack(anchor="w", padx=20, pady=1)

        tk.Label(self.sidebar, text="v4.0.0", font=("Arial", 8), bg=BG_PANEL, fg="#3D5270").pack(side="bottom", pady=10)

        self.content = tk.Frame(self, bg=BG_LIGHT)
        self.content.pack(side="left", fill="both", expand=True)

        self.pages = {}
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

    def _update_badge(self):
        if self.issue_count_lbl:
            self.issue_count_lbl.configure(text=str(len(self.issue_records)))

    # ══════════════════════════════════════════════════════════
    # [REMOVED: 儀表板]
    # ══════════════════════════════════════════════════════════
    def _UNUSED_build_dashboard_page(self):
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

    def _UNUSED_refresh_dashboard(self):
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
        tk.Label(hdr, text="File Report", font=("Arial", 15, "bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=24, pady=14)
        tk.Label(hdr, text="RCP Compare + Report Info  |  Auto Log TS", font=("Arial", 10), bg=BG_DARK, fg=TEXT_MUTED).pack(side="left", padx=4)

        pane = tk.PanedWindow(page, orient="horizontal", bg=BORDER, sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        left_col  = self._build_left_column(pane)
        right_col = self._build_log_panel(pane)
        pane.add(left_col,  minsize=420, stretch="always")
        pane.add(right_col, minsize=280, stretch="always")
        return page

    # ── 左欄：RCP比對 + 報案資訊 ──────────────────────────────
    def _build_left_column(self, parent):
        col = tk.Frame(parent, bg=BG_LIGHT)
        compare = self._build_compare_panel(col)
        compare.pack(fill="both", expand=True)
        tk.Frame(col, bg=BORDER, height=1).pack(fill="x")
        self._build_screenshot_panel(col).pack(fill="both", expand=True)
        return col

    def _build_compare_panel(self, parent):
        panel = tk.Frame(parent, bg=BG_LIGHT)
        shdr = tk.Frame(panel, bg=SH_COMPARE, height=38)
        shdr.pack(fill="x"); shdr.pack_propagate(False)
        tk.Label(shdr, text="⊞  RCP Compare", font=("Arial", 11, "bold"), bg=SH_COMPARE, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=8)

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
        self.golden_card = self._build_rcp_card(cards_row, "GOLDEN RCP", "Baseline", SUCCESS, 0)
        self.issue_card  = self._build_rcp_card(cards_row, "ISSUE RCP",  "Issue",    ACCENT,  1)

        btn_row = tk.Frame(inner, bg=BG_LIGHT)
        btn_row.pack(fill="x", padx=pad, pady=(2,6))
        tk.Button(btn_row, text="▶ Run Compare  Ctrl+R",
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
        for dot_c, txt in [(DOT_GREEN,"Match"),(DOT_YELLOW,"Mismatch")]:
            lf = tk.Frame(leg, bg=BG_LIGHT); lf.pack(side="left", padx=4)
            tk.Label(lf, text="●", font=("Arial", 9), bg=BG_LIGHT, fg=dot_c).pack(side="left")
            tk.Label(lf, text=txt, font=("Arial", 7), bg=BG_LIGHT, fg=TEXT_MID).pack(side="left")

        diff_hdr = tk.Frame(inner, bg=BG_DARK)
        diff_hdr.pack(fill="x", padx=pad)
        tk.Label(diff_hdr, text="", bg=BG_DARK, width=2, padx=4, pady=5).pack(side="left")
        for txt, w in [("Field",14),("Golden",18),("Issue",18)]:
            tk.Label(diff_hdr, text=txt, font=("Arial", 8, "bold"),
                     bg=BG_DARK, fg=TEXT_LIGHT, anchor="w", width=w, padx=6, pady=5).pack(side="left")

        self.diff_frame = tk.Frame(inner, bg=BG_LIGHT)
        self.diff_frame.pack(fill="x", padx=pad, pady=(0,10))
        tk.Label(self.diff_frame, text="Load two RCP files then click Run Compare",
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
        file_var = tk.StringVar(value="Not selected")
        row = tk.Frame(inner, bg=BG_CARD); row.pack(fill="x")
        tk.Label(row, textvariable=file_var, font=("Arial", 7), bg=BG_INPUT, fg=TEXT_MID, anchor="w",
                 padx=5, pady=3, width=14).pack(side="left", fill="x", expand=True)
        tag = "golden" if col==0 else "issue"
        tk.Button(row, text="Select", font=("Arial", 7, "bold"),
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
        path = filedialog.askopenfilename(title=f"Select {tag.upper()} RCP File",
                                          filetypes=[("Text files","*.txt"),("All files","*.*")])
        if not path: return
        try:    raw = open(path, "r", encoding="utf-8-sig").read()
        except: raw = open(path, "r", encoding="big5", errors="replace").read()
        card._raw  = raw
        card._data = parse_rcp_text(raw)
        card._file_var.set(os.path.basename(path))
        card._preview.configure(state="normal")
        card._preview.delete("1.0", "end")
        for f in RCP_FIELDS:
            card._preview.insert("end", f"{f}:\n  {card._data.get(f) or '(not found)'}\n\n")
        card._preview.configure(state="disabled")
        if tag == "golden": self.golden_data = card._data
        else:               self.issue_data  = card._data

    def _run_compare(self):
        if not self.golden_data and not self.issue_data:
            messagebox.showwarning("Notice", "Please load at least one RCP file."); return
        rows = diff_dicts(self.golden_data, self.issue_data)
        for w in self.diff_frame.winfo_children(): w.destroy()
        active  = [r for r in rows if r[3] != "empty"]
        n_match = sum(1 for r in active if r[3]=="match")
        n_miss  = sum(1 for r in active if r[3]=="mismatch")
        self.compare_status.configure(text=f"● {n_match} Match  ● {n_miss} Mismatch",
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
            messagebox.showinfo("Notice", "Please load RCP files first."); return
        win = tk.Toplevel(self)
        win.title("Side-by-Side Diff — Golden vs Issue")
        win.geometry("1100x720")
        win.configure(bg=BG_DARK)
        hdr = tk.Frame(win, bg=BG_DARK)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Side-by-Side RCP Diff", font=("Arial",13,"bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=20, pady=10)
        tk.Label(hdr, text="Yellow = line only on this side  |  Red = lines differ", font=("Arial",9), bg=BG_DARK, fg=TEXT_MUTED).pack(side="left", padx=4)
        tk.Button(hdr, text="Close", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT, relief="flat",
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
        tk.Label(shdr, text="✎  Report Info", font=("Arial", 10, "bold"), bg=SH_REPORT, fg=TEXT_LIGHT).pack(side="left", padx=14, pady=7)

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
        # 標籤
        meta_card = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        meta_card.pack(fill="x", padx=pad, pady=(10,6))
        mi = tk.Frame(meta_card, bg=BG_CARD, padx=10, pady=8); mi.pack(fill="x")
        tk.Label(mi, text="Tags (comma-separated)", font=("Arial", 8), bg=BG_CARD, fg=TEXT_MID).pack(anchor="w", pady=(0,2))
        self.tags_entry = tk.Entry(mi, font=("Arial", 9), bg=BG_INPUT, fg=TEXT_DARK, relief="flat",
                                   highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BORDER)
        self.tags_entry.pack(fill="x")
        self.tags_entry.insert(0, "e.g. Alarm, Process, Hardware")

        self._sec(inner, "Issue Description", pad)
        desc_card = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        desc_card.pack(fill="x", padx=pad, pady=(0,8))
        di = tk.Frame(desc_card, bg=BG_CARD, padx=10, pady=8); di.pack(fill="x")
        tk.Label(di, text="Describe symptoms, time, and reproduction steps:", font=("Arial", 8), bg=BG_CARD, fg=TEXT_MID).pack(anchor="w")
        self.desc_text = tk.Text(di, height=5, font=("Arial", 9), bg=BG_INPUT, fg=TEXT_DARK,
                                  relief="flat", wrap="word", padx=7, pady=5,
                                  highlightthickness=1, highlightcolor=ACCENT,
                                  highlightbackground=BORDER, insertbackground=ACCENT)
        self.desc_text.pack(fill="x", pady=(5,0))
        self.desc_text.insert("end", "e.g. Device showed abnormal behavior during testing...")
        self.desc_text.bind("<FocusIn>", self._clear_placeholder)

        self._sec(inner, "Screenshots", pad)
        img_card = tk.Frame(inner, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        img_card.pack(fill="x", padx=pad, pady=(0,8))
        img_top = tk.Frame(img_card, bg=BG_CARD, padx=10, pady=7); img_top.pack(fill="x")
        tk.Button(img_top, text="+ Upload Screenshot", font=("Arial", 8, "bold"),
                  bg=ACCENT, fg=TEXT_LIGHT, relief="flat", padx=10, pady=4, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._upload_images).pack(side="left")
        self.img_count_lbl = tk.Label(img_top, text="None uploaded", font=("Arial", 7), bg=BG_CARD, fg=TEXT_MUTED)
        self.img_count_lbl.pack(side="left", padx=6)
        tk.Button(img_top, text="Clear", font=("Arial", 7), bg=BG_LIGHT, fg=TEXT_MID,
                  relief="flat", padx=6, pady=3, cursor="hand2",
                  command=self._clear_images).pack(side="right")
        self.img_grid = tk.Frame(img_card, bg=BG_CARD)
        self.img_grid.pack(fill="x", padx=10, pady=(0,8))

        sub_row = tk.Frame(inner, bg=BG_LIGHT)
        sub_row.pack(fill="x", padx=pad, pady=(6,14))
        tk.Button(sub_row, text="📋  Submit Report  Ctrl+↵", font=("Arial", 10, "bold"),
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
        if self.desc_text.get("1.0","end-1c").startswith("e.g."): self.desc_text.delete("1.0","end")

    # ── Log panel ─────────────────────────────────────────────
    def _build_log_panel(self, parent):
        panel = tk.Frame(parent, bg=BG_LIGHT)
        shdr = tk.Frame(panel, bg=SH_LOG, height=38)
        shdr.pack(fill="x"); shdr.pack_propagate(False)
        tk.Label(shdr, text="📋  Auto Log TS", font=("Arial", 11, "bold"), bg=SH_LOG, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=8)

        pick_row = tk.Frame(panel, bg=BG_LIGHT, pady=8)
        pick_row.pack(fill="x", padx=12)
        self.log_file_var = tk.StringVar(value="No log file selected")
        tk.Label(pick_row, textvariable=self.log_file_var, font=("Arial", 8),
                 bg=BG_INPUT, fg=TEXT_MID, anchor="w", padx=8, pady=4).pack(side="left", fill="x", expand=True)
        tk.Button(pick_row, text="Select Log  Ctrl+L", font=("Arial", 9, "bold"),
                  bg=SH_LOG, fg=TEXT_LIGHT, relief="flat", padx=12, pady=4, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._pick_log_file).pack(side="left", padx=(6,0))
        tk.Button(pick_row, text="Clear", font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MID,
                  relief="flat", padx=6, pady=4, cursor="hand2",
                  command=self._clear_log).pack(side="left", padx=(4,0))

        self.log_status_var = tk.StringVar(value="")
        self.log_status_lbl = tk.Label(panel, textvariable=self.log_status_var,
                                        font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MUTED, anchor="w", padx=12)
        self.log_status_lbl.pack(fill="x")

        kw_outer = tk.Frame(panel, bg=BG_LIGHT)
        kw_outer.pack(fill="x", padx=12, pady=(2,4))
        kw_left = tk.Frame(kw_outer, bg=BG_LIGHT); kw_left.pack(side="left", fill="x", expand=True)
        tk.Label(kw_left, text="Keywords:", font=("Arial", 8), bg=BG_LIGHT, fg=TEXT_MUTED).pack(side="left")
        self.kw_pills_frame = tk.Frame(kw_left, bg=BG_LIGHT); self.kw_pills_frame.pack(side="left", fill="x", expand=True)
        self._refresh_kw_pills()
        tk.Button(kw_outer, text="✏ Edit Keywords", font=("Arial", 7, "bold"),
                  bg="#354A61", fg=TEXT_LIGHT, relief="flat", padx=7, pady=3, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._open_keyword_editor).pack(side="right", padx=(6,0))

        hit_hdr = tk.Frame(panel, bg=BG_DARK, height=28)
        hit_hdr.pack(fill="x", padx=12); hit_hdr.pack_propagate(False)
        tk.Label(hit_hdr, text="Detection Results", font=("Arial", 8, "bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=8, pady=5)
        self.hit_count_lbl = tk.Label(hit_hdr, text="", font=("Arial", 8, "bold"), bg=BG_DARK, fg=WARNING)
        self.hit_count_lbl.pack(side="right", padx=8)

        _, self.log_hit_inner, _ = _make_scrollable(panel, LOG_BG)
        tk.Label(self.log_hit_inner, text="Select a log file to auto-scan keywords",
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
        editor.title("Edit Keyword List"); editor.geometry("480x520")
        editor.configure(bg=BG_LIGHT); editor.grab_set()
        hdr = tk.Frame(editor, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text="✏  Log TS Keyword List", font=("Arial", 12, "bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=10)
        info = tk.Frame(editor, bg="#EDF3FA"); info.pack(fill="x")
        tk.Label(info, text="One keyword per line    # lines are comments\nTakes effect on next log scan after saving.",
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
            txt.insert("end", "# Log TS Keyword List\n\n" + "\n".join(_DEFAULT_KEYWORDS) + "\n")
        btn_row = tk.Frame(editor, bg=BG_LIGHT); btn_row.pack(fill="x", padx=14, pady=(0,14))
        save_status = tk.Label(btn_row, text="", font=("Arial", 8), bg=BG_LIGHT, fg=DOT_GREEN)
        save_status.pack(side="right", padx=8)
        def _save():
            global ISSUE_KEYWORDS
            content = txt.get("1.0","end")
            try:
                with open(KEYWORDS_FILE, "w", encoding="utf-8") as f: f.write(content)
                ISSUE_KEYWORDS = load_keywords(); self._refresh_kw_pills()
                save_status.configure(text=f"✓ Saved  {len(ISSUE_KEYWORDS)} keywords")
            except Exception as e: save_status.configure(text=f"❌ Error: {e}", fg="#F87171")
        tk.Button(btn_row, text="💾  Save", font=("Arial", 10, "bold"),
                  bg=ACCENT, fg=TEXT_LIGHT, relief="flat", padx=18, pady=7, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT, command=_save).pack(side="left")
        tk.Button(btn_row, text="Close", font=("Arial", 9), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=14, pady=7, cursor="hand2", command=editor.destroy).pack(side="left", padx=8)

    def _pick_log_file(self):
        path = filedialog.askopenfilename(title="Select Log File",
                                          filetypes=[("Log files","*.txt *.log"),("All files","*.*")])
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
        self.log_status_var.set("⏳ Scanning, please wait…")
        self.log_status_lbl.configure(fg=TEXT_MUTED)
        self.hit_count_lbl.configure(text="")
        for w in self.log_hit_inner.winfo_children(): w.destroy()
        tk.Label(self.log_hit_inner, text="⏳  Reading and scanning log…",
                 font=("Arial", 9), bg=LOG_BG, fg="#64748B", pady=30).pack()

    def _log_set_error(self, msg):
        self.log_status_var.set(f"❌ Read error: {msg}")
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
                self.log_status_var.set(f"Range {rs}  {in_rng:,} lines  No issue keywords found ✓")
            else:
                self.log_status_var.set(f"{total:,} lines — No issue keywords found ✓")
            self.log_status_lbl.configure(fg=DOT_GREEN)
            self.hit_count_lbl.configure(text="")
            tk.Label(self.log_hit_inner, text="✓  No issue keywords detected",
                     font=("Arial", 10), bg=LOG_BG, fg=DOT_GREEN, pady=30).pack()
            return
        if t_start and t_end:
            rs = f"{t_start.strftime('%m/%d %H:%M:%S')} ~ {t_end.strftime('%m/%d %H:%M:%S')}"
            self.log_status_var.set(f"Range {rs}  {in_rng:,} lines  {n} hits found")
        else:
            self.log_status_var.set(f"{total:,} lines — {n} hits found")
        self.log_status_lbl.configure(fg=WARNING)
        self.hit_count_lbl.configure(text=f"⚠ {n} hits")
        self._log_progress_lbl = tk.Label(self.log_hit_inner, text=f"Loading… 0 / {n}",
                                           font=("Arial", 8), bg=LOG_BG, fg="#64748B")
        self._log_progress_lbl.pack(pady=(6,0))
        self._render_batch(list(self.log_hits), 0, n)

    def _render_batch(self, hits, offset, total):
        batch = hits[offset:offset+self._BATCH]
        if offset == 0 and hasattr(self,"_log_progress_lbl"):
            try: self._log_progress_lbl.destroy()
            except: pass
        for lineno, line, kws in batch:
            row = tk.Frame(self.log_hit_inner, bg="#0F1E35",
                           highlightbackground="#1B2F4A", highlightthickness=1)
            row.pack(fill="x", pady=1, padx=4)
            tk.Label(row, text=f"L{lineno}", font=("Courier",7,"bold"),
                     bg="#1B2B4B", fg="#8A9AB0", padx=6, pady=4).pack(side="left")
            kw_f = tk.Frame(row, bg="#1E2B3C"); kw_f.pack(side="right", padx=5, pady=3)
            for kw in kws:
                tk.Label(kw_f, text=kw, font=("Arial",7,"bold"),
                         bg=KW_TAG_BG, fg=TEXT_LIGHT, padx=4, pady=1).pack(side="left", padx=(0,2))
            tk.Label(row, text=line.strip()[:130], font=("Courier",8),
                     bg="#1E2B3C", fg=LOG_KW_FG, anchor="w", padx=8, pady=4,
                     wraplength=360).pack(side="left", fill="x", expand=True)
        next_offset = offset + self._BATCH
        if next_offset < total:
            prog = tk.Label(self.log_hit_inner, text=f"Loading… {next_offset} / {total}",
                            font=("Arial",7), bg=LOG_BG, fg="#475569")
            prog.pack()
            self.after(0, lambda p=prog: (p.destroy(), self._render_batch(hits, next_offset, total)))
        else:
            tk.Button(self.log_hit_inner, text="📄  View Full Log",
                      font=("Arial",8), bg="#1E2B3C", fg="#94A3B8", relief="flat",
                      padx=10, pady=5, cursor="hand2",
                      activebackground="#2A3D55", activeforeground=TEXT_LIGHT,
                      command=self._show_full_log).pack(pady=8)

    def _clear_log(self):
        self.log_raw_text=""; self.log_hits=[]; self.log_filename=""
        self.log_file_var.set("No log file selected"); self.log_status_var.set("")
        self.hit_count_lbl.configure(text="")
        for w in self.log_hit_inner.winfo_children(): w.destroy()
        tk.Label(self.log_hit_inner, text="Select a log file to auto-scan keywords",
                 font=("Arial",9), bg=LOG_BG, fg="#475569", pady=30).pack()

    def _show_full_log(self):
        if not self.log_raw_text: return
        win = tk.Toplevel(self); win.title(f"Full Log — {self.log_filename}")
        win.geometry("960x700"); win.configure(bg=LOG_BG)
        hdr = tk.Frame(win, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text=f"📄  {self.log_filename}", font=("Arial",12,"bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text=f"⚠ {len(self.log_hits)} hits",
                 font=("Arial",9), bg=BG_DARK, fg=WARNING).pack(side="right", padx=16)
        prog_var = tk.StringVar(value="Loading…")
        prog_lbl = tk.Label(win, textvariable=prog_var, font=("Arial",8), bg=LOG_BG, fg="#64748B")
        prog_lbl.pack(anchor="w", padx=12, pady=(4,0))
        txt = scrolledtext.ScrolledText(win, font=("Courier",9), bg=LOG_BG, fg=LOG_FG,
                                         relief="flat", wrap="none", padx=12, pady=8,
                                         highlightthickness=0, state="disabled")
        txt.pack(fill="both", expand=True)
        txt.tag_configure("hit_line", background="#1B3050", foreground=LOG_KW_FG)
        txt.tag_configure("kw", foreground="#FB923C", font=("Courier",9,"bold"))
        tk.Button(win, text="Close", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
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
                prog_var.set(f"Loading… {end:,} / {total_lines:,} lines")
                win.after(0, lambda: _insert_chunk(end))
            else:
                prog_lbl.destroy()
                if self.log_hits: txt.configure(state="normal"); txt.see(f"{self.log_hits[0][0]}.0"); txt.configure(state="disabled")
        win.after(50, lambda: _insert_chunk(0))

    # ── Image ─────────────────────────────────────────────────
    def _upload_images(self):
        paths = filedialog.askopenfilenames(title="Select Screenshots",
                                            filetypes=[("Images","*.png *.jpg *.jpeg *.bmp *.gif *.webp"),("All files","*.*")])
        for p in paths:
            try: self.report_images.append((os.path.basename(p), Image.open(p)))
            except Exception as ex: messagebox.showerror("Error", f"Cannot open {p}: {ex}")
        self._refresh_img_grid()

    def _clear_images(self):
        self.report_images.clear(); self._photo_refs.clear(); self._refresh_img_grid()

    def _refresh_img_grid(self):
        for w in self.img_grid.winfo_children(): w.destroy()
        self._photo_refs.clear()
        if not self.report_images:
            self.img_count_lbl.configure(text="None uploaded")
            tk.Label(self.img_grid, text="Click above to upload screenshots",
                     font=("Arial",8), bg=BG_CARD, fg=TEXT_MUTED, pady=10).pack(); return
        self.img_count_lbl.configure(text=f"{len(self.report_images)} uploaded")
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
        if not desc or desc.startswith("e.g."):
            messagebox.showwarning("Notice","Please enter an issue description."); return
        tags_raw = self.tags_entry.get().strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip() and not t.strip().startswith("e.g")] if tags_raw else []
        hit_kws = list(dict.fromkeys(kw for _,_,kws in self.log_hits for kw in kws))
        record = {
            "id":    len(self.issue_records)+1,
            "time":  datetime.now().strftime("%Y-%m-%d %H:%M"),
            "desc":  desc,
            "tags":  tags,
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
        self.submit_status.configure(text=f"✓ Submitted Issue #{record['id']}")
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
        tk.Label(search_f, text="Search desc/Tool ID/LOT ID", font=("Arial",7), bg="#EEF1F6", fg=TEXT_MUTED).pack(side="left", padx=4)

        # 按鈕群
        tk.Button(toolbar, text="Ctrl+E  Export Selected", font=("Arial",8,"bold"),
                  bg=INFO, fg=TEXT_LIGHT, relief="flat", padx=10, pady=5, cursor="hand2",
                  activebackground=BG_DARK, activeforeground=TEXT_LIGHT,
                  command=self._export_selected).pack(side="right", padx=4)
        tk.Button(toolbar, text="Select All", font=("Arial",8),
                  bg=BG_LIGHT, fg=TEXT_MID, relief="flat", padx=8, pady=5, cursor="hand2",
                  command=self._select_all).pack(side="right", padx=2)
        tk.Button(toolbar, text="Clear Selection", font=("Arial",8),
                  bg=BG_LIGHT, fg=TEXT_MID, relief="flat", padx=8, pady=5, cursor="hand2",
                  command=self._clear_selection).pack(side="right", padx=2)

        self._col_defs = [
            ("",              3),("☐",  2),("#",   3),
            ("Time",          10),("Tool ID",      9),
            ("RCP NAME",      12),("LOT ID",        9),("RCP MODIFY TIME",14),
            ("RCP SCAN TIME", 13),("SCAN END TIME", 13),("Log TS", 0),("Description", 0),
        ]
        # Proportional column specs for grid-based table:
        # (header_label, data_key, weight, minsize)
        self._tbl_cols = [
            ("#",               "id",              2,  28),
            ("Time",            "time",            6,  90),
            ("Tool id",         "Tool ID",         5,  70),
            ("RCP name",        "RCP NAME",        8,  90),
            ("Lot id",          "LOT ID",          5,  70),
            ("RCP modify time", "RCP MODIFY TIME", 9, 110),
            ("RCP scan time",   "RCP SCAN TIME",   9, 110),
            ("Scan end time",   "SCAN END TIME",   9, 110),
            ("Log ts",          "__log__",         5,  60),
            ("Description",     "__desc__",       12, 100),
        ]
        # Put scrollbar, header, and rows all in the same container so they
        # share exactly the same usable width → column grid lines align perfectly.
        table_outer = tk.Frame(page, bg=BG_LIGHT)
        table_outer.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(table_outer, orient="vertical")
        vsb.pack(side="right", fill="y")

        th = tk.Frame(table_outer, bg=BG_DARK)
        th.pack(side="top", fill="x")
        self._apply_table_cols(th)
        tk.Label(th, text="", bg=BG_DARK, width=4).grid(row=0, column=0)
        tk.Frame(th, bg="#374D65", width=1).grid(row=0, column=1, sticky="ns")
        tk.Label(th, text="☐", font=("Arial",8,"bold"), bg=BG_DARK, fg=TEXT_LIGHT,
                 anchor="center", padx=4, pady=6).grid(row=0, column=2)
        tk.Frame(th, bg="#374D65", width=1).grid(row=0, column=3, sticky="ns")
        for i, (label, _, _w, _ms) in enumerate(self._tbl_cols):
            dc = i * 2 + 4
            tk.Label(th, text=label, font=("Arial",8,"bold"), bg=BG_DARK, fg=TEXT_LIGHT,
                     anchor="w", padx=6, pady=6).grid(row=0, column=dc, sticky="ew")
            if i < len(self._tbl_cols) - 1:
                tk.Frame(th, bg="#374D65", width=1).grid(row=0, column=dc+1, sticky="ns")
        tk.Frame(th, bg="#374D65", width=1).grid(row=0, column=4+len(self._tbl_cols)*2-1, sticky="ns")
        tk.Label(th, text="", bg=BG_DARK, width=7).grid(row=0, column=4+len(self._tbl_cols)*2)

        canvas = tk.Canvas(table_outer, bg=BG_LIGHT, highlightthickness=0, yscrollcommand=vsb.set)
        vsb.configure(command=canvas.yview)
        canvas.pack(side="left", fill="both", expand=True)
        self.issue_list_inner = tk.Frame(canvas, bg=BG_LIGHT)
        _wid = canvas.create_window((0, 0), window=self.issue_list_inner, anchor="nw")
        self.issue_list_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_wid, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._selected_ids = set()
        self._show_empty_placeholder()
        return page

    def _apply_table_cols(self, frame):
        """Apply proportional grid column config to a table row/header frame."""
        frame.columnconfigure(0, minsize=32,  weight=0)   # del btn
        frame.columnconfigure(2, minsize=26,  weight=0)   # checkbox
        for i, (_, _, w, ms) in enumerate(self._tbl_cols):
            dc = i * 2 + 4
            frame.columnconfigure(dc, weight=w, minsize=ms)
            frame.columnconfigure(dc + 1, minsize=1, weight=0)  # vsep
        frame.columnconfigure(3, minsize=1, weight=0)     # sep after chk
        last_export_col = 4 + len(self._tbl_cols) * 2
        frame.columnconfigure(last_export_col, minsize=58, weight=0)  # export btn

    def _show_empty_placeholder(self):
        tk.Label(self.issue_list_inner, text="No records yet. Submit a report to see data here.",
                 font=("Arial",11), bg=BG_LIGHT, fg=TEXT_MUTED, pady=60).pack()

    def _filtered_records(self):
        q   = self._filter_text.get().lower()
        out = []
        for r in self.issue_records:
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
            messagebox.showinfo("Notice","No data to export."); return
        exported = []
        for r in targets:
            try: exported.append(export_html(r))
            except Exception as e: messagebox.showerror("Error", f"Export #{r['id']} failed: {e}")
        if exported:
            msg = f"Exported {len(exported)} report(s) to:\n{EXPORTS_DIR}"
            if messagebox.askyesno("Export Complete", msg + "\n\nOpen folder?"):
                try: os.startfile(EXPORTS_DIR)
                except: webbrowser.open(f"file://{EXPORTS_DIR}")

    def _refresh_issue_list(self):
        for w in self.issue_list_inner.winfo_children(): w.destroy()
        records = self._filtered_records()
        if not records:
            self._show_empty_placeholder(); return

        for i, rec in enumerate(reversed(records)):
            bg = BG_CARD if i % 2 == 0 else BG_LIGHT
            if rec["id"] in self._selected_ids: bg = "#EFF6FF"

            row = tk.Frame(self.issue_list_inner, bg=bg)
            row.pack(fill="x")
            self._apply_table_cols(row)

            # Delete btn (col 0)
            del_btn = tk.Button(row, text="🗑", font=("Arial",9), bg=bg, fg=DANGER,
                                relief="flat", cursor="hand2", borderwidth=0,
                                activebackground=bg, activeforeground=ACCENT,
                                command=lambda rid=rec["id"]: self._delete_record(rid))
            del_btn.grid(row=0, column=0, padx=(4,2), pady=4)
            tk.Frame(row, bg=BORDER, width=1).grid(row=0, column=1, sticky="ns")

            # Checkbox (col 2)
            chk_var = tk.BooleanVar(value=rec["id"] in self._selected_ids)
            tk.Checkbutton(row, variable=chk_var, bg=bg, relief="flat",
                           activebackground=bg, cursor="hand2",
                           command=lambda v=chk_var, rid=rec["id"]: self._toggle_select(v, rid)
                           ).grid(row=0, column=2, padx=2, pady=4)
            tk.Frame(row, bg=BORDER, width=1).grid(row=0, column=3, sticky="ns")

            # Data columns
            data_values = {
                "id":              f"#{rec['id']}",
                "time":            rec.get("time","—"),
                "Tool ID":         rec.get("Tool ID","—"),
                "RCP NAME":        rec.get("RCP NAME","—"),
                "LOT ID":          rec.get("LOT ID","—"),
                "RCP MODIFY TIME": rec.get("RCP MODIFY TIME","—"),
                "RCP SCAN TIME":   rec.get("RCP SCAN TIME","—"),
                "SCAN END TIME":   rec.get("SCAN END TIME","—"),
            }
            mono_keys = {"Tool ID","RCP NAME","LOT ID","RCP MODIFY TIME","RCP SCAN TIME","SCAN END TIME"}
            fg_map    = {"id": TEXT_MUTED, "time": TEXT_MID}

            for ci, (_, key, _, _) in enumerate(self._tbl_cols):
                dc = ci * 2 + 4

                if key == "__log__":
                    log_kws = rec.get("log_keywords", [])
                    cell = tk.Frame(row, bg=bg)
                    cell.grid(row=0, column=dc, sticky="ew", padx=4, pady=3)
                    if log_kws:
                        for kw in log_kws[:3]:
                            pill = tk.Label(cell, text=kw, font=("Arial",6,"bold"),
                                            bg=KW_TAG_BG, fg=TEXT_LIGHT, padx=3, pady=1, cursor="hand2")
                            pill.pack(side="left", padx=(0,2))
                            pill.bind("<Button-1>", lambda e, r=rec: self._show_log_detail(r))
                        if len(log_kws) > 3:
                            tk.Label(cell, text=f"+{len(log_kws)-3}", font=("Arial",6),
                                     bg=bg, fg=TEXT_MUTED).pack(side="left")
                    else:
                        tk.Label(cell, text="—", font=("Arial",8), bg=bg, fg=TEXT_MUTED).pack(side="left")

                elif key == "__desc__":
                    n_img = len(rec.get("images",[]))
                    desc_short = rec["desc"][:40] + ("…" if len(rec["desc"]) > 40 else "")
                    cell = tk.Frame(row, bg=bg)
                    cell.grid(row=0, column=dc, sticky="ew", padx=2, pady=2)
                    tags = rec.get("tags", [])
                    if tags:
                        tf = tk.Frame(cell, bg=bg); tf.pack(anchor="w")
                        for tag in tags[:3]:
                            tk.Label(tf, text=tag, font=("Arial",6), bg="#EDE9FE", fg="#7C3AED",
                                     padx=3, pady=0).pack(side="left", padx=(0,2))
                    dl = tk.Label(cell, text=desc_short + (f"  📷{n_img}" if n_img else ""),
                                  font=("Arial",8,"underline"), bg=bg, fg=INFO,
                                  anchor="w", padx=4, pady=2, cursor="hand2")
                    dl.pack(side="left")
                    dl.bind("<Button-1>", lambda e, r=rec: self._show_issue_detail(r))

                else:
                    val = data_values.get(key, "—") or "—"
                    font_f = "Courier" if key in mono_keys else "Arial"
                    fg_c   = fg_map.get(key, TEXT_DARK)
                    tk.Label(row, text=val, font=(font_f, 8), bg=bg, fg=fg_c,
                             anchor="w", padx=5, pady=6).grid(row=0, column=dc, sticky="ew")

                # vertical separator after each col except last data col
                if ci < len(self._tbl_cols) - 1:
                    tk.Frame(row, bg=BORDER, width=1).grid(row=0, column=dc+1, sticky="ns")

            # last separator + export btn
            last_sep = 4 + len(self._tbl_cols) * 2 - 1
            tk.Frame(row, bg=BORDER, width=1).grid(row=0, column=last_sep, sticky="ns")
            export_col = last_sep + 1
            tk.Button(row, text="⬇ HTML", font=("Arial",7,"bold"),
                      bg="#EFF6FF", fg=INFO, relief="flat", padx=6, pady=3, cursor="hand2",
                      command=lambda r=rec: self._export_one(r)).grid(row=0, column=export_col, padx=4, pady=4)

            tk.Frame(self.issue_list_inner, bg=BORDER, height=1).pack(fill="x")

    def _toggle_select(self, var, rid):
        if var.get(): self._selected_ids.add(rid)
        else:         self._selected_ids.discard(rid)

    def _export_one(self, rec):
        try:
            path = export_html(rec)
            if messagebox.askyesno("Export Complete", f"Exported Issue #{rec['id']}\n{path}\n\nOpen now?"):
                webbrowser.open(f"file://{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _delete_record(self, rec_id):
        if not messagebox.askyesno("Confirm Delete", f"Delete Issue #{rec_id}?"): return
        self.issue_records = [r for r in self.issue_records if r["id"] != rec_id]
        self._selected_ids.discard(rec_id)
        save_records(self.issue_records)
        self._update_badge(); self._refresh_issue_list()

    # ── Log detail popup ──────────────────────────────────────
    def _show_log_detail(self, rec):
        popup = tk.Toplevel(self)
        popup.title(f"Issue #{rec['id']} — Log TS Details")
        popup.geometry("860x600"); popup.configure(bg=LOG_BG); popup.grab_set()
        hdr = tk.Frame(popup, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text=f"📋  {rec.get('log_file','—')}", font=("Arial",12,"bold"),
                 bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text=f"⚠ {len(rec.get('log_hits',[]))} hits",
                 font=("Arial",9), bg=BG_DARK, fg=WARNING).pack(side="right", padx=16)
        if not rec.get("log_hits"):
            tk.Label(popup, text="No Log TS data for this issue.",
                     font=("Arial",11), bg=LOG_BG, fg="#475569", pady=40).pack()
            tk.Button(popup, text="Close", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
                      relief="flat", padx=14, pady=5, command=popup.destroy).pack(pady=8); return
        kw_bar = tk.Frame(popup, bg="#1E293B"); kw_bar.pack(fill="x")
        tk.Label(kw_bar, text="Matched Keywords:", font=("Arial",8), bg="#1E293B", fg="#94A3B8",
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
        tk.Button(popup, text="Close", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
                  relief="flat", padx=14, pady=5, command=popup.destroy).pack(pady=10)

    # ── Issue detail popup ────────────────────────────────────
    def _show_issue_detail(self, rec):
        popup = tk.Toplevel(self)
        popup.title(f"Issue #{rec['id']} Details")
        popup.geometry("840x700"); popup.configure(bg=BG_LIGHT); popup.grab_set()
        hdr = tk.Frame(popup, bg=BG_DARK); hdr.pack(fill="x")
        tk.Label(hdr, text=f"Issue #{rec['id']}  —  {rec['time']}",
                 font=("Arial",13,"bold"), bg=BG_DARK, fg=TEXT_LIGHT).pack(side="left", padx=20, pady=12)
        tk.Button(hdr, text="⬇ Export HTML", font=("Arial",9,"bold"),
                  bg=INFO, fg=TEXT_LIGHT, relief="flat", padx=14, pady=6, cursor="hand2",
                  command=lambda: self._export_one(rec)).pack(side="right", padx=16, pady=8)
        _, body, _ = _make_scrollable(popup, BG_LIGHT)
        pad = 20

        # 標籤列
        tags = rec.get("tags",[])
        if tags:
            tf = tk.Frame(body, bg=BG_LIGHT); tf.pack(fill="x", padx=pad, pady=(12,4))
            tk.Label(tf, text="Tags:", font=("Arial",9), bg=BG_LIGHT, fg=TEXT_MID).pack(side="left")
            for tag in tags:
                tk.Label(tf, text=tag, font=("Arial",9,"bold"), bg="#EDE9FE", fg="#7C3AED",
                         padx=8, pady=2).pack(side="left", padx=(0,6))

        self._popup_sec(body, "RCP Field Comparison", pad)
        tbl = tk.Frame(body, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        tbl.pack(fill="x", padx=pad, pady=(0,12))
        th = tk.Frame(tbl, bg=BG_DARK); th.pack(fill="x")
        tk.Label(th, text="", bg=BG_DARK, width=2, padx=4, pady=5).pack(side="left")
        for t,w in [("Field",18),("Golden Value",22),("Issue Value",22)]:
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

        self._popup_sec(body, "Issue Description", pad)
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
            tk.Label(lf, text=f"{len(rec.get('log_hits',[]))} lines matched",
                     font=("Arial",8), bg=BG_CARD, fg=TEXT_MUTED, padx=12, pady=(0,8)).pack(anchor="w")

        if rec["images"]:
            self._popup_sec(body, f"Screenshots ({len(rec['images'])})", pad)
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
            tk.Label(img_f, text="(Click an image to enlarge)",
                     font=("Arial",8), bg=BG_CARD, fg=TEXT_MUTED).pack(pady=(0,8))

        tk.Button(body, text="Close", font=("Arial",10), bg="#374D65", fg=TEXT_LIGHT,
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
        tk.Button(win, text="Close", font=("Arial",9), bg="#374D65", fg=TEXT_LIGHT,
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
