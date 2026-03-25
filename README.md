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
  SampleRate: 5 MHz
  Timebase:   199.967µs/div  (estimated)
  V/div:      CH1=100mV, CH2=200mV  (from header)
  Sample int: 200ns  (6000 samples, total 1.1998ms)
  CH1:        Vpp=800.0mV, GND offset=6400, ADC range=[0-12800]
  CH2:        Vpp=1600.0mV, GND offset=6400, ADC range=[0-12800]
```

With `--vdiv` override:
```
==================================================
  File:       19.wav
  Model:      FNIRSI DPOX180H
  SampleRate: 5 MHz
  Timebase:   199.967µs/div  (estimated)
  V/div:      CH1=500mV, CH2=1V  (from cli)
  Sample int: 200ns  (6000 samples, total 1.1998ms)
  CH1:        Vpp=4000.0mV, GND offset=6400, ADC range=[0-12800]
  CH2:        Vpp=8000.0mV, GND offset=6400, ADC range=[0-12800]
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

Trace files have **variable size** (e.g. 59981 or 107993 bytes). Structure is described by three uint32 Big-Endian fields in the header:

| Offset (bytes) | Type | Description |
|---|---|---|
| 16–19 | uint32 BE | Settings header size |
| 20–23 | uint32 BE | Data section size (display buffer + ADC data, split 50/50) |
| 24–27 | uint32 BE | Total file size |
| 0x72–0x75 | uint32 BE | Sample rate in Hz (e.g. 5000000 = 5 MHz) |

### Per-channel configuration blocks

The header contains two configuration blocks with identical structure — one per channel:

| Block | Offset range | Channel |
|---|---|---|
| Block 1 | 0x60–0x9F | CH1 |
| Block 2 | 0xA0–0xDF | CH2 |

Key fields within each block (offsets relative to block start):

| Relative offset | Absolute (CH1 / CH2) | Type | Description |
|---|---|---|---|
| +0x0A | 0x6A / 0xAA | uint16 BE | V/div index into standard table |

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

`settings_header | display_buffer (D/2 bytes) | ADC_data (D/2 bytes)`

ADC data block: first half = CH1, second half = CH2. Format: unsigned uint16 Big-Endian.

Samples per channel = `data_section_size / 8`.

### Known file sizes

| Size (bytes) | Samples/ch | Notes |
|---|---|---|
| 59981 | 6000 | 5 MHz or 10 MHz sample rate |
| 107993 | 12000 | 200 kHz sample rate |
