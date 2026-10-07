import csv
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

from playwright.sync_api import sync_playwright


# ============================================================
# V17.2 GITHUB
# URL-TIMESTAMP RECOVERY + STALL DETECTION
# + YOUTUBE LOADING DIAGNOSTIC
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_CSV = BASE_DIR / "videos.csv"
OUTPUT_CSV = BASE_DIR / "hasil_test_play_button.csv"

# Folder diagnosis
DEBUG_DIR = BASE_DIR / "debug_v17_2"
DEBUG_DIR.mkdir(exist_ok=True)


# ============================================================
# CONFIG
# ============================================================

# Posisi resume = posisi terakhir yang valid + 2 detik
RESUME_OFFSET = 2.0

# Jika timestamp target gagal,
# coba timestamp 5 detik lebih awal
TIMESTAMP_FALLBACK_BACKOFF = 5.0

# Stall dianggap terjadi jika currentTime
# tidak bergerak selama 4 detik
STALL_TIMEOUT = 4.0

# Hard reset harus terdeteksi 2 kali berturut-turut
RESET_CONFIRM_COUNT = 2

# Interval pemeriksaan player
CHECK_INTERVAL = 0.25

# Maksimum recovery per video
MAX_RECOVERY = 5

# Timeout menunggu player
PLAYER_TIMEOUT = 25

# Timeout memastikan playback bergerak
MOVE_TIMEOUT = 8

# Timeout setelah timestamp dibuka
TIMESTAMP_START_TIMEOUT = 12


# ============================================================
# DEBUG PAGE
# ============================================================

def save_debug(page, label):

    try:

        safe_label = "".join(
            c if c.isalnum() or c in "_-" else "_"
            for c in label
        )

        txt_file = (
            DEBUG_DIR /
            f"{safe_label}.txt"
        )

        png_file = (
            DEBUG_DIR /
            f"{safe_label}.png"
        )

        try:
            current_url = page.url
        except Exception:
            current_url = ""

        try:
            title = page.title()
        except Exception:
            title = ""

        try:
            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=3000
            )
        except Exception:
            body_text = ""

        body_text = body_text[:12000]

        with open(
            txt_file,
            "w",
            encoding="utf-8"
        ) as f:

            f.write("URL:\n")
            f.write(current_url)
            f.write("\n\n")

            f.write("TITLE:\n")
            f.write(title)
            f.write("\n\n")

            f.write("BODY:\n")
            f.write(body_text)

        try:

            page.screenshot(
                path=str(png_file),
                full_page=False,
                timeout=10000
            )

        except Exception as e:

            print(
                f"      Screenshot warning: {e}"
            )

        print()
        print(
            f"      DEBUG URL   : "
            f"{current_url}"
        )

        print(
            f"      DEBUG TITLE : "
            f"{title}"
        )

        print(
            f"      DEBUG TEXT  : "
            f"{body_text[:500]!r}"
        )

        print(
            f"      DEBUG FILE  : "
            f"{txt_file}"
        )

    except Exception as e:

        print(
            f"      Debug gagal: {e}"
        )


# ============================================================
# YOUTUBE INTERSTITIAL / CONSENT
# ============================================================

