# FNIRSI Oscilloscope Trace Decoder

Decodes proprietary `.wav` trace files saved by **FNIRSI** oscilloscopes and exports them as:

- **CSV** — time (ns) + voltage (mV) + raw ADC values
- **PNG** — waveform plot with oscilloscope-style dark theme
- **Tektronix-compatible bundle** (optional) — per-channel CSV + BMP image in `ALLxxxx/` directory structure

Supported models:
- **FNIRSI 1014D** — 15000-byte files, uint16 LE, calibrated voltage
- **FNIRSI DPOX180H** — variable-size files, uint16 BE, V/div auto-detected from header (override with `--vdiv`)

## Requirements

- Python 3.8+
- Dependencies listed in `requirements.txt`

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Basic — export to CSV + PNG (1014D, default)

```bash
python fnirsi_decoder.py trace1.wav trace2.wav
```

### DPOX180H mode

```bash
python fnirsi_decoder.py -m dpox180h Waveform/*.wav -o output
```

### DPOX180H with V/div override

V/div is auto-detected from the file header. To override, use `--vdiv`:

```bash
# Override: CH1=1V/div, CH2=500mV/div
python fnirsi_decoder.py -m dpox180h --vdiv 1000,500 Waveform/19.wav -o output

# Single value applies to both channels
python fnirsi_decoder.py -m dpox180h --vdiv 1000 Waveform/*.wav -o output
```

V/div values are in millivolts (e.g. 10000 = 10V, 500 = 500mV, 1000 = 1V).

Output files are saved next to the input files (`trace1.csv`, `trace1.png`, etc.).

### Specify output directory

```bash
python fnirsi_decoder.py test_oscil/*.wav -o output
```

### Tektronix-compatible export (`-t`)

```bash
python fnirsi_decoder.py test_oscil/4.wav test_oscil/7.wav -o output -t
```

This additionally creates a Tektronix TDS2012C-compatible directory structure:

```
output/
├── 4.csv                  # standard CSV
├── 4.png                  # standard PNG plot
├── ALL0004/
│   ├── F0004CH1.CSV       # CH1 in Tektronix CSV format
│   └── F0004TEK.BMP       # waveform plot as BMP
├── 7.csv
├── 7.png
└── ALL0007/
    ├── F0007CH1.CSV
    ├── F0007CH2.CSV       # CH2 (dual-channel traces only)
    └── F0007TEK.BMP
```

The Tektronix CSV format includes a standard 18-row header (`Record Length`, `Sample Interval`, `Vertical Scale`, `Horizontal Scale`, etc.) with time in seconds and voltage in volts — compatible with tools that import TDS2012C data.

### Command-line options

| Option | Description |
|---|---|
| `FILE ...` | One or more `.wav` trace files to decode |
| `-o DIR` | Output directory (default: same as input file) |
| `-t` | Also export in Tektronix-compatible format |
| `-m MODEL` | Oscilloscope model: `1014d` (default) or `dpox180h` |
| `--vdiv CH1[,CH2]` | V/div in mV for DPOX180H (e.g. `10000,500`). Overrides auto-detection from header. |

### Example output

```
==================================================
  File:       4.wav
  Timebase:   500ns/div  (index 25)
  Sample int: 5ns  (1500 samples, total 7.495µs)
  CH1:        Vpp=1313mV, GND offset=202, ADC range=[139-267]
  CH2:        disabled
  CSV:        output/4.csv
  PNG:        output/4.png
```

### DPOX180H example output

V/div auto-detected from header:
```
==================================================
  File:       19.wav
  Model:      FNIRSI DPOX180H
  SampleRate: 10 MHz
  Timebase:   100µs/div
  V/div:      CH1=100mV, CH2=200mV  (from header)
  Sample int: 100ns  (12000 samples, total 1.1999ms)
  CH1:        Vpp=497.06mV, GND offset=6400, ADC range=[4847-12800]
  CH2:        Vpp=1600.0mV, GND offset=6400, ADC range=[0-12800]
```

