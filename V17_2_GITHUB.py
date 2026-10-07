import csv
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

from playwright.sync_api import sync_playwright


# ============================================================
# V17.3
# V17 + PERSISTENT CHROME PROFILE
# + YOUTUBE BOT-CHECK DETECTION
# + URL-TIMESTAMP RECOVERY
# + STALL DETECTION
# ============================================================


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_CSV = BASE_DIR / "videos.csv"
OUTPUT_CSV = BASE_DIR / "hasil_test_play_button.csv"

# Profile Chrome KHUSUS untuk automation.
# JANGAN gunakan profile Chrome utama.
CHROME_PROFILE = BASE_DIR / "chrome_profile_v17_3"

# Debug
DEBUG_DIR = BASE_DIR / "debug_v17_3"

# Resume = posisi terakhir valid + 2 detik
RESUME_OFFSET = 2.0

# Fallback timestamp
TIMESTAMP_FALLBACK_BACKOFF = 5.0

# Stall
STALL_TIMEOUT = 4.0

# Hard reset
RESET_CONFIRM_COUNT = 2

# Interval monitoring
CHECK_INTERVAL = 0.25

# Maximum recovery
MAX_RECOVERY = 5

# Player timeout
PLAYER_TIMEOUT = 25

# Playback movement timeout
MOVE_TIMEOUT = 8

# Timestamp start timeout
TIMESTAMP_START_TIMEOUT = 12

# Waktu memberi kesempatan manual menyelesaikan
# login / verification YouTube
BOT_CHECK_WAIT = 90


# ============================================================
# SAFE TEXT
# ============================================================

def safe_text(value):
    return str(value or "").strip()


# ============================================================
# DEBUG
# ============================================================

def save_debug(page, label):

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    txt_file = DEBUG_DIR / f"{label}.txt"
    png_file = DEBUG_DIR / f"{label}.png"

    try:
        url = page.url
    except Exception:
        url = ""

    try:
        title = page.title()
    except Exception:
        title = ""

    try:
        body = page.locator("body").inner_text(
            timeout=5000
        )
    except Exception as e:
        body = f"BODY ERROR: {e}"

    try:
        txt_file.write_text(
            "URL:\n"
            + url
            + "\n\nTITLE:\n"
            + title
            + "\n\nBODY:\n"
            + body,
            encoding="utf-8"
        )
    except Exception:
        pass

    try:
        page.screenshot(
            path=str(png_file),
            full_page=False
        )
    except Exception:
        pass

    print()
    print(
        f"      DEBUG URL   : {url}"
    )
    print(
        f"      DEBUG TITLE : {title}"
    )
    print(
        f"      DEBUG FILE  : {txt_file}"
    )

    return txt_file


# ============================================================
# YOUTUBE BOT CHECK DETECTION
# ============================================================

def youtube_bot_check(page):

    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=3000
        ).lower()

    except Exception:

        return False

    indicators = [

        "sign in to confirm you're not a bot",

        "sign in to confirm you’re not a bot",

        "confirm you're not a bot",

        "confirm you’re not a bot",

        "this helps protect our community",

        "not a bot"

    ]

    for indicator in indicators:

        if indicator in text:

            return True

    return False


# ============================================================
# WAIT FOR MANUAL BOT CHECK
# ============================================================

def wait_manual_bot_check(page):

    print()
    print("=" * 70)
    print("YOUTUBE BOT CHECK TERDETEKSI")
    print("=" * 70)

    print()
    print("YouTube meminta verifikasi.")
    print()
    print("Silakan selesaikan verifikasi secara MANUAL")
    print("pada browser Chrome yang terbuka.")
    print()
    print(
        f"Waktu tunggu maksimal: {BOT_CHECK_WAIT} detik"
    )
    print("=" * 70)

    start = time.time()

    while time.time() - start < BOT_CHECK_WAIT:

        if not youtube_bot_check(page):

            print()
            print(
                "✓ Bot-check sudah tidak terdeteksi."
            )

            return True

        remaining = (
            BOT_CHECK_WAIT
            - (time.time() - start)
        )

        print(
            f"      Menunggu verifikasi..."
            f" {max(0, remaining):.0f}s",
            end="\r",
            flush=True
        )

        time.sleep(2)

    print()

    print(
        "✗ Waktu verifikasi habis."
    )

    return False


# ============================================================
# FIND VIDEO
# ============================================================

