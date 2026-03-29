#!/usr/bin/env python3
"""
FNIRSI Oscilloscope WAV Trace Decoder

Decodes proprietary .wav files saved by FNIRSI oscilloscopes
and exports them as .csv (data) and .png (plot).

Supported models:
  - FNIRSI 1014D  (15000-byte files, uint16 LE)
  - FNIRSI DPOX180H (variable-size files, uint16 BE)

--- FNIRSI 1014D format (15000 bytes total) ---
  Header:    bytes 0-999    (500 uint16 LE values)
  CH1 data:  bytes 1000-3999 (1500 uint16 LE samples)
  CH2 data:  bytes 4000-6999 (1500 uint16 LE samples, zeros if single channel)
  Extra:     bytes 7000+     (additional data, ignored)

--- FNIRSI DPOX180H format (variable size) ---
  File structure (firmware-confirmed, FUN_0005da08 + FUN_0005c98c):
    [0x00..0x31]  50-byte section table (7 × u32 BE at 0x00-0x1B, rest reserved)
    [0x32..+S)    Settings block (oscilloscope state struct dump)
    [0x32+S..+B)  Screen buffer (thumbnail: u16 W + u16 H + W×H u16 RGB565)
    [W..W+D)      Waveform data: ADC samples, uint16 BE
                  CH1 (if enabled) then CH2 (if enabled), sample_count each

  Section table (uint32 BE):
    0x00  settings_start      (always 50 = 0x32)
    0x04  settings_size
    0x08  screen_buffer_start
    0x0C  screen_buffer_size
    0x10  waveform_data_start (W)
    0x14  waveform_data_size  (D = active_channels × sample_count × 2)
    0x18  total_file_size     (= W + D)

  Channel enable flags (firmware: struct+0x3C / struct+0xEC):
    0x66  CH1 enabled (uint8, non-zero = on)
    0xA6  CH2 enabled (uint8, non-zero = on)

  V/div indices (uint16 BE, standard 1-2-5 table 0-9):
    0x6A  CH1 V/div index
    0xAA  CH2 V/div index

  Stale V/div flags (uint8, 0=current, 1=stale from prev capture):
    0x62  CH1 stale flag
    0xA2  CH2 stale flag

  Time/div in picoseconds (uint32 BE) at 0x1D9.
  ADC sample rate in Hz (uint32 BE) at 0x13D.
  ADC calibration: voltage_mV = (adc - 6400) * vdiv_mV / 1600
"""

import struct
import csv
import sys
import os
import argparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
import io

# --- Constants ---

FILE_SIZE = 15000
SAMPLES_PER_CHANNEL = 1500
SAMPLES_PER_DIV = 100   # 100 samples per horizontal division
N_HDIV = 15             # number of horizontal divisions

# Data offsets (uint16 index)
CH1_START = 500   # byte 1000
CH2_START = 2000  # byte 4000

# Timebase lookup: index → nanoseconds per division
# 1-2-5 sequence, higher index = faster timebase
# Empirically verified: tb=25 → 500ns/div, tb=24 → 1µs/div
TIMEBASE_NS_PER_DIV = {
    0: 100_000_000_000,  # 100s
    1:  50_000_000_000,  # 50s
    2:  20_000_000_000,  # 20s
    3:  10_000_000_000,  # 10s
    4:   5_000_000_000,  # 5s
    5:   2_000_000_000,  # 2s
    6:   1_000_000_000,  # 1s
    7:     500_000_000,  # 500ms
    8:     200_000_000,  # 200ms
    9:     100_000_000,  # 100ms
   10:      50_000_000,  # 50ms
   11:      20_000_000,  # 20ms
   12:      10_000_000,  # 10ms
   13:       5_000_000,  # 5ms
   14:       2_000_000,  # 2ms
   15:       1_000_000,  # 1ms
   16:         500_000,  # 500µs
   17:         200_000,  # 200µs
   18:         100_000,  # 100µs
   19:          50_000,  # 50µs
   20:          20_000,  # 20µs
   21:          10_000,  # 10µs
   22:           5_000,  # 5µs
   23:           2_000,  # 2µs
   24:           1_000,  # 1µs
   25:             500,  # 500ns
}


def format_time(ns):
    """Format nanoseconds into a human-readable string."""
    if ns >= 1e9:
        return f"{ns/1e9:.6g}s"
    elif ns >= 1e6:
        return f"{ns/1e6:.6g}ms"
    elif ns >= 1e3:
        return f"{ns/1e3:.6g}µs"
    else:
        return f"{ns:.6g}ns"


def format_time_per_div(ns_per_div):
    """Format timebase as time/div string."""
    return format_time(ns_per_div) + "/div"


