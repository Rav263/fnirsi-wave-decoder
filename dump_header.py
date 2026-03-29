#!/usr/bin/env python3
"""
Dump known and suspected DPOX180H header fields in hex/dec/float formats.

Usage:
    python dump_header.py Waveform/19.wav [Waveform/29.wav ...]
"""
import struct
import sys
import os

VDIV_TABLE = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]  # mV

# Variable-length buffer boundary table inserted at this offset.
# Firmware: FUN_0005c98c writes struct+0x290/+0x3D0/+0x510 arrays
# (3 × u32 per entry) right after display dimensions at 0x2B6.
# Count stored at file offset 0x1E9 (struct+0x750).
# Fields after this point are shifted by (waveform_data_start - BASE_WAV_DATA_START) bytes.
VAR_TABLE_OFFSET = 0x2B8
BASE_WAV_DATA_START = 11981  # Minimum waveform_data_start when var table is empty
                             # = 50 (header) + 911 (base settings) + 11020 (screen buffer 102×54×2+4)


def fmt_vdiv(idx):
    if 0 <= idx < len(VDIV_TABLE):
        v = VDIV_TABLE[idx]
        return f"{v/1000:.6g}V" if v >= 1000 else f"{v}mV"
    return f"INVALID({idx})"


def fmt_sr(hz):
    if hz == 0:
        return "0"
    if hz >= 1_000_000:
        return f"{hz/1e6:.6g} MHz"
    if hz >= 1000:
        return f"{hz/1e3:.6g} kHz"
    return f"{hz} Hz"


def u8(data, off):
    return data[off]


def u16(data, off):
    return struct.unpack('>H', data[off:off+2])[0]


def s16(data, off):
    return struct.unpack('>h', data[off:off+2])[0]


def u32(data, off):
    return struct.unpack('>I', data[off:off+4])[0]


def s32(data, off):
    return struct.unpack('>i', data[off:off+4])[0]


def f32(data, off):
    return struct.unpack('>f', data[off:off+4])[0]


