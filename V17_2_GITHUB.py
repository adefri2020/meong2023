import csv
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_CSV = Path(
    __import__("os").environ.get(
        "INPUT_CSV",
        str(BASE_DIR / "videos.csv")
    )
)
OUTPUT_CSV = Path(
    __import__("os").environ.get(
        "OUTPUT_CSV",
        str(BASE_DIR / "hasil_test_play_button.csv")
    )
)

# Posisi resume = posisi terakhir yang valid + 2 detik
RESUME_OFFSET = 2.0

# Jika URL timestamp target gagal,
# coba timestamp sedikit lebih awal.
TIMESTAMP_FALLBACK_BACKOFF = 5.0

# Stall dianggap terjadi jika currentTime tidak bergerak
# selama waktu berikut.
STALL_TIMEOUT = 4.0

# Hard reset harus terdeteksi beberapa kali berturut-turut.
RESET_CONFIRM_COUNT = 2

# Interval pemeriksaan player
CHECK_INTERVAL = 0.25

# Maksimum recovery per video
MAX_RECOVERY = 5

# Timeout menunggu player baru
PLAYER_TIMEOUT = 20

# Timeout memastikan playback benar-benar bergerak
MOVE_TIMEOUT = 8

# Timeout setelah membuka URL timestamp
TIMESTAMP_START_TIMEOUT = 12

# Batas maksimum satu GitHub Actions job.
# Setelah 90 menit, video aktif dihentikan dan hasil terakhir ditulis.
MAX_RUN_SECONDS = 90 * 60


# ============================================================
# FIND VIDEO
# ============================================================

def find_video(page):

    try:

        video = page.locator("video").first

        if video.count() > 0:
            return video

    except Exception:
        pass

    return None


# ============================================================
# GET VIDEO STATE
# ============================================================

def get_video_state(video):

    try:

        return video.evaluate("""
        v => {

            let bufferedEnd = 0;

            try {
                if (v.buffered && v.buffered.length > 0) {
                    bufferedEnd =
                        v.buffered.end(
                            v.buffered.length - 1
                        );
                }
            } catch(e) {}

            return {
                current: Number(v.currentTime || 0),
                duration: Number(v.duration || 0),
                paused: Boolean(v.paused),
                ended: Boolean(v.ended),
                seeking: Boolean(v.seeking),
                ready: Number(v.readyState || 0),
                network: Number(v.networkState || 0),
                bufferedEnd: Number(bufferedEnd || 0)
            };
        }
        """)

    except Exception:

        return {
            "current": 0,
            "duration": 0,
            "paused": True,
            "ended": False,
            "seeking": False,
            "ready": 0,
            "network": 0,
            "bufferedEnd": 0
        }


# ============================================================
# PLAY VIDEO
# ============================================================

def play_video(video):

    try:

        return video.evaluate("""
        async v => {

            try {

                v.muted = true;

                await v.play();

                return {
                    ok: true,
                    current: v.currentTime,
                    paused: v.paused,
                    ready: v.readyState
                };

            } catch(e) {

                return {
                    ok: false,
                    error:
                        e.name + ": " + e.message,
                    current: v.currentTime,
                    paused: v.paused,
                    ready: v.readyState
                };
            }
        }
        """)

    except Exception as e:

        return {
            "ok": False,
            "error": str(e)
        }


# ============================================================
# HARD RESET
# ============================================================

def is_hard_reset(state):

    return (
        state["current"] <= 0.05
        and state["duration"] <= 0.05
        and state["ready"] == 0
        and state["network"] == 0
        and state["bufferedEnd"] <= 0.05
    )


# ============================================================
# SET TIMESTAMP URL
# ============================================================

def make_timestamp_url(url, seconds):

    seconds = max(
        0,
        int(round(seconds))
    )

    parts = urlsplit(url)

    query = dict(
        parse_qsl(
            parts.query,
            keep_blank_values=True
        )
    )

    # Hapus parameter timestamp lama
    query.pop("t", None)
    query.pop("start", None)

    # YouTube timestamp
    query["t"] = f"{seconds}s"

    new_query = urlencode(query)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            new_query,
            parts.fragment
        )
    )


# ============================================================
# WAIT VIDEO ELEMENT
# ============================================================