def parse_trace(filepath):
    """
    Parse an FNIRSI 1014D .wav trace file.

    Returns a dict with:
      ch1_raw, ch2_raw: raw ADC values (list of int)
      ch1_mV, ch2_mV:   voltage in millivolts (list of float)
      time_ns:           time axis in nanoseconds (list of float)
      ch2_enabled:       bool
      timebase_idx:      int
      ns_per_div:        float
      ch1_vpp_mV, ch2_vpp_mV: int
      ch1_gnd, ch2_gnd:  int (GND ADC offsets)
      sample_interval_ns: float
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) != FILE_SIZE:
        raise ValueError(
            f"Invalid file size: expected {FILE_SIZE} bytes, got {len(data)}"
        )

    vals = struct.unpack('<' + 'H' * (FILE_SIZE // 2), data)

    # --- Parse header ---
    ch2_enabled = vals[6] != 0
    timebase_idx = vals[11]
    ch1_gnd = vals[41]
    ch2_gnd = vals[42]
    ch1_vpp_mV = vals[105]
    ch2_vpp_mV = vals[129] if ch2_enabled else 0

    # --- Extract raw samples (always decode both channels) ---
    ch1_raw = list(vals[CH1_START:CH1_START + SAMPLES_PER_CHANNEL])
    ch2_raw = list(vals[CH2_START:CH2_START + SAMPLES_PER_CHANNEL])

    # --- Time axis ---
    ns_per_div = TIMEBASE_NS_PER_DIV.get(timebase_idx)
    if ns_per_div is None:
        print(f"  Warning: unknown timebase index {timebase_idx}, "
              f"defaulting to 1µs/div", file=sys.stderr)
        ns_per_div = 1000  # 1µs/div fallback

    sample_interval_ns = ns_per_div / SAMPLES_PER_DIV
    time_ns = [i * sample_interval_ns for i in range(SAMPLES_PER_CHANNEL)]

    # --- Voltage conversion ---
    def adc_to_mV(raw_samples, gnd_offset, vpp_mV):
        lo = min(raw_samples)
        hi = max(raw_samples)
        adc_range = hi - lo
        if adc_range > 0 and vpp_mV > 0:
            mV_per_count = vpp_mV / adc_range
        else:
            # Flat signal or no Vpp info — assume 10 mV/count (≈500mV/div)
            mV_per_count = 10.0
        return [round((v - gnd_offset) * mV_per_count, 2) for v in raw_samples]

    ch1_mV = adc_to_mV(ch1_raw, ch1_gnd, ch1_vpp_mV)
    ch2_mV = adc_to_mV(ch2_raw, ch2_gnd, ch2_vpp_mV if ch2_enabled else ch1_vpp_mV)

    return {
        'ch1_raw': ch1_raw,
        'ch2_raw': ch2_raw,
        'ch1_mV': ch1_mV,
        'ch2_mV': ch2_mV,
        'time_ns': time_ns,
        'ch2_enabled': ch2_enabled,
        'timebase_idx': timebase_idx,
        'ns_per_div': ns_per_div,
        'ch1_vpp_mV': ch1_vpp_mV,
        'ch2_vpp_mV': ch2_vpp_mV,
        'ch1_gnd': ch1_gnd,
        'ch2_gnd': ch2_gnd,
        'sample_interval_ns': sample_interval_ns,
        'model': '1014D',
    }


# --- DPOX180H display constants ---
DPOX_N_VDIV = 8          # vertical divisions on screen
DPOX_ADC_MAX = 12800     # full ADC range (0..12800)
DPOX_ADC_CENTER = 6400   # center of screen in ADC counts
DPOX_COUNTS_PER_DIV = DPOX_ADC_MAX // DPOX_N_VDIV  # 1600

# Standard V/div table (mV), indexed 0-9
DPOX_VDIV_TABLE = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]

# Header offsets (firmware: FUN_0005c98c serialises oscilloscope state struct)
# V/div index: struct+0x42 (CH1) / struct+0xF2 (CH2), written as u8(pad)+u16
# The u16BE read at 0x6A works because the pad byte (struct+0x40) is always 0.
DPOX_CH1_VDIV_IDX_OFFSET = 0x6A  # struct+0x40(1B) + struct+0x42(2B)
DPOX_CH2_VDIV_IDX_OFFSET = 0xAA  # struct+0xF0(1B) + struct+0xF2(2B)

# Channel enable flags (firmware: struct+0x3C for CH1, struct+0xEC for CH2)
# FUN_0005da08 checks these to decide whether to write CH1/CH2 ADC samples.
DPOX_CH1_ENABLE_OFFSET = 0x66
DPOX_CH2_ENABLE_OFFSET = 0xA6


def _dpox_read_vdiv(data, offset):
    """Read V/div index from header and return value in mV."""
    idx = struct.unpack('>H', data[offset:offset + 2])[0]
    if 0 <= idx < len(DPOX_VDIV_TABLE):
        return DPOX_VDIV_TABLE[idx]
    return None


def parse_trace_dpox180h(filepath, ch1_vdiv_mV=None, ch2_vdiv_mV=None):
    """
    Parse an FNIRSI DPOX180H .wav trace file.

    File layout (4 contiguous sections):
      [0x00 .. 0x32)            — section table (7 × u32 BE + reserved)
      [0x32 .. +settings_size)  — settings (oscilloscope state)
      [scr_start .. +scr_size)  — screen buffer (RGB565 thumbnail)
      [wav_start .. +wav_size)  — waveform ADC data (CH1 then CH2, uint16 BE)

    ADC data contains only enabled channels (per flags at 0x66/0xA6),
    sample_count samples each (from header field 0x12D).

    ch1_vdiv_mV / ch2_vdiv_mV: V/div in millivolts for each channel.
      If provided, overrides the value read from the header.
      Otherwise, V/div is auto-detected from the header (index at
      0x6A for CH1, 0xAA for CH2 → standard 1-2-5 table).
      Calibrated formula: voltage_mV = (adc - 6400) * vdiv_mV / 1600

    Returns a dict compatible with save_csv / save_png / save_tek_*.
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    if len(data) < 256:
        raise ValueError(
            f"File too small for DPOX180H format: {len(data)} bytes"
        )

    # --- Parse section table (7 × uint32 BE at 0x00–0x1B) ---
    settings_start    = struct.unpack('>I', data[0x00:0x04])[0]
    settings_size     = struct.unpack('>I', data[0x04:0x08])[0]
    scr_buf_start     = struct.unpack('>I', data[0x08:0x0C])[0]
    scr_buf_size      = struct.unpack('>I', data[0x0C:0x10])[0]
    wav_data_start    = struct.unpack('>I', data[0x10:0x14])[0]
    wav_data_size     = struct.unpack('>I', data[0x14:0x18])[0]
    total_file_size   = struct.unpack('>I', data[0x18:0x1C])[0]

    if len(data) != total_file_size:
        raise ValueError(
            f"DPOX180H: file size mismatch: header says {total_file_size}, "
            f"actual {len(data)}"
        )
    # Validate section continuity invariants
    if settings_start + settings_size != scr_buf_start:
        raise ValueError(
            f"DPOX180H: section gap: settings end "
            f"({settings_start + settings_size}) != "
            f"screen_buffer_start ({scr_buf_start})"
        )
    if scr_buf_start + scr_buf_size != wav_data_start:
        raise ValueError(
            f"DPOX180H: section gap: screen_buffer end "
            f"({scr_buf_start + scr_buf_size}) != "
            f"waveform_data_start ({wav_data_start})"
        )
    if wav_data_start + wav_data_size != total_file_size:
        raise ValueError(
            f"DPOX180H: section gap: waveform end "
            f"({wav_data_start + wav_data_size}) != "
            f"total_file_size ({total_file_size})"
        )

    # --- Time/div (uint32 BE at offset 0x1D9, in picoseconds) ---
    tdiv_ps = struct.unpack('>I', data[0x1D9:0x1DD])[0]
    if tdiv_ps == 0:
        print("  Warning: time/div is 0, defaulting to 1µs",
              file=sys.stderr)
        tdiv_ps = 1_000_000  # 1µs in picoseconds

    # --- Sample rate ---
    # Primary: ADC sample rate at 0x13D (uint32 BE).
    # For real-time captures this equals 6 * tdiv / spc exactly.
    # For ETS captures (effective rate > 1 GSa/s) the value at 0x13D
    # does not match the display time span; fall back to display formula.
    adc_sample_rate = struct.unpack('>I', data[0x13D:0x141])[0]
    dual_tb_flag_ch1 = data[0x62]
    dual_tb_flag_ch2 = data[0xA2]
    original_sample_rate = adc_sample_rate
    dual_tb_corrected = False  # kept for backward compatibility
    is_ets = False

    # --- Channel enable flags (firmware-confirmed at 0x66/0xA6) ---
    # The firmware only writes ADC data for enabled channels.
    # Disabled channels have no data in the waveform section.
    ch1_enabled_flag = data[DPOX_CH1_ENABLE_OFFSET] != 0
    ch2_enabled_flag = data[DPOX_CH2_ENABLE_OFFSET] != 0
    active_channels = int(ch1_enabled_flag) + int(ch2_enabled_flag)

    # --- Sample count per channel ---
    if active_channels > 0 and wav_data_size > 0:
        samples_per_channel = wav_data_size // (active_channels * 2)
    else:
        samples_per_channel = 0

    # Cross-validate with buffer_sample_count at 0x12D
    if len(data) > 0x131:
        header_spc = struct.unpack('>I', data[0x12D:0x131])[0]
        if header_spc != 0 and header_spc != samples_per_channel:
            print(f"  Warning: sample count: waveform section gives "
                  f"{samples_per_channel}, header 0x12D says {header_spc}",
                  file=sys.stderr)

    if samples_per_channel == 0:
        raise ValueError("DPOX180H: no waveform data (both channels disabled?)")

    # --- Extract ADC samples from waveform data section ---
    # Data layout: [CH1 samples if enabled] [CH2 samples if enabled]
    # Each sample is uint16 BE, sample_count per channel.
    offset = wav_data_start

    if ch1_enabled_flag:
        ch1_raw = list(struct.unpack(
            '>' + 'H' * samples_per_channel,
            data[offset:offset + samples_per_channel * 2]))
        offset += samples_per_channel * 2
    else:
        ch1_raw = [DPOX_ADC_CENTER] * samples_per_channel

    if ch2_enabled_flag:
        ch2_raw = list(struct.unpack(
            '>' + 'H' * samples_per_channel,
            data[offset:offset + samples_per_channel * 2]))
    else:
        ch2_raw = [DPOX_ADC_CENTER] * samples_per_channel

    ch2_enabled = ch2_enabled_flag

    # --- Time axis ---
    # ns_per_div is known exactly from 0x1D9
    ns_per_div = tdiv_ps / 1000.0
    display_time_ps = 6 * tdiv_ps  # 6 horizontal divisions
    display_time_s = display_time_ps * 1e-12

    # Choose sample rate: detect ETS by effective display rate, otherwise
    # use the real ADC sample rate (buffer may be larger than display).
    eff_rate = samples_per_channel / display_time_s if display_time_s > 0 else 0
    if eff_rate > 1e9:
        # Effective rate > 1 GSa/s → ETS (equivalent-time sampling)
        # The scope reconstructs a fast waveform from many slow captures;
        # display geometry defines the time axis.
        sample_rate = eff_rate
        is_ets = True
    elif adc_sample_rate > 0:
        # Real-time mode: use ADC sample rate from 0x13D.
        # Buffer may contain more samples than screen (long capture).
        sample_rate = adc_sample_rate
        is_ets = False
    else:
        sample_rate = eff_rate if eff_rate > 0 else 5_000_000
        is_ets = False

    sample_interval_ns = 1e9 / sample_rate
    time_ns = [i * sample_interval_ns for i in range(samples_per_channel)]

    # --- V/div: CLI override → header auto-detect → uncalibrated fallback ---
    vdiv_source = 'cli' if (ch1_vdiv_mV is not None or ch2_vdiv_mV is not None) else None
    if ch1_vdiv_mV is None:
        ch1_vdiv_mV = _dpox_read_vdiv(data, DPOX_CH1_VDIV_IDX_OFFSET)
        if ch1_vdiv_mV is not None and vdiv_source is None:
            vdiv_source = 'header'
    if ch2_vdiv_mV is None:
        ch2_vdiv_mV = _dpox_read_vdiv(data, DPOX_CH2_VDIV_IDX_OFFSET)

    # --- Stale V/div correction ---
    # When a channel's flag (0x62 for CH1, 0xA2 for CH2) is 1, the V/div
    # index stored in the header is stale (from a previous capture).
    # If exactly one flag is set, the non-flagged channel has the correct
    # V/div; copy it to the flagged channel.
    # If both flags are set, both V/div are stale and no auto-fix is
    # possible — warn the user.
    vdiv_corrected = False
    both_vdiv_stale = False
    if vdiv_source != 'cli':
        if dual_tb_flag_ch1 == 1 and dual_tb_flag_ch2 == 0 and ch2_vdiv_mV is not None:
            ch1_vdiv_mV = ch2_vdiv_mV
            vdiv_corrected = True
        elif dual_tb_flag_ch2 == 1 and dual_tb_flag_ch1 == 0 and ch1_vdiv_mV is not None:
            ch2_vdiv_mV = ch1_vdiv_mV
            vdiv_corrected = True
        elif dual_tb_flag_ch1 == 1 and dual_tb_flag_ch2 == 1:
            both_vdiv_stale = True
            print("  Warning: both V/div flags are set — stored V/div "
                  f"(CH1={_format_vdiv(ch1_vdiv_mV) if ch1_vdiv_mV else '?'}, "
                  f"CH2={_format_vdiv(ch2_vdiv_mV) if ch2_vdiv_mV else '?'}) "
                  "may be stale. Use --vdiv to override.",
                  file=sys.stderr)

    calibrated = ch1_vdiv_mV is not None
    ch1_gnd = DPOX_ADC_CENTER
    ch2_gnd = DPOX_ADC_CENTER

    if calibrated:
        # Proper calibration: voltage = (adc - center) * vdiv / counts_per_div
        ch1_mV_per_count = ch1_vdiv_mV / DPOX_COUNTS_PER_DIV
        ch1_mV = [round((v - DPOX_ADC_CENTER) * ch1_mV_per_count, 2)
                  for v in ch1_raw]
        c2_vdiv = ch2_vdiv_mV if ch2_vdiv_mV is not None else ch1_vdiv_mV
        ch2_mV_per_count = c2_vdiv / DPOX_COUNTS_PER_DIV
        ch2_mV = [round((v - DPOX_ADC_CENTER) * ch2_mV_per_count, 2)
                  for v in ch2_raw]
    else:
        # Uncalibrated fallback: 10 mV/count from median-based GND
        def estimate_gnd(raw_samples):
            s = sorted(raw_samples)
            n = len(s)
            return (s[n // 2] + s[(n - 1) // 2]) / 2
        ch1_gnd = int(estimate_gnd(ch1_raw))
        ch2_gnd = int(estimate_gnd(ch2_raw))
        mV_per_count = 10.0
        ch1_mV = [round((v - ch1_gnd) * mV_per_count, 2) for v in ch1_raw]
        ch2_mV = [round((v - ch2_gnd) * mV_per_count, 2) for v in ch2_raw]

    # Vpp from data
    ch1_vpp_mV = round(max(ch1_mV) - min(ch1_mV), 2) if ch1_mV else 0
    ch2_vpp_mV = round(max(ch2_mV) - min(ch2_mV), 2) if ch2_mV else 0

    return {
        'ch1_raw': ch1_raw,
        'ch2_raw': ch2_raw,
        'ch1_mV': ch1_mV,
        'ch2_mV': ch2_mV,
        'time_ns': time_ns,
        'ch2_enabled': ch2_enabled,
        'timebase_idx': -1,
        'ns_per_div': ns_per_div,
        'ch1_vpp_mV': ch1_vpp_mV,
        'ch2_vpp_mV': ch2_vpp_mV,
        'ch1_gnd': ch1_gnd,
        'ch2_gnd': ch2_gnd,
        'sample_interval_ns': sample_interval_ns,
        'sample_rate': sample_rate,
        'samples_per_channel': samples_per_channel,
        'settings_size': settings_size,
        'wav_data_start': wav_data_start,
        'wav_data_size': wav_data_size,
        'model': 'DPOX180H',
        'calibrated': calibrated,
        'vdiv_source': vdiv_source if calibrated else None,
        'ch1_vdiv_mV': ch1_vdiv_mV,
        'ch2_vdiv_mV': ch2_vdiv_mV if ch2_vdiv_mV is not None else ch1_vdiv_mV,
        'dual_tb_corrected': dual_tb_corrected,
        'original_sample_rate': original_sample_rate,
        'is_ets': is_ets,
        'tdiv_ps': tdiv_ps,
        'vdiv_corrected': vdiv_corrected,
        'both_vdiv_stale': both_vdiv_stale,
    }


def _format_vdiv(mV):
    """Format V/div value in mV to human-readable string."""
    if mV >= 1000:
        return f"{mV/1000:.6g}V"
    else:
        return f"{mV:.6g}mV"


def save_csv(trace, output_path):
    """Export trace data to CSV."""
    n_samples = len(trace['ch1_raw'])
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)

        writer.writerow([
            'time_ns', 'ch1_mV', 'ch2_mV', 'ch1_raw', 'ch2_raw'
        ])
        for i in range(n_samples):
            writer.writerow([
                f"{trace['time_ns'][i]:.2f}",
                f"{trace['ch1_mV'][i]:.2f}",
                f"{trace['ch2_mV'][i]:.2f}",
                trace['ch1_raw'][i],
                trace['ch2_raw'][i],
            ])


def choose_time_units(max_ns):
    """Choose appropriate time units for the plot axis."""
    if max_ns >= 1e9:
        return 1e9, 's'
    elif max_ns >= 1e6:
        return 1e6, 'ms'
    elif max_ns >= 1e3:
        return 1e3, 'µs'
    else:
        return 1, 'ns'


def save_png(trace, output_path, title=''):
    """Generate a PNG plot of the trace."""
    fig, ax = plt.subplots(figsize=(14, 6))

    # Time units
    factor, unit = choose_time_units(trace['time_ns'][-1])
    time_plot = [t / factor for t in trace['time_ns']]

    # Timebase label
    tb_label = format_time_per_div(trace['ns_per_div'])

    # Plot channels
    is_dpox = trace.get('model') == 'DPOX180H'
    dpox_cal = trace.get('calibrated', False)
    if is_dpox and not dpox_cal:
        ch1_label = 'CH1'
        y_label = 'mV (uncalibrated, 10 mV/count)'
    elif is_dpox and dpox_cal:
        ch1_vd = trace.get('ch1_vdiv_mV', 0)
        ch1_label = f"CH1 ({_format_vdiv(ch1_vd)}/div)"
        y_label = 'Voltage (mV)'
    else:
        ch1_label = f"CH1 (Vpp={trace['ch1_vpp_mV']}mV)"
        y_label = 'Voltage (mV)'
    ax.plot(time_plot, trace['ch1_mV'],
            label=ch1_label, color='#FFD700', linewidth=0.8)

    ch2_disabled_tag = '' if trace['ch2_enabled'] else ' [off]'
    if is_dpox and dpox_cal:
        ch2_vd = trace.get('ch2_vdiv_mV', 0)
        ch2_label = f"CH2 ({_format_vdiv(ch2_vd)}/div){ch2_disabled_tag}"
    elif is_dpox:
        ch2_label = f"CH2{ch2_disabled_tag}"
    else:
        ch2_label = f"CH2 (Vpp={trace['ch2_vpp_mV']}mV){ch2_disabled_tag}"
    ax.plot(time_plot, trace['ch2_mV'],
            label=ch2_label, color='#00FFFF', linewidth=0.8)

    # Styling (dark oscilloscope theme)
    ax.set_xlabel(f'Time ({unit})', color='white')
    ax.set_ylabel(y_label, color='white')
    ax.set_title(
        (title or os.path.basename(output_path)) + f'  [{tb_label}]',
        color='white', fontsize=13
    )
    ax.legend(
        facecolor='#16213e', edgecolor='#555',
        labelcolor='white', fontsize=10
    )
    ax.grid(True, alpha=0.25, color='#446688')
    ax.set_facecolor('#1a1a2e')
    fig.patch.set_facecolor('#0f0f23')
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#444')

    # Zero line
    ax.axhline(y=0, color='#666', linewidth=0.5, linestyle='--')

    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)