# ── Field definitions ──────────────────────────────────────────────
# (offset, size, name, status, decoder_hint)
# status: "USED" = used in decoder, "KNOWN" = understood but not used,
#         "GUESS" = hypothesis, "?" = unknown
#
# Firmware source: FUN_0005c98c serialises the oscilloscope state
# structure (DAT_0005d5e8 / DAT_0005dba0) starting at file offset 0x32.
# The 50-byte header (0x00–0x31) is written separately by FUN_0005da08.
# A second structure (DAT_0005d780, trigger/measurements) follows
# after the variable-length buffer table.
FIELDS = [
    # ── Section table (0x00–0x1B, 7×u32 BE, written last by FUN_0005da08) ──
    # Each section is contiguous: start[N+1] = start[N] + size[N].
    (0x00, 4,  "settings_start (struct+0x838)",       "USED",  "always 50 (0x32)"),
    (0x04, 4,  "settings_size (struct+0x844)",        "USED",  None),
    (0x08, 4,  "screen_buffer_start (struct+0x83c)",  "USED",  None),
    (0x0C, 4,  "screen_buffer_size (struct+0x848)",   "USED",  None),
    (0x10, 4,  "waveform_data_start (struct+0x840)",  "USED",  None),
    (0x14, 4,  "waveform_data_size (struct+0x84c)",   "USED",  None),
    (0x18, 4,  "total_file_size (struct+0x850)",      "USED",  None),
    # ── Gap bytes (0x1C–0x31) — constant across all test files, origin unknown ──
    (0x1C, 4,  "gap 0x1C",                            "?",     "constant across files"),
    (0x20, 4,  "gap 0x20",                            "?",     "constant across files"),
    (0x24, 4,  "gap 0x24",                            "?",     "constant across files"),
    (0x28, 4,  "gap 0x28",                            "?",     "constant across files"),
    (0x2C, 4,  "gap 0x2C",                            "?",     "constant across files"),
    (0x30, 2,  "gap 0x30",                            "?",     "constant across files"),

    # ── Display settings (struct+0x00..+0x30, file 0x32–0x61) ──
    (0x32, 2,  "grid_columns (struct+0x00)",          "KNOWN", "constant 10"),
    (0x34, 2,  "grid_rows (struct+0x02)",             "KNOWN", "constant 20"),
    (0x36, 2,  "display_height (struct+0x04)",        "KNOWN", "300 pixels"),
    (0x38, 2,  "display_param (struct+0x06)",         "KNOWN", "constant 200"),
    (0x3A, 2,  "CH1 vert center Y (struct+0x08)",    "KNOWN", "display_height/2 = 150"),
    (0x3C, 2,  "CH2 vert center Y (struct+0x0A)",    "KNOWN", "display_height/2 = 150"),
    (0x3E, 2,  "display_state (struct+0x0C)",         "KNOWN", "0=dual-TB?, 1=normal"),
    (0x40, 2,  "CH1 GND line Y (struct+0x0E)",       "KNOWN", "display_height-1 = 299"),
    (0x42, 2,  "CH2 GND line Y (struct+0x10)",       "KNOWN", "display_height-2 = 298"),
    (0x44, 2,  "display_param_2 (struct+0x12)",       "KNOWN", "UI state"),
    (0x46, 2,  "cursor_y_1 (struct+0x14)",            "KNOWN", "cursor Y position, 0 or 299"),
    (0x48, 2,  "cursor_y_2 (struct+0x16)",            "KNOWN", "cursor Y position copy"),
    (0x4A, 2,  "num_timebase_settings (struct+0x18)", "KNOWN", "constant 25"),
    (0x4C, 2,  "num_display_divs (struct+0x1A)",      "KNOWN", "constant 12"),
    (0x4E, 2,  "num_timebase_settings2 (struct+0x1C)","KNOWN", "constant 25"),
    (0x50, 2,  "firmware_param_1 (struct+0x1E)",      "KNOWN", "display state"),
    (0x52, 2,  "firmware_param_2 (struct+0x20)",      "KNOWN", "display state"),
    (0x54, 2,  "firmware_param_3 (struct+0x22)",      "KNOWN", "display state"),
    (0x56, 1,  "display_flag_1 (struct+0x24)",        "KNOWN", "1-byte field"),
    (0x57, 1,  "display_flag_2 (struct+0x26)",        "KNOWN", "1-byte field"),
    (0x58, 2,  "display_param_3 (struct+0x28)",       "KNOWN", "display state"),
    (0x5A, 8,  "display_block (struct+0x30)",         "KNOWN", "8-byte firmware state block"),

    # ── CH1 config block (struct+0x38..+0x5A, file 0x62–0x81) ──
    (0x62, 1,  "CH1 V/div stale flag (struct+0x38)", "USED",  "0=ok, 1=stale"),
    (0x63, 1,  "CH1 config_1 (struct+0x39)",          "KNOWN", "constant 0"),
    (0x64, 1,  "CH1 config_2 (struct+0x3A)",          "KNOWN", "firmware state"),
    (0x65, 1,  "CH1 config_3 (struct+0x3B)",          "KNOWN", "firmware state"),
    (0x66, 1,  "CH1 channel_enabled (struct+0x3C)",   "USED",  "0=off, non-zero=on"),
    (0x67, 1,  "CH1 config_4 (struct+0x3D)",          "KNOWN", "constant 0"),
    (0x68, 1,  "CH1 config_5 (struct+0x3E)",          "KNOWN", "firmware state flag"),
    (0x69, 1,  "CH1 timebase_index (struct+0x3F)",    "USED",  "0=10MHz,1=5MHz,5=200kHz"),
    (0x6A, 1,  "CH1 vdiv_pad (struct+0x40)",          "KNOWN", "always 0, high byte of V/div u16 read"),
    (0x6B, 2,  "CH1 V/div index (struct+0x42)",       "USED",  "vdiv_table"),
    (0x6D, 1,  "CH1 display_state (struct+0x44)",     "KNOWN", "varies with timebase/vert position"),
    (0x6E, 8,  "CH1 sample_rate block (struct+0x48)", "KNOWN", "sample_rate"),
    (0x76, 8,  "CH1 sample_rate_copy (struct+0x50)",  "KNOWN", "sample_rate"),
    (0x7E, 2,  "CH1 vert_position (struct+0x58)",     "KNOWN", "GND Y pixel (0=top, 150=center)"),
    (0x80, 2,  "CH1 vert_position_copy (struct+0x5A)","KNOWN", "always == vert_position"),

    # ── CH1 extended config (struct+0xC0..+0xDE, file 0x82–0x9F) ──
    (0x82, 8,  "CH1 voltage_scale block (struct+0xC0)","KNOWN", "8B: includes scale constant"),
    (0x8A, 4,  "CH1 display_param (struct+0xC8)",      "KNOWN", "display alignment / scaling"),
    (0x8E, 4,  "CH1 firmware_param (struct+0xCC)",      "KNOWN", "firmware state"),
    (0x92, 4,  "CH1 firmware_const (struct+0xD0)",      "KNOWN", "constant 0x04000000"),
    (0x96, 2,  "CH1 config_6 (struct+0xD4)",            "KNOWN", "0 for CH1, 260/514 for CH2"),
    (0x98, 2,  "CH1 config_7 (struct+0xD6)",            "KNOWN", "firmware state"),
    (0x9A, 2,  "CH1 config_8 (struct+0xD8)",            "KNOWN", "firmware state"),
    (0x9C, 2,  "CH1 config_9 (struct+0xDA)",            "KNOWN", "firmware state"),
    (0x9E, 2,  "CH1 config_10 (struct+0xDC)",           "KNOWN", "firmware state"),

    # ── CH2 firmware state + config (struct+0xDE..+0x108, file 0xA0–0xC1) ──
    (0xA0, 2,  "CH2 firmware_state (struct+0xDE)",     "KNOWN", "always 0 for CH2"),
    (0xA2, 1,  "CH2 V/div stale flag (struct+0xE8)",  "USED",  "0=ok, 1=stale"),
    (0xA3, 1,  "CH2 config_1 (struct+0xE9)",           "KNOWN", "constant 0"),
    (0xA4, 2,  "CH2 config_2 (struct+0xEA)",           "KNOWN", "firmware state"),
    (0xA6, 1,  "CH2 channel_enabled (struct+0xEC)",    "USED",  "0=off, non-zero=on"),
    (0xA7, 1,  "CH2 config_3 (struct+0xED)",           "KNOWN", "constant 0"),
    (0xA8, 1,  "CH2 config_4 (struct+0xEE)",           "KNOWN", "firmware state flag"),
    (0xA9, 1,  "CH2 timebase_index (struct+0xEF)",     "USED",  "0=10MHz,1=5MHz,5=200kHz"),
    (0xAA, 1,  "CH2 vdiv_pad (struct+0xF0)",           "KNOWN", "always 0, high byte of V/div u16 read"),
    (0xAB, 2,  "CH2 V/div index (struct+0xF2)",        "USED",  "vdiv_table"),
    (0xAD, 1,  "CH2 display_state (struct+0xF4)",      "KNOWN", "varies with timebase/vert position"),
    (0xAE, 8,  "CH2 sample_rate block (struct+0xF8)",  "KNOWN", "sample_rate"),
    (0xB6, 8,  "CH2 sample_rate_copy (struct+0x100)",  "KNOWN", "sample_rate"),
    (0xBE, 2,  "CH2 vert_position (struct+0x108)",     "KNOWN", "GND Y pixel (0=top, 150=center)"),
    (0xC0, 2,  "CH2 vert_position_copy (DAT_0005d5ec)","KNOWN", "separate global, always == vert_position"),

    # ── Post-channel extended config (struct+0x170..+0x198, file 0xC2–0xE3) ──
    (0xC2, 8,  "ext_config_block_1 (struct+0x170)",    "KNOWN", "firmware config"),
    (0xCA, 4,  "ext_config_1 (struct+0x178)",           "KNOWN", "firmware state"),
    (0xCE, 4,  "ext_config_2 (struct+0x17C)",           "KNOWN", "firmware state"),
    (0xD2, 4,  "ext_config_3 (struct+0x180)",           "KNOWN", "firmware state"),
    (0xD6, 1,  "ext_flag_1 (DAT_0005d5f0)",            "KNOWN", "firmware state"),
    (0xD7, 1,  "ext_flag_2 (DAT_0005d5f4)",            "KNOWN", "firmware state"),
    (0xD8, 1,  "ext_flag_3 (struct+0x188)",             "KNOWN", "firmware state"),
    (0xD9, 1,  "ext_flag_4 (DAT_0005d5f8)",            "KNOWN", "firmware state"),
    (0xDA, 1,  "ext_flag_5 (DAT_0005d5fc)",            "KNOWN", "firmware state"),
    (0xDB, 1,  "ext_flag_6 (struct+0x190)",             "KNOWN", "firmware state"),
    (0xDC, 4,  "ext_param_1 (struct+0x194)",            "KNOWN", "firmware state"),
    (0xE0, 4,  "ext_param_2 (struct+0x198)",            "KNOWN", "firmware state"),

    # ── Trigger/cursor config (struct+0x23C..+0x278, file 0xE4–0x11A) ──
    (0xE4, 4,  "trigger_param_1 (struct+0x23C)",       "KNOWN", "trigger/cursor config"),
    (0xE8, 4,  "trigger_param_2 (struct+0x240)",       "KNOWN", "trigger/cursor config"),
    (0xEC, 4,  "trigger_param_3 (struct+0x244)",       "KNOWN", "trigger/cursor config"),
    (0xF0, 4,  "trigger_param_4 (struct+0x248)",       "KNOWN", "trigger/cursor config"),
    (0xF4, 1,  "trigger_flag_1 (struct+0x24C)",        "KNOWN", "trigger state"),
    (0xF5, 1,  "trigger_flag_2 (DAT_0005d600)",        "KNOWN", "trigger state"),
    (0xF6, 2,  "trigger_param_5 (DAT_0005d604)",       "KNOWN", "trigger state"),
    (0xF8, 1,  "cursor_flag_1 (struct+0x250)",          "KNOWN", "cursor state"),
    (0xF9, 1,  "cursor_flag_2 (DAT_0005d608)",          "KNOWN", "cursor state"),
    (0xFA, 1,  "cursor_flag_3 (DAT_0005d60c)",          "KNOWN", "cursor state"),
    (0xFB, 1,  "cursor_flag_4 (DAT_0005d610)",          "KNOWN", "cursor state"),
    (0xFC, 1,  "cursor_flag_5 (struct+0x254)",           "KNOWN", "cursor state"),
    (0xFD, 2,  "cursor_param_1 (DAT_0005d614)",         "KNOWN", "cursor config"),
    (0xFF, 2,  "cursor_param_2 (struct+0x258)",          "KNOWN", "cursor config"),
    (0x101, 2, "cursor_param_3 (DAT_0005d618)",         "KNOWN", "cursor config"),
    (0x103, 4, "math_param_1 (struct+0x25C)",            "KNOWN", "math/FFT config"),
    (0x107, 4, "math_param_2 (struct+0x260)",            "KNOWN", "math/FFT config"),
    (0x10B, 4, "math_param_3 (struct+0x264)",            "KNOWN", "math/FFT config"),
    (0x10F, 1, "math_flag_1 (struct+0x268)",             "KNOWN", "math channel flag"),
    (0x110, 2, "math_param_4 (struct+0x26C)",            "KNOWN", "math config"),
    (0x112, 4, "math_param_5 (struct+0x270)",            "KNOWN", "math config"),
    (0x116, 1, "acq_flag_1 (struct+0x274)",              "KNOWN", "acquisition state"),
    (0x117, 1, "acq_flag_2 (DAT_0005d61c)",             "KNOWN", "acquisition state"),
    (0x118, 1, "acq_flag_3 (DAT_0005d620)",             "KNOWN", "acquisition state"),
    (0x119, 1, "acq_flag_4 (DAT_0005d624)",             "KNOWN", "acquisition state"),
    (0x11A, 1, "acq_flag_5 (struct+0x278)",              "KNOWN", "acquisition state"),
    (0x11B, 2, "adc_center_const (DAT_0005d628)",        "KNOWN", "ADC center = 6400"),

    # ── Sample/calibration params (struct+0x27C..+0x28C, file 0x11D–0x130) ──
    (0x11D, 4, "calib_param_1 (struct+0x27C)",          "KNOWN", "calibration param"),
    (0x121, 4, "calib_param_2 (struct+0x280)",          "KNOWN", "calibration param"),
    (0x125, 4, "calib_param_3 (struct+0x284)",          "KNOWN", "calibration param"),
    (0x129, 4, "calib_param_4 (struct+0x288)",          "KNOWN", "calibration param"),
    (0x12D, 4, "buffer_sample_count (struct+0x28C)",    "KNOWN", "total samples in buffer per ch (display+ADC)"),
    (0x131, 4, "buffer_param_1 (DAT_0005d62c)",         "KNOWN", "buffer config"),
    (0x135, 4, "buffer_param_2 (DAT_0005d630)",         "KNOWN", "buffer config"),

    # ── ADC / timing config (struct+0x660..+0x6F8, file 0x139–0x15D) ──
    (0x139, 4, "adc_config_1 (struct+0x660 lo)",         "KNOWN", "ADC timing config"),
    (0x13D, 4, "adc_sample_rate (struct+0x664)",         "USED",  "sample_rate"),
    (0x141, 8, "adc_timing_block (DAT_0005d634)",        "KNOWN", "ADC timing params"),
    (0x149, 4, "adc_config_3 (struct+0x670)",            "KNOWN", "ADC config"),
    (0x14D, 4, "adc_config_4 (DAT_0005d638)",           "KNOWN", "ADC config"),
    (0x151, 4, "adc_config_5 (DAT_0005d63c)",           "KNOWN", "ADC config"),
    (0x155, 4, "adc_config_6 (DAT_0005d640)",           "KNOWN", "ADC config"),
    (0x159, 4, "adc_config_7 (DAT_0005d644)",           "KNOWN", "ADC config"),
    (0x15D, 4, "adc_config_8 (DAT_0005d648)",           "KNOWN", "ADC config"),

    # ── Extended settings / timer config (struct+0x690..+0x6F8, file 0x161+) ──
    # (firmware state dump — timer/clock, display params, measurement config)
    # These blocks follow repeating 4×u32 pattern from struct+DAT globals.

    # Timing / horizontal config
    (0x19E, 1, "horiz resolution param",             "KNOWN", "correlates with timebase"),
    (0x1A8, 4, "base_clock (=2560000)",              "KNOWN", "timer base constant"),
    (0x1AC, 4, "horiz_timer_param",                  "KNOWN", "10240/20480/256"),
    (0x1B0, 4, "base_clock_2",                       "KNOWN", "2560000 (Waveform), 25600000 (Google)"),
    (0x1B4, 4, "const_256",                          "KNOWN", "=256, constant"),
    (0x1B8, 4, "display_x_param",                    "KNOWN", "511 (Waveform), 2815 (Google)"),
    (0x1BC, 4, "y_range_lower (=-38400)",            "KNOWN", "-display_height/2 × 256"),
    (0x1C0, 4, "y_range_upper (=+38400)",            "KNOWN", "+display_height/2 × 256"),

    # Primary timebase
    (0x1D4, 1, "timebase_index (DAT_0005d6a4)",      "USED",  "1-2-5 sequence: 11≈5ns..25≈1s"),
    (0x1D5, 8, "timebase_block (struct+0x710)",       "KNOWN", "8B: offset+4 = time/div in ps"),
    (0x1D9, 4, "time_per_div_ps (struct+0x714)",      "USED",  "time/div in picoseconds"),
    (0x1DD, 1, "const_0x15 (DAT_0005d6a8)",           "KNOWN", "constant 21 across all files"),

    # Dual-timebase / secondary
    (0x1E7, 1, "sample_count_factor",                "KNOWN", "N/6000 for Waveform (1 or 2)"),
    (0x1E9, 2, "var_table_count (struct+0x750)",      "KNOWN", "entries in variable-length buffer table"),
    (0x1EF, 4, "timer_value_secondary",              "KNOWN", "secondary timing param"),
    (0x1F3, 1, "timebase_index_secondary (struct+0x730)", "KNOWN", "differs from primary in dual-TB"),
    (0x1F8, 4, "timer_value_tertiary",               "KNOWN", "maps to secondary TB index"),

    # Display range
    (0x215, 4, "y_range_lower_px (DAT_0005d6c8)",   "KNOWN", "-display_height/2 in pixels = -150"),
    (0x219, 4, "y_range_upper_px (DAT_0005d6cc)",   "KNOWN", "+display_height/2 in pixels = +150"),

    # Sample count / display dimensions
    (0x2B4, 2, "display_height (DAT_0005d778)",      "KNOWN", "constant 300"),
    (0x2B6, 2, "display_width (DAT_0005d77c)",       "KNOWN", "constant 500"),

    # ── Variable-length buffer table (0x2B8+, count from file 0x1E9) ──
    # 3 × uint32 BE per entry: (boundary_1, boundary_2, stride=2×spc)
    # All fields after this are shifted by table_size bytes.

    # ── Second structure (DAT_0005d780, trigger/measurements) ──
    # Starts at file 0x2B8 + var_table_size.
    # 5 × u8 flags, 4 × u16 params, 24 × 8B timer/clock blocks,
    # then a variable-length array of u16 measurement values.

    # Known fields in second struct (base offsets for settings_size=11981):
    (0x2BC, 4, "struct2 sample_count_per_ch",         "KNOWN", "6000/12000/150 — samples per channel"),
    (0x2C0, 4, "struct2 sample_count_total",          "KNOWN", "2 × sample_count_per_ch"),

    # Measurement config (base offsets, shifted by var_table_size)
    (0x305, 1, "meas_state_ch1",                     "GUESS", "0=off, 1-3=active"),
    (0x392, 1, "meas_type_1",                        "GUESS", "7=frequency? 0=off"),
    (0x394, 1, "meas_type_2",                        "GUESS", "6=period? 0=off"),
]


