# GeneLife PDF 一括出力

https://genesis2.genelife.jp/ の検査項目ごとの PDF をすべて保存し、しおり付きの統合 PDF も作ります。

## 使い方（Windows）
1. Python 3 をインストールしておく
2. `run_genelife_pdf.bat` をダブルクリック
3. Chrome が開くのでログインし、検査項目の**一覧ページ**を表示してからコンソールで Enter
4. `J:\マイドライブ\00_基本情報\99_健康関係\genelife` に以下が保存されます
   - `01_項目名.pdf`, `02_項目名.pdf`, …（項目ごと）
   - `genelife_全項目_統合_YYYYMMDD.pdf`（統合版）

出力先を変える場合: `run_genelife_pdf.bat --out "D:\保存先"`

PDF ボタンがダウンロード・新しいタブ表示・印刷ダイアログのどの方式でも取得します。
PDF ボタンが見つからない項目は画面を PDF 化して保存します。