def save_plot(trace, output_path, title='', fmt='png'):
    """Generate a plot of the trace in the given format (png or bmp)."""
    fig, ax = plt.subplots(figsize=(14, 6))

    factor, unit = choose_time_units(trace['time_ns'][-1])
    time_plot = [t / factor for t in trace['time_ns']]
    tb_label = format_time_per_div(trace['ns_per_div'])

    is_dpox = trace.get('model') == 'DPOX180H'
    dpox_cal = trace.get('calibrated', False)
    if is_dpox and not dpox_cal:
        ch1_label = 'CH1'
        y_label = 'mV (uncalibrated, 10 mV/count)'
    elif is_dpox and dpox_cal:
        ch1_vd = trace.get('ch1_vdiv_mV', 0)
        ch1_label = f"CH1 ({_format_vdiv(ch1_vd)}/div)"
        y_label = 'Voltage (mV)'
    else:
        ch1_label = f"CH1 (Vpp={trace['ch1_vpp_mV']}mV)"
        y_label = 'Voltage (mV)'
    ax.plot(time_plot, trace['ch1_mV'],
            label=ch1_label, color='#FFD700', linewidth=0.8)

    ch2_disabled_tag = '' if trace['ch2_enabled'] else ' [off]'
    if is_dpox and dpox_cal:
        ch2_vd = trace.get('ch2_vdiv_mV', 0)
        ch2_label = f"CH2 ({_format_vdiv(ch2_vd)}/div){ch2_disabled_tag}"
    elif is_dpox:
        ch2_label = f"CH2{ch2_disabled_tag}"
    else:
        ch2_label = f"CH2 (Vpp={trace['ch2_vpp_mV']}mV){ch2_disabled_tag}"
    ax.plot(time_plot, trace['ch2_mV'],
            label=ch2_label, color='#00FFFF', linewidth=0.8)

    ax.set_xlabel(f'Time ({unit})', color='white')
    ax.set_ylabel(y_label, color='white')
    ax.set_title(
        (title or os.path.basename(output_path)) + f'  [{tb_label}]',
        color='white', fontsize=13
    )
    ax.legend(
        facecolor='#16213e', edgecolor='#555',
        labelcolor='white', fontsize=10
    )
    ax.grid(True, alpha=0.25, color='#446688')
    ax.set_facecolor('#1a1a2e')
    fig.patch.set_facecolor('#0f0f23')
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#444')
    ax.axhline(y=0, color='#666', linewidth=0.5, linestyle='--')

    if fmt == 'bmp':
        buf = io.BytesIO()
        fig.savefig(buf, dpi=150, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), format='png')
        plt.close(fig)
        buf.seek(0)
        img = Image.open(buf)
        img.save(output_path, format='BMP')
        buf.close()
    else:
        fig.savefig(output_path, dpi=150, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), format=fmt)
        plt.close(fig)