def wait_video_element(page, timeout=PLAYER_TIMEOUT):

    start = time.time()

    while time.time() - start < timeout:

        video = find_video(page)

        if video is not None:

            try:

                state = get_video_state(video)

                if state["duration"] > 1:

                    return video

            except Exception:
                pass

        time.sleep(0.25)

    return None


# ============================================================
# WAIT PLAYER READY
# ============================================================

def wait_player_ready(
    page,
    video,
    timeout=PLAYER_TIMEOUT
):

    start = time.time()

    while time.time() - start < timeout:

        state = get_video_state(video)

        if (
            state["duration"] > 1
            and state["ready"] >= 2
        ):

            return True

        time.sleep(0.25)

    return False


# ============================================================
# WAIT VIDEO MOVING
# ============================================================

def wait_video_moving(
    video,
    timeout=MOVE_TIMEOUT
):

    start = time.time()

    previous = None

    while time.time() - start < timeout:

        state = get_video_state(video)

        current = state["current"]

        if previous is not None:

            delta = current - previous

            if (
                delta >= 0.08
                and not state["paused"]
                and not state["ended"]
                and state["ready"] >= 2
            ):

                return True

        previous = current

        time.sleep(0.25)

    return False


# ============================================================
# WAIT UNTIL TIMESTAMP TARGET IS ACTIVE
# ============================================================

def wait_timestamp_playback(
    page,
    video,
    target,
    timeout=TIMESTAMP_START_TIMEOUT
):

    start = time.time()

    previous = None

    while time.time() - start < timeout:

        state = get_video_state(video)

        current = state["current"]

        print(
            f"      Timestamp check: "
            f"current={current:.2f} "
            f"target={target:.2f} "
            f"ready={state['ready']} "
            f"paused={state['paused']} "
            f"seeking={state['seeking']} "
            f"buffer={state['bufferedEnd']:.2f}"
        )

        # ----------------------------------------------------
        # Hard reset
        # ----------------------------------------------------

        if is_hard_reset(state):

            return False

        # ----------------------------------------------------
        # Timestamp reached / near target
        # ----------------------------------------------------

        if (
            abs(current - target) <= 3.0
            and state["ready"] >= 2
            and not state["paused"]
        ):

            if previous is not None:

                delta = current - previous

                if delta >= 0.08:

                    print(
                        "      ✓ Timestamp playback bergerak"
                    )

                    return True

        previous = current

        # ----------------------------------------------------
        # Kalau paused, play lagi
        # ----------------------------------------------------

        if (
            state["paused"]
            and not state["ended"]
        ):

            play_video(video)

        time.sleep(0.25)

    return False


# ============================================================
# OPEN URL TIMESTAMP
# ============================================================

def open_timestamp(
    page,
    base_url,
    target
):

    timestamp_url = make_timestamp_url(
        base_url,
        target
    )

    print()
    print(
        f"      Buka URL timestamp:"
    )

    print(
        f"      t={int(round(target))}s"
    )

    print(
        f"      {timestamp_url}"
    )

    try:

        page.goto(
            timestamp_url,
            wait_until="domcontentloaded",
            timeout=30000
        )

    except Exception as e:

        print(
            f"      goto warning: {e}"
        )

    video = wait_video_element(page)

    if video is None:

        print(
            "      ✗ Video tidak ditemukan"
        )

        return None, False

    if not wait_player_ready(
        page,
        video
    ):

        print(
            "      ✗ Player tidak ready"
        )

        return video, False

    state = get_video_state(video)

    print(
        f"      Player siap: "
        f"current={state['current']:.2f}, "
        f"duration={state['duration']:.2f}, "
        f"ready={state['ready']}"
    )

    result = play_video(video)

    print(
        f"      Play: {result}"
    )

    time.sleep(0.8)

    success = wait_timestamp_playback(
        page,
        video,
        target
    )

    return video, success


# ============================================================
# URL TIMESTAMP RECOVERY
# ============================================================

