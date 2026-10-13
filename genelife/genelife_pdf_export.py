"""
GeneLife (https://genesis2.genelife.jp/) の検査項目ごとの PDF を一括保存し、
1つの PDF に統合するスクリプト（Windows のローカル PC で実行する想定）。

流れ:
  1. Chrome が開くので、手動でログインし「検査項目の一覧ページ」を表示する
  2. コンソールで Enter を押すと、一覧から各項目の PDF を順番に取得する
     - PDF ボタンがダウンロード / 新しいタブ / 印刷ダイアログのどれでも対応
  3. 個別 PDF と、しおり付きの統合 PDF を出力先フォルダに保存する

使い方:
  pip install playwright pypdf
  python genelife_pdf_export.py
  python genelife_pdf_export.py --out "D:\\別の保存先"
"""

import argparse
import datetime
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

START_URL = "https://genesis2.genelife.jp/"
DEFAULT_OUT = r"J:\マイドライブ\00_基本情報\99_健康関係\genelife"
PROFILE_DIR = Path(__file__).with_name(".genelife_profile")

# PDF 出力ボタンらしき要素
PDF_SELECTOR = (
    "a:has-text('PDF'), button:has-text('PDF'), [role=button]:has-text('PDF'), "
    "a[href$='.pdf'], a[href*='pdf'], a:has-text('印刷'), button:has-text('印刷')"
)
# 項目リンクとして扱わないもの
EXCLUDE_WORDS = ("logout", "ログアウト", "signout", "mypage/edit", "faq", "contact",
                 "privacy", "terms", "お問い合わせ", "よくある", "利用規約", "プライバシー")

# window.print() を横取りし、呼ばれたことを記録する
PRINT_HOOK = "window.print = () => { window.__printCalled = true; };"


def safe_name(text, limit=60):
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    return text[:limit] or "item"


def launch(p, headless):
    kwargs = dict(user_data_dir=str(PROFILE_DIR), headless=headless,
                  accept_downloads=True, locale="ja-JP")
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception:
        # Chrome が無い場合は Playwright 同梱の Chromium を使う
        return p.chromium.launch_persistent_context(**kwargs)