Long-buffer capture (buffer extends beyond display window):
```
==================================================
  File:       56.wav
  Model:      FNIRSI DPOX180H
  SampleRate: 10 MHz
  Timebase:   200µs/div
  V/div:      CH1=500mV, CH2=500mV  (corrected — stale flag detected)
  Sample int: 100ns  (48000 samples, total 4.7999ms)
  CH1:        Vpp=2320.94mV, GND offset=6400, ADC range=[2436-9863]
  CH2:        Vpp=0.0mV, GND offset=6400, ADC range=[6400-6400] (disabled in header)
```

ETS capture (fast timebase, time axis approximate):
```
==================================================
  File:       1MHz-1V.wav
  Model:      FNIRSI DPOX180H
  SampleRate: 1e+05 MHz  (ETS — time axis approximate)
  Timebase:   5ns/div
  V/div:      CH1=100mV, CH2=200mV  (from header)
  Sample int: 0.01ns  (3000 samples, total 29.99ns)
  CH1:        Vpp=95.63mV, GND offset=6400, ADC range=[5625-7155]
  CH2:        Vpp=0.0mV, GND offset=6400, ADC range=[6400-6400] (disabled in header)
```

Both V/div flags set (stale warning):
```
  Warning: both V/div flags are set — stored V/div (CH1=100mV, CH2=200mV) may be stale. Use --vdiv to override.
```

> **Calibration formula:** `voltage_mV = (adc_value - 6400) * vdiv_mV / 1600`
> where 6400 is the ADC center (8 divisions × 1600 counts/div = 12800 total range).
> Raw ADC values are always included in the CSV for post-processing.

## FNIRSI 1014D WAV file format

All trace files are exactly **15000 bytes** with the following layout:

| Offset (bytes) | Size | Content |
|---|---|---|
| 0–999 | 1000 B | Header (oscilloscope settings, measurements) |
| 1000–3999 | 3000 B | CH1 data — 1500 samples, uint16 LE |
| 4000–6999 | 3000 B | CH2 data — 1500 samples, uint16 LE (zeros if single channel) |
| 7000–14999 | 8000 B | Extra data |

### Key header fields (uint16 LE)

| Byte offset | Description |
|---|---|
| `0x0C` | CH2 enabled (0 = off, 1 = on) |
| `0x16` | Timebase index (higher = faster; 25 = 500ns/div) |
| `0x52` | CH1 GND offset (ADC value for 0V reference) |
| `0x54` | CH2 GND offset |
| `0xD2` | CH1 Vpp in mV |
| `0x102` | CH2 Vpp in mV |

### Timebase index mapping

| Index | Time/div | Index | Time/div |
|---|---|---|---|
| 25 | 500 ns | 17 | 200 µs |
| 24 | 1 µs | 16 | 500 µs |
| 23 | 2 µs | 15 | 1 ms |
| 22 | 5 µs | 14 | 2 ms |
| 21 | 10 µs | 13 | 5 ms |
| 20 | 20 µs | 12 | 10 ms |
| 19 | 50 µs | 11 | 20 ms |
| 18 | 100 µs | 10 | 50 ms |

## License

MIT

## FNIRSI DPOX180H WAV file format

Trace files have **variable size** (e.g. 59981 or 107993 bytes). The format has been fully reverse-engineered from firmware (V40, Allwinner F1C100s/F1C200s ARM SoC) using Ghidra disassembly.

The file is assembled by `FUN_0005da08` which calls `FUN_0005c98c` to serialize the oscilloscope state structure. The writer (`FUN_000315d4`) converts native ARM little-endian values to Big-Endian on write.

### File structure

The file consists of 4 contiguous sections with no gaps:

| Region | Offset | Size | Description |
|---|---|---|---|
| Section table | 0x00–0x31 | 50 B | 7 × u32 BE section offsets/sizes + 22 reserved bytes |
| Settings | 0x32..+S | variable (~1019 B) | Oscilloscope state dump (FUN_0005c98c) |
| Screen buffer | 0x32+S..+B | variable (~11020 B) | RGB565 thumbnail (u16 W + u16 H + W×H×2 pixels) |
| Waveform data | W..W+D | variable | ADC samples: CH1 (if enabled) then CH2 (if enabled), uint16 BE |