def timestamp_recovery(
    page,
    base_url,
    last_position
):

    target = last_position + RESUME_OFFSET

    print()
    print("=" * 70)
    print("   URL-TIMESTAMP RECOVERY")
    print("=" * 70)

    print(
        f"   Last valid : {last_position:.2f}s"
    )

    print(
        f"   Target     : {target:.2f}s"
    )

    # ========================================================
    # ATTEMPT 1
    # ========================================================

    video, success = open_timestamp(
        page,
        base_url,
        target
    )

    if success:

        state = get_video_state(video)

        print()
        print(
            f"      ✓ URL TIMESTAMP BERHASIL "
            f"di {state['current']:.2f}s"
        )

        return True, video

    print()
    print(
        "      ✗ URL timestamp target gagal"
    )

    # ========================================================
    # ATTEMPT 2
    # TIMESTAMP LEBIH AWAL
    # ========================================================

    fallback_target = max(
        0,
        target - TIMESTAMP_FALLBACK_BACKOFF
    )

    print()
    print(
        f"      FALLBACK TIMESTAMP "
        f"→ {fallback_target:.2f}s"
    )

    video, success = open_timestamp(
        page,
        base_url,
        fallback_target
    )

    if not success:

        print(
            "      ✗ Fallback timestamp gagal"
        )

        return False, video

    print()
    print(
        "      ✓ Playback mulai dari fallback"
    )

    # ========================================================
    # NATURAL CATCH-UP
    # ========================================================

    print()
    print(
        f"      Natural catch-up "
        f"→ target {target:.2f}s"
    )

    start = time.time()

    previous = None

    while time.time() - start < 20:

        state = get_video_state(video)

        current = state["current"]

        print(
            f"      Catch-up: "
            f"{current:.2f} / {target:.2f} "
            f"ready={state['ready']} "
            f"paused={state['paused']} "
            f"seeking={state['seeking']}"
        )

        # ----------------------------------------------------
        # Target tercapai
        # ----------------------------------------------------

        if (
            current >= target - 0.5
            and state["ready"] >= 2
            and not state["paused"]
            and not state["ended"]
        ):

            print()
            print(
                f"      ✓ TARGET TERCAPAI "
                f"di {current:.2f}s"
            )

            return True, video

        # ----------------------------------------------------
        # Hard reset
        # ----------------------------------------------------

        if is_hard_reset(state):

            print(
                "      ✗ Hard reset saat catch-up"
            )

            return False, video

        # ----------------------------------------------------
        # Playback pause
        # ----------------------------------------------------

        if (
            state["paused"]
            and not state["ended"]
        ):

            play_video(video)

        previous = current

        time.sleep(0.4)

    print(
        "      ✗ Natural catch-up timeout"
    )

    return False, video


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print(" V17.1 GITHUB - URL-TIMESTAMP RECOVERY + STALL DETECTION")
    print("=" * 70)
    print()

    # ========================================================
    # READ CSV
    # ========================================================

    if not INPUT_CSV.exists():

        print(
            f"ERROR CSV tidak ditemukan:"
        )

        print(
            INPUT_CSV
        )

        return

    rows = []

    with open(
        INPUT_CSV,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            rows.append(row)

    print(
        f"Total video: {len(rows)}"
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    output_fields = [
        "nama",
        "url",
        "judul",
        "waktu_tunggu_detik",
        "Space",
        "pause_space",
        "durasi_aktual_detik",
        "status"
    ]

    results = []

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    with sync_playwright() as p:

        browser = None
        context = None
        page = None

        try:

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-extensions",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--disable-translate",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-features=Translate,MediaRouter"
                ]
            )

            context = browser.new_context(
                viewport={
                    "width": 1280,
                    "height": 800
                }
            )

            page = context.new_page()

            # =================================================
            # RAM OPTIMIZATION
            # =================================================
            # Gambar/thumbnail tidak diperlukan untuk pengujian
            # playback + recovery. Media/video TIDAK diblokir.
            # Ini lebih aman daripada mematikan GPU atau media.
            def lightweight_route(route):
                try:
                    if route.request.resource_type == "image":
                        route.abort()
                    else:
                        route.continue_()
                except Exception:
                    try:
                        route.continue_()
                    except Exception:
                        pass

            page.route("**/*", lightweight_route)

            # =================================================
            # EACH VIDEO
            # =================================================

            for index, row in enumerate(
                rows,
                start=1
            ):

                nama = row.get(
                    "nama",
                    ""
                ).strip()

                url = row.get(
                    "url",
                    ""
                ).strip()

                durasi_target = row.get(
                    "durasi",
                    ""
                ).strip()

                print()
                print()
                print("#" * 70)

                print(
                    f"VIDEO {index:02d}"
                )

                print(
                    f"Nama   : {nama}"
                )

                print(
                    f"URL    : {url}"
                )

                print(
                    f"Durasi : {durasi_target}"
                )

                print("#" * 70)

                # ---------------------------------------------
                # OPEN ORIGINAL URL
                # ---------------------------------------------

                try:

                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )

                except Exception as e:

                    print(
                        f"goto warning: {e}"
                    )

                # ---------------------------------------------
                # FIND VIDEO
                # ---------------------------------------------

                video = wait_video_element(page)

                if video is None:

                    print(
                        "VIDEO TIDAK DITEMUKAN"
                    )

                    results.append({
                        "nama": nama,
                        "url": url,
                        "judul": "",
                        "waktu_tunggu_detik": 0,
                        "Space": "",
                        "pause_space": "",
                        "durasi_aktual_detik": 0,
                        "status": "VIDEO_NOT_FOUND"
                    })

                    continue

                # ---------------------------------------------
                # TITLE
                # ---------------------------------------------

                try:

                    title = page.title()

                except Exception:

                    title = ""

                # ---------------------------------------------
                # START PLAYBACK
                # ---------------------------------------------

                result = play_video(video)

                print(
                    f"Play: {result}"
                )

                time.sleep(1)

                state = get_video_state(video)

                print(
                    f"Initial: "
                    f"current={state['current']:.2f}, "
                    f"duration={state['duration']:.2f}, "
                    f"ready={state['ready']}"
                )

                # =================================================
                # TIMER
                # =================================================

                active_play_time = 0.0

                last_position = state["current"]

                previous_current = state["current"]

                last_movement_time = time.time()

                reset_count = 0

                recovery_count = 0

                status = "RUNNING"

                start_time = time.time()

                # =================================================
                # MONITOR
                # =================================================

                while True:

                    time.sleep(
                        CHECK_INTERVAL
                    )

                    # =================================================
                    # MAX JOB TIME (GITHUB)
                    # =================================================
                    if time.time() - start_time >= MAX_RUN_SECONDS:
                        print()
                        print("BATAS 90 MENIT TERCAPAI")
                        status = "MAX_RUN_90_MIN"
                        break

                    state = get_video_state(
                        video
                    )

                    current = state["current"]

                    now = time.time()

                    moved = (
                        current
                        - previous_current
                    )

                    # ---------------------------------------------
                    # PLAYBACK MOVING
                    # ---------------------------------------------

                    if (
                        moved >= 0.08
                        and not state["paused"]
                        and not state["ended"]
                        and state["ready"] >= 2
                    ):

                        active_play_time += CHECK_INTERVAL

                        last_position = current

                        last_movement_time = now

                    # ---------------------------------------------
                    # LOG
                    # ---------------------------------------------

                    print(
                        f"[{active_play_time:6.1f}s] "
                        f"current={current:7.2f} "
                        f"duration={state['duration']:7.2f} "
                        f"ready={state['ready']} "
                        f"paused={state['paused']} "
                        f"seeking={state['seeking']} "
                        f"buffer={state['bufferedEnd']:7.2f}"
                    )

                    # =================================================
                    # HARD RESET
                    # =================================================

                    if is_hard_reset(state):

                        reset_count += 1

                    else:

                        reset_count = 0

                    # =================================================
                    # STALL DETECTION
                    # =================================================

                    stall_time = (
                        now
                        - last_movement_time
                    )

                    # Stall hanya dianggap valid kalau:
                    #
                    # - video belum selesai
                    # - current > 0
                    # - duration valid
                    # - tidak sedang seek
                    # - tidak paused
                    # - sudah tidak bergerak cukup lama

                    stalled = (
                        stall_time >= STALL_TIMEOUT
                        and current > 0.5
                        and state["duration"] > 1
                        and not state["paused"]
                        and not state["ended"]
                        and not state["seeking"]
                    )

                    # =================================================
                    # RECOVERY TRIGGER
                    # =================================================

                    recovery_reason = None

                    if (
                        reset_count
                        >= RESET_CONFIRM_COUNT
                    ):

                        recovery_reason = (
                            "HARD_RESET"
                        )

                    elif stalled:

                        recovery_reason = (
                            "STALL"
                        )

                    # =================================================
                    # RECOVERY
                    # =================================================

                    if recovery_reason:

                        print()
                        print(
                            "!" * 70
                        )

                        print(
                            f"{recovery_reason} TERDETEKSI"
                        )

                        print(
                            f"Last valid position: "
                            f"{last_position:.2f}s"
                        )

                        print(
                            f"Active timer: "
                            f"{active_play_time:.1f}s"
                        )

                        print(
                            f"Target resume: "
                            f"{last_position + RESUME_OFFSET:.2f}s"
                        )

                        print(
                            "!" * 70
                        )

                        # ---------------------------------------------
                        # MAX RECOVERY
                        # ---------------------------------------------

                        if recovery_count >= MAX_RECOVERY:

                            print(
                                "MAX RECOVERY TERCAPAI"
                            )

                            status = (
                                "MAX_RECOVERY_FAILED"
                            )

                            break

                        recovery_count += 1

                        # ---------------------------------------------
                        # URL TIMESTAMP RECOVERY
                        # ---------------------------------------------

                        success, new_video = (
                            timestamp_recovery(
                                page,
                                url,
                                last_position
                            )
                        )

                        if success:

                            video = new_video

                            state = get_video_state(
                                video
                            )

                            print()
                            print(
                                "✓ RECOVERY BERHASIL"
                            )

                            print(
                                f"Posisi sekarang: "
                                f"{state['current']:.2f}s"
                            )

                            print(
                                f"Active timer tetap: "
                                f"{active_play_time:.1f}s"
                            )

                            # -----------------------------------------
                            # IMPORTANT
                            # -----------------------------------------

                            previous_current = (
                                state["current"]
                            )

                            last_movement_time = (
                                time.time()
                            )

                            reset_count = 0

                            continue

                        # ---------------------------------------------
                        # RECOVERY FAILED
                        # ---------------------------------------------

                        print()
                        print(
                            "✗ RECOVERY GAGAL"
                        )

                        status = (
                            "RECOVERY_FAILED"
                        )

                        break

                    # =================================================
                    # VIDEO ENDED
                    # =================================================

                    if (
                        state["ended"]
                        or (
                            state["duration"] > 1
                            and current
                            >= state["duration"] - 0.5
                        )
                    ):

                        print()
                        print(
                            "VIDEO SELESAI"
                        )

                        status = "SELESAI"

                        break

                    # =================================================
                    # TARGET ACTIVE TIME
                    # =================================================

                    try:

                        target_seconds = float(
                            durasi_target
                        )

                    except Exception:

                        target_seconds = 0

                    if (
                        target_seconds > 0
                        and active_play_time
                        >= target_seconds
                    ):

                        print()
                        print(
                            "TARGET DURASI TERCAPAI"
                        )

                        print(
                            f"Active time: "
                            f"{active_play_time:.1f}s"
                        )

                        status = (
                            "TARGET_TERCAPAI"
                        )

                        break

                    # =================================================
                    # UPDATE PREVIOUS
                    # =================================================

                    previous_current = current

                # =================================================
                # FINAL
                # =================================================

                elapsed = (
                    time.time()
                    - start_time
                )

                final_state = get_video_state(
                    video
                )

                final_position = (
                    final_state["current"]
                )

                print()
                print(
                    "-" * 70
                )

                print(
                    f"FINAL VIDEO {index:02d}"
                )

                print(
                    f"Active time : "
                    f"{active_play_time:.1f}s"
                )

                print(
                    f"Position    : "
                    f"{final_position:.2f}s"
                )

                print(
                    f"Recovery    : "
                    f"{recovery_count}"
                )

                print(
                    f"Elapsed     : "
                    f"{elapsed:.1f}s"
                )

                print(
                    f"Status      : "
                    f"{status}"
                )

                print(
                    "-" * 70
                )

                results.append({
                    "nama": nama,
                    "url": url,
                    "judul": title,
                    "waktu_tunggu_detik":
                        round(elapsed, 2),
                    "Space": "",
                    "pause_space": "",
                    "durasi_aktual_detik":
                        round(active_play_time, 2),
                    "status": status
                })

        finally:

            print()
            print(
                "Menutup browser..."
            )

            try:

                if page:
                    page.close()

            except Exception:
                pass

            try:

                if context:
                    context.close()

            except Exception:
                pass

            try:

                if browser:
                    browser.close()

            except Exception:
                pass

    # ========================================================
    # WRITE CSV
    # ========================================================

    with open(
        OUTPUT_CSV,
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=output_fields
        )

        writer.writeheader()

        writer.writerows(results)

    print()
    print("=" * 70)
    print("SEMUA VIDEO SELESAI")
    print("=" * 70)
    print(
        f"Output: {OUTPUT_CSV}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
