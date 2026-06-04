#!/usr/bin/env python3
# DJ Playlist Exporter v7
# macOS 10.14 Mojave / iTunes Library XML compatible

import json
import plistlib
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from urllib.parse import unquote, urlparse

APP_NAME = "DJ Playlist Exporter"
CONFIG_FILE = Path.home() / ".dj_playlist_exporter_config.json"

XML_CANDIDATES = [
    Path.home() / "Music/iTunes/iTunes Library.xml",
    Path.home() / "Music/iTunes/iTunes Music Library.xml",
]


def find_itunes_xml():
    for path in XML_CANDIDATES:
        if path.exists():
            return path
    return None


def safe_filename(name):
    if not name:
        return "Untitled"
    for c in '<>:"/\\|?*':
        name = name.replace(c, "")
    name = name.strip()
    return name or "Untitled"


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(config):
    try:
        CONFIG_FILE.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def human_size(num_bytes):
    gb = num_bytes / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = num_bytes / (1024 ** 2)
    if mb >= 1:
        return f"{mb:.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def open_folder(path):
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
    except Exception as e:
        print(f"[WARN] open_folder failed: {e}")


def free_space(path):
    try:
        usage = shutil.disk_usage(str(path))
        return usage.free
    except Exception as e:
        print(f"[WARN] free_space failed: {e}")
        return None


class RoundButton(tk.Canvas):
    def __init__(
        self,
        master,
        text,
        command=None,
        width=None,
        height=52,
        bg="#1F7AFF",
        fg="#FFFFFF",
        radius=18,
        font=("Helvetica", 18, "bold"),
        icon=None
    ):
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bg=master["bg"]
        )
        self.text = text
        self.command = command
        self.btn_bg = bg
        self.fg = fg
        self.radius = radius
        self.font = font
        self.icon = icon
        self.enabled = True
        self.bind("<Configure>", self.draw)
        self.bind("<Button-1>", self.click)
        self.bind("<Enter>", lambda e: self.config(cursor="hand2"))
        self.bind("<Leave>", lambda e: self.config(cursor=""))

    def round_rect(self, x1, y1, x2, y2, r, fill, outline):
        points = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1
        ]
        self.create_polygon(points, smooth=True, fill=fill, outline=outline)

    def draw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        color = self.btn_bg if self.enabled else "#4B5563"
        self.round_rect(2, 2, w - 2, h - 2, self.radius, color, color)
        text = self.text
        if self.icon:
            text = f"{self.icon}  {self.text}"
        self.create_text(w / 2, h / 2, text=text, fill=self.fg, font=self.font)

    def click(self, event=None):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.draw()