**Invariant** — sections follow strictly after each other:
```
settings_start + settings_size = screen_buffer_start
screen_buffer_start + screen_buffer_size = waveform_data_start
waveform_data_start + waveform_data_size = total_file_size
```

### Key header fields (section table)

| Offset | Type | Description |
|---|---|---|
| 0x00 | uint32 BE | Settings start (always 50 = 0x32) — struct+0x838 |
| 0x04 | uint32 BE | Settings size — struct+0x844 |
| 0x08 | uint32 BE | Screen buffer start — struct+0x83C |
| 0x0C | uint32 BE | Screen buffer size — struct+0x848 |
| 0x10 | uint32 BE | Waveform data start — struct+0x840 |
| 0x14 | uint32 BE | Waveform data size — struct+0x84C |
| 0x18 | uint32 BE | Total file size — struct+0x850 |
| **0x66** | **uint8** | **CH1 channel enabled** (0=off, non-zero=on) — firmware: struct+0x3C |
| **0xA6** | **uint8** | **CH2 channel enabled** (0=off, non-zero=on) — firmware: struct+0xEC |
| 0x62 | uint8 | CH1 V/div stale flag (0=current, 1=stale) — firmware: struct+0x38 |
| 0xA2 | uint8 | CH2 V/div stale flag (0=current, 1=stale) — firmware: struct+0xE8 |
| 0x6A | uint16 BE | CH1 V/div index (0-9) — firmware: struct+0x40(pad) + struct+0x42 |
| 0xAA | uint16 BE | CH2 V/div index (0-9) — firmware: struct+0xF0(pad) + struct+0xF2 |
| 0x13D | uint32 BE | ADC sample rate in Hz — firmware: struct+0x664 |
| 0x1D4 | uint8 | Timebase index — firmware: DAT_0005d6a4 |
| 0x1D9 | uint32 BE | Time/div in picoseconds — firmware: struct+0x714 |

### Time axis computation

The time/div is stored directly at offset **0x1D9** as uint32 BE in **picoseconds** (e.g. 5000 = 5 ns, 5000000 = 5 µs). This gives the exact horizontal scale: total display time = 6 × time/div.

The ADC sample rate at offset **0x13D** (uint32 BE, in Hz) gives the real-time sampling rate and is used for the time axis in normal captures. The waveform buffer may contain more samples than fit on the display (long-buffer captures), resulting in actual capture time > display time — this is expected.

For **ETS (Equivalent-Time Sampling)** captures — fast timebases like 5 ns/div — the decoder computes the effective display rate (`samples / display_time`). If this exceeds **1 GSa/s** (impossible for real-time on this hardware), ETS mode is detected and the time axis uses `interval = 6 × tdiv / samples_per_channel` (approximate).

> **Note:** Offset 0x72 stores a per-channel config constant (typically 200000), **not** the actual capture sample rate. It should not be used for time axis computation.

### Channel enable flags

The channel enable flags at **0x66** (CH1) and **0xA6** (CH2) are confirmed by firmware disassembly. `FUN_0005da08` checks these flags (`struct+0x3C` for CH1, `struct+0xEC` for CH2) to decide whether to write ADC samples for each channel.

> **Important:** Only enabled channels have data in the waveform section. If only CH1 is enabled, the entire waveform section contains CH1 samples — there is no CH2 block at all. The waveform data size reflects only the enabled channels: `waveform_data_size = active_channels × sample_count × 2`.

### Stale V/div flags

The flags at bytes `0x62` (CH1) and `0xA2` (CH2) also indicate that the stored V/div is stale (leftover from a previous capture). This is independent of the sample rate correction:

- **One flag set** — the flagged channel's V/div is replaced with the non-flagged channel's V/div:
  - CH1 flagged (`0x62 = 0x01`), CH2 not → CH1 inherits CH2's V/div
  - CH2 flagged (`0xA2 = 0x01`), CH1 not → CH2 inherits CH1's V/div
- **Both flags set** — both V/div values may be stale. The decoder prints a warning and keeps the header values. Use `--vdiv` to override.

The `--vdiv` CLI override bypasses all V/div auto-correction.

### Per-channel configuration blocks