STATUS_COLORS = {
    "USED":  "\033[32m",   # green
    "KNOWN": "\033[36m",   # cyan
    "GUESS": "\033[33m",   # yellow
    "?":     "\033[91m",   # bright red
}
RESET = "\033[0m"


def dump_field(data, offset, size, name, status, hint, base_offset=None):
    color = STATUS_COLORS.get(status, "")

    # Raw hex bytes
    raw = data[offset:offset+size]
    hex_str = ' '.join(f'{b:02X}' for b in raw)

    # Numeric interpretations
    vals = []
    if size == 1:
        v = u8(data, offset)
        vals.append(f"u8={v}")
        vals.append(f"hex=0x{v:02X}")
    elif size == 2:
        vu = u16(data, offset)
        vs = s16(data, offset)
        vals.append(f"u16={vu}")
        if vs != vu:
            vals.append(f"s16={vs}")
        vals.append(f"hex=0x{vu:04X}")
    elif size == 4:
        vu = u32(data, offset)
        vs = s32(data, offset)
        vf = f32(data, offset)
        vals.append(f"u32={vu}")
        if vs != vu:
            vals.append(f"s32={vs}")
        vals.append(f"hex=0x{vu:08X}")
        # Show float only if it looks reasonable (not NaN/Inf/tiny)
        if vf == vf and abs(vf) < 1e12 and abs(vf) > 1e-12:
            vals.append(f"f32={vf:.6g}")
        elif vf == 0.0:
            vals.append(f"f32=0.0")

    # Extra decoded meaning
    extra = ""
    if hint == "vdiv_table" and size == 2:
        idx = u16(data, offset)
        extra = f" → {fmt_vdiv(idx)}/div"
    elif hint == "sample_rate" and size == 4:
        sr = u32(data, offset)
        extra = f" → {fmt_sr(sr)}"
    elif hint == "0=ok, 1=stale":
        v = u8(data, offset)
        extra = f" → {'STALE' if v == 1 else 'ok' if v == 0 else f'? ({v})'}"
    elif hint and hint.startswith("0=") or hint and hint.startswith("display") or hint and hint.startswith("max"):
        extra = f"  ({hint})"
    elif hint:
        extra = f"  ({hint})"

    val_str = ', '.join(vals)
    tag = f"[{status:>5}]"
    if base_offset is not None and base_offset != offset:
        addr = f"0x{offset:04X} (base 0x{base_offset:04X})"
    else:
        addr = f"0x{offset:04X}"
    print(f"  {color}{addr:<24s} {tag}  {hex_str:<12s}  {val_str}{extra}{RESET}")
    print(f"  {color}{'':>26} {name}{RESET}")


