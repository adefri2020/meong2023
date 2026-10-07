# V17.1 GitHub Actions

Versi cloud dari V17.1. Laptop tidak perlu menyala ketika workflow sedang berjalan.

## Struktur repository

    V17_1_GITHUB.py
    videos.csv
    requirements.txt
    .github/workflows/v17_1.yml

## Jadwal

Workflow dijalankan:
- manual melalui Actions -> V17.1 YouTube Test -> Run workflow
- otomatis setiap 3 jam (`0 */3 * * *`, UTC)

Satu job dibatasi sekitar 90 menit oleh script dan 100 menit oleh GitHub Actions.

## Hasil

`hasil_test_play_button.csv` di-upload sebagai GitHub Actions Artifact selama 7 hari.

## Catatan

Versi GitHub memakai Chromium Playwright dalam mode headless. Tidak membuka jendela Chrome di laptop.