The settings block (starting at file offset 0x32) contains the serialized oscilloscope state structure. Channel config is written by `FUN_0005c98c` from the main struct (DAT_0005d5e8/DAT_0005dba0):

| Block | File range | Struct range | Channel |
|---|---|---|---|
| Display settings | 0x32–0x61 | +0x00..+0x30 | Shared display state |
| CH1 config | 0x62–0x81 | +0x38..+0x5A | CH1 |
| CH1 extended | 0x82–0x9F | +0xC0..+0xDC | CH1 voltage scale, firmware constants |
| CH2 config | 0xA0–0xC1 | +0xDE..+0x108 | CH2 |

Key fields (firmware struct offset → file offset):

| Struct offset | File offset (CH1/CH2) | Type | Description |
|---|---|---|---|
| +0x38 / +0xE8 | 0x62 / 0xA2 | uint8 | V/div stale flag (0=current, 1=stale) |
| +0x3C / +0xEC | **0x66 / 0xA6** | **uint8** | **Channel enabled** (0=off, non-zero=on) |
| +0x3F / +0xEF | 0x69 / 0xA9 | uint8 | Timebase index |
| +0x40 / +0xF0 | 0x6A / 0xAA | uint8 | V/div pad byte (always 0) |
| +0x42 / +0xF2 | 0x6B / 0xAB | uint16 | V/div index (0–9, LE in struct → BE in file) |
| +0x48 / +0xF8 | 0x6E / 0xAE | 8 B | Sample rate block |
| +0x58 / +0x108 | 0x7E / 0xBE | uint16 | Vertical position (GND Y pixel) |

> **Note on V/div read:** The decoder reads u16 BE at 0x6A. The pad byte (+0x40) is always 0, so the u16 BE value equals the V/div index stored at +0x42. This works because the writer byte-swaps from LE to BE.

### V/div table

V/div is stored as an index (0–9) into the standard 1-2-5 sequence:

| Index | V/div |
|---|---|
| 0 | 10 mV |
| 1 | 20 mV |
| 2 | 50 mV |
| 3 | 100 mV |
| 4 | 200 mV |
| 5 | 500 mV |
| 6 | 1 V |
| 7 | 2 V |
| 8 | 5 V |
| 9 | 10 V |

### ADC calibration

- ADC range: 0–12800 (unsigned uint16)
- ADC center (0V): 6400
- 8 vertical divisions, 1600 counts/division
- Formula: `voltage_mV = (adc - 6400) * vdiv_mV / 1600`

### Data layout

The waveform data section starts at `waveform_data_start` and contains **only enabled channels**:

```
[CH1 data: sample_count × u16 BE]   (if CH1 enabled at 0x66)
[CH2 data: sample_count × u16 BE]   (if CH2 enabled at 0xA6)
```

- `sample_count` = `waveform_data_size / (active_channels × 2)`
- Cross-validate with `buffer_sample_count` at offset **0x12D** (u32 BE)
- If only one channel is enabled, the entire waveform section belongs to that channel
- Disabled channels have **no data** in the waveform section (not zeros — simply absent)

### Known file sizes

| Size (bytes) | Settings | Screen buf | Waveform | Samples/ch | Channels | Var table | Notes |
|---|---|---|---|---|---|---|---|
| 18089 | 1019 | 11020 | 6000 | 3000 | 1 (CH1) | 108 B (9) | ETS captures (5 ns/div) |
| 59981 | 911 | 11020 | 48000 | 12000 | 2 (both) | 0 B | 10 MHz, dual-channel |
| 59981 | 911 | 11020 | 48000 | 24000 | 1 (CH1) | 0 B | 10 MHz, single-channel |
| 107993 | 923 | 11020 | 96000 | 24000 | 2 (both) | 12 B (1) | 50 MHz, dual-channel |
| 107993 | 923 | 11020 | 96000 | 48000 | 1 (CH1) | 12 B (1) | 10 MHz, single-channel, long buffer |

Constraint: `settings_start + settings_size + screen_buffer_size + waveform_data_size = total_file_size`.