def find_video(page):

    try:

        video = page.locator(
            "video"
        ).first

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

        return video.evaluate(
            """
            v => {

                let bufferedEnd = 0;

                try {

                    if (
                        v.buffered &&
                        v.buffered.length > 0
                    ) {

                        bufferedEnd =
                            v.buffered.end(
                                v.buffered.length - 1
                            );
                    }

                } catch(e) {}

                return {

                    current:
                        Number(
                            v.currentTime || 0
                        ),

                    duration:
                        Number(
                            v.duration || 0
                        ),

                    paused:
                        Boolean(v.paused),

                    ended:
                        Boolean(v.ended),

                    seeking:
                        Boolean(v.seeking),

                    ready:
                        Number(v.readyState || 0),

                    network:
                        Number(v.networkState || 0),

                    bufferedEnd:
                        Number(
                            bufferedEnd || 0
                        )
                };
            }
            """
        )

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

        return video.evaluate(
            """
            async v => {

                try {

                    v.muted = true;

                    await v.play();

                    return {

                        ok: true,

                        current:
                            v.currentTime,

                        paused:
                            v.paused,

                        ready:
                            v.readyState
                    };

                } catch(e) {

                    return {

                        ok: false,

                        error:
                            e.name + ": " + e.message,

                        current:
                            v.currentTime,

                        paused:
                            v.paused,

                        ready:
                            v.readyState
                    };
                }
            }
            """
        )

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
# TIMESTAMP URL
# ============================================================

def make_timestamp_url(
    url,
    seconds
):

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

    query.pop(
        "t",
        None
    )

    query.pop(
        "start",
        None
    )

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

def wait_video_element(
    page,
    timeout=PLAYER_TIMEOUT
):

    start = time.time()

    while time.time() - start < timeout:

        # -----------------------------------------
        # BOT CHECK
        # -----------------------------------------

        if youtube_bot_check(page):

            print()
            print(
                "      ! YouTube bot-check terdeteksi"
            )

            if not wait_manual_bot_check(page):

                return None

        # -----------------------------------------
        # FIND VIDEO
        # -----------------------------------------

        video = find_video(page)

        if video is not None:

            try:

                state = get_video_state(
                    video
                )

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

        state = get_video_state(
            video
        )

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

        state = get_video_state(
            video
        )

        current = state["current"]

        if previous is not None:

            delta = (
                current
                - previous
            )

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
# WAIT TIMESTAMP PLAYBACK
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

        state = get_video_state(
            video
        )

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

        # -----------------------------------------
        # HARD RESET
        # -----------------------------------------

        if is_hard_reset(state):

            return False

        # -----------------------------------------
        # TARGET
        # -----------------------------------------

        if (

            abs(
                current - target
            ) <= 3.0

            and state["ready"] >= 2

            and not state["paused"]
        ):

            if previous is not None:

                delta = (
                    current
                    - previous
                )

                if delta >= 0.08:

                    print(
                        "      ✓ Timestamp playback bergerak"
                    )

                    return True

        previous = current

        # -----------------------------------------
        # PAUSED
        # -----------------------------------------

        if (

            state["paused"]

            and not state["ended"]
        ):

            play_video(video)

        time.sleep(0.25)

    return False


# ============================================================
# OPEN TIMESTAMP
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
        "      Buka URL timestamp:"
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

    video = wait_video_element(
        page
    )

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

    state = get_video_state(
        video
    )

    print(
        f"      Player siap: "
        f"current={state['current']:.2f}, "
        f"duration={state['duration']:.2f}, "
        f"ready={state['ready']}"
    )

    result = play_video(
        video
    )

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
# TIMESTAMP RECOVERY
# ============================================================