class DarkEntry(tk.Entry):
    def __init__(self, master, textvariable=None):
        super().__init__(
            master,
            textvariable=textvariable,
            bg="#101820",
            fg="#FFFFFF",
            insertbackground="#FFFFFF",
            relief="flat",
            font=("Helvetica", 14),
            highlightthickness=1,
            highlightbackground="#26313D",
            highlightcolor="#1F7AFF"
        )


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("820x560")
        self.root.minsize(700, 480)

        self.bg = "#070C12"
        self.panel = "#111820"
        self.field = "#101820"
        self.line = "#26313D"
        self.text = "#F5F7FA"
        self.sub = "#AEB8C5"
        self.muted = "#7D8794"
        self.blue = "#1F7AFF"
        self.green = "#62D12F"
        self.red = "#FF5C5C"

        self.root.configure(bg=self.bg)

        self.config = load_config()
        self.export_base_dir = self.config.get("last_dir", str(Path.home() / "Desktop"))

        self.xml_path = find_itunes_xml()
        if not self.xml_path:
            messagebox.showerror(
                "エラー",
                "iTunes Library XML が見つかりません。\n\n"
                "iTunes > 環境設定 > 詳細 で\n"
                "「ほかのアプリケーションと iTunes ライブラリ XML を共有」\n"
                "にチェックが入っているか確認してください。"
            )
            root.destroy()
            return

        try:
            with open(self.xml_path, "rb") as f:
                self.library = plistlib.load(f)
        except Exception as e:
            messagebox.showerror("エラー", f"iTunes XMLを読み込めませんでした。\n\n{e}")
            root.destroy()
            return

        self.all_playlists = self.get_playlists()
        self.filtered_playlists = list(self.all_playlists)
        self.playlist_map = {
            p["Name"]: p
            for p in self.library.get("Playlists", [])
            if p.get("Name")
        }
        self.selected_playlist = None
        self.folder_touched = False
        self._cached_tracks = None

        self.playlist_var = tk.StringVar()
        self.build_ui()
        self.init_selection()

    def label(self, master, text, size=13, weight="normal", color=None, bg=None):
        return tk.Label(
            master,
            text=text,
            font=("Helvetica", size, weight),
            fg=color or self.text,
            bg=bg or master["bg"],
            anchor="w"
        )

    def get_playlists(self):
        result = []
        for playlist in self.library.get("Playlists", []):
            name = playlist.get("Name")
            items = playlist.get("Playlist Items")
            if not name or playlist.get("Master") or not items:
                continue
            result.append(name)
        return sorted(result)

    def field_shell(self, master, height=42):
        shell = tk.Frame(master, bg=self.field, highlightbackground=self.line, highlightthickness=1)
        shell.configure(height=height)
        shell.pack_propagate(False)
        return shell

    def build_ui(self):
        outer = tk.Frame(self.root, bg=self.bg)
        outer.pack(fill="both", expand=True)

        # ── Footer (fixed at bottom) ──────────────────────────────────────
        footer = tk.Frame(outer, bg="#0B1118", highlightbackground=self.line, highlightthickness=1)
        footer.pack(fill="x", side="bottom")

        footer_inner = tk.Frame(footer, bg="#0B1118")
        footer_inner.pack(fill="x", padx=24, pady=8)

        self.status_var = tk.StringVar(value="準備完了")
        tk.Label(
            footer_inner,
            textvariable=self.status_var,
            bg="#0B1118",
            fg=self.green,
            font=("Helvetica", 12, "bold")
        ).pack(side="left")

        self.progress = tk.Canvas(footer_inner, height=6, bg="#0B1118", highlightthickness=0, width=200)
        self.progress.pack(side="left", padx=(18, 0))

        self.open_button = RoundButton(
            footer_inner,
            "出力先を開く",
            command=self.open_current_output,
            width=120,
            height=34,
            bg="#1A2430",
            fg=self.text,
            font=("Helvetica", 11, "bold"),
            radius=12
        )
        self.open_button.pack(side="right")

        # ── Main area (no scroll) ─────────────────────────────────────────
        main = tk.Frame(outer, bg=self.bg)
        main.pack(fill="both", expand=True)

        pad = dict(padx=24)

        # ── Header ───────────────────────────────────────────────────────
        header = tk.Frame(main, bg=self.bg)
        header.pack(fill="x", pady=(12, 10), **pad)

        icon = tk.Canvas(header, width=36, height=36, bg=self.bg, highlightthickness=0)
        icon.pack(side="left", padx=(0, 10))
        icon.create_rectangle(3, 3, 33, 33, fill="#204DFF", outline="#204DFF")
        icon.create_text(18, 19, text="♫", fill="white", font=("Helvetica", 18, "bold"))

        title_box = tk.Frame(header, bg=self.bg)
        title_box.pack(side="left", fill="x", expand=True)
        self.label(title_box, "USBプレイリスト屋さん太郎", size=20, weight="bold", bg=self.bg).pack(anchor="w")
        self.label(title_box, "for iTunes", size=11, color=self.sub, bg=self.bg).pack(anchor="w")

        # ── Search + Playlist list (2カラム風に横並び) ───────────────────
        # 検索とリストを左カラム、フォルダ名・保存先を右カラムに分ける
        columns = tk.Frame(main, bg=self.bg)
        columns.pack(fill="both", expand=True, **pad, pady=(0, 6))
        columns.columnconfigure(0, weight=1)
        columns.columnconfigure(1, weight=1)

        # ── 左カラム: 検索 + プレイリスト ────────────────────────────────
        left = tk.Frame(columns, bg=self.bg)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.label(left, "🔍  検索", size=12, weight="bold", bg=self.bg).pack(anchor="w", pady=(0, 4))
        self.search_var = tk.StringVar()
        self.search_entry = DarkEntry(left, self.search_var)
        self.search_entry.pack(fill="x", ipady=6, pady=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_playlists())

        self.label(left, "♫  プレイリスト", size=12, weight="bold", bg=self.bg).pack(anchor="w", pady=(0, 4))

        list_frame = tk.Frame(left, bg=self.panel, highlightbackground=self.line, highlightthickness=1)
        list_frame.pack(fill="both", expand=True)

        list_scroll = tk.Scrollbar(list_frame, orient="vertical")
        self.playlist_list = tk.Listbox(
            list_frame,
            bg=self.panel,
            fg=self.text,
            selectbackground=self.blue,
            selectforeground="white",
            relief="flat",
            highlightthickness=0,
            font=("Helvetica", 12),
            activestyle="none",
            yscrollcommand=list_scroll.set
        )
        list_scroll.config(command=self.playlist_list.yview)
        list_scroll.pack(side="right", fill="y", pady=4)
        self.playlist_list.pack(fill="both", expand=True, padx=6, pady=6)
        self.playlist_list.bind("<<ListboxSelect>>", self.on_list_select)

        # ── 右カラム: 曲数・フォルダ・保存先・容量 ───────────────────────
        right = tk.Frame(columns, bg=self.bg)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        self.info_var = tk.StringVar(value="")
        tk.Label(
            right,
            textvariable=self.info_var,
            bg=self.bg,
            fg=self.text,
            font=("Helvetica", 15, "bold"),
            anchor="w"
        ).pack(anchor="w", pady=(0, 10))

        self.label(right, "📁  保存フォルダ名", size=12, weight="bold", bg=self.bg).pack(anchor="w", pady=(0, 4))
        folder_row = tk.Frame(right, bg=self.bg)
        folder_row.pack(fill="x", pady=(0, 10))

        self.folder_name_var = tk.StringVar()
        self.folder_entry = DarkEntry(folder_row, self.folder_name_var)
        self.folder_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.folder_entry.bind("<KeyRelease>", self.on_folder_edit)

        use_btn = RoundButton(
            folder_row,
            "PL名",
            command=self.use_playlist_name,
            width=60,
            height=36,
            bg="#1A2430",
            fg=self.text,
            font=("Helvetica", 10, "bold"),
            radius=12
        )
        use_btn.pack(side="left", padx=(8, 0))

        self.label(right, "📂  保存先", size=12, weight="bold", bg=self.bg).pack(anchor="w", pady=(0, 4))
        dest_row = tk.Frame(right, bg=self.bg)
        dest_row.pack(fill="x", pady=(0, 4))

        dest_shell = self.field_shell(dest_row, height=36)
        dest_shell.pack(side="left", fill="x", expand=True)

        self.destination_var = tk.StringVar()
        self.dest_label = self.label(dest_shell, "", size=11, color=self.text, bg=self.field)
        self.dest_label.pack(fill="both", expand=True, padx=8, pady=6)

        change_btn = RoundButton(
            dest_row,
            "変更",
            command=self.choose_base_dir,
            width=60,
            height=36,
            bg="#1A2430",
            fg=self.text,
            font=("Helvetica", 10, "bold"),
            radius=12
        )
        change_btn.pack(side="left", padx=(8, 0))

        self.capacity_var = tk.StringVar(value="")
        self.capacity_label = tk.Label(
            right,
            textvariable=self.capacity_var,
            bg=self.bg,
            fg=self.sub,
            font=("Helvetica", 10),
            anchor="w"
        )
        self.capacity_label.pack(anchor="w", pady=(0, 10))

        # ── Mode (横並び) ─────────────────────────────────────────────────
        self.label(right, "☷  書き出しモード", size=12, weight="bold", bg=self.bg).pack(anchor="w", pady=(0, 4))

        mode_panel = tk.Frame(right, bg=self.panel, highlightbackground=self.line, highlightthickness=1)
        mode_panel.pack(fill="x")

        self.mode_var = tk.StringVar(value=self.config.get("mode", "playlist"))

        mode_row = tk.Frame(mode_panel, bg=self.panel)
        mode_row.pack(fill="x", padx=10, pady=8)

        for value, text in [("playlist", "プレイリスト順"), ("bpm_asc", "BPM順")]:
            tk.Radiobutton(
                mode_row,
                text=text,
                variable=self.mode_var,
                value=value,
                command=self.update_summary,
                bg=self.panel,
                fg=self.text,
                selectcolor=self.panel,
                activebackground=self.panel,
                activeforeground=self.text,
                font=("Helvetica", 12),
                relief="flat"
            ).pack(side="left", padx=(0, 16))

        # ── Export button ─────────────────────────────────────────────────
        self.export_button = RoundButton(
            main,
            "EXPORT",
            command=self.export_playlist,
            height=52,
            bg=self.blue,
            fg="white",
            font=("Helvetica", 16, "bold"),
            radius=16
        )
        self.export_button.pack(fill="x", pady=(8, 12), **pad)

    def init_selection(self):
        self.refresh_list()

        last = self.config.get("last_playlist")
        if last in self.all_playlists:
            self.select_playlist(last)
        elif self.all_playlists:
            self.select_playlist(self.all_playlists[0])
        self.draw_progress(0)

    def refresh_list(self):
        self.playlist_list.delete(0, "end")
        for name in self.filtered_playlists:
            self.playlist_list.insert("end", name)

    def filter_playlists(self):
        q = self.search_var.get().strip().lower()
        if not q:
            self.filtered_playlists = list(self.all_playlists)
        else:
            self.filtered_playlists = [p for p in self.all_playlists if q in p.lower()]

        self.refresh_list()

        if self.filtered_playlists:
            current = self.playlist_var.get()
            if current not in self.filtered_playlists:
                self.select_playlist(self.filtered_playlists[0])

    def on_list_select(self, event=None):
        sel = self.playlist_list.curselection()
        if not sel:
            return
        name = self.playlist_list.get(sel[0])
        self.select_playlist(name)

    def select_playlist(self, name):
        self.selected_playlist = name
        self.playlist_var.set(name)
        self.folder_name_var.set(safe_filename(name))
        self.folder_touched = False
        self.update_destination_label()
        self.update_summary()

        try:
            idx = self.filtered_playlists.index(name)
            self.playlist_list.selection_clear(0, "end")
            self.playlist_list.selection_set(idx)
            self.playlist_list.see(idx)
        except Exception:
            pass

    def on_folder_edit(self, event=None):
        self.folder_touched = True
        self.update_destination_label()
        self.update_capacity()

    def use_playlist_name(self):
        self.folder_name_var.set(safe_filename(self.playlist_var.get()))
        self.folder_touched = False
        self.update_destination_label()

    def choose_base_dir(self):
        chosen = filedialog.askdirectory(title="保存先を選択", initialdir=self.export_base_dir)
        if chosen:
            self.export_base_dir = chosen
            self.config["last_dir"] = chosen
            save_config(self.config)
            self.update_destination_label()
            self.update_capacity()

    def update_destination_label(self):
        folder = safe_filename(self.folder_name_var.get() or self.playlist_var.get() or "Export")
        self.destination_var.set(str(Path(self.export_base_dir) / folder))
        try:
            self.dest_label.config(text=self.destination_var.get())
        except Exception:
            pass

    def get_playlist_by_name(self, name):
        return self.playlist_map.get(name)

    def track_path_from_location(self, location):
        if not location:
            return None
        return Path(unquote(urlparse(location).path))

    def collect_tracks(self, playlist):
        tracks_db = self.library.get("Tracks", {})
        items = playlist.get("Playlist Items", [])
        tracks = []

        for index, item in enumerate(items, start=1):
            track = tracks_db.get(str(item.get("Track ID")))
            if not track:
                continue

            src = self.track_path_from_location(track.get("Location"))
            if not src or not src.exists():
                continue

            bpm = track.get("BPM")
            try:
                bpm_value = int(round(float(bpm))) if bpm is not None else None
            except Exception:
                bpm_value = None

            try:
                size = src.stat().st_size
            except Exception:
                size = 0

            tracks.append({
                "index": index,
                "src": src,
                "name": safe_filename(track.get("Name") or src.stem),
                "bpm": bpm_value,
                "ext": src.suffix,
                "size": size,
            })

        return tracks

    def get_sorted_tracks(self, tracks):
        if self.mode_var.get() == "bpm_asc":
            return sorted(
                tracks,
                key=lambda t: (
                    t["bpm"] is None,
                    t["bpm"] if t["bpm"] is not None else 9999,
                    t["index"]
                )
            )
        return sorted(tracks, key=lambda t: t["index"])

    def update_summary(self):
        playlist = self.get_playlist_by_name(self.playlist_var.get())
        if not playlist:
            self.info_var.set("")
            self._cached_tracks = None
            return

        tracks = self.collect_tracks(playlist)
        self._cached_tracks = tracks
        total_size = sum(t["size"] for t in tracks)
        self.current_total_size = total_size
        self.info_var.set(f"{len(tracks)}曲 / {human_size(total_size)}")
        self.update_capacity()
        self.draw_progress(0)

    def update_capacity(self):
        base = Path(self.export_base_dir)
        free = free_space(base)
        total = getattr(self, "current_total_size", 0)

        if free is None:
            self.capacity_var.set("")
            self.capacity_label.config(fg=self.sub)
            return

        if free >= total:
            self.capacity_var.set(f"空き容量 {human_size(free)} / 必要容量 {human_size(total)}   ✓ 容量OK")
            self.capacity_label.config(fg=self.green)
        else:
            self.capacity_var.set(f"空き容量 {human_size(free)} / 必要容量 {human_size(total)}   ✕ 容量不足")
            self.capacity_label.config(fg=self.red)

    def current_output_dir(self):
        folder = safe_filename(self.folder_name_var.get() or self.playlist_var.get() or "Export")
        return Path(self.export_base_dir) / folder

    def open_current_output(self):
        target = self.current_output_dir()
        if target.exists():
            open_folder(target)
        elif Path(self.export_base_dir).exists():
            open_folder(Path(self.export_base_dir))

    def draw_progress(self, pct):
        self.progress.delete("all")
        w = self.progress.winfo_width() or 240
        h = 8
        self.progress.create_rectangle(0, 0, w, h, fill="#1A2430", outline="#1A2430")
        self.progress.create_rectangle(0, 0, int(w * pct), h, fill=self.blue, outline=self.blue)

    def make_filename(self, track, new_index, digits):
        if self.mode_var.get() == "playlist":
            return f"{new_index:0{digits}d} {track['name']}{track['ext']}"
        bpm = track["bpm"]
        prefix = f"{bpm} " if bpm is not None else ""
        return f"{prefix}{track['name']}{track['ext']}"

    def export_playlist(self):
        playlist_name = self.playlist_var.get()
        playlist = self.get_playlist_by_name(playlist_name)

        if not playlist:
            messagebox.showerror("エラー", "プレイリストが見つかりません。")
            return

        folder_name = safe_filename(self.folder_name_var.get())
        if not folder_name:
            messagebox.showerror("エラー", "保存フォルダ名を入力してください。")
            return

        tracks = self.get_sorted_tracks(
            self._cached_tracks if self._cached_tracks is not None
            else self.collect_tracks(playlist)
        )
        if not tracks:
            messagebox.showerror("エラー", "コピーできる曲が見つかりませんでした。")
            return

        total_size = sum(t["size"] for t in tracks)
        free = free_space(Path(self.export_base_dir))
        if free is not None and free < total_size:
            ok = messagebox.askyesno(
                "容量不足",
                "保存先の空き容量が不足している可能性があります。\n\nそれでも書き出しますか？"
            )
            if not ok:
                return

        self.config["last_dir"] = self.export_base_dir
        self.config["last_playlist"] = playlist_name
        self.config["mode"] = self.mode_var.get()
        save_config(self.config)

        target_dir = self.current_output_dir()
        target_dir.mkdir(parents=True, exist_ok=True)

        self.export_button.set_enabled(False)
        self.status_var.set("書き出し中...")

        thread = threading.Thread(
            target=self._do_export,
            args=(tracks, target_dir),
            daemon=True
        )
        thread.start()

    def _do_export(self, tracks, target_dir):
        copied = 0
        errors = 0
        digits = max(2, len(str(len(tracks))))

        for new_index, track in enumerate(tracks, start=1):
            try:
                filename = self.make_filename(track, new_index, digits)
                dst = target_dir / filename

                if dst.exists():
                    base = dst.stem
                    suffix = dst.suffix
                    for n in range(2, 10000):
                        candidate = target_dir / f"{base} ({n}){suffix}"
                        if not candidate.exists():
                            dst = candidate
                            break
                    else:
                        raise RuntimeError(f"重複ファイル名の上限に達しました: {base}")

                shutil.copy2(track["src"], dst)
                copied += 1
            except Exception as e:
                print(f"[WARN] copy failed: {track.get('src')} -> {e}")
                errors += 1

            pct = new_index / len(tracks)
            self.root.after(0, lambda p=pct, i=new_index, total=len(tracks): (
                self.draw_progress(p),
                self.status_var.set(f"{i}/{total}")
            ))

        self.root.after(0, lambda: self._export_done(copied, errors, target_dir))

    def _export_done(self, copied, errors, target_dir):
        self.export_button.set_enabled(True)
        self.status_var.set("完了")
        open_folder(target_dir)
        if errors:
            messagebox.showwarning("完了", f"{copied}曲を書き出しました。\n{errors}曲はコピーできませんでした。")
        else:
            messagebox.showinfo("完了", f"{copied}曲を書き出しました。\n\n出力フォルダを開きました。")


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