def save_tek_csv(trace, output_path, channel='CH1'):
    """
    Export a single channel in Tektronix-compatible CSV format.

    Format matches TDS2012C CSV output:
      - First 18 rows: header fields in cols 1-2 + data in cols 4-5
      - Remaining rows: data only in cols 4-5 (prefixed with ,,,)
    """
    n_samples = len(trace['time_ns'])
    sample_interval_s = trace['sample_interval_ns'] * 1e-9
    ns_per_div = trace['ns_per_div']
    h_scale_s = ns_per_div * 1e-9

    if channel == 'CH2':
        mV_data = trace['ch2_mV']
        vpp_mV = trace['ch2_vpp_mV']
        source = 'CH2'
    else:
        mV_data = trace['ch1_mV']
        vpp_mV = trace['ch1_vpp_mV']
        source = 'CH1'

    # Voltage in V
    v_data = [mv / 1000.0 for mv in mV_data]

    # Time axis in seconds, centered around trigger (midpoint)
    trigger_sample = n_samples // 2
    time_s = [(i - trigger_sample) * sample_interval_s for i in range(n_samples)]

    # Estimate vertical scale from Vpp
    v_scale = vpp_mV / 1000.0 / 4.0  # ~4 divisions for Vpp
    # Round to nearest standard V/div value
    std_vdiv = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
    v_scale = min(std_vdiv, key=lambda x: abs(x - v_scale))

    # Header rows (Tektronix TDS format)
    header_rows = [
        (f'Record Length,{n_samples:.6e}',),
        (f'Sample Interval,{sample_interval_s:.6e}',),
        (f'Trigger Point,{trigger_sample:.12e}',),
        ('',),
        ('',),
        ('',),
        (f'Source,{source}',),
        ('Vertical Units,V',),
        (f'Vertical Scale,{v_scale:.6e}',),
        ('Vertical Offset,0.000000e+00',),
        ('Horizontal Units,s',),
        (f'Horizontal Scale,{h_scale_s:.6e}',),
        ('Pt Fmt,Y',),
        ('Yzero,0.000000e+00',),
        ('Probe Atten,1.000000e+00',),
        (f'Model Number,FNIRSI {trace.get("model", "1014D")}',),
        ('Serial Number,',),
        ('Firmware Version,',),
    ]

    with open(output_path, 'w', newline='') as f:
        for i in range(n_samples):
            t_val = time_s[i]
            v_val = v_data[i]

            if i < len(header_rows):
                hdr = header_rows[i][0]
                t_str = f'  {t_val:+.12f}'
                v_str = f'  {v_val:+.5f}'
                if hdr:
                    f.write(f'{hdr},,{t_str},{v_str},\n')
                else:
                    f.write(f',,,{t_str},{v_str},\n')
            else:
                t_str = f'{t_val:+015.12f}'
                v_str = f'  {v_val:+.5f}'
                f.write(f',,,{t_str},{v_str},\n')