def handle_youtube_interstitial(page):

    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=3000
        ).lower()

    except Exception:

        text = ""

    if not text:
        return False

    consent_words = [

        "before you continue to youtube",
        "sebelum melanjutkan ke youtube",

        "accept all",
        "terima semua",

        "reject all",
        "tolak semua"
    ]

    looks_like_consent = any(
        word in text
        for word in consent_words
    )

    if not looks_like_consent:

        return False

    print(
        "      ⚠ YouTube consent/interstitial terdeteksi"
    )

    # Kita pilih Reject All.
    # Tidak memberikan persetujuan tracking tambahan.
    candidates = [

        "Reject all",
        "Tolak semua",

        "Reject All",
        "Tolak Semua"
    ]

    # --------------------------------------------------------
    # BUTTON
    # --------------------------------------------------------

    for name in candidates:

        try:

            button = page.get_by_role(
                "button",
                name=name,
                exact=True
            )

            if button.count() > 0:

                button.first.click(
                    timeout=5000
                )

                print(
                    f"      ✓ Consent ditangani: "
                    f"{name}"
                )

                time.sleep(1)

                return True

        except Exception:

            pass

    # --------------------------------------------------------
    # TEXT FALLBACK
    # --------------------------------------------------------

    for name in candidates:

        try:

            locator = page.get_by_text(
                name,
                exact=True
            )

            if locator.count() > 0:

                locator.first.click(
                    timeout=5000
                )

                print(
                    f"      ✓ Consent ditangani via text: "
                    f"{name}"
                )

                time.sleep(1)

                return True

        except Exception:

            pass

    print(
        "      ⚠ Consent terlihat "
        "tetapi tombol tidak berhasil diklik"
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

        return video.evaluate("""
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
                    Boolean(
                        v.paused
                    ),

                ended:
                    Boolean(
                        v.ended
                    ),

                seeking:
                    Boolean(
                        v.seeking
                    ),

                ready:
                    Number(
                        v.readyState || 0
                    ),

                network:
                    Number(
                        v.networkState || 0
                    ),

                bufferedEnd:
                    Number(
                        bufferedEnd || 0
                    )
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
                        e.name +
                        ": " +
                        e.message,

                    current:
                        v.currentTime,

                    paused:
                        v.paused,

                    ready:
                        v.readyState
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

        and
        state["duration"] <= 0.05

        and
        state["ready"] == 0

        and
        state["network"] == 0

        and
        state["bufferedEnd"] <= 0.05
    )


# ============================================================
# MAKE TIMESTAMP URL
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

    query["t"] = (
        f"{seconds}s"
    )

    new_query = urlencode(
        query
    )

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

    consent_checked = False

    while (
        time.time() - start
        < timeout
    ):

        # ----------------------------------------------------
        # CHECK CONSENT
        # ----------------------------------------------------

        try:

            if not consent_checked:

                changed = (
                    handle_youtube_interstitial(
                        page
                    )
                )

                if changed:

                    consent_checked = True

        except Exception:

            pass

        # ----------------------------------------------------
        # FIND VIDEO
        # ----------------------------------------------------

        video = find_video(page)

        if video is not None:

            try:

                state = get_video_state(
                    video
                )

                if (
                    state["duration"] > 1
                ):

                    return video

            except Exception:

                pass

        time.sleep(
            0.25
        )

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

    while (
        time.time() - start
        < timeout
    ):

        try:

            handle_youtube_interstitial(
                page
            )

        except Exception:

            pass

        state = get_video_state(
            video
        )

        if (

            state["duration"] > 1

            and
            state["ready"] >= 2
        ):

            return True

        time.sleep(
            0.25
        )

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

    while (
        time.time() - start
        < timeout
    ):

        state = get_video_state(
            video
        )

        current = state[
            "current"
        ]

        if previous is not None:

            delta = (
                current -
                previous
            )

            if (

                delta >= 0.08

                and
                not state["paused"]

                and
                not state["ended"]

                and
                state["ready"] >= 2
            ):

                return True

        previous = current

        time.sleep(
            0.25
        )

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

    while (
        time.time() - start
        < timeout
    ):

        state = get_video_state(
            video
        )

        current = state[
            "current"
        ]

        print(
            f"      Timestamp check: "
            f"current={current:.2f} "
            f"target={target:.2f} "
            f"ready={state['ready']} "
            f"paused={state['paused']} "
            f"seeking={state['seeking']} "
            f"buffer={state['bufferedEnd']:.2f}"
        )

        # HARD RESET
        if is_hard_reset(
            state
        ):

            return False

        # TIMESTAMP REACHED
        if (

            abs(
                current - target
            ) <= 3.0

            and
            state["ready"] >= 2

            and
            not state["paused"]
        ):

            if previous is not None:

                delta = (
                    current -
                    previous
                )

                if delta >= 0.08:

                    print(
                        "      ✓ Timestamp playback bergerak"
                    )

                    return True

        previous = current

        # PLAY AGAIN
        if (

            state["paused"]

            and
            not state["ended"]
        ):

            play_video(
                video
            )

        time.sleep(
            0.25
        )

    return False


# ============================================================
# OPEN TIMESTAMP
# ============================================================

def open_timestamp(
    page,
    base_url,
    target
):

    timestamp_url = (
        make_timestamp_url(
            base_url,
            target
        )
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

            wait_until=
            "domcontentloaded",

            timeout=30000
        )

    except Exception as e:

        print(
            f"      goto warning: {e}"
        )

    # CONSENT
    try:

        handle_youtube_interstitial(
            page
        )

    except Exception:

        pass

    # FIND PLAYER
    video = wait_video_element(
        page
    )

    if video is None:

        print(
            "      ✗ Video tidak ditemukan"
        )

        save_debug(
            page,
            f"timestamp_no_video_"
            f"{int(round(target))}"
        )

        return None, False

    # PLAYER READY
    if not wait_player_ready(
        page,
        video
    ):

        print(
            "      ✗ Player tidak ready"
        )

        save_debug(
            page,
            f"timestamp_not_ready_"
            f"{int(round(target))}"
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

    time.sleep(
        0.8
    )

    success = (
        wait_timestamp_playback(
            page,
            video,
            target
        )
    )

    return (
        video,
        success
    )


# ============================================================
# TIMESTAMP RECOVERY
# ============================================================

def timestamp_recovery(
    page,
    base_url,
    last_position
):

    target = (
        last_position +
        RESUME_OFFSET
    )

    print()
    print(
        "=" * 70
    )

    print(
        "   URL-TIMESTAMP RECOVERY"
    )

    print(
        "=" * 70
    )

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

    video, success = (
        open_timestamp(
            page,
            base_url,
            target
        )
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

        return (
            True,
            video
        )

    print()
    print(
        "      ✗ URL timestamp target gagal"
    )

    # ========================================================
    # ATTEMPT 2
    # ========================================================

    fallback_target = max(
        0,
        target -
        TIMESTAMP_FALLBACK_BACKOFF
    )

    print()
    print(
        f"      FALLBACK TIMESTAMP "
        f"→ {fallback_target:.2f}s"
    )

    video, success = (
        open_timestamp(
            page,
            base_url,
            fallback_target
        )
    )

    if not success:

        print(
            "      ✗ Fallback timestamp gagal"
        )

        return (
            False,
            video
        )

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

    while (
        time.time() - start
        < 20
    ):

        state = get_video_state(
            video
        )

        current = state[
            "current"
        ]

        print(
            f"      Catch-up: "
            f"{current:.2f} / {target:.2f} "
            f"ready={state['ready']} "
            f"paused={state['paused']} "
            f"seeking={state['seeking']}"
        )

        if (

            current >=
            target - 0.5

            and
            state["ready"] >= 2

            and
            not state["paused"]

            and
            not state["ended"]
        ):

            print()
            print(
                f"      ✓ TARGET TERCAPAI "
                f"di {current:.2f}s"
            )

            return (
                True,
                video
            )

        if is_hard_reset(
            state
        ):

            print(
                "      ✗ Hard reset saat catch-up"
            )

            return (
                False,
                video
            )

        if (

            state["paused"]

            and
            not state["ended"]
        ):

            play_video(
                video
            )

        time.sleep(
            0.4
        )

    print(
        "      ✗ Natural catch-up timeout"
    )

    return (
        False,
        video
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "=" * 70
    )

    print(
        " V17.2 GITHUB"
    )

    print(
        " URL-TIMESTAMP RECOVERY + STALL DETECTION"
    )

    print(
        " YOUTUBE LOADING + DEBUG"
    )

    print(
        "=" * 70
    )

    print()

    # ========================================================
    # READ CSV
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

        reader = csv.DictReader(
            f
        )

        for row in reader:

            rows.append(
                row
            )

    print(
        f"Total video: "
        f"{len(rows)}"
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

            # =================================================
            # GITHUB:
            # PAKAI CHROMIUM BAWAAN PLAYWRIGHT
            # BUKAN channel="chrome"
            # =================================================

            browser = p.chromium.launch(

                headless=True,

                args=[

                    "--disable-extensions",

                    "--disable-dev-shm-usage",

                    "--no-sandbox",

                    "--autoplay-policy="
                    "no-user-gesture-required"
                ]
            )

            context = (
                browser.new_context(

                    viewport={
                        "width": 1280,
                        "height": 800
                    },

                    locale="en-US"
                )
            )

            page = (
                context.new_page()
            )

            # =================================================
            # EACH VIDEO
            # =================================================

            for index, row in enumerate(
                rows,
                start=1
            ):

                # ---------------------------------------------
                # SAFE CSV READ
                # ---------------------------------------------

                nama = str(
                    row.get("nama")
                    or ""
                ).strip()

                url = str(
                    row.get("url")
                    or ""
                ).strip()

                durasi_target = str(
                    row.get("durasi")
                    or ""
                ).strip()

                print()
                print()

                print(
                    "#" * 70
                )

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

                print(
                    "#" * 70
                )

                # ---------------------------------------------
                # EMPTY URL
                # ---------------------------------------------

                if not url:

                    print(
                        "URL KOSONG"
                    )

                    results.append({

                        "nama": nama,

                        "url": "",

                        "judul": "",

                        "waktu_tunggu_detik": 0,

                        "Space": "",

                        "pause_space": "",

                        "durasi_aktual_detik": 0,

                        "status": "URL_EMPTY"
                    })

                    continue

                # ---------------------------------------------
                # OPEN URL
                # ---------------------------------------------

                try:

                    page.goto(

                        url,

                        wait_until=
                        "domcontentloaded",

                        timeout=30000
                    )

                except Exception as e:

                    print(
                        f"goto warning: {e}"
                    )

                # Beri waktu YouTube membangun player.
                time.sleep(
                    1.0
                )

                # ---------------------------------------------
                # CONSENT
                # ---------------------------------------------

                try:

                    handle_youtube_interstitial(
                        page
                    )

                except Exception:

                    pass

                # ---------------------------------------------
                # FIND VIDEO
                # ---------------------------------------------

                video = (
                    wait_video_element(
                        page
                    )
                )

                if video is None:

                    print(
                        "VIDEO TIDAK DITEMUKAN"
                    )

                    # Simpan bukti halaman
                    save_debug(

                        page,

                        f"video_{index:02d}"
                        "_not_found"
                    )

                    results.append({

                        "nama": nama,

                        "url": url,

                        "judul": "",

                        "waktu_tunggu_detik": 0,

                        "Space": "",

                        "pause_space": "",

                        "durasi_aktual_detik": 0,

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
                # PLAY
                # ---------------------------------------------

                result = play_video(
                    video
                )

                print(
                    f"Play: {result}"
                )

                time.sleep(
                    1
                )

                state = get_video_state(
                    video
                )

                print(
                    f"Initial: "
                    f"current="
                    f"{state['current']:.2f}, "
                    f"duration="
                    f"{state['duration']:.2f}, "
                    f"ready="
                    f"{state['ready']}"
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

                start_time = (
                    time.time()
                )

                # =================================================
                # MONITOR
                # =================================================

                while True:

                    time.sleep(
                        CHECK_INTERVAL
                    )

                    state = (
                        get_video_state(
                            video
                        )
                    )

                    current = (
                        state["current"]
                    )

                    now = (
                        time.time()
                    )

                    moved = (
                        current -
                        previous_current
                    )

                    # -----------------------------------------
                    # PLAYBACK MOVING
                    # -----------------------------------------

                    if (

                        moved >= 0.08

                        and
                        not state["paused"]

                        and
                        not state["ended"]

                        and
                        state["ready"] >= 2
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

                    # -----------------------------------------
                    # LOG
                    # -----------------------------------------

                    print(

                        f"["
                        f"{active_play_time:6.1f}s"
                        f"] "

                        f"current="
                        f"{current:7.2f} "

                        f"duration="
                        f"{state['duration']:7.2f} "

                        f"ready="
                        f"{state['ready']} "

                        f"paused="
                        f"{state['paused']} "

                        f"seeking="
                        f"{state['seeking']} "

                        f"buffer="
                        f"{state['bufferedEnd']:7.2f}"
                    )

                    # -----------------------------------------
                    # HARD RESET
                    # -----------------------------------------

                    if is_hard_reset(
                        state
                    ):

                        reset_count += 1

                    else:

                        reset_count = 0

                    # -----------------------------------------
                    # STALL
                    # -----------------------------------------

                    stall_time = (

                        now -
                        last_movement_time
                    )

                    stalled = (

                        stall_time >=
                        STALL_TIMEOUT

                        and
                        current > 0.5

                        and
                        state["duration"] > 1

                        and
                        not state["paused"]

                        and
                        not state["ended"]

                        and
                        not state["seeking"]
                    )

                    # -----------------------------------------
                    # RECOVERY TRIGGER
                    # -----------------------------------------

                    recovery_reason = None

                    if (

                        reset_count >=
                        RESET_CONFIRM_COUNT
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
                            f"{recovery_reason} "
                            f"TERDETEKSI"
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

                            video = (
                                new_video
                            )

                            state = (
                                get_video_state(
                                    video
                                )
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
                        # RECOVERY FAILED
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

                        or
                        (
                            state["duration"] > 1

                            and
                            current >=
                            state["duration"] - 0.5
                        )
                    ):

                        print()
                        print(
                            "VIDEO SELESAI"
                        )

                        status = (
                            "SELESAI"
                        )

                        break

                    # =================================================
                    # TARGET ACTIVE TIME
                    # =================================================

                    try:

                        target_seconds = (
                            float(
                                durasi_target
                            )
                        )

                    except Exception:

                        target_seconds = 0

                    if (

                        target_seconds > 0

                        and
                        active_play_time >=
                        target_seconds
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

                    # -----------------------------------------
                    # UPDATE
                    # -----------------------------------------

                    previous_current = (
                        current
                    )

                # =================================================
                # FINAL
                # =================================================

                elapsed = (

                    time.time() -
                    start_time
                )

                final_state = (
                    get_video_state(
                        video
                    )
                )

                final_position = (
                    final_state["current"]
                )

                print()
                print(
                    "-" * 70
                )

                print(
                    f"FINAL VIDEO "
                    f"{index:02d}"
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

            fieldnames=
            output_fields
        )

        writer.writeheader()

        writer.writerows(
            results
        )

    print()
    print(
        "=" * 70
    )

    print(
        "SEMUA VIDEO SELESAI"
    )

    print(
        "=" * 70
    )

    print(
        f"Output: "
        f"{OUTPUT_CSV}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