def login_and_pick_list(p):
    ctx = launch(p, headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(START_URL)
    print("\n=== ブラウザでログインし、検査項目の『一覧ページ』を表示してください ===")
    input("表示できたらこのウィンドウで Enter を押してください... ")
    page = ctx.pages[-1]
    list_url = page.url
    ctx.close()
    return list_url


def collect_items(page):
    """一覧ページから項目ページへのリンクを集める。"""
    host = urlparse(page.url).netloc
    seen, items = set(), []
    for a in page.locator("a[href]").all():
        href = a.get_attribute("href") or ""
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = page.evaluate("h => new URL(h, location.href).href.split('#')[0]", href)
        if urlparse(url).netloc != host or url.rstrip("/") == page.url.split("#")[0].rstrip("/"):
            continue
        try:
            text = a.inner_text(timeout=1000).strip()
        except PWTimeout:
            text = ""
        low = (url + " " + text).lower()
        if any(w.lower() in low for w in EXCLUDE_WORDS) or url in seen:
            continue
        seen.add(url)
        items.append((text or url.rsplit("/", 1)[-1], url))
    return items


def fetch_pdf(ctx, url, out_path):
    """ログイン済みセッションで url を取得し、中身が PDF なら保存する。"""
    if not url.startswith("http"):
        return False
    try:
        body = ctx.request.get(url).body()
    except Exception:
        return False
    if not body.startswith(b"%PDF"):
        return False
    out_path.write_bytes(body)
    return True


def grab_pdf(ctx, page, target, out_path):
    """target をクリックして得られた PDF を out_path に保存する。成功なら True。"""
    pdf_responses, new_pages = [], []

    def on_response(resp):
        if "application/pdf" in (resp.headers.get("content-type") or ""):
            pdf_responses.append(resp)

    def on_page(np):
        new_pages.append(np)

    ctx.on("page", on_page)
    ctx.on("response", on_response)
    page.evaluate("window.__printCalled = false")
    try:
        try:
            with page.expect_download(timeout=15000) as dl:
                target.click()
            dl.value.save_as(out_path)
            return True
        except PWTimeout:
            pass

        # ダウンロード以外: レスポンス / 新タブ / window.print のいずれか
        time.sleep(2)
        for url in [r.url for r in reversed(pdf_responses)] + [np.url for np in new_pages]:
            if fetch_pdf(ctx, url, out_path):
                return True
        for np in new_pages:
            # PDF ではなく印刷用ページが新しいタブで開いたケース
            np.wait_for_load_state()
            np.emulate_media(media="print")
            np.pdf(path=str(out_path), format="A4", print_background=True)
            np.close()
            return True
        if page.evaluate("window.__printCalled"):
            page.emulate_media(media="print")
            page.pdf(path=str(out_path), format="A4", print_background=True)
            return True
        return False
    finally:
        ctx.remove_listener("page", on_page)
        ctx.remove_listener("response", on_response)


def save_page_as_pdf(page, out_path):
    page.emulate_media(media="print")
    page.pdf(path=str(out_path), format="A4", print_background=True)


def export_all(p, list_url, out_dir):
    ctx = launch(p, headless=True)  # page.pdf() はヘッドレスでのみ使える
    ctx.add_init_script(PRINT_HOOK)
    page = ctx.new_page()
    page.goto(list_url, wait_until="networkidle")

    saved = []
    buttons = page.locator(PDF_SELECTOR)
    n_buttons = buttons.count()

    if n_buttons > 1:
        # 一覧ページ上に項目ごとの PDF ボタンが並んでいるケース
        print(f"一覧ページ上に PDF ボタンを {n_buttons} 個検出しました。")
        for i in range(n_buttons):
            btn = page.locator(PDF_SELECTOR).nth(i)
            label = btn.evaluate(
                "e => (e.closest('tr,li,section,article,div') || e).innerText.split('\\n')[0]")
            out = out_dir / f"{i + 1:02d}_{safe_name(label)}.pdf"
            ok = grab_pdf(ctx, page, btn, out)
            print(f"  [{'OK' if ok else 'NG'}] {out.name}")
            if ok:
                saved.append((label, out))
            if page.url.split("#")[0] != list_url.split("#")[0]:
                page.goto(list_url, wait_until="networkidle")
    else:
        # 各項目ページを開いて、その中の PDF ボタンを押すケース
        items = collect_items(page)
        print(f"項目リンクを {len(items)} 件検出しました。")
        for i, (title, url) in enumerate(items, 1):
            page.goto(url, wait_until="networkidle")
            heading = page.locator("h1, h2").first
            if heading.count():
                title = heading.inner_text().strip() or title
            out = out_dir / f"{i:02d}_{safe_name(title)}.pdf"
            btn = page.locator(PDF_SELECTOR).first
            ok = btn.count() > 0 and grab_pdf(ctx, page, btn, out)
            if not ok:
                # PDF ボタンが無いページは画面をそのまま PDF 化
                save_page_as_pdf(page, out)
                print(f"  [画面保存] {out.name}")
            else:
                print(f"  [OK] {out.name}")
            saved.append((title, out))

    ctx.close()
    return saved


def merge(saved, out_dir):
    writer = PdfWriter()
    for title, path in saved:
        try:
            reader = PdfReader(str(path))
        except Exception as e:
            print(f"  統合スキップ（読めないPDF）: {path.name} ({e})")
            continue
        start = len(writer.pages)
        for pg in reader.pages:
            writer.add_page(pg)
        writer.add_outline_item(title, start)
    merged = out_dir / f"genelife_全項目_統合_{datetime.date.today():%Y%m%d}.pdf"
    with open(merged, "wb") as f:
        writer.write(f)
    return merged, len(writer.pages)


def main():
    ap = argparse.ArgumentParser(description="GeneLife の項目別 PDF を一括保存・統合")
    ap.add_argument("--out", default=DEFAULT_OUT, help="出力先フォルダ")
    ap.add_argument("--list-url", help="一覧ページの URL（ログイン済みならブラウザ操作を省略）")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        list_url = args.list_url or login_and_pick_list(p)
        print(f"一覧ページ: {list_url}")
        saved = export_all(p, list_url, out_dir)

    if not saved:
        print("PDF を1件も取得できませんでした。一覧ページを確認してください。")
        sys.exit(1)
    merged, pages = merge(saved, out_dir)
    print(f"\n完了: 個別 {len(saved)} 件 / 統合 {pages} ページ")
    print(f"保存先: {out_dir}")
    print(f"統合ファイル: {merged.name}")


if __name__ == "__main__":
    main()