def save_tek_bundle(trace, out_dir, name, title=''):
    """
    Save trace in Tektronix-compatible directory structure:
      ALL{name}/
        F{name}CH1.CSV   — CH1 data
        F{name}CH2.CSV   — CH2 data (if dual channel)
        F{name}TEK.BMP   — waveform plot
    """
    bundle_dir = os.path.join(out_dir, f'ALL{name}')
    os.makedirs(bundle_dir, exist_ok=True)

    # CH1 CSV
    ch1_csv = os.path.join(bundle_dir, f'F{name}CH1.CSV')
    save_tek_csv(trace, ch1_csv, channel='CH1')

    # CH2 CSV
    ch2_csv = os.path.join(bundle_dir, f'F{name}CH2.CSV')
    save_tek_csv(trace, ch2_csv, channel='CH2')

    # BMP plot
    bmp_path = os.path.join(bundle_dir, f'F{name}TEK.BMP')
    save_plot(trace, bmp_path, title=title, fmt='bmp')

    return bundle_dir, ch1_csv, ch2_csv, bmp_path


def print_info(filepath, trace):
    """Print summary info about the trace."""
    name = os.path.basename(filepath)
    model = trace.get('model', '1014D')
    tb = format_time_per_div(trace['ns_per_div'])
    si = format_time(trace['sample_interval_ns'])
    n_samples = len(trace['ch1_raw'])
    total = format_time(trace['time_ns'][-1])

    print(f"  File:       {name}")
    print(f"  Model:      FNIRSI {model}")
    if model == 'DPOX180H':
        sr = trace.get('sample_rate', 0)
        sr_str = f"{sr/1e6:.3g} MHz" if sr >= 1e6 else f"{sr/1e3:.3g} kHz"
        ets_note = "  (ETS — time axis approximate)" if trace.get('is_ets') else ""
        print(f"  SampleRate: {sr_str}{ets_note}")
        print(f"  Timebase:   {tb}")
        if trace.get('calibrated'):
            ch1_vd = trace.get('ch1_vdiv_mV', 0)
            ch2_vd = trace.get('ch2_vdiv_mV', 0)
            src = trace.get('vdiv_source', 'unknown')
            if trace.get('both_vdiv_stale'):
                print(f"  V/div:      CH1={_format_vdiv(ch1_vd)} (possibly stale), CH2={_format_vdiv(ch2_vd)} (possibly stale)  (from {src})")
            elif trace.get('vdiv_corrected'):
                print(f"  V/div:      CH1={_format_vdiv(ch1_vd)}, CH2={_format_vdiv(ch2_vd)}  (corrected — stale flag detected)")
            else:
                print(f"  V/div:      CH1={_format_vdiv(ch1_vd)}, CH2={_format_vdiv(ch2_vd)}  (from {src})")
        else:
            print(f"  V/div:      not detected (use --vdiv to calibrate)")
    else:
        print(f"  Timebase:   {tb}  (index {trace['timebase_idx']})")
    print(f"  Sample int: {si}  ({n_samples} samples, total {total})")
    print(f"  CH1:        Vpp={trace['ch1_vpp_mV']}mV, "
          f"GND offset={trace['ch1_gnd']}, "
          f"ADC range=[{min(trace['ch1_raw'])}-{max(trace['ch1_raw'])}]")
    ch2_status = '' if trace['ch2_enabled'] else ' (disabled in header)'
    print(f"  CH2:        Vpp={trace['ch2_vpp_mV']}mV, "
          f"GND offset={trace['ch2_gnd']}, "
          f"ADC range=[{min(trace['ch2_raw'])}-{max(trace['ch2_raw'])}]"
          f"{ch2_status}")