def timestamp_recovery(
    page,
    base_url,
    last_position
):

    target = (
        last_position
        + RESUME_OFFSET
    )

    print()
    print("=" * 70)
    print("   URL-TIMESTAMP RECOVERY")
    print("=" * 70)

    print(
        f"   Last valid : "
        f"{last_position:.2f}s"
    )

    print(
        f"   Target     : "
        f"{target:.2f}s"
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

        state = get_video_state(
            video
        )

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
    # ========================================================

    fallback_target = max(
        0,
        target
        - TIMESTAMP_FALLBACK_BACKOFF
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

    while time.time() - start < 20:

        state = get_video_state(
            video
        )

        current = state["current"]

        print(
            f"      Catch-up: "
            f"{current:.2f} / {target:.2f} "
            f"ready={state['ready']} "
            f"paused={state['paused']} "
            f"seeking={state['seeking']}"
        )

        # -----------------------------------------
        # TARGET
        # -----------------------------------------

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

        # -----------------------------------------
        # HARD RESET
        # -----------------------------------------

        if is_hard_reset(state):

            print(
                "      ✗ Hard reset saat catch-up"
            )

            return False, video

        # -----------------------------------------
        # PAUSED
        # -----------------------------------------

        if (

            state["paused"]

            and not state["ended"]
        ):

            play_video(video)

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
    print(
        " V17.3"
    )
    print(
        " PERSISTENT CHROME + "
        "URL-TIMESTAMP RECOVERY + STALL DETECTION"
    )
    print("=" * 70)

    print()
    print(
        f"Chrome profile:"
    )

    print(
        CHROME_PROFILE
    )

    print()

    # ========================================================
    # CSV
    # ========================================================

    if not INPUT_CSV.exists():

        print(
            "ERROR CSV tidak ditemukan:"
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

        context = None
        page = None

        try:

            # =================================================
            # PERSISTENT CHROME
            # =================================================

            context = p.chromium.launch_persistent_context(

                user_data_dir=str(
                    CHROME_PROFILE
                ),

                headless=False,

                channel="chrome",

                viewport={
                    "width": 1280,
                    "height": 800
                },

                locale="en-US",

                args=[

                    "--disable-extensions",

                    "--autoplay-policy="
                    "no-user-gesture-required"
                ]
            )

            # Persistent context sudah memiliki
            # page sendiri bila Chrome membukanya.
            # Kita gunakan page pertama jika ada.

            if len(context.pages) > 0:

                page = context.pages[0]

            else:

                page = context.new_page()

            # =================================================
            # EACH VIDEO
            # =================================================

            for index, row in enumerate(
                rows,
                start=1
            ):

                nama = safe_text(
                    row.get("nama")
                )

                url = safe_text(
                    row.get("url")
                )

                durasi_target = safe_text(
                    row.get("durasi")
                )

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
                # OPEN ORIGINAL
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

                video = wait_video_element(
                    page
                )

                if video is None:

                    print()
                    print(
                        "VIDEO TIDAK DITEMUKAN"
                    )

                    debug_file = save_debug(
                        page,
                        f"video_{index:02d}_not_found"
                    )

                    print(
                        f"      DEBUG FILE : "
                        f"{debug_file}"
                    )

                    results.append({

                        "nama": nama,

                        "url": url,

                        "judul":
                            safe_text(
                                page.title()
                            ),

                        "waktu_tunggu_detik":
                            0,

                        "Space": "",

                        "pause_space": "",

                        "durasi_aktual_detik":
                            0,

                        "status":
                            "VIDEO_NOT_FOUND"
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
                # START
                # ---------------------------------------------

                result = play_video(
                    video
                )

                print(
                    f"Play: {result}"
                )

                time.sleep(1)

                state = get_video_state(
                    video
                )

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

                last_position = (
                    state["current"]
                )

                previous_current = (
                    state["current"]
                )

                last_movement_time = (
                    time.time()
                )

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

                        active_play_time += (
                            CHECK_INTERVAL
                        )

                        last_position = (
                            current
                        )

                        last_movement_time = (
                            now
                        )

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
                    # STALL
                    # =================================================

                    stall_time = (
                        now
                        - last_movement_time
                    )

                    stalled = (

                        stall_time
                        >= STALL_TIMEOUT

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
                        print("!" * 70)

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

                        print("!" * 70)

                        # -----------------------------------------
                        # MAX RECOVERY
                        # -----------------------------------------

                        if (
                            recovery_count
                            >= MAX_RECOVERY
                        ):

                            print(
                                "MAX RECOVERY TERCAPAI"
                            )

                            status = (
                                "MAX_RECOVERY_FAILED"
                            )

                            break

                        recovery_count += 1

                        # -----------------------------------------
                        # TIMESTAMP RECOVERY
                        # -----------------------------------------

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

                            previous_current = (
                                state["current"]
                            )

                            last_movement_time = (
                                time.time()
                            )

                            reset_count = 0

                            continue

                        # -----------------------------------------
                        # FAILED
                        # -----------------------------------------

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
                    # UPDATE
                    # =================================================

                    previous_current = (
                        current
                    )

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
                print("-" * 70)

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

                print("-" * 70)

                results.append({

                    "nama":
                        nama,

                    "url":
                        url,

                    "judul":
                        title,

                    "waktu_tunggu_detik":
                        round(
                            elapsed,
                            2
                        ),

                    "Space":
                        "",

                    "pause_space":
                        "",

                    "durasi_aktual_detik":
                        round(
                            active_play_time,
                            2
                        ),

                    "status":
                        status
                })

        finally:

            print()
            print(
                "Menutup browser..."
            )

            try:

                if context:

                    context.close()

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

        writer.writerows(
            results
        )

    print()
    print("=" * 70)
    print(
        "SEMUA VIDEO SELESAI"
    )
    print("=" * 70)

    print(
        f"Output: {OUTPUT_CSV}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