def dump_file(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < 256:
        print(f"  ERROR: file too small ({len(data)} bytes)", file=sys.stderr)
        return

    # ── Section table (7 × u32 BE at 0x00–0x1B) ──
    settings_start    = u32(data, 0x00)   # always 50 (0x32)
    settings_size     = u32(data, 0x04)
    scr_buf_start     = u32(data, 0x08)
    scr_buf_size      = u32(data, 0x0C)
    wav_data_start    = u32(data, 0x10)
    wav_data_size     = u32(data, 0x14)
    total_file_size   = u32(data, 0x18)

    # Variable-length buffer table within the settings section
    var_table_size = max(0, wav_data_start - BASE_WAV_DATA_START)
    var_table_entries = var_table_size // 12  # each entry is 3 × uint32

    # Channel enable flags and sample count
    ch1_enabled = data[0x66] if len(data) > 0xA7 else 0
    ch2_enabled = data[0xA6] if len(data) > 0xA7 else 0
    sample_count = u32(data, 0x12D) if len(data) > 0x131 else 0

    print(f"\n{'='*72}")
    print(f"  File: {filepath}")
    print(f"  Size: {len(data)} bytes  (reported: {total_file_size})")
    print(f"  Sections:")
    print(f"    Settings:      0x{settings_start:04X}–0x{settings_start+settings_size-1:04X}"
          f"  ({settings_size} bytes)")
    print(f"    Screen buffer: 0x{scr_buf_start:04X}–0x{scr_buf_start+scr_buf_size-1:04X}"
          f"  ({scr_buf_size} bytes)")
    print(f"    Waveform data: 0x{wav_data_start:04X}–0x{wav_data_start+wav_data_size-1:04X}"
          f"  ({wav_data_size} bytes)")
    print(f"  Channels: CH1={'ON' if ch1_enabled else 'OFF'}"
          f"  CH2={'ON' if ch2_enabled else 'OFF'}"
          f"  samples/ch={sample_count}")

    # Section table validation
    errors = []
    if settings_start + settings_size != scr_buf_start:
        errors.append(f"settings end ({settings_start+settings_size}) "
                      f"!= screen_buffer_start ({scr_buf_start})")
    if scr_buf_start + scr_buf_size != wav_data_start:
        errors.append(f"screen_buffer end ({scr_buf_start+scr_buf_size}) "
                      f"!= waveform_data_start ({wav_data_start})")
    if wav_data_start + wav_data_size != total_file_size:
        errors.append(f"waveform end ({wav_data_start+wav_data_size}) "
                      f"!= total_file_size ({total_file_size})")
    if total_file_size != len(data):
        errors.append(f"total_file_size ({total_file_size}) != actual ({len(data)})")
    active_ch = (1 if ch1_enabled else 0) + (1 if ch2_enabled else 0)
    if active_ch and sample_count and wav_data_size != active_ch * sample_count * 2:
        errors.append(f"waveform_data_size ({wav_data_size}) != "
                      f"{active_ch}ch × {sample_count} × 2 = {active_ch*sample_count*2}")
    if errors:
        for e in errors:
            print(f"  \033[91mVALIDATION ERROR: {e}\033[0m")
    else:
        print(f"  \033[32mSection table: OK\033[0m")

    if var_table_size > 0:
        print(f"  Var table: {var_table_size} bytes at 0x{VAR_TABLE_OFFSET:X} "
              f"({var_table_entries} triplets of uint32 BE)")
    print(f"{'='*72}")

    # Legend
    print(f"  Legend: "
          f"{STATUS_COLORS['USED']}USED{RESET}=in decoder  "
          f"{STATUS_COLORS['KNOWN']}KNOWN{RESET}=understood  "
          f"{STATUS_COLORS['GUESS']}GUESS{RESET}=hypothesis  "
          f"{STATUS_COLORS['?']}?{RESET}=unknown")
    print()

    last_section = None
    var_table_dumped = False
    for base_offset, size, name, status, hint in FIELDS:
        # Fields at or after VAR_TABLE_OFFSET are shifted by var_table_size
        if base_offset >= VAR_TABLE_OFFSET:
            actual_offset = base_offset + var_table_size
            show_base = base_offset
        else:
            actual_offset = base_offset
            show_base = None

        if actual_offset + size > len(data):
            break

        # Dump variable table when we first cross the boundary
        if base_offset >= VAR_TABLE_OFFSET and not var_table_dumped:
            var_table_dumped = True
            if var_table_size > 0:
                print(f"\n  ── Variable buffer table at 0x{VAR_TABLE_OFFSET:X} "
                      f"({var_table_size} bytes, {var_table_entries} entries) ──")
                for i in range(var_table_entries):
                    toff = VAR_TABLE_OFFSET + i * 12
                    v1 = u32(data, toff)
                    v2 = u32(data, toff + 4)
                    v3 = u32(data, toff + 8)
                    print(f"    0x{toff:04X}: ({v1}, {v2}, {v3})")
            else:
                print(f"\n  ── No variable buffer table (base settings size) ──")

        # Section separators (based on canonical base_offset)
        if base_offset < 0x08 and last_section != "sig":
            print(f"  ── Section table (0x00–0x1B, 7×u32 BE) ──")
            last_section = "sig"
        elif 0x1C <= base_offset < 0x32 and last_section != "gap":
            print(f"\n  ── Gap bytes (0x1C–0x31, constant across files) ──")
            last_section = "gap"
        elif 0x32 <= base_offset < 0x62 and last_section != "display":
            print(f"\n  ── Display settings (0x32–0x61, struct+0x00..+0x30) ──")
            last_section = "display"
        elif 0x62 <= base_offset < 0x82 and last_section != "ch1":
            print(f"\n  ── CH1 config (0x62–0x81, struct+0x38..+0x5A) ──")
            last_section = "ch1"
        elif 0x82 <= base_offset < 0xA0 and last_section != "ch1ext":
            print(f"\n  ── CH1 extended config (0x82–0x9F, struct+0xC0..+0xDC) ──")
            last_section = "ch1ext"
        elif 0xA0 <= base_offset < 0xC2 and last_section != "ch2":
            print(f"\n  ── CH2 config (0xA0–0xC1, struct+0xDE..+0x108) ──")
            last_section = "ch2"
        elif 0xC2 <= base_offset < 0xE4 and last_section != "post":
            print(f"\n  ── Post-channel config (0xC2–0xE3, struct+0x170..+0x198) ──")
            last_section = "post"
        elif 0xE4 <= base_offset < 0x139 and last_section != "trigger":
            print(f"\n  ── Trigger/cursor/math (0xE4–0x138, struct+0x23C..+0x288) ──")
            last_section = "trigger"
        elif 0x139 <= base_offset < 0x161 and last_section != "adc":
            print(f"\n  ── ADC/timing config (0x139–0x160, struct+0x660..+0x6F8) ──")
            last_section = "adc"
        elif 0x161 <= base_offset < VAR_TABLE_OFFSET and last_section != "ext":
            print(f"\n  ── Extended timing/display (0x161–0x{VAR_TABLE_OFFSET-1:X}) ──")
            last_section = "ext"
        elif base_offset >= VAR_TABLE_OFFSET and last_section != "shifted":
            print(f"\n  ── Second struct / shifted fields (base+{var_table_size}) ──")
            last_section = "shifted"

        dump_field(data, actual_offset, size, name, status, hint, show_base)

    # ── Screen buffer summary ──
    print(f"\n  ── Screen buffer ──")
    if scr_buf_start + 4 <= len(data):
        scr_w = u16(data, scr_buf_start)
        scr_h = u16(data, scr_buf_start + 2)
        expected_scr = 4 + scr_w * scr_h * 2
        print(f"  Dimensions: {scr_w} × {scr_h} pixels (RGB565 u16 BE)")
        print(f"  Payload: {scr_buf_size} bytes "
              f"(expected {expected_scr}, "
              f"{'OK' if expected_scr == scr_buf_size else 'MISMATCH'})")
    else:
        print(f"  (not enough data)")

    # ── Waveform data summary ──
    print(f"\n  ── Waveform data ──")
    if wav_data_start + wav_data_size <= len(data) and sample_count > 0:
        off = wav_data_start
        if ch1_enabled:
            ch1 = struct.unpack('>' + 'H' * sample_count,
                                data[off:off + sample_count * 2])
            vdiv_idx = u16(data, 0x6B) if len(data) > 0x6D else -1
            vdiv_str = f" ({fmt_vdiv(vdiv_idx)}/div)" if 0 <= vdiv_idx < len(VDIV_TABLE) else ""
            print(f"  CH1: min={min(ch1)}, max={max(ch1)}, "
                  f"median={sorted(ch1)[sample_count//2]}, "
                  f"samples={sample_count}{vdiv_str}")
            off += sample_count * 2
        else:
            print(f"  CH1: disabled")
        if ch2_enabled:
            ch2 = struct.unpack('>' + 'H' * sample_count,
                                data[off:off + sample_count * 2])
            vdiv_idx = u16(data, 0xAB) if len(data) > 0xAD else -1
            vdiv_str = f" ({fmt_vdiv(vdiv_idx)}/div)" if 0 <= vdiv_idx < len(VDIV_TABLE) else ""
            print(f"  CH2: min={min(ch2)}, max={max(ch2)}, "
                  f"median={sorted(ch2)[sample_count//2]}, "
                  f"samples={sample_count}{vdiv_str}")
        else:
            # Try reading CH2 region anyway to detect non-zero data
            remaining = wav_data_size - (off - wav_data_start)
            if remaining >= sample_count * 2:
                ch2 = struct.unpack('>' + 'H' * sample_count,
                                    data[off:off + sample_count * 2])
                if any(v != 0 for v in ch2):
                    print(f"  CH2: flag=OFF but data present! "
                          f"min={min(ch2)}, max={max(ch2)}")
                else:
                    print(f"  CH2: disabled (no data)")
            else:
                print(f"  CH2: disabled (no data section)")
    else:
        print(f"  (not enough data or sample_count=0)")

    # ── Raw hex dump of first 0x60 bytes ──
    print(f"\n  ── Raw hex: 0x00–0x5F ──")
    for row_off in range(0, 0x60, 16):
        hex_part = ' '.join(f'{data[row_off+i]:02X}' for i in range(16)
                            if row_off+i < len(data))
        ascii_part = ''.join(
            chr(data[row_off+i]) if 32 <= data[row_off+i] < 127 else '.'
            for i in range(16) if row_off+i < len(data))
        print(f"  {row_off:04X}: {hex_part:<48s}  {ascii_part}")

    # ── Scan for interesting uint16 BE values in unexplored settings ──
    settings_end = settings_start + settings_size
    print(f"\n  ── Interesting values in settings (0x160–0x{min(settings_end, 0x400):X}) ──")
    interesting = {6400: "ADC center", 12800: "ADC max",
                   10: "10mV", 20: "20mV", 50: "50mV", 100: "100mV",
                   200: "200mV", 500: "500mV", 1000: "1V", 2000: "2V",
                   5000: "5V", 10000: "10V"}
    scan_end = min(settings_end, 0x400)
    found = []
    for off in range(0x160, scan_end - 1, 2):
        v = u16(data, off)
        if v in interesting:
            found.append((off, v, interesting[v]))
    if found:
        for off, v, desc in found:
            print(f"  0x{off:04X}: {v} ({desc})")
    else:
        print(f"  (none found)")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} FILE.wav [FILE2.wav ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        if not os.path.isfile(path):
            print(f"  ERROR: {path} not found", file=sys.stderr)
            continue
        dump_file(path)


if __name__ == '__main__':
    main()