def main():
    parser = argparse.ArgumentParser(
        description='FNIRSI oscilloscope WAV trace decoder — '
                    'converts .wav traces to .csv and .png'
    )
    parser.add_argument(
        'files', nargs='+', metavar='FILE',
        help='WAV trace file(s) to decode'
    )
    parser.add_argument(
        '-o', '--output-dir', default=None,
        help='Output directory (default: same directory as input file)'
    )
    parser.add_argument(
        '-t', '--tek', action='store_true',
        help='Also export in Tektronix-compatible format '
             '(ALL{name}/ directory with per-channel CSV + BMP)'
    )
    parser.add_argument(
        '-m', '--model', default='1014d',
        choices=['1014d', 'dpox180h'],
        help='Oscilloscope model (default: 1014d)'
    )
    parser.add_argument(
        '--vdiv', metavar='CH1[,CH2]',
        help='V/div in millivolts for DPOX180H channels, comma-separated '
             '(e.g. --vdiv 10000,500 for CH1=10V CH2=500mV). '
             'One value applies to both channels. '
             'Overrides auto-detection from the file header.'
    )
    args = parser.parse_args()

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    model_name = 'FNIRSI DPOX180H' if args.model == 'dpox180h' else 'FNIRSI 1014D'

    # V/div for DPOX180H
    ch1_vdiv = ch2_vdiv = None
    if args.vdiv and args.model == 'dpox180h':
        parts = [float(x) for x in args.vdiv.split(',')]
        ch1_vdiv = parts[0]
        ch2_vdiv = parts[1] if len(parts) > 1 else parts[0]

    if args.model == 'dpox180h':
        def parse_fn(fp):
            return parse_trace_dpox180h(fp, ch1_vdiv, ch2_vdiv)
    else:
        parse_fn = parse_trace

    for filepath in args.files:
        if not os.path.isfile(filepath):
            print(f"ERROR: File not found: {filepath}", file=sys.stderr)
            continue

        basename = os.path.splitext(os.path.basename(filepath))[0]
        out_dir = args.output_dir or os.path.dirname(filepath) or '.'

        try:
            trace = parse_fn(filepath)
        except ValueError as e:
            print(f"ERROR: {filepath}: {e}", file=sys.stderr)
            continue

        csv_path = os.path.join(out_dir, f'{basename}.csv')
        png_path = os.path.join(out_dir, f'{basename}.png')

        save_csv(trace, csv_path)
        save_png(trace, png_path, title=f'{model_name} — {basename}')

        print(f"\n{'='*50}")
        print_info(filepath, trace)
        print(f"  CSV:        {csv_path}")
        print(f"  PNG:        {png_path}")

        if args.tek:
            tek_name = basename.zfill(4)
            bundle_dir, ch1_csv, ch2_csv, bmp_path = save_tek_bundle(
                trace, out_dir, tek_name,
                title=f'{model_name} — {basename}'
            )
            print(f"  TEK dir:    {bundle_dir}")
            print(f"  TEK CH1:    {ch1_csv}")
            if ch2_csv:
                print(f"  TEK CH2:    {ch2_csv}")
            print(f"  TEK BMP:    {bmp_path}")


if __name__ == '__main__':
    main()