The settings block has **variable length** — see [Variable-length buffer table](#variable-length-buffer-table) below.

### Settings block detailed map

The settings block is ~900–1100 bytes with **variable length** (911–1019 bytes observed). It consists of a serialized dump of the oscilloscope's main state structure (`FUN_0005c98c`) and a second structure (trigger/measurements, DAT_0005d780).

The settings block contains ~644 bytes from the main struct, followed by an optional variable-length buffer table, then ~280+ bytes from the second struct.

#### Section table (0x00–0x31)

Written **last** by `FUN_0005da08` — the firmware first writes settings, screen buffer and waveform data, records positions via ftell, then seeks to byte 0 and writes the section table. 50 bytes total: 7 × uint32 BE at 0x00–0x1B, followed by 22 reserved bytes.

| Offset | Size | Status | Description |
|---|---|---|---|
| 0x00 | uint32 BE | USED | Settings start (struct+0x838) — always 50 (0x32) |
| 0x04 | uint32 BE | USED | Settings size (struct+0x844) |
| 0x08 | uint32 BE | USED | Screen buffer start (struct+0x83C) |
| 0x0C | uint32 BE | USED | Screen buffer size (struct+0x848) |
| 0x10 | uint32 BE | USED | Waveform data start (struct+0x840) |
| 0x14 | uint32 BE | USED | Waveform data size (struct+0x84C) |
| 0x18 | uint32 BE | USED | Total file size (struct+0x850) |
| 0x1C–0x31 | 22 B | KNOWN | Reserved (constant across all test files) |

#### Display settings (0x32–0x61)

Serialized from main struct offsets +0x00 through +0x30.

| Offset | Size | Status | Description | Struct offset |
|---|---|---|---|---|
| 0x32 | uint16 BE | KNOWN | Grid columns (=10) | +0x00 |
| 0x34 | uint16 BE | KNOWN | Grid rows (=20) | +0x02 |
| 0x36 | uint16 BE | KNOWN | Display height (=300 px) | +0x04 |
| 0x38 | uint16 BE | KNOWN | Display param (=200) | +0x06 |
| 0x3A | uint16 BE | KNOWN | CH1 vertical center Y (=150) | +0x08 |
| 0x3C | uint16 BE | KNOWN | CH2 vertical center Y (=150) | +0x0A |
| 0x3E | uint16 BE | KNOWN | Display state flag | +0x0C |
| 0x40 | uint16 BE | KNOWN | CH1 GND line Y (=299) | +0x0E |
| 0x42 | uint16 BE | KNOWN | CH2 GND line Y (=298) | +0x10 |
| 0x4A | uint16 BE | KNOWN | Num timebase settings (=25) | +0x18 |
| 0x56 | uint8 | KNOWN | Display flag 1 | +0x24 |
| 0x57 | uint8 | KNOWN | Display flag 2 | +0x26 |
| 0x5A | 8 B | KNOWN | Display state block | +0x30 |

#### CH1 config block (0x62–0x81)

Serialized from struct offsets +0x38 through +0x5A.

| Offset | Size | Status | Description | Struct offset |
|---|---|---|---|---|
| 0x62 | uint8 | USED | V/div stale flag | +0x38 |
| **0x66** | **uint8** | **USED** | **Channel enabled** (0=off, non-zero=on) | +0x3C |
| 0x69 | uint8 | USED | Timebase index | +0x3F |
| 0x6A | uint8 | KNOWN | V/div pad (always 0) | +0x40 |
| 0x6B | uint16 | USED | V/div index (0–9) | +0x42 |
| 0x6E | 8 B | KNOWN | Sample rate block | +0x48 |
| 0x76 | 8 B | KNOWN | Sample rate copy | +0x50 |
| 0x7E | uint16 BE | KNOWN | Vertical position (GND Y pixel) | +0x58 |
| 0x80 | uint16 BE | KNOWN | Vertical position copy | +0x5A |

#### CH1 extended config (0x82–0x9F)

Serialized from struct offsets +0xC0 through +0xDC.

| Offset | Size | Status | Description | Struct offset |
|---|---|---|---|---|
| 0x82 | 8 B | KNOWN | Voltage scale block | +0xC0 |
| 0x8A | uint32 BE | KNOWN | Display param | +0xC8 |
| 0x92 | uint32 BE | KNOWN | Firmware constant (0x04000000) | +0xD0 |

#### CH2 config block (0xA0–0xC1)

Mirror of CH1 block, from struct offsets +0xDE through +0x108. The CH2 vertical position copy is stored as a separate global (DAT_0005d5ec) at file offset 0xC0.

| Offset | Size | Status | Description | Struct offset |
|---|---|---|---|---|
| 0xA2 | uint8 | USED | V/div stale flag | +0xE8 |
| **0xA6** | **uint8** | **USED** | **Channel enabled** | +0xEC |
| 0xA9 | uint8 | USED | Timebase index | +0xEF |
| 0xAA | uint8 | KNOWN | V/div pad (always 0) | +0xF0 |
| 0xAB | uint16 | USED | V/div index (0–9) | +0xF2 |
| 0xBE | uint16 BE | KNOWN | Vertical position | +0x108 |

#### Post-channel config (0xC2–0xE3)

Extended configuration from struct offsets +0x170 through +0x198, mixed with standalone DAT globals.

#### Trigger / cursor / math config (0xE4–0x138)

Firmware-confirmed: trigger parameters (struct+0x23C..+0x248), trigger state flags, cursor position values, math/FFT configuration (struct+0x25C..+0x270), and acquisition state flags. Individual fields from ~40 standalone DAT globals are interleaved with struct fields.

| Offset | Size | Status | Description |
|---|---|---|---|
| 0x11B | uint16 BE | KNOWN | ADC center constant (=6400, from DAT_0005d628) |
| 0x12D | uint32 BE | KNOWN | Buffer sample count per channel (struct+0x28C) |
| 0x13D | uint32 BE | USED | ADC sample rate in Hz (struct+0x664) |

#### Extended settings area (0x160–end of settings header)

~11.6 KB of firmware state dump. Low entropy (3.77 bits/byte). Contains timer/clock configuration, display parameters, measurement state, and UI state. Key decoded sub-regions:

##### Constant preamble (0x160–0x198)

Identical across all files (both Waveform and Waveform-google). Likely firmware config lookup tables.

##### Timing / horizontal config (0x198–0x220)

| Offset | Size | Status | Description | Struct offset |
|---|---|---|---|---|
| 0x19E | uint8 | KNOWN | Horizontal resolution parameter | — (DAT global) |
| 0x1A8 | uint32 BE | KNOWN | Base clock constant (=2,560,000) | +0x70C |
| 0x1AC | uint32 BE | KNOWN | Horizontal timer parameter | +0x710 |
| 0x1B0 | uint32 BE | KNOWN | Base clock 2 (=2,560,000 or =25,600,000) | +0x714 |
| 0x1B4 | uint32 BE | KNOWN | Constant = 256 | +0x718 |
| 0x1B8 | uint32 BE | KNOWN | Display X parameter (511 / 2815) | +0x71C |
| 0x1BC | int32 BE | KNOWN | Y-axis range lower = −38,400 | +0x720 |
| 0x1C0 | int32 BE | KNOWN | Y-axis range upper = +38,400 | +0x724 |
| **0x1D4** | **uint8** | **USED** | **Timebase index (s/div)** | DAT_0005d6a4 |
| **0x1D9** | **uint32 BE** | **USED** | **Time/div in picoseconds** | +0x734 |
| 0x1DD | uint8 | KNOWN | Constant = 21 (0x15) |
| 0x1E7 | uint8 | KNOWN | Sample count factor (=N/6000 for Waveform; 1 or 2) |
| **0x1EF** | **uint32 BE** | **KNOWN** | **Timer value (secondary)** — secondary timing parameter |
| **0x1F3** | **uint8** | **KNOWN** | **Timebase index (secondary)** — same as 0x1D4 in single-TB; differs in dual-TB mode |
| **0x1F8** | **uint32 BE** | **KNOWN** | **Timer value (tertiary)** — maps to secondary TB index |

**Dual-timebase**: Files with dual-TB mode (e.g., 3.wav: TB1=1, TB2=5) have 0x1D4 ≠ 0x1F3 and corresponding different timer values at 0x1D9 vs 0x1F8.

**0x1D9 = time/div in picoseconds** (verified):

| Timebase idx (0x1D4) | 0x1D9 (ps) | Time/div | 0x13D (ADC SR) |
|---|---|---|---|
| 11 | 5,000 | 5 ns | 705,032,704 (ETS) |
| 20 | 5,000,000 | 5 µs | 400,000,000 |
| 21 | 10,000,000 | 10 µs | — |
| 22 | 20,000,000 | 20 µs | 50,000,000 |
| 24 | 100,000,000 | 100 µs | 10,000,000 |
| 25 | 200,000,000 | 200 µs | — |

##### Display range (0x208–0x220)

| Offset | Size | Status | Description |
|---|---|---|---|
| 0x208 | uint8 | KNOWN | Mirrors 0x1AE (horizontal resolution) |
| 0x20A | uint32 BE | KNOWN | Mirrors 0x1A8 (base clock = 2,560,000) |
| 0x215 | int32 BE | KNOWN | Y-axis range lower in pixels = −150 |
| 0x219 | uint32 BE | KNOWN | Y-axis range upper in pixels = +150 |

##### Sample count / display block (0x2B0–0x2B7)

Firmware-confirmed: these are the last fixed-offset fields before the variable-length table.

| Offset | Size | Status | Description | Struct source |
|---|---|---|---|---|
| 0x2B4 | uint16 BE | KNOWN | Display height = 300 | DAT_0005d778 |
| 0x2B6 | uint16 BE | KNOWN | Display width = 500 | DAT_0005d77c |

The buffer sample count previously read at 0x2BC is now understood to be part of the second structure (DAT_0005d780), serialized after the variable-length table at base offset 0x2B8+table_size.

##### Variable-length buffer table (0x2B8+)

At offset **0x2B8** (immediately after display_width at 0x2B6) the header contains a **variable-length table** of buffer boundary triplets. The count comes from struct+0x750 written at file offset 0x1E9. All fields after this point are shifted by `table_size` bytes.

`table_size = settings_header_size − 11981`

Each entry is 3 × uint32 BE (12 bytes): `(boundary_1, boundary_2, stride)` where stride = 2 × samples_per_channel.

| Settings header | Table size | Entries | Example values |
|---|---|---|---|
| 11981 | 0 B | 0 | (no table) |
| 11993 | 12 B | 1 | (12000, 18000, 12000) |
| 12089 | 108 B | 9 | (300, 450, 300), (600, 750, 300), … |

> **Important:** All offsets documented below are **base offsets** (for `settings_size = 11981`). For files with a variable table, add `table_size` to get the actual file offset.

##### Measurement config (base 0x305–0x3A0)

| Base offset | Size | Status | Description |
|---|---|---|---|
| 0x305 | uint8 | GUESS | CH1 measurement state (0=off, 1–3=active) |
| 0x392 | uint8 | GUESS | Measurement type 1 (7=frequency?, 0=off) |
| 0x394 | uint8 | GUESS | Measurement type 2 (6=period?, 0=off) |

##### Grid / display rendering (base 0x3C0+)

Contains repeating patterns `E3 18` (28× occurrences) and `29 65` — likely display graticule or grid rendering data. Not useful for signal processing.

##### Trigger / cursor / math channel

**Firmware-confirmed** (FUN_0005c98c): The trigger/cursor/math settings are serialized from the main oscilloscope struct at file offsets 0xE4–0x138, interleaved with ~40 standalone DAT globals. Specific fields include trigger mode, trigger edge, trigger level, cursor positions, math/FFT configuration, and acquisition state flags. Individual field identification is in progress — many of the ~40 DAT_* references in the firmware serializer still need mapping to oscilloscope features.

### Screen buffer

The screen buffer section (~11020 bytes typically) stores a screenshot of the oscilloscope display as an RGB565 bitmap, prefixed by uint16 BE width and uint16 BE height. This is a thumbnail of the oscilloscope's LCD at the moment of capture. Not useful for signal reconstruction.

### Header dump utility

`dump_header.py` — dumps all known and suspected DPOX180H header fields with hex/dec/float formatting and color-coded status tags (USED / KNOWN / GUESS / ?).

```bash
python dump_header.py Waveform/19.wav [Waveform/29.wav ...]
```
